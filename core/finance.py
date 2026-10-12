"""Moliyaviy hisob-kitoblar: hammasi `Transaction` daftaridan olinadi."""
import re
from collections import OrderedDict, defaultdict
from datetime import date, timedelta

from sqlalchemy import and_, case, func, or_

from core.extensions import db
from core.models import (
    TX_IN, TX_OUT, Account, Category, Debt, Enrollment, Program, Setting,
    Transaction,
)

MONTHS_SHORT = ["Yan", "Fev", "Mar", "Apr", "May", "Iyn", "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"]
MONTHS_FULL = [
    "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul", "Avgust",
    "Sentabr", "Oktabr", "Noyabr", "Dekabr",
]

DEFAULT_SETTINGS = {
    "org_name": "Assoodiq",
    "usd_rate": "12800",
    "gold_price_g": "1250000",   # 1 gramm oltin narxi, so'm
    "silver_price_g": "14500",   # 1 gramm kumush narxi, so'm
    "nisob_basis": "oltin",      # oltin (85 g) | kumush (595 g)
    "hawl_start": "",            # havl boshlangan sana (YYYY-MM-DD)
    "inventory_value": "0",      # zaxiradagi tovar (kitob, mahsulot) bozor qiymati
    "sadaqa_percent": "2.5",     # sof foydadan sadaqaga ajratiladigan ulush
    # Telegram eslatmalari (core/telegram.py)
    "tg_token": "", "tg_bot": "", "tg_webhook": "",
    "tg_auto_lessons": "1", "tg_lead_hours": "3",
    "tg_auto_expiry": "1", "tg_expiry_days": "3",
    "tg_auto_pay": "0", "tg_pay_day": "5",
    "tg_tpl_dars": "", "tg_tpl_qarz": "", "tg_tpl_obuna": "",
    # O'quvchi ilovasi (views/ilova.py): video — Bunny Stream, namoz vaqtlari hisobi
    "bunny_library": "", "bunny_key": "", "bunny_token_key": "",
    "prayer_method": "MWL", "prayer_asr": "hanafi", "prayer_offsets": "0,0,0,0,0,0", "app_city": "Toshkent",
    # Sun'iy intellekt (core/ai.py)
    "ai_key": "", "ai_weekly": "1", "ai_weekly_day": "0", "ai_weekly_hour": "9", "ai_daily_limit": "100",
}

NISOB_GRAMS = {"oltin": 85, "kumush": 595}
ZAKAT_RATE = 0.025


# ── Sozlamalar ──────────────────────────────────────────────────────────────

def get_setting(key):
    row = db.session.get(Setting, key)
    return row.value if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(key, value):
    row = db.session.get(Setting, key)
    if row is None:
        row = Setting(key=key)
        db.session.add(row)
    row.value = str(value)


def setting_float(key):
    try:
        return float(re.sub(r"\s", "", str(get_setting(key))).replace(",", "."))
    except ValueError:
        return float(DEFAULT_SETTINGS.get(key) or 0)


def usd_rate():
    return setting_float("usd_rate") or 1.0


def to_uzs(amount, currency):
    return amount * usd_rate() if currency == "USD" else amount


def convert(amount, from_cur, to_cur):
    if from_cur == to_cur:
        return amount
    if from_cur == "USD":
        return amount * usd_rate()
    return amount / usd_rate()


def parse_money(raw):
    """'1 500 000' yoki '1500,50' → float. Bo'sh yoki xato → 0."""
    if raw is None:
        return 0.0
    s = re.sub(r"\s", "", str(raw)).replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


# ── Daftar yozuvi ───────────────────────────────────────────────────────────

def record(kind, amount, account, **fields):
    """Yangi yozuv: so'mdagi qiymatini yozilgan paytdagi kurs bilan saqlaydi."""
    tx = Transaction(kind=kind, amount=amount, account_id=account.id, **fields)
    tx.amount_uzs = round(to_uzs(amount, account.currency), 2)
    db.session.add(tx)
    return tx


# ── Balanslar ───────────────────────────────────────────────────────────────

def account_balances(before=None):
    """{account_id: balans (hisobning o'z valyutasida)}. before — shu sanagacha (o'zi kirmaydi)."""
    signed = case(
        (Transaction.kind.in_(TX_IN), Transaction.amount),
        else_=-Transaction.amount,
    )
    flows_q = db.session.query(Transaction.account_id, func.coalesce(func.sum(signed), 0))
    transfers_q = (
        db.session.query(
            Transaction.to_account_id,
            func.coalesce(func.sum(func.coalesce(Transaction.to_amount, Transaction.amount)), 0),
        )
        .filter(Transaction.kind == "otkazma", Transaction.to_account_id.isnot(None))
    )
    if before is not None:
        flows_q = flows_q.filter(Transaction.date < before)
        transfers_q = transfers_q.filter(Transaction.date < before)
    flows = dict(flows_q.group_by(Transaction.account_id).all())
    transfers_in = dict(transfers_q.group_by(Transaction.to_account_id).all())
    result = {}
    for acc in Account.query.all():
        result[acc.id] = acc.opening_balance + flows.get(acc.id, 0) + transfers_in.get(acc.id, 0)
    return result


def accounts_with_balance(active_only=True):
    bal = account_balances()
    q = Account.query
    if active_only:
        q = q.filter_by(active=True)
    rows = []
    for acc in q.order_by(Account.sort, Account.id).all():
        b = bal.get(acc.id, 0)
        rows.append({"account": acc, "balance": b, "balance_uzs": to_uzs(b, acc.currency)})
    return rows


def total_balance_uzs():
    return sum(r["balance_uzs"] for r in accounts_with_balance(active_only=False))


def ledger_rows(rows, account=None, start=None):
    """Kassa daftari (Sheets'dagidek): har yozuvdan keyingi qoldiq.

    rows — davrdagi barcha yozuvlar (sana bo'yicha o'sib boradi). account berilsa qoldiq
    shu hisob valyutasida, aks holda barcha hisoblar so'mda (joriy kurs — yuqoridagi
    umumiy balans bilan bir xil chiqishi uchun). Natija: (boshlang'ich qoldiq, valyuta, {tx.id: qator}).
    """
    accounts = {a.id: a for a in Account.query.all()}
    opening_map = account_balances(before=start)
    if account is not None:
        cur = account.currency
        opening = opening_map.get(account.id, 0)
    else:
        cur = "UZS"
        opening = sum(to_uzs(v, accounts[k].currency) for k, v in opening_map.items() if k in accounts)

    def flows(t):
        """(kirdi, chiqdi) — ko'rsatiladigan valyutada."""
        if account is not None:
            inc = out = 0.0
            if t.account_id == account.id:
                if t.kind in TX_IN:
                    inc += t.amount
                else:
                    out += t.amount
            if t.kind == "otkazma" and t.to_account_id == account.id:
                inc += t.to_amount if t.to_amount is not None else t.amount
            return inc, out
        src = to_uzs(t.amount, t.currency)
        if t.kind == "otkazma":
            dst_cur = t.to_account.currency if t.to_account else t.currency
            dst = to_uzs(t.to_amount if t.to_amount is not None else t.amount, dst_cur)
            return dst, src
        return (src, 0.0) if t.kind in TX_IN else (0.0, src)

    out_map, bal = {}, opening
    for t in rows:
        inc, out = flows(t)
        if inc < 0:  # qaytarilgan to'lov (manfiy kirim) — chiqib ketgan pul
            inc, out = 0.0, out - inc
        bal += inc - out
        out_map[t.id] = {"inc": inc, "out": out, "bal": bal,
                         "move": t.kind == "otkazma" and account is None}
    return opening, cur, out_map


# ── Davr bo'yicha ko'rsatkichlar ────────────────────────────────────────────

def month_bounds(d):
    start = d.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def shift_month(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def pnl_scope():
    """Foyda-zararga kiradigan yozuvlar sharti.

    Kirim — faqat halol tushum (shubhali/nohalol tozalash fondiga ketadi, egasiniki emas).
    Chiqim — tozalash fondidan chiqarilgan pul bundan mustasno (u o'sha tushumning o'zi).
    O'tkazma va qarz harakatlari umuman kirmaydi.
    """
    purge = system_category("tozalash")
    expense = Transaction.kind == "chiqim"
    if purge is not None:
        expense = and_(expense, or_(Transaction.category_id.is_(None), Transaction.category_id != purge.id))
    return or_(and_(Transaction.kind == "kirim", Transaction.shariat == "halol"), expense)


def period_totals(start, end):
    """Foyda-zarar uchun: faqat kirim va chiqim (o'tkazma va qarz kirmaydi)."""
    rows = (
        db.session.query(Transaction.kind, func.coalesce(func.sum(Transaction.amount_uzs), 0))
        .filter(Transaction.date >= start, Transaction.date <= end, pnl_scope())
        .group_by(Transaction.kind).all()
    )
    d = dict(rows)
    income, expense = d.get("kirim", 0), d.get("chiqim", 0)
    return {"income": income, "expense": expense, "profit": income - expense}


def monthly_series(months=12, today=None):
    today = today or date.today()
    first = shift_month(today.replace(day=1), -(months - 1))
    rows = (
        db.session.query(Transaction.date, Transaction.kind, Transaction.amount_uzs)
        .filter(Transaction.date >= first, pnl_scope())
        .all()
    )
    buckets = OrderedDict()
    for i in range(months):
        m = shift_month(first, i)
        buckets[(m.year, m.month)] = {
            "label": MONTHS_SHORT[m.month - 1],
            "full": f"{MONTHS_FULL[m.month - 1]} {m.year}",
            "income": 0.0, "expense": 0.0,
        }
    for d, kind, amt in rows:
        b = buckets.get((d.year, d.month))
        if b is not None:
            b["income" if kind == "kirim" else "expense"] += amt
    out = list(buckets.values())
    for b in out:
        b["profit"] = b["income"] - b["expense"]
    return out


def nice_scale(maxv, ticks=4):
    """Grafik o'qi uchun yaxlit qadam: (yuqori chegara, qadam)."""
    import math
    if maxv <= 0:
        return 1.0, 0.25
    raw = maxv / ticks
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return step * ticks, step


def breakdown(kind, start, end, by="group", limit=None):
    """Kategoriya yoki guruh bo'yicha taqsimot (kamayish tartibida)."""
    col = Category.group if by == "group" else Category.name
    rows = (
        db.session.query(func.coalesce(col, "Kategoriyasiz"), func.sum(Transaction.amount_uzs))
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(Transaction.kind == kind, Transaction.date >= start, Transaction.date <= end, pnl_scope())
        .group_by(col).all()
    )
    rows = sorted(((n, v or 0) for n, v in rows), key=lambda r: -r[1])
    total = sum(v for _, v in rows) or 1
    items = [{"name": n, "value": v, "share": v / total} for n, v in rows]
    if limit and len(items) > limit:
        rest = items[limit - 1:]
        items = items[:limit - 1] + [{
            "name": "Boshqalar", "value": sum(i["value"] for i in rest),
            "share": sum(i["share"] for i in rest),
        }]
    return items


def pnl_table(year):
    """Yillik foyda-zarar: guruh × oy jadvali."""
    rows = (
        db.session.query(Transaction.kind, func.coalesce(Category.group, "Kategoriyasiz"),
                         Transaction.date, Transaction.amount_uzs)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(pnl_scope(),
                Transaction.date >= date(year, 1, 1), Transaction.date <= date(year, 12, 31))
        .all()
    )
    table = {"kirim": defaultdict(lambda: [0.0] * 12), "chiqim": defaultdict(lambda: [0.0] * 12)}
    for kind, group, d, amt in rows:
        table[kind][group][d.month - 1] += amt

    def section(kind):
        groups = sorted(table[kind].items(), key=lambda g: -sum(g[1]))
        totals = [sum(g[1][i] for g in groups) for i in range(12)]
        return {"groups": [{"name": n, "months": m, "total": sum(m)} for n, m in groups],
                "totals": totals, "total": sum(totals)}

    inc, exp = section("kirim"), section("chiqim")
    profit = [inc["totals"][i] - exp["totals"][i] for i in range(12)]
    return {"income": inc, "expense": exp, "profit": profit, "profit_total": sum(profit)}


# ── Dasturlar va a'zolar ────────────────────────────────────────────────────

def enrollment_paid_map():
    """{enrollment_id: to'langan (so'm)}"""
    return dict(
        db.session.query(Transaction.enrollment_id, func.sum(Transaction.amount_uzs))
        .filter(Transaction.kind == "kirim", Transaction.enrollment_id.isnot(None))
        .group_by(Transaction.enrollment_id).all()
    )


def enrollment_row(enr, paid_map=None):
    paid_map = paid_map if paid_map is not None else enrollment_paid_map()
    price = to_uzs(enr.price, enr.program.currency)
    paid = paid_map.get(enr.id, 0) or 0
    return {"enrollment": enr, "price": price, "paid": paid, "due": max(price - paid, 0),
            "progress": min(paid / price, 1) if price else 1}


def program_stats(program, paid_map=None):
    paid_map = paid_map if paid_map is not None else enrollment_paid_map()
    enrs = program.enrollments.filter(Enrollment.status != "chiqqan").all()
    expected = sum(to_uzs(e.price, program.currency) for e in enrs)
    collected = (
        db.session.query(func.coalesce(func.sum(Transaction.amount_uzs), 0))
        .filter(Transaction.kind == "kirim", Transaction.program_id == program.id).scalar()
    )
    exp_rows = (
        db.session.query(func.coalesce(Category.group, "Kategoriyasiz"), func.sum(Transaction.amount_uzs))
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(Transaction.kind == "chiqim", Transaction.program_id == program.id)
        .group_by(Category.group).all()
    )
    expenses = sum(v or 0 for _, v in exp_rows)
    marketing = sum(v or 0 for g, v in exp_rows if g == "Marketing")
    n = len(enrs)
    dues = [enrollment_row(e, paid_map)["due"] for e in enrs]
    due = sum(dues)
    return {
        "program": program, "members": n, "expected": expected, "collected": collected,
        "due": due, "debtors": sum(1 for d in dues if d > 0.01),
        "expenses": expenses, "profit": collected - expenses,
        "margin": (collected - expenses) / collected if collected else 0,
        "cac": marketing / n if n else 0,
        "progress": min(collected / expected, 1) if expected else 0,
        "fill": (n / program.capacity) if program.capacity else None,
    }


def receivables_from_members():
    paid_map = enrollment_paid_map()
    total = 0.0
    for e in Enrollment.query.filter(Enrollment.status != "chiqqan").all():
        total += enrollment_row(e, paid_map)["due"]
    return total


def expiring_memberships(days=7, today=None):
    today = today or date.today()
    return (
        Enrollment.query.join(Program)
        .filter(Program.kind == "klub", Enrollment.status == "faol",
                Enrollment.valid_until.isnot(None),
                Enrollment.valid_until <= today + timedelta(days=days))
        .order_by(Enrollment.valid_until).all()
    )


# ── Qarz daftari ────────────────────────────────────────────────────────────

def debt_remaining(debt):
    """Qoldiq qarz valyutasida. Berilgan qarzni qaytarish — kirim, olinganniki — chiqim."""
    repay_kind = "qarz_kirim" if debt.direction == "berilgan" else "qarz_chiqim"
    repaid = sum(convert(m.amount, m.account.currency, debt.currency)
                 for m in debt.moves.filter(Transaction.kind == repay_kind).all())
    return max(debt.amount - repaid, 0)


def debts_summary():
    out = {"berilgan": 0.0, "olingan": 0.0, "overdue": 0}
    today = date.today()
    for d in Debt.query.filter_by(closed=False).all():
        rem = debt_remaining(d)
        out[d.direction] += to_uzs(rem, d.currency)
        if rem > 0 and d.due_date and d.due_date < today:
            out["overdue"] += 1
    return out


# ── Halollik: tozalash fondi va sadaqa ──────────────────────────────────────

def system_category(code):
    return Category.query.filter_by(system_code=code).first()


def _spent_on(code, start=None, end=None):
    cat = system_category(code)
    if not cat:
        return 0.0
    q = db.session.query(func.coalesce(func.sum(Transaction.amount_uzs), 0)).filter(
        Transaction.kind == "chiqim", Transaction.category_id == cat.id)
    if start:
        q = q.filter(Transaction.date >= start)
    if end:
        q = q.filter(Transaction.date <= end)
    return q.scalar()


def purification_fund():
    """Shubhali/nohalol tushumlar — foydaga qo'shilmaydi, savob niyatisiz chiqariladi."""
    flagged = (
        db.session.query(func.coalesce(func.sum(Transaction.amount_uzs), 0))
        .filter(Transaction.kind == "kirim", Transaction.shariat.in_(("shubhali", "nohalol")))
        .scalar()
    )
    paid = _spent_on("tozalash")
    return {"flagged": flagged, "paid": paid, "remaining": max(flagged - paid, 0)}


def sadaqa_status(year=None):
    year = year or date.today().year
    start, end = date(year, 1, 1), date(year, 12, 31)
    profit = period_totals(start, end)["profit"]
    target = max(profit, 0) * setting_float("sadaqa_percent") / 100
    given = _spent_on("sadaqa", start, end)
    return {"year": year, "profit": profit, "target": target, "given": given,
            "progress": min(given / target, 1) if target else 0}


# ── Zakot ───────────────────────────────────────────────────────────────────

def nisob_value(basis=None):
    basis = basis or get_setting("nisob_basis")
    price = setting_float("gold_price_g" if basis == "oltin" else "silver_price_g")
    return NISOB_GRAMS.get(basis, 85) * price


def zakat_compute(cash, receivables, inventory, other_assets, liabilities, nisob):
    base = cash + receivables + inventory + other_assets - liabilities
    due = round(base * ZAKAT_RATE, 2) if base >= nisob and base > 0 else 0.0
    return {"base": base, "due": due, "reached": base >= nisob and base > 0}


def zakat_defaults():
    """Daftardan avtomatik yig'ilgan qiymatlar (formada tahrirlash mumkin).

    Tozalash fondidagi pul egasiniki emas, shuning uchun naqddan ayriladi.
    """
    debts = debts_summary()
    purif = purification_fund()["remaining"]
    return {
        "cash": max(total_balance_uzs() - purif, 0),
        "receivables": debts["berilgan"] + receivables_from_members(),
        "inventory": setting_float("inventory_value"),
        "other_assets": 0.0,
        "liabilities": debts["olingan"],
    }
