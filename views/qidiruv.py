"""Global qidiruv (Ctrl+K): a'zolar, dasturlar, kassa yozuvlari va qarzlar."""
from flask import Blueprint, g, render_template, request
from sqlalchemy import or_

from core.models import Debt, Member, Program, Transaction

bp = Blueprint("qidiruv", __name__, url_prefix="/qidiruv")

LIMIT = 15


@bp.route("/")
def search():
    q = (request.args.get("q") or "").strip()
    res = {"members": [], "programs": [], "txs": [], "debts": []}
    if len(q) >= 2:
        like = f"%{q}%"
        res["members"] = (Member.query.filter(or_(Member.full_name.ilike(like), Member.phone.ilike(like),
                                                  Member.business.ilike(like), Member.city.ilike(like)))
                          .order_by(Member.full_name).limit(LIMIT).all())
        res["programs"] = Program.query.filter(Program.name.ilike(like)).order_by(Program.name).limit(LIMIT).all()
        txq = Transaction.query.filter(or_(Transaction.counterparty.ilike(like), Transaction.note.ilike(like)))
        if g.user.role == "menejer":
            txq = txq.filter(Transaction.kind == "kirim")
        res["txs"] = txq.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(LIMIT).all()
        if g.user.role != "menejer":
            res["debts"] = (Debt.query.filter(or_(Debt.counterparty.ilike(like), Debt.note.ilike(like),
                                                  Debt.witness.ilike(like)))
                            .order_by(Debt.date.desc()).limit(LIMIT).all())
    total = sum(len(v) for v in res.values())
    return render_template("pages/search.html", q=q, total=total, **res)
