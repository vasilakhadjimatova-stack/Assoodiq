from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from core import finance as F
from core.extensions import db
from core.models import (
    BILLING, PROGRAM_KINDS, PROGRAM_STATUS, Category, Enrollment, Member, Program,
    Transaction,
)
from views import form_date, form_date_opt, form_int, money, safe_next
from views.kassa import form_context

bp = Blueprint("dastur", __name__)


def _add_period(d, billing):
    if billing == "yillik":
        try:
            return d.replace(year=d.year + 1)
        except ValueError:  # 29-fevral
            return d.replace(year=d.year + 1, day=28)
    m = F.shift_month(d, 1)
    last = F.month_bounds(m)[1].day
    return m.replace(day=min(d.day, last))


# ── Dasturlar ───────────────────────────────────────────────────────────────

@bp.route("/dasturlar")
def programs():
    kind = request.args.get("tur", "")
    q = Program.query
    if kind in PROGRAM_KINDS:
        q = q.filter_by(kind=kind)
    order = {"faol": 0, "rejada": 1, "yakunlangan": 2}
    items = sorted(q.all(), key=lambda p: (order.get(p.status, 3), -(p.start_date or date.min).toordinal()))
    paid_map = F.enrollment_paid_map()
    stats = [F.program_stats(p, paid_map) for p in items]
    counts = {k: Program.query.filter_by(kind=k).count() for k in PROGRAM_KINDS}
    counts[""] = Program.query.count()
    return render_template("pages/programs.html", stats=stats, kind=kind, counts=counts,
                           kinds=PROGRAM_KINDS, statuses=PROGRAM_STATUS, billings=BILLING)


@bp.route("/dasturlar/saqlash", methods=["POST"])
@bp.route("/dasturlar/<int:pid>/saqlash", methods=["POST"])
def program_save(pid=None):
    f = request.form
    p = db.get_or_404(Program, pid) if pid else Program()
    name = (f.get("name") or "").strip()
    if not name:
        flash("Dastur nomini yozing.", "bad")
        return redirect(safe_next(url_for("dastur.programs")))
    p.name = name[:160]
    p.kind = f.get("kind") if f.get("kind") in PROGRAM_KINDS else "kurs"
    p.billing = f.get("billing") if f.get("billing") in BILLING else "bir_martalik"
    p.price = money(f.get("price"))
    p.currency = "USD" if f.get("currency") == "USD" else "UZS"
    p.start_date = form_date_opt(f.get("start_date"))
    p.end_date = form_date_opt(f.get("end_date"))
    p.capacity = form_int(f.get("capacity"))
    p.status = f.get("status") if f.get("status") in PROGRAM_STATUS else "faol"
    p.description = (f.get("description") or "").strip()
    if not pid:
        db.session.add(p)
    db.session.commit()
    flash("Dastur saqlandi.", "ok")
    return redirect(url_for("dastur.program", pid=p.id))


@bp.route("/dasturlar/<int:pid>")
def program(pid):
    p = db.get_or_404(Program, pid)
    paid_map = F.enrollment_paid_map()
    stat = F.program_stats(p, paid_map)
    enrs = p.enrollments.order_by(Enrollment.joined_at.desc()).all()
    rows = [F.enrollment_row(e, paid_map) for e in enrs]
    seg = request.args.get("holat", "")
    if seg == "qarzdor":
        rows = [r for r in rows if r["due"] > 0 and r["enrollment"].status != "chiqqan"]
    expenses = (Transaction.query.filter_by(program_id=p.id, kind="chiqim")
                .order_by(Transaction.date.desc()).all())
    members = Member.query.order_by(Member.full_name).all()
    return render_template("pages/program.html", p=p, stat=stat, rows=rows, seg=seg,
                           expenses=expenses, members=members, kinds=PROGRAM_KINDS,
                           statuses=PROGRAM_STATUS, billings=BILLING,
                           pay_category=_payment_category(p), **form_context())


def _payment_category(program):
    cat = Category.query.filter_by(kind="kirim", program_kind=program.kind, active=True).first()
    return cat or Category.query.filter_by(kind="kirim", active=True).order_by(Category.sort).first()


@bp.route("/dasturlar/<int:pid>/yozish", methods=["POST"])
def enroll(pid):
    p = db.get_or_404(Program, pid)
    f = request.form
    member = db.session.get(Member, form_int(f.get("member_id")) or 0)
    if member is None:
        name = (f.get("full_name") or "").strip()
        if not name:
            flash("A'zoni tanlang yoki yangi ism yozing.", "bad")
            return redirect(url_for("dastur.program", pid=pid))
        member = Member(full_name=name[:160], phone=(f.get("phone") or "").strip()[:40],
                        business=(f.get("business") or "").strip()[:160])
        db.session.add(member)
        db.session.flush()
    if p.enrollments.filter_by(member_id=member.id, status="faol").first():
        flash(f"{member.full_name} bu dasturda allaqachon bor.", "bad")
        return redirect(url_for("dastur.program", pid=pid))
    joined = form_date(f.get("joined_at"))
    price = money(f.get("price")) if (f.get("price") or "").strip() else p.price
    enr = Enrollment(member_id=member.id, program_id=p.id, price=price, joined_at=joined,
                     note=(f.get("note") or "").strip()[:255])
    if p.billing != "bir_martalik":
        enr.valid_until = _add_period(joined, p.billing) - timedelta(days=1)
    db.session.add(enr)
    db.session.commit()
    flash(f"{member.full_name} dasturga yozildi.", "ok")
    return redirect(url_for("dastur.program", pid=pid))


@bp.route("/yozilish/<int:eid>/uzaytirish", methods=["POST"])
def renew(eid):
    """Klub obunasini yana bir davrga uzaytirish: hisoblangan summa ham oshadi."""
    e = db.get_or_404(Enrollment, eid)
    p = e.program
    base = max(e.valid_until or date.today(), date.today() - timedelta(days=1))
    e.valid_until = _add_period(base + timedelta(days=1), p.billing) - timedelta(days=1)
    e.price += p.price
    e.status = "faol"
    db.session.commit()
    flash(f"{e.member.full_name}: obuna {e.valid_until.strftime('%d.%m.%Y')} gacha uzaytirildi.", "ok")
    return redirect(safe_next(url_for("dastur.program", pid=p.id)))


@bp.route("/yozilish/<int:eid>/holat", methods=["POST"])
def enrollment_status(eid):
    e = db.get_or_404(Enrollment, eid)
    st = request.form.get("status")
    if st in ("faol", "tugatgan", "chiqqan"):
        e.status = st
        db.session.commit()
        flash("Holat yangilandi.", "ok")
    return redirect(safe_next(url_for("dastur.program", pid=e.program_id)))


# ── A'zolar ─────────────────────────────────────────────────────────────────

@bp.route("/azolar")
def members():
    seg = request.args.get("holat", "")
    q_text = (request.args.get("q") or "").strip()
    q = Member.query
    if q_text:
        like = f"%{q_text}%"
        q = q.filter(or_(Member.full_name.ilike(like), Member.phone.ilike(like), Member.business.ilike(like)))
    paid_map = F.enrollment_paid_map()
    expiring_ids = {e.member_id for e in F.expiring_memberships(7)}
    rows = []
    for m in q.order_by(Member.full_name).all():
        enrs = [F.enrollment_row(e, paid_map) for e in m.enrollments.all()]
        active = [r for r in enrs if r["enrollment"].status != "chiqqan"]
        rows.append({
            "member": m,
            "programs": [r["enrollment"].program for r in active],
            "paid": sum(r["paid"] for r in enrs),
            "due": sum(r["due"] for r in active),
            "club": any(r["enrollment"].program.kind == "klub" and r["enrollment"].status == "faol" for r in enrs),
            "expiring": m.id in expiring_ids,
        })
    counts = {
        "": len(rows),
        "qarzdor": sum(1 for r in rows if r["due"] > 0),
        "klub": sum(1 for r in rows if r["club"]),
        "tugayapti": sum(1 for r in rows if r["expiring"]),
    }
    filt = {"qarzdor": lambda r: r["due"] > 0, "klub": lambda r: r["club"],
            "tugayapti": lambda r: r["expiring"]}.get(seg)
    if filt:
        rows = [r for r in rows if filt(r)]
    return render_template("pages/members.html", rows=rows, seg=seg, counts=counts, q=q_text,
                           total_due=sum(r["due"] for r in rows))


@bp.route("/azolar/saqlash", methods=["POST"])
@bp.route("/azolar/<int:mid>/saqlash", methods=["POST"])
def member_save(mid=None):
    f = request.form
    m = db.get_or_404(Member, mid) if mid else Member()
    name = (f.get("full_name") or "").strip()
    if not name:
        flash("Ism-familiyani yozing.", "bad")
        return redirect(safe_next(url_for("dastur.members")))
    m.full_name = name[:160]
    m.phone = (f.get("phone") or "").strip()[:40]
    m.business = (f.get("business") or "").strip()[:160]
    m.city = (f.get("city") or "").strip()[:80]
    m.note = (f.get("note") or "").strip()
    if not mid:
        db.session.add(m)
    db.session.commit()
    flash("A'zo saqlandi.", "ok")
    return redirect(url_for("dastur.member", mid=m.id))


@bp.route("/azolar/<int:mid>")
def member(mid):
    m = db.get_or_404(Member, mid)
    paid_map = F.enrollment_paid_map()
    enrs = [F.enrollment_row(e, paid_map) for e in m.enrollments.order_by(Enrollment.joined_at.desc()).all()]
    eids = [r["enrollment"].id for r in enrs]
    payments = (Transaction.query.filter(Transaction.enrollment_id.in_(eids))
                .order_by(Transaction.date.desc()).all()) if eids else []
    return render_template("pages/member.html", m=m, enrs=enrs, payments=payments,
                           total_paid=sum(r["paid"] for r in enrs),
                           total_due=sum(r["due"] for r in enrs if r["enrollment"].status != "chiqqan"),
                           pay_categories={r["enrollment"].id: _payment_category(r["enrollment"].program) for r in enrs},
                           **form_context())
