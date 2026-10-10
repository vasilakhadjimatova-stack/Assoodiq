from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func

from core import finance as F
from core import hijri
from core.extensions import db
from core.models import AQD_TYPES, Transaction, ZakatSnapshot
from views import form_date_opt, money
from views.kassa import form_context

bp = Blueprint("islomiy", __name__)

FIELDS = ("cash", "receivables", "inventory", "other_assets", "liabilities")


@bp.route("/zakot")
def zakat():
    today = date.today()
    defaults = F.zakat_defaults()
    values = {k: money(request.args[k]) if k in request.args else defaults[k] for k in FIELDS}
    basis = request.args.get("nisob") or F.get_setting("nisob_basis")
    if basis not in F.NISOB_GRAMS:
        basis = "oltin"
    nisob = F.nisob_value(basis)
    result = F.zakat_compute(nisob=nisob, **values)

    hawl_raw = F.get_setting("hawl_start")
    hawl = None
    if hawl_raw:
        start = date.fromisoformat(hawl_raw)
        nxt = hijri.next_hawl(start, today)
        hawl = {"start": start, "date": nxt, "days": (nxt - today).days}

    zcat = F.system_category("zakot")
    paid_year = 0.0
    if zcat:
        paid_year = (db.session.query(func.coalesce(func.sum(Transaction.amount_uzs), 0))
                     .filter(Transaction.kind == "chiqim", Transaction.category_id == zcat.id,
                             Transaction.date >= date(today.year, 1, 1)).scalar())
    return render_template(
        "pages/zakat.html", values=values, defaults=defaults, result=result, nisob=nisob,
        basis=basis, grams=F.NISOB_GRAMS, gold=F.setting_float("gold_price_g"),
        silver=F.setting_float("silver_price_g"), hawl=hawl, hijri_today=hijri.format_hijri(today),
        history=ZakatSnapshot.query.order_by(ZakatSnapshot.date.desc()).limit(10).all(),
        zcat=zcat, paid_year=paid_year, **form_context(),
    )


@bp.route("/zakot/saqlash", methods=["POST"])
def zakat_save():
    f = request.form
    values = {k: money(f.get(k)) for k in FIELDS}
    basis = f.get("nisob") if f.get("nisob") in F.NISOB_GRAMS else "oltin"
    nisob = F.nisob_value(basis)
    res = F.zakat_compute(nisob=nisob, **values)
    snap = ZakatSnapshot(date=date.today(), hijri=hijri.format_hijri(date.today()), nisob_basis=basis,
                         nisob_value=nisob, base=res["base"], due=res["due"],
                         note=(f.get("note") or "").strip(), **values)
    db.session.add(snap)
    db.session.commit()
    flash("Zakot hisobi tarixga saqlandi.", "ok")
    return redirect(url_for("islomiy.zakat"))


@bp.route("/zakot/havl", methods=["POST"])
def hawl_save():
    d = form_date_opt(request.form.get("hawl_start"))
    F.set_setting("hawl_start", d.isoformat() if d else "")
    db.session.commit()
    flash("Havl sanasi saqlandi.", "ok")
    return redirect(url_for("islomiy.zakat"))


@bp.route("/halollik")
def purity():
    today = date.today()
    flagged = (Transaction.query.filter(Transaction.kind == "kirim",
                                        Transaction.shariat.in_(("shubhali", "nohalol")))
               .order_by(Transaction.date.desc()).all())
    by_aqd = (db.session.query(Transaction.aqd, func.sum(Transaction.amount_uzs))
              .filter(Transaction.kind == "kirim", Transaction.date >= date(today.year, 1, 1))
              .group_by(Transaction.aqd).all())
    total = sum(v or 0 for _, v in by_aqd) or 1
    aqd_rows = sorted(({"name": AQD_TYPES.get(k or "", "Belgilanmagan"), "value": v or 0,
                        "share": (v or 0) / total} for k, v in by_aqd), key=lambda r: -r["value"])
    untagged = sum(r["value"] for r in aqd_rows if r["name"] == "Belgilanmagan")
    return render_template(
        "pages/purity.html", fund=F.purification_fund(), sadaqa=F.sadaqa_status(today.year),
        flagged=flagged, aqd_rows=aqd_rows, untagged=untagged,
        tcat=F.system_category("tozalash"), scat=F.system_category("sadaqa"),
        sadaqa_percent=F.setting_float("sadaqa_percent"), **form_context(),
    )
