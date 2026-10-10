from datetime import date

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import or_

from core import finance as F
from core.extensions import db
from core.models import (
    AQD_TYPES, SHARIAT, Account, Category, Enrollment, Program, Transaction,
)
from views import form_date, form_int, money, safe_next

bp = Blueprint("kassa", __name__, url_prefix="/kassa")

KIND_FILTERS = {
    "": "Hammasi",
    "kirim": "Kirim",
    "chiqim": "Chiqim",
    "otkazma": "O'tkazma",
    "qarz": "Qarz",
}


def _month_arg():
    raw = request.args.get("oy", "")
    try:
        y, m = (int(x) for x in raw.split("-"))
        return date(y, m, 1)
    except ValueError:
        return date.today().replace(day=1)


@bp.route("/")
def ledger():
    month = _month_arg()
    start, end = F.month_bounds(month)
    kind = request.args.get("tur", "")
    acc_id = form_int(request.args.get("hisob"))
    q_text = (request.args.get("q") or "").strip()

    base = Transaction.query.filter(Transaction.date >= start, Transaction.date <= end)
    if acc_id:
        base = base.filter(or_(Transaction.account_id == acc_id, Transaction.to_account_id == acc_id))
    if q_text:
        like = f"%{q_text}%"
        base = base.filter(or_(Transaction.counterparty.ilike(like), Transaction.note.ilike(like)))

    counts = {}
    for k in KIND_FILTERS:
        counts[k] = _kind_filter(base, k).count()
    rows = _kind_filter(base, kind).order_by(Transaction.date.desc(), Transaction.id.desc()).all()

    totals = F.period_totals(start, end)
    return render_template(
        "pages/kassa.html",
        rows=rows, kind=kind, kinds=KIND_FILTERS, counts=counts, acc_id=acc_id, q=q_text,
        month=month, prev_month=F.shift_month(month, -1), next_month=F.shift_month(month, 1),
        month_name=f"{F.MONTHS_FULL[month.month - 1]} {month.year}",
        totals=totals, **form_context(),
    )


def _kind_filter(q, kind):
    if kind == "qarz":
        return q.filter(Transaction.kind.in_(("qarz_kirim", "qarz_chiqim")))
    if kind:
        return q.filter(Transaction.kind == kind)
    return q


def form_context():
    """Kirim/chiqim oynasi uchun ro'yxatlar (boshqa sahifalar ham ishlatadi)."""
    return {
        "f_accounts": F.accounts_with_balance(),
        "f_categories": Category.query.filter_by(active=True).order_by(Category.kind, Category.sort, Category.name).all(),
        "f_programs": Program.query.filter(Program.status != "yakunlangan").order_by(Program.name).all(),
        "aqd_types": AQD_TYPES,
        "shariat_types": SHARIAT,
    }


@bp.route("/yangi", methods=["POST"])
def create():
    f = request.form
    kind = f.get("kind", "kirim")
    if g.user.role == "menejer" and kind != "kirim":
        flash("Menejer faqat kirim yozishi mumkin.", "bad")
        return _back()
    if kind not in ("kirim", "chiqim", "otkazma"):
        kind = "kirim"
    amount = money(f.get("amount"))
    account = db.session.get(Account, form_int(f.get("account_id")) or 0)
    if amount <= 0 or account is None:
        flash("Summa va hisobni ko'rsating.", "bad")
        return _back()

    fields = {
        "date": form_date(f.get("date")),
        "note": (f.get("note") or "").strip()[:500],
        "counterparty": (f.get("counterparty") or "").strip()[:160],
        "created_by": g.user.id,
    }
    if kind == "otkazma":
        to_acc = db.session.get(Account, form_int(f.get("to_account_id")) or 0)
        if to_acc is None or to_acc.id == account.id:
            flash("O'tkazma uchun boshqa hisobni tanlang.", "bad")
            return _back()
        to_amount = money(f.get("to_amount"))
        if not to_amount:
            to_amount = round(F.convert(amount, account.currency, to_acc.currency), 2)
        fields.update(to_account_id=to_acc.id, to_amount=to_amount)
    else:
        cat = db.session.get(Category, form_int(f.get("category_id")) or 0)
        fields["category_id"] = cat.id if cat and cat.kind == kind else None
        prog = db.session.get(Program, form_int(f.get("program_id")) or 0)
        fields["program_id"] = prog.id if prog else None
        enr = db.session.get(Enrollment, form_int(f.get("enrollment_id")) or 0)
        if enr and kind == "kirim":
            fields["enrollment_id"] = enr.id
            fields["program_id"] = enr.program_id
            if not fields["counterparty"]:
                fields["counterparty"] = enr.member.full_name
        if kind == "kirim":
            fields["aqd"] = f.get("aqd") if f.get("aqd") in AQD_TYPES else ""
            fields["shariat"] = f.get("shariat") if f.get("shariat") in SHARIAT else "halol"

    F.record(kind, amount, account, **fields)
    db.session.commit()
    flash(f"{'Kirim' if kind == 'kirim' else 'Chiqim' if kind == 'chiqim' else 'O‘tkazma'} saqlandi: "
          f"{amount:,.0f} {'$' if account.currency == 'USD' else 'so‘m'}".replace(",", " "), "ok")
    if f.get("again"):
        return redirect(_back_url() + ("&" if "?" in _back_url() else "?") + f"yangi={kind}")
    return _back()


@bp.route("/<int:tx_id>/ochirish", methods=["POST"])
def delete(tx_id):
    if g.user.role == "menejer":
        flash("O'chirish uchun ruxsat yo'q.", "bad")
        return _back()
    tx = db.get_or_404(Transaction, tx_id)
    db.session.delete(tx)
    db.session.commit()
    flash("Yozuv o'chirildi.", "ok")
    return _back()


def _back_url():
    return safe_next(url_for("kassa.ledger"))


def _back():
    return redirect(_back_url())
