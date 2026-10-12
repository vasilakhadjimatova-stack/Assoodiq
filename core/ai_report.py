"""Moliyaviy tahlil: raqamlar dasturda hisoblanadi, sun'iy intellekt faqat ularni tushuntiradi.

- snapshot() — kassa, dasturlar, qarzdorlar, obunalar va davomat bo'yicha aniq raqamlar (JSON)
- weekly() — haftalik hisobot (rahbar va buxgalterga Telegram'da, bosh sahifada)
- answer() — «Nega bu oy zarar?» kabi savollarga javob
"""
import html
import json
import re
from datetime import date, datetime, timedelta

from sqlalchemy import func

from core import ai
from core import finance as F
from core.extensions import db
from core.models import AiReport, Attendance, Enrollment, Lesson, Program, StaffLink, Transaction, User


def _r(v):
    return int(round(v or 0))


def _program_income(start, end):
    rows = (db.session.query(Program.name, func.sum(Transaction.amount_uzs))
            .join(Program, Transaction.program_id == Program.id)
            .filter(Transaction.kind == "kirim", Transaction.date >= start, Transaction.date <= end)
            .group_by(Program.name).all())
    return {n: _r(v) for n, v in sorted(rows, key=lambda r: -(r[1] or 0))}


def snapshot(today=None):
    today = today or date.today()
    m0 = today.replace(day=1)
    pm0 = F.shift_month(m0, -1)
    pm_same = min(today.replace(year=pm0.year, month=pm0.month, day=1) + timedelta(days=today.day - 1),
                  m0 - timedelta(days=1))
    w0 = today - timedelta(days=6)
    pw0, pw1 = w0 - timedelta(days=7), w0 - timedelta(days=1)

    def tot(a, b):
        t = F.period_totals(a, b)
        return {k: _r(v) for k, v in t.items()}

    paid = F.enrollment_paid_map()
    programs = []
    for p in Program.query.filter(Program.status != "yakunlangan").all():
        s = F.program_stats(p, paid)
        if not s["members"] and not s["collected"]:
            continue
        programs.append({"name": p.name, "kind": p.kind_name, "members": s["members"], "expected": _r(s["expected"]),
                         "collected": _r(s["collected"]), "due": _r(s["due"]), "debtors": s["debtors"],
                         "expenses": _r(s["expenses"]), "profit": _r(s["profit"]),
                         "collected_pct": round(s["progress"] * 100)})
    debtors = []
    last_pay = dict(db.session.query(Transaction.enrollment_id, func.max(Transaction.date))
                    .filter(Transaction.kind == "kirim", Transaction.enrollment_id.isnot(None))
                    .group_by(Transaction.enrollment_id).all())
    for e in Enrollment.query.filter(Enrollment.status != "chiqqan").all():
        due = F.enrollment_row(e, paid)["due"]
        if due > 0.01:
            lp = last_pay.get(e.id)
            debtors.append({"name": e.member.full_name, "programme": e.program.name, "due": _r(due),
                            "last_payment": lp.isoformat() if lp else None})
    debtors.sort(key=lambda d: -d["due"])
    exp = F.expiring_memberships(7, today)
    two_weeks = today - timedelta(days=14)
    marks = (db.session.query(Attendance.status).join(Lesson, Attendance.lesson_id == Lesson.id)
             .filter(Lesson.date >= two_weeks, Lesson.date <= today).all())
    present = sum(1 for (s,) in marks if s in ("keldi", "kechikdi"))
    return {
        "today": today.isoformat(),
        "balances": [{"account": r["account"].name, "currency": r["account"].currency, "balance": _r(r["balance"])}
                     for r in F.accounts_with_balance()],
        "total_balance_uzs": _r(F.total_balance_uzs()),
        "this_month_so_far": tot(m0, today),
        "last_month_same_days": tot(pm0, pm_same),
        "last_month_full": tot(pm0, m0 - timedelta(days=1)),
        "last_7_days": tot(w0, today),
        "previous_7_days": tot(pw0, pw1),
        "expenses_this_month_by_group": {i["name"]: _r(i["value"]) for i in F.breakdown("chiqim", m0, today)},
        "expenses_last_month_by_group": {i["name"]: _r(i["value"]) for i in F.breakdown("chiqim", pm0, m0 - timedelta(days=1))},
        "income_this_month_by_programme": _program_income(m0, today),
        "monthly_trend_6": [{"month": b["full"], "income": _r(b["income"]), "expense": _r(b["expense"]),
                             "profit": _r(b["profit"])} for b in F.monthly_series(6, today)],
        "programmes": programs,
        "students_total_due": _r(sum(d["due"] for d in debtors)),
        "debtors_count": len(debtors),
        "top_debtors": debtors[:10],
        "memberships_expiring_7_days": [{"name": e.member.full_name, "programme": e.program.name,
                                         "valid_until": e.valid_until.isoformat()} for e in exp[:10]],
        "loans": {k: (_r(v) if isinstance(v, float) else v) for k, v in F.debts_summary().items()},
        "attendance_last_14_days_pct": round(present / len(marks) * 100) if marks else None,
    }


SYSTEM = """You are the financial analyst of an Islamic business-education centre in Uzbekistan
(courses and business clubs). You receive exact figures as JSON (amounts in UZS unless a currency is
given). Write in Uzbek (Latin script), plainly, like a trusted CFO talking to the owner.

Rules:
- Use ONLY numbers present in the data or simple arithmetic on them. Never invent figures, names or
  causes the data does not show; if something can't be explained from the data, say so.
- Write money as "12.5 mln", "850 ming" (so'm). Percentages rounded.
- Formatting: Telegram HTML - only <b> and <i> tags, line breaks, emoji bullets. No markdown,
  no tables, no headings with #.
- Islamic finance context: no interest (riba) advice; recommend fair, respectful collection.
"""

WEEKLY = """Write the weekly report (max ~1500 characters) with these parts:
📊 <b>Haftalik moliyaviy hisobot</b> + date
1) 3-4 lines of key numbers: balance, this month income/expense/profit vs the same days last month,
   last 7 days vs previous 7 days.
2) ✅ What is going well (1-2 points).
3) ⚠️ What needs attention (2-3 points: biggest expense changes, low collection programmes, top debtors
   by name with amounts, expiring memberships).
4) 🎯 <b>Bu hafta 3 ta qadam</b> - three concrete, specific actions (who/what), numbered.

DATA:
"""

ANSWER = """Answer the owner's question using the data. Be specific with names and numbers, max ~900
characters, finish with one practical suggestion if relevant. If the data cannot answer it, say what
is missing.

DATA:
"""


def sanitize(text):
    """Telegram/HTML uchun xavfsiz: faqat <b> va <i> qoladi."""
    safe = html.escape(text or "", quote=False)
    return re.sub(r"&lt;(/?)(b|i)&gt;", r"<\1\2>", safe)


def _data_json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def weekly(user_id=None, today=None, period=None):
    """Hisobotni tuzadi va saqlaydi. Natija: AiReport."""
    today = today or date.today()
    data = snapshot(today)
    text = ai.ask(SYSTEM, WEEKLY + _data_json(data), feature="hisobot", user_id=user_id, effort="medium",
                  max_tokens=16000)
    rep = AiReport(period=period or f"qo'lda:{datetime.now():%Y-%m-%d %H:%M:%S}", text=sanitize(text),
                   data=_data_json(data), created_by=user_id)
    db.session.add(rep)
    db.session.commit()
    return rep


def answer(question, user_id=None, today=None):
    data = snapshot(today)
    text = ai.ask(SYSTEM, ANSWER + _data_json(data) + "\n\nQUESTION: " + question[:1000],
                  feature="savol", user_id=user_id, effort="medium", max_tokens=16000)
    return sanitize(text)


def latest():
    return AiReport.query.order_by(AiReport.created_at.desc()).first()


def recipients():
    """Haftalik hisobot oladiganlar: Telegram'ga ulangan rahbar va buxgalterlar."""
    return (StaffLink.query.join(User, StaffLink.user_id == User.id)
            .filter(StaffLink.active.is_(True), User.active.is_(True), User.role.in_(("rahbar", "buxgalter"))).all())


_tries = {}


def run_due(now=None):
    """Fon oqimi chaqiradi: belgilangan kun va soatda haftada bir marta hisobot."""
    if not ai.enabled() or F.get_setting("ai_weekly") != "1":
        return None
    now = now or datetime.now()
    try:
        day, hour = int(F.get_setting("ai_weekly_day") or 0), int(F.get_setting("ai_weekly_hour") or 9)
    except ValueError:
        day, hour = 0, 9
    if now.weekday() != day or now.hour < hour:
        return None
    y, w, _ = now.isocalendar()
    period = f"{y}-W{w:02d}"
    if AiReport.query.filter_by(period=period).first():
        return None
    last = _tries.get(period)
    if last and now - last < timedelta(hours=1):  # xato bo'lsa — soatiga bir martadan ko'p urinmaydi
        return None
    _tries[period] = now
    rep = weekly(today=now.date(), period=period)
    from core import telegram as T
    if T.enabled():
        for link in recipients():
            T.send(link.chat_id, rep.text)
    return rep
