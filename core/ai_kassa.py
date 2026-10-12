"""Telegram orqali kassaga yozish: oddiy matn yoki chek rasmi → tasdiqlanadigan qoralama → yozuv.

Sun'iy intellekt faqat maydonlarni to'ldiradi; summa, hisob va kategoriya bu yerda qayta tekshiriladi,
yozuv esa xodim «Saqlash»ni bosgandan keyingina kassaga tushadi.
"""
import html
import json
from datetime import date, datetime, timedelta

from core import ai
from core import finance as F
from core.extensions import db
from core.models import Account, AiDraft, Category, Enrollment

MAX_ENTRIES = 10

ENTRY = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["kirim", "chiqim", "otkazma"]},
        "amount": {"type": "number"},
        "currency": {"type": "string", "enum": ["UZS", "USD"]},
        "account_id": {"type": "integer"},
        "to_account_id": {"type": "integer"},
        "category_id": {"type": "integer"},
        "enrollment_id": {"type": "integer"},
        "counterparty": {"type": "string"},
        "date": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["kind", "amount", "currency", "account_id", "to_account_id", "category_id", "enrollment_id",
                 "counterparty", "date", "note"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["yozuv", "savol", "boshqa"]},
        "entries": {"type": "array", "items": ENTRY},
        "reply": {"type": "string"},
    },
    "required": ["intent", "entries", "reply"],
    "additionalProperties": False,
}

SYSTEM = """You are the bookkeeping assistant of an Islamic business-education centre in Uzbekistan.
Staff write to you in Uzbek (Latin or Cyrillic), Russian or mixed slang, or send a photo of a receipt,
invoice or bank screenshot. Turn each money movement into a structured cash-book entry.

Rules:
- intent "yozuv": the message reports money received (kirim), paid out (chiqim) or moved between the
  centre's own accounts (otkazma). One message may contain several entries (max 10).
- intent "savol": the user asks a question about the finances (why, how much, who owes, compare...).
  Leave entries empty; put the question, cleaned up, in "reply".
- intent "boshqa": greetings or anything else. Leave entries empty and write a one-line friendly
  Uzbek reply explaining what you can do.
- Amounts: understand "1.5 mln", "1,5 million", "500 ming", "500k", "ikki yarim million", "$200",
  "200 dollar", "1 500 000". amount is a plain number in the stated currency (currency UZS unless
  dollars are mentioned).
- account_id: pick from ACCOUNTS by words like naqd/kassa, karta, bank, payme, click, dollar.
  Use 0 if nothing indicates the account. For otkazma also set to_account_id, else 0.
- category_id: pick the best matching category OF THE SAME KIND from CATEGORIES, 0 if unsure.
- enrollment_id: only for kirim that is a student's/member's payment - match the person's name
  (allow spelling variants and first-name-only matches when unique) and the programme against
  STUDENTS. 0 if no clear match. Never guess between two different people.
- counterparty: who paid or who was paid (person or company), as written. "" if unknown.
- date: YYYY-MM-DD. Resolve "bugun", "kecha", "o'tgan juma", weekday names and dates on a receipt
  relative to TODAY given in the message. Default: TODAY.
- note: a short Uzbek description (what it was for), max 120 characters.
- For receipts: one entry per receipt with the TOTAL paid (not each line), kind chiqim unless the
  image clearly shows money received.
- Never invent amounts. If the amount is missing or unreadable, use intent "boshqa" and ask for it
  in "reply" in Uzbek.

DATA (ids are what you return):
"""


def _context():
    accounts = [{"id": a.id, "name": a.name, "currency": a.currency, "type": a.kind}
                for a in Account.query.filter_by(active=True).order_by(Account.id).all()]
    cats = [{"id": c.id, "name": c.name, "kind": c.kind, "group": c.group or ""}
            for c in Category.query.filter(Category.active.is_(True), Category.kind.in_(("kirim", "chiqim")))
            .order_by(Category.kind, Category.id).all()]
    paid = F.enrollment_paid_map()
    students = []
    for e in (Enrollment.query.filter(Enrollment.status != "chiqqan").order_by(Enrollment.id).all()):
        row = F.enrollment_row(e, paid)
        students.append({"enrollment_id": e.id, "name": e.member.full_name, "programme": e.program.name,
                         "due": round(row["due"])})
    return {"ACCOUNTS": accounts, "CATEGORIES": cats, "STUDENTS": students}


def system_prompt():
    # Barqaror tartib — prompt keshi ishlashi uchun (sana bu yerga yozilmaydi)
    return SYSTEM + json.dumps(_context(), ensure_ascii=False, sort_keys=True)


def _today_line(today=None):
    today = today or date.today()
    wd = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"][today.weekday()]
    return f"TODAY: {today.isoformat()} ({wd})"


def understand(text="", image=None, user_id=None, today=None):
    """Matn/rasmni tahlil qiladi → {"intent", "entries" (tekshirilgan), "reply"}."""
    content = []
    if image:
        data, mime = image
        import base64
        block = "document" if mime == "application/pdf" else "image"
        content.append({"type": block, "source": {"type": "base64", "media_type": mime,
                                                   "data": base64.standard_b64encode(data).decode()}})
    content.append({"type": "text", "text": f"{_today_line(today)}\nMESSAGE: {text or '(rasm)'}"})
    out = ai.ask(system_prompt(), content, feature="kassa", user_id=user_id, schema=SCHEMA, effort="low")
    entries = [e for e in (clean(x, today) for x in (out.get("entries") or [])[:MAX_ENTRIES]) if e]
    return {"intent": out.get("intent") or "boshqa", "entries": entries, "reply": (out.get("reply") or "").strip()}


def _payment_category(program):
    return (Category.query.filter(Category.kind == "kirim", Category.program_kind == program.kind,
                                  Category.active.is_(True)).first())


def clean(e, today=None):
    """Sun'iy intellekt bergan maydonlarni bazaga qarab tekshiradi; yaroqsiz bo'lsa None."""
    today = today or date.today()
    kind = e.get("kind")
    if kind not in ("kirim", "chiqim", "otkazma"):
        return None
    try:
        amount = round(float(e.get("amount") or 0), 2)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    cur = "USD" if e.get("currency") == "USD" else "UZS"
    accounts = Account.query.filter_by(active=True).order_by(Account.id).all()
    by_id = {a.id: a for a in accounts}
    acc = by_id.get(e.get("account_id") or 0)
    guessed = acc is None
    if acc is None:  # hisob aytilmagan — valyutaga mos birinchi hisob
        acc = next((a for a in accounts if a.currency == cur), accounts[0] if accounts else None)
    if acc is None:
        return None
    if acc.currency != cur:  # 200 dollar, lekin so'mli hisob — kurs bo'yicha o'giriladi
        amount = round(F.convert(amount, cur, acc.currency), 2)
    try:
        d = datetime.strptime(str(e.get("date") or ""), "%Y-%m-%d").date()
    except ValueError:
        d = today
    if d > today + timedelta(days=1) or d < today - timedelta(days=366):
        d = today
    out = {"kind": kind, "amount": amount, "account_id": acc.id, "account_guessed": guessed, "date": d.isoformat(),
           "counterparty": (e.get("counterparty") or "").strip()[:160], "note": (e.get("note") or "").strip()[:500],
           "category_id": None, "enrollment_id": None, "program_id": None, "to_account_id": None}
    if kind == "otkazma":
        to = by_id.get(e.get("to_account_id") or 0)
        if to is None or to.id == acc.id:
            return None
        out["to_account_id"] = to.id
        return out
    cat = db.session.get(Category, e.get("category_id") or 0)
    if cat and cat.kind == kind and cat.active:
        out["category_id"] = cat.id
    if kind == "kirim":
        enr = db.session.get(Enrollment, e.get("enrollment_id") or 0)
        if enr and enr.status != "chiqqan":
            out.update(enrollment_id=enr.id, program_id=enr.program_id)
            out["counterparty"] = out["counterparty"] or enr.member.full_name
            if not out["category_id"]:
                pc = _payment_category(enr.program)
                out["category_id"] = pc.id if pc else None
    return out


def _money(v, cur):
    s = f"{v:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    return f"${s}" if cur == "USD" else f"{s} so'm"


def describe(entries):
    """Telegram uchun (HTML) qisqa ko'rinish."""
    lines = []
    icons = {"kirim": "🟢 Kirim", "chiqim": "🔴 Chiqim", "otkazma": "🔁 O'tkazma"}
    for i, e in enumerate(entries, 1):
        acc = db.session.get(Account, e["account_id"])
        head = f"{icons[e['kind']]} · <b>{_money(e['amount'], acc.currency)}</b>"
        rows = [f"{i}. {head}" if len(entries) > 1 else head]
        if e["kind"] == "otkazma":
            to = db.session.get(Account, e["to_account_id"])
            rows.append(f"💳 {html.escape(acc.name)} → {html.escape(to.name)}")
        else:
            if e.get("enrollment_id"):
                enr = db.session.get(Enrollment, e["enrollment_id"])
                rows.append(f"🎓 {html.escape(enr.member.full_name)} — {html.escape(enr.program.name)} "
                            "<i>(qarzidan ayiriladi)</i>")
            elif e["counterparty"]:
                rows.append(f"👤 {html.escape(e['counterparty'])}")
            cat = db.session.get(Category, e["category_id"]) if e.get("category_id") else None
            rows.append(f"📂 {html.escape(cat.name) if cat else '<i>kategoriyasiz</i>'}")
            rows.append(f"💳 {html.escape(acc.name)}{' <i>(taxminiy)</i>' if e.get('account_guessed') else ''}")
        d = date.fromisoformat(e["date"])
        rows.append(f"📅 {d:%d.%m.%Y}" + (" (bugun)" if d == date.today() else ""))
        if e["note"]:
            rows.append(f"📝 {html.escape(e['note'])}")
        lines.append("\n".join(rows))
    return "\n\n".join(lines)


def create_draft(user, chat_id, request, entries, source="matn"):
    d = AiDraft(user_id=user.id, chat_id=str(chat_id), source=source, request=(request or "")[:2000],
                payload=json.dumps(entries, ensure_ascii=False))
    db.session.add(d)
    db.session.commit()
    return d


def save_draft(draft, user):
    """Qoralamani kassaga yozadi. (ok, xabar)"""
    if draft.user_id != user.id:
        return False, "Bu yozuv sizniki emas."
    if draft.status != "pending":
        return False, "Bu yozuv allaqachon " + ("saqlangan." if draft.status == "saved" else "bekor qilingan.")
    if draft.created_at and ai._utcnow() - draft.created_at > timedelta(days=2):
        return False, "Qoralama eskirgan — qaytadan yuboring."
    entries = json.loads(draft.payload or "[]")
    if user.role == "menejer" and any(e["kind"] != "kirim" for e in entries):
        return False, "Menejer faqat kirim yozishi mumkin."
    txs = []
    for e in entries:
        acc = db.session.get(Account, e["account_id"])
        if acc is None:
            return False, "Hisob topilmadi — qaytadan yuboring."
        fields = {"date": date.fromisoformat(e["date"]), "note": e["note"], "counterparty": e["counterparty"],
                  "created_by": user.id}
        if e["kind"] == "otkazma":
            to = db.session.get(Account, e["to_account_id"])
            fields.update(to_account_id=to.id, to_amount=round(F.convert(e["amount"], acc.currency, to.currency), 2))
        else:
            fields.update(category_id=e.get("category_id"), program_id=e.get("program_id"),
                          enrollment_id=e.get("enrollment_id"), shariat="halol", aqd="")
        txs.append(F.record(e["kind"], e["amount"], acc, **fields))
    db.session.flush()
    draft.status = "saved"
    draft.transaction_id = txs[0].id if txs else None
    db.session.commit()
    total = len(txs)
    return True, f"✅ Kassaga yozildi{f' ({total} ta yozuv)' if total > 1 else ''}."


def cancel_draft(draft, user):
    if draft.user_id != user.id or draft.status != "pending":
        return False
    draft.status = "cancelled"
    db.session.commit()
    return True

