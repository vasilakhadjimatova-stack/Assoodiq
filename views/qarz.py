from datetime import date

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from core import finance as F
from core.extensions import db
from core.models import DEBT_DIRECTIONS, Account, Debt, Transaction
from views import form_date, form_date_opt, form_int, money

bp = Blueprint("qarz", __name__, url_prefix="/qarz")


@bp.route("/")
def debts():
    seg = request.args.get("holat", "ochiq")
    today = date.today()
    rows = []
    for d in Debt.query.order_by(Debt.closed, Debt.due_date.is_(None), Debt.due_date, Debt.date.desc()).all():
        rem = F.debt_remaining(d)
        rows.append({"debt": d, "remaining": rem, "paid": d.amount - rem,
                     "progress": (d.amount - rem) / d.amount if d.amount else 1,
                     "overdue": (not d.closed) and rem > 0 and d.due_date and d.due_date < today})
    counts = {
        "ochiq": sum(1 for r in rows if not r["debt"].closed),
        "otgan": sum(1 for r in rows if r["overdue"]),
        "yopilgan": sum(1 for r in rows if r["debt"].closed),
    }
    filt = {"ochiq": lambda r: not r["debt"].closed, "otgan": lambda r: r["overdue"],
            "yopilgan": lambda r: r["debt"].closed}.get(seg, lambda r: True)
    return render_template("pages/debts.html", rows=[r for r in rows if filt(r)], seg=seg,
                           counts=counts, summary=F.debts_summary(), directions=DEBT_DIRECTIONS,
                           f_accounts=F.accounts_with_balance())


@bp.route("/yangi", methods=["POST"])
def create():
    f = request.form
    direction = f.get("direction") if f.get("direction") in DEBT_DIRECTIONS else "berilgan"
    amount = money(f.get("amount"))
    name = (f.get("counterparty") or "").strip()
    if amount <= 0 or not name:
        flash("Kim va qancha ekanini yozing.", "bad")
        return redirect(url_for("qarz.debts"))
    acc = db.session.get(Account, form_int(f.get("account_id")) or 0)
    debt = Debt(direction=direction, counterparty=name[:160], phone=(f.get("phone") or "").strip()[:40],
                amount=amount, currency=acc.currency if acc else ("USD" if f.get("currency") == "USD" else "UZS"),
                date=form_date(f.get("date")), due_date=form_date_opt(f.get("due_date")),
                witness=(f.get("witness") or "").strip()[:160], note=(f.get("note") or "").strip())
    db.session.add(debt)
    db.session.flush()
    if acc:  # pul hozir hisobdan chiqdi / hisobga tushdi
        F.record("qarz_chiqim" if direction == "berilgan" else "qarz_kirim", amount, acc,
                 date=debt.date, debt_id=debt.id, counterparty=debt.counterparty,
                 note="Qarz berildi" if direction == "berilgan" else "Qarz olindi", created_by=g.user.id)
    db.session.commit()
    flash("Qarz daftarga yozildi.", "ok")
    return redirect(url_for("qarz.debts"))


@bp.route("/<int:did>/qaytarish", methods=["POST"])
def repay(did):
    d = db.get_or_404(Debt, did)
    f = request.form
    acc = db.session.get(Account, form_int(f.get("account_id")) or 0)
    amount = money(f.get("amount"))
    if acc is None or amount <= 0:
        flash("Summa va hisobni ko'rsating.", "bad")
        return redirect(url_for("qarz.debts"))
    F.record("qarz_kirim" if d.direction == "berilgan" else "qarz_chiqim", amount, acc,
             date=form_date(f.get("date")), debt_id=d.id, counterparty=d.counterparty,
             note="Qarz qaytarildi", created_by=g.user.id)
    db.session.flush()
    if F.debt_remaining(d) <= 0.01:
        d.closed = True
    db.session.commit()
    flash("Qaytarilgan summa yozildi." + (" Qarz to'liq yopildi." if d.closed else ""), "ok")
    return redirect(url_for("qarz.debts"))


@bp.route("/<int:did>/yopish", methods=["POST"])
def toggle(did):
    d = db.get_or_404(Debt, did)
    d.closed = not d.closed
    db.session.commit()
    flash("Qarz yopildi." if d.closed else "Qarz qayta ochildi.", "ok")
    return redirect(url_for("qarz.debts"))


@bp.route("/<int:did>")
def detail(did):
    d = db.get_or_404(Debt, did)
    moves = d.moves.order_by(Transaction.date).all()
    return render_template("pages/debt.html", d=d, moves=moves, remaining=F.debt_remaining(d),
                           f_accounts=F.accounts_with_balance())
