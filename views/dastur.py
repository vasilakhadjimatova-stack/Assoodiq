import re
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_

from core import finance as F
from core.extensions import db
from core.models import (
    BILLING, PROGRAM_KINDS, PROGRAM_STATUS, Account, Category, Debt, Enrollment, Member, MemberEvent, Program,
    Transaction,
)
from core import audit
from views import form_date, form_date_opt, form_int, money, require_role, safe_next
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
    # Holat bo'yicha guruhlar: faol → rejada → yakunlangan
    groups = [(st, PROGRAM_STATUS[st], [s for s in stats if s["program"].status == st])
              for st in ("faol", "rejada", "yakunlangan")]
    groups = [g for g in groups if g[2]]
    active = [s for s in stats if s["program"].status == "faol"]
    summary = {
        "active": len(active),
        "members": sum(s["members"] for s in active),
        "collected": sum(s["collected"] for s in stats),
        "expected": sum(s["expected"] for s in stats),
        "due": sum(s["due"] for s in stats),
        "debtors": sum(s["debtors"] for s in stats),
        "profit": sum(s["profit"] for s in stats),
        "expenses": sum(s["expenses"] for s in stats),
    }
    summary["margin"] = summary["profit"] / summary["collected"] if summary["collected"] else 0
    summary["progress"] = min(summary["collected"] / summary["expected"], 1) if summary["expected"] else 0
    best = max(stats, key=lambda s: s["profit"], default=None)
    return render_template("pages/programs.html", stats=stats, groups=groups, summary=summary, best=best,
                           kind=kind, counts=counts, kinds=PROGRAM_KINDS, statuses=PROGRAM_STATUS,
                           billings=BILLING)


@bp.route("/dasturlar/saqlash", methods=["POST"])
@bp.route("/dasturlar/<int:pid>/saqlash", methods=["POST"])
def program_save(pid=None):
    require_role("rahbar", "buxgalter")
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
    db.session.flush()
    audit.log("program_save", f"#{p.id} {p.name}, narx {p.price:,.0f} {p.currency}".replace(",", " "))
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
    from core.calendar import color_for
    from core.models import Lesson
    next_lessons = (Lesson.query.filter(Lesson.program_id == p.id, Lesson.date >= date.today(),
                                        Lesson.status != "bekor").order_by(Lesson.date, Lesson.start).limit(6).all())
    lesson_stat = {"total": p.lessons.filter(Lesson.status != "bekor").count(),
                   "done": p.lessons.filter_by(status="otdi").count()}
    from core.attendance import PRESENT
    from core.models import Attendance
    marks = (db.session.query(Attendance.status).join(Lesson, Attendance.lesson_id == Lesson.id)
             .filter(Lesson.program_id == p.id).all())
    lesson_stat["att"] = (sum(1 for (st,) in marks if st in PRESENT) / len(marks)) if marks else None
    from core import telegram as T
    from core.models import TelegramLink
    mids = [r["enrollment"].member_id for r in rows if r["enrollment"].status == "faol"]
    tg = {"enabled": T.enabled(), "members": len(set(mids)),
          "linked": TelegramLink.query.filter(TelegramLink.member_id.in_(mids), TelegramLink.active.is_(True)).count() if mids else 0,
          "debtors": sum(1 for r in rows if r["due"] > 0 and r["enrollment"].status != "chiqqan")}
    return render_template("pages/program.html", p=p, stat=stat, rows=rows, seg=seg,
                           next_lessons=next_lessons, lesson_stat=lesson_stat, color=color_for(p.id), tg=tg,
                           expenses=expenses, members=members, kinds=PROGRAM_KINDS,
                           statuses=PROGRAM_STATUS, billings=BILLING,
                           pay_category=_payment_category(p), transfer_targets=transfer_targets(),
                           **form_context())


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
    _enroll(p, member, f)
    return redirect(url_for("dastur.program", pid=pid))


@bp.route("/azolar/<int:mid>/yozish", methods=["POST"])
def member_enroll(mid):
    """O'quvchi kartasidan boshqa dasturga yozish."""
    member = db.get_or_404(Member, mid)
    p = db.session.get(Program, form_int(request.form.get("program_id")) or 0)
    if p is None:
        flash("Dasturni tanlang.", "bad")
    else:
        _enroll(p, member, request.form)
    return redirect(url_for("dastur.member", mid=mid))


def _enroll(p, member, f):
    if p.enrollments.filter_by(member_id=member.id, status="faol").first():
        flash(f"{member.full_name} bu dasturda allaqachon bor.", "bad")
        return None
    joined = form_date(f.get("joined_at"))
    price = money(f.get("price")) if (f.get("price") or "").strip() else p.price
    enr = Enrollment(member_id=member.id, program_id=p.id, price=price, joined_at=joined,
                     note=(f.get("note") or "").strip()[:255])
    if p.billing != "bir_martalik":
        enr.valid_until = _add_period(joined, p.billing) - timedelta(days=1)
    db.session.add(enr)
    db.session.commit()
    flash(f"{member.full_name} dasturga yozildi.", "ok")
    return enr


def _event(enr, kind, text, amount=None, on=None):
    """on — voqea sanasi (o'tgan sana bilan kiritilsa tarixda o'z o'rnida turadi)."""
    ev = MemberEvent(member_id=enr.member_id, enrollment_id=enr.id, kind=kind, text=text[:255],
                     amount=amount, user_id=g.user.id if g.get("user") else None)
    if on is not None and on != date.today():
        ev.created_at = datetime.combine(on, datetime.min.time())
    db.session.add(ev)


@bp.route("/yozilish/<int:eid>/uzaytirish", methods=["POST"])
def renew(eid):
    """Klub obunasini yana bir davrga uzaytirish: hisoblangan summa ham oshadi."""
    e = db.get_or_404(Enrollment, eid)
    p = e.program
    base = max(e.valid_until or date.today(), date.today() - timedelta(days=1))
    e.valid_until = _add_period(base + timedelta(days=1), p.billing) - timedelta(days=1)
    e.price += p.price
    e.status = "faol"
    _event(e, "renew", f"«{p.name}» obunasi {e.valid_until:%d.%m.%Y} gacha uzaytirildi", p.price)
    db.session.commit()
    flash(f"{e.member.full_name}: obuna {e.valid_until.strftime('%d.%m.%Y')} gacha uzaytirildi.", "ok")
    return redirect(safe_next(url_for("dastur.program", pid=p.id)))


@bp.route("/yozilish/otkazish", methods=["POST"])
def transfer():
    """A'zoni bir dasturdan (klubdan) boshqasiga o'tkazish.

    Eski yozilish yopiladi («chiqqan»), yangi dasturda yozilish ochiladi va eski
    dasturga qilingan to'lovlar yangisiga o'tadi: eski dastur daromadi shuncha
    kamayadi, yangisiniki oshadi. Kassadagi summalar o'zgarmaydi.
    """
    if g.user.role == "menejer":
        flash("O'tkazish uchun ruxsat yo'q.", "bad")
        return redirect(safe_next(url_for("dastur.members")))
    f = request.form
    e = db.get_or_404(Enrollment, form_int(f.get("eid")) or 0)
    back = safe_next(url_for("dastur.member", mid=e.member_id))
    target = db.session.get(Program, form_int(f.get("program_id")) or 0)
    if target is None or target.id == e.program_id:
        flash("Boshqa dasturni tanlang.", "bad")
        return redirect(back)
    if e.status == "chiqqan":
        flash("Bu yozilish allaqachon yopilgan.", "bad")
        return redirect(back)
    if target.enrollments.filter_by(member_id=e.member_id, status="faol").first():
        flash(f"{e.member.full_name} «{target.name}» dasturida allaqachon bor.", "bad")
        return redirect(back)
    when = form_date(f.get("date"))
    price = money(f.get("price")) if (f.get("price") or "").strip() else target.price
    old = e.program
    new = Enrollment(member_id=e.member_id, program_id=target.id, price=price, joined_at=when,
                     note=f"«{old.name}» dan o'tkazildi"[:255])
    if target.billing != "bir_martalik":
        new.valid_until = _add_period(when, target.billing) - timedelta(days=1)
    db.session.add(new)
    db.session.flush()
    moved = 0.0
    for t in Transaction.query.filter_by(enrollment_id=e.id, kind="kirim").all():
        t.enrollment_id, t.program_id = new.id, target.id
        moved += t.amount_uzs
    e.status = "chiqqan"
    e.note = f"→ «{target.name}» ga o'tkazildi {when:%d.%m.%Y}"[:255]
    reason = (f.get("note") or "").strip()
    _event(new, "transfer", f"«{old.name}» → «{target.name}» ga o'tkazildi" + (f" · {reason}" if reason else ""),
           moved or None, on=when)
    audit.log("transfer", f"{e.member.full_name}: «{old.name}» → «{target.name}», {moved:,.0f} so'm".replace(",", " "))
    db.session.commit()
    msg = f"{e.member.full_name} «{target.name}» ga o'tkazildi"
    if moved:
        n = lambda v: f"{v:,.0f}".replace(",", " ")  # noqa: E731
        msg += f", {n(moved)} so'm to'lov ham o'tdi"
        price_uzs = F.to_uzs(price, target.currency)
        if moved > price_uzs + 0.01:
            msg += f" (ortiqcha {n(moved - price_uzs)} so'm — keyingi davrlarga hisoblanadi)"
    flash(msg + ".", "ok")
    return redirect(back)


@bp.route("/yozilish/qaytarish", methods=["POST"])
def refund():
    """O'quvchiga pul qaytarish.

    Kassada manfiy kirim bo'lib yoziladi (o'sha kategoriya va dasturga): hisob qoldig'i,
    dastur daromadi va foyda-zarardagi kirim shuncha kamayadi — xarajat bo'lib ko'rinmaydi.
    Keyin a'zolik yopiladi yoki (chegirma bo'lsa) hisoblangan narx kamaytiriladi.
    """
    if g.user.role == "menejer":
        flash("Pul qaytarish uchun ruxsat yo'q.", "bad")
        return redirect(safe_next(url_for("dastur.members")))
    f = request.form
    e = db.get_or_404(Enrollment, form_int(f.get("eid")) or 0)
    back = safe_next(url_for("dastur.member", mid=e.member_id))
    amount = money(f.get("amount"))
    account = db.session.get(Account, form_int(f.get("account_id")) or 0)
    if amount <= 0 or account is None:
        flash("Qaytariladigan summa va hisobni ko'rsating.", "bad")
        return redirect(back)
    paid = F.enrollment_paid_map().get(e.id, 0) or 0
    amount_uzs = F.to_uzs(amount, account.currency)
    if amount_uzs > paid + 0.01:
        flash(f"Qaytariladigan summa to'langanidan ({paid:,.0f} so'm) ko'p bo'lmasin.".replace(",", " "), "bad")
        return redirect(back)
    last = (Transaction.query.filter(Transaction.enrollment_id == e.id, Transaction.kind == "kirim",
                                     Transaction.amount > 0)
            .order_by(Transaction.date.desc()).first())
    cat = last.category if last and last.category else _payment_category(e.program)
    reason = (f.get("note") or "").strip()
    when = form_date(f.get("date"))
    F.record("kirim", -amount, account, date=when, category_id=cat.id if cat else None, program_id=e.program_id,
             enrollment_id=e.id, counterparty=e.member.full_name, shariat="halol", aqd="",
             note=("Pul qaytarildi" + (f": {reason}" if reason else ""))[:500], created_by=g.user.id)
    n = lambda v: f"{v:,.0f}".replace(",", " ")  # noqa: E731
    if f.get("then") == "chegirma":
        cut = F.convert(amount, account.currency, e.program.currency)
        e.price = round(max(e.price - cut, 0), 2)
        _event(e, "refund", f"«{e.program.name}»: narx {n(e.price)} ga kamaytirildi (pul qaytarildi)", on=when)
    elif e.status != "chiqqan":
        e.status = "chiqqan"
        _event(e, "status", f"«{e.program.name}»: dasturdan chiqdi, pul qaytarildi", on=when)
    audit.log("refund", f"{e.member.full_name}: «{e.program.name}», {n(amount)} "
                        f"{'$' if account.currency == 'USD' else 'so‘m'} {account.name} hisobidan")
    db.session.commit()
    flash(f"{e.member.full_name}ga {n(amount)} {'$' if account.currency == 'USD' else 'so‘m'} qaytarildi "
          f"({account.name}).", "ok")
    return redirect(back)


def transfer_targets():
    return (Program.query.filter(Program.status != "yakunlangan")
            .order_by(Program.kind, Program.name).all())


@bp.route("/yozilish/<int:eid>/holat", methods=["POST"])
def enrollment_status(eid):
    e = db.get_or_404(Enrollment, eid)
    st = request.form.get("status")
    if st in ("faol", "tugatgan", "chiqqan") and st != e.status:
        e.status = st
        label = {"faol": "faol deb belgilandi", "tugatgan": "dasturni tugatdi", "chiqqan": "dasturdan chiqdi"}[st]
        _event(e, "status", f"«{e.program.name}»: {label}")
        db.session.commit()
        flash("Holat yangilandi.", "ok")
    return redirect(safe_next(url_for("dastur.program", pid=e.program_id)))


# ── A'zolar ─────────────────────────────────────────────────────────────────

HOLAT = (("", "Hammasi"), ("faol", "Faol"), ("qarzdor", "Qarzdorlar"), ("tugayapti", "Obunasi tugayapti"),
         ("tugagan", "Obunasi tugagan"), ("yangi", "Yangi (30 kun)"), ("nofaol", "Nofaol"))
SORTS = (("ism", "Ism bo'yicha"), ("qarz", "Qarzi ko'p"), ("tolov_yangi", "Oxirgi to'lov — yangi"),
         ("tolov_eski", "Oxirgi to'lov — eski"), ("tolagan", "Ko'p to'lagan"), ("yangi", "Yangi qo'shilgan"))
HOLAT_TABS = ("", "faol", "qarzdor", "tugayapti", "nofaol")   # qolganlari — statistika kartochkalaridan
KIND_ALL = {"kurs": "Barcha kurslar", "klub": "Barcha klublar", "tadbir": "Barcha tadbirlar",
            "konsalting": "Barcha konsalting"}
HOLAT_TEST = {
    "faol": lambda r: r["active"],
    "qarzdor": lambda r: r["due"] > 0,
    "tugayapti": lambda r: r["expiring"],
    "tugagan": lambda r: r["expired"],
    "yangi": lambda r: r["new"],
    "nofaol": lambda r: not r["active"],
}


def member_filters(args):
    """URL parametrlari → tozalangan filtrlar."""
    f = {k: (args.get(k) or "").strip() for k in ("q", "holat", "dastur", "tur", "shahar", "tg", "ilova", "tartib")}
    f["holat"] = f["holat"] if f["holat"] in HOLAT_TEST else ""
    if f["dastur"].startswith("tur:"):          # dastur ro'yxatidagi «Barcha kurslar» kabi band
        f["tur"], f["dastur"] = f["dastur"][4:], ""
    f["dastur"] = form_int(f["dastur"])
    f["tur"] = f["tur"] if f["tur"] in PROGRAM_KINDS else ""
    f["tg"] = f["tg"] if f["tg"] in ("1", "0") else ""
    f["ilova"] = f["ilova"] if f["ilova"] in ("1", "0") else ""
    f["tartib"] = f["tartib"] if f["tartib"] in dict(SORTS) else "ism"
    return f


def member_rows(f):
    """Filtr qo'llangan a'zolar qatorlari va holat bo'yicha sonlar (boshqa filtrlar hisobga olingan)."""
    from core.attendance import parse_code
    from core.models import StudentAccess, TelegramLink
    today = date.today()
    q = Member.query
    if f["q"]:
        like = f"%{f['q']}%"
        conds = [Member.full_name.ilike(like), Member.phone.ilike(like), Member.business.ilike(like),
                 Member.city.ilike(like), Member.note.ilike(like)]
        digits = re.sub(r"\D", "", f["q"])
        if len(digits) >= 4:  # telefon raqami probel/qavslar bilan saqlangan bo'lsa ham topiladi
            conds.append(func.replace(func.replace(func.replace(Member.phone, " ", ""), "-", ""), "+", "").like(f"%{digits}%"))
        code_id = parse_code(f["q"])
        if code_id:
            conds.append(Member.id == code_id)
        q = q.filter(or_(*conds))
    if f["shahar"]:
        q = q.filter(Member.city == f["shahar"])
    paid_map = F.enrollment_paid_map()
    expiring_ids = {e.member_id for e in F.expiring_memberships(7) if e.valid_until >= today}
    last_pay = dict(
        db.session.query(Enrollment.member_id, func.max(Transaction.date))
        .join(Transaction, Transaction.enrollment_id == Enrollment.id)
        .filter(Transaction.kind == "kirim", Transaction.amount > 0).group_by(Enrollment.member_id).all()
    )
    tg_ids = {mid for (mid,) in db.session.query(TelegramLink.member_id).filter(TelegramLink.active.is_(True))}
    app_ids = {mid for (mid,) in db.session.query(StudentAccess.member_id).filter(StudentAccess.last_seen.isnot(None))}
    rows = []
    for m in q.all():
        enrs = [F.enrollment_row(e, paid_map) for e in m.enrollments.all()]
        active = [r for r in enrs if r["enrollment"].status != "chiqqan"]
        faol = [r["enrollment"] for r in enrs if r["enrollment"].status == "faol"]
        if f["dastur"] and not any(r["enrollment"].program_id == f["dastur"] for r in active):
            continue
        if f["tur"] and not any(r["enrollment"].program.kind == f["tur"] for r in active):
            continue
        if f["tg"] and (m.id in tg_ids) != (f["tg"] == "1"):
            continue
        if f["ilova"] and (m.id in app_ids) != (f["ilova"] == "1"):
            continue
        paid = sum(r["paid"] for r in enrs)
        due = sum(r["due"] for r in active)
        rows.append({
            "member": m,
            "programs": [r["enrollment"].program for r in sorted(active, key=lambda r: r["enrollment"].status != "faol")],
            "paid": paid,
            "due": due,
            "progress": paid / (paid + due) if paid + due else 1,
            "active": bool(faol),
            "club": any(e.program.kind == "klub" for e in faol),
            "expiring": m.id in expiring_ids,
            "expired": any(e.valid_until and e.valid_until < today for e in faol),
            "new": bool(m.created_at and m.created_at.date() >= today - timedelta(days=30)),
            "last_pay": last_pay.get(m.id),
            "tg": m.id in tg_ids,
            "app": m.id in app_ids,
        })
    counts = {k: (sum(1 for r in rows if HOLAT_TEST[k](r)) if k else len(rows)) for k, _ in HOLAT}
    if f["holat"]:
        rows = [r for r in rows if HOLAT_TEST[f["holat"]](r)]
    key = {
        "ism": lambda r: r["member"].full_name.lower(),
        "qarz": lambda r: -r["due"],
        "tolov_yangi": lambda r: -(r["last_pay"] or date.min).toordinal(),
        "tolov_eski": lambda r: (r["last_pay"] or date.min).toordinal(),
        "tolagan": lambda r: -r["paid"],
        "yangi": lambda r: -(r["member"].created_at or datetime.min).timestamp(),
    }[f["tartib"]]
    rows.sort(key=lambda r: (key(r), r["member"].full_name.lower()))
    return rows, counts


def member_filter_options():
    cities = [c for (c,) in db.session.query(Member.city).filter(Member.city != "").distinct().order_by(Member.city)]
    programs = (Program.query.filter(Program.enrollments.any())
                .order_by(Program.status != "faol", Program.kind, Program.name).all())
    return {"cities": cities, "programs": programs}


@bp.route("/azolar")
def members():
    f = member_filters(request.args)
    rows, counts = member_rows(f)
    opts = member_filter_options()
    pnames = {p.id: p.name for p in opts["programs"]}
    chips = []  # faol filtrlar: (yozuv, olib tashlash uchun parametr)
    if f["q"]:
        chips.append((f"«{f['q']}»", "q"))
    if f["holat"] and f["holat"] not in HOLAT_TABS:
        chips.append((dict(HOLAT)[f["holat"]], "holat"))
    if f["dastur"]:
        chips.append((pnames.get(f["dastur"], "Dastur"), "dastur"))
    if f["tur"]:
        chips.append((KIND_ALL.get(f["tur"], PROGRAM_KINDS[f["tur"]]), "tur"))
    if f["shahar"]:
        chips.append((f["shahar"], "shahar"))
    if f["tg"]:
        chips.append(("Telegram ulangan" if f["tg"] == "1" else "Telegram ulanmagan", "tg"))
    if f["ilova"]:
        chips.append(("Ilovadan foydalanadi" if f["ilova"] == "1" else "Ilovaga kirmagan", "ilova"))

    def url_with(**changes):
        args = {k: v for k, v in request.args.items() if v}
        for k, v in changes.items():
            if v in (None, ""):
                args.pop(k, None)
            else:
                args[k] = v
        return url_for("dastur.members", **args)

    summary = {"active": sum(1 for r in rows if r["active"]), "paid": sum(r["paid"] for r in rows),
               "debtors": sum(1 for r in rows if r["due"] > 0)}
    extra = sum(1 for k in ("dastur", "tur", "shahar", "tg", "ilova") if f[k])
    return render_template("pages/members.html", rows=rows, f=f, seg=f["holat"], q=f["q"], counts=counts,
                           holat=[h for h in HOLAT if h[0] in HOLAT_TABS], sorts=SORTS, kind_all=KIND_ALL, kinds=PROGRAM_KINDS, chips=chips, url_with=url_with,
                           extra=extra, total_due=sum(r["due"] for r in rows), summary=summary, **opts)


@bp.route("/azolar/excel")
def members_export():
    from io import BytesIO

    from flask import send_file
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    if g.user.role == "menejer":
        flash("Eksport uchun ruxsat yo'q.", "bad")
        return redirect(url_for("dastur.members", **request.args))
    from core.attendance import member_code
    rows, _ = member_rows(member_filters(request.args))
    wb = Workbook()
    ws = wb.active
    ws.title = "A'zolar"
    ws.append(["Ism", "Telefon", "Biznesi", "Shahar", "Dasturlar", "To'lagan, so'm", "Qoldiq, so'm",
               "Oxirgi to'lov", "Telegram", "Ilova", "A'zo kodi", "Qo'shilgan"])
    for c in ws[1]:
        c.font, c.fill = Font(bold=True), PatternFill("solid", fgColor="E0F1E9")
    for r in rows:
        m = r["member"]
        ws.append([m.full_name, m.phone, m.business, m.city, ", ".join(p.name for p in r["programs"]),
                   round(r["paid"]), round(r["due"]), r["last_pay"], "ha" if r["tg"] else "", "ha" if r["app"] else "",
                   member_code(m.id), m.created_at.date() if m.created_at else None])
    last = ws.max_row
    ws.append(["Jami", f"{len(rows)} kishi", "", "", "", f"=SUM(F2:F{last})" if last >= 2 else 0,
               f"=SUM(G2:G{last})" if last >= 2 else 0])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for row in ws.iter_rows(min_row=2):
        row[5].number_format = row[6].number_format = "# ##0"
        row[7].number_format = row[11].number_format = "DD.MM.YYYY"
    for i, w in enumerate((26, 18, 26, 14, 40, 15, 15, 14, 10, 8, 12, 12), start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    ws.freeze_panes = "A2"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"assoodiq-azolar-{date.today():%Y-%m-%d}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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
                .order_by(Transaction.date.desc(), Transaction.id.desc()).all()) if eids else []
    pay_count = {}
    for t in payments:
        if t.amount > 0:
            pay_count[t.enrollment_id] = pay_count.get(t.enrollment_id, 0) + 1
    timeline = member_timeline(m, enrs, payments)
    enrolled = {r["enrollment"].program_id for r in enrs if r["enrollment"].status == "faol"}
    open_programs = [p for p in Program.query.filter(Program.status != "yakunlangan").order_by(Program.name).all()
                     if p.id not in enrolled]
    from core.attendance import member_rate
    att_rates = {r["enrollment"].id: member_rate(m.id, r["enrollment"].program_id) for r in enrs}
    from core import telegram as T
    tg = {"enabled": T.enabled(), "link": m.telegram, "deep": T.deep_link(m.id), "bot": T.bot_username()}
    from core import student as S
    app = {"access": m.app_access, "courses": [c for c in S.courses(m, paid_map) if c["lectures"]]}
    return render_template("pages/member.html", m=m, enrs=enrs, payments=payments, timeline=timeline,
                           att_rates=att_rates, tg=tg, app=app,
                           since=member_since(m, enrs),
                           pay_count=pay_count, open_programs=open_programs, transfer_targets=transfer_targets(),
                           total_paid=sum(r["paid"] for r in enrs),
                           total_price=sum(r["price"] for r in enrs if r["enrollment"].status != "chiqqan"),
                           total_due=sum(r["due"] for r in enrs if r["enrollment"].status != "chiqqan"),
                           pay_categories={r["enrollment"].id: _payment_category(r["enrollment"].program) for r in enrs},
                           **form_context())


def member_timeline(m, enrs, payments):
    """O'quvchining butun tarixi bitta ro'yxatda (yangidan eskiga).

    To'lovlar, dasturga yozilish, obuna uzaytirish va holat o'zgarishi, shuningdek
    kassadagi uning nomi yozilgan boshqa yozuvlar va qarz daftaridagi qarzlari.
    """
    items = []
    for t in payments:
        e = t.enrollment
        back = t.amount < 0  # qaytarilgan pul
        items.append({"date": t.date, "kind": "pay", "icon": "out" if back else "in", "tone": "bad" if back else "ok",
                      "title": "Pul qaytarildi" if back else "To'lov qabul qilindi",
                      "amount": abs(t.amount), "cur": t.currency, "sign": "−" if back else "+",
                      "sub": " · ".join(x for x in (e.program.name if e else "", t.account.name, t.note) if x),
                      "tx": t})
    for r in enrs:
        e = r["enrollment"]
        items.append({"date": e.joined_at, "kind": "program", "icon": "cap", "tone": "brand",
                      "title": f"«{e.program.name}» dasturiga yozildi",
                      "sub": f"Kelishilgan narx {e.price:,.0f} {'$' if e.program.currency == 'USD' else 'so‘m'}".replace(",", " ")
                             + (f" · {e.note}" if e.note else "")})
    for ev in MemberEvent.query.filter_by(member_id=m.id).all():
        icon, tone = {"renew": ("renew", "gold"), "transfer": ("swap", "brand"),
                      "refund": ("out", "bad")}.get(ev.kind, ("info", "info"))
        if ev.kind == "refund":
            sub = ""
        elif ev.kind == "transfer":
            sub = f"Yangi dasturga o'tgan to'lov {ev.amount:,.0f} so'm".replace(",", " ") if ev.amount else "To'lov bo'lmagan"
        else:
            sub = f"Hisoblangan summa +{ev.amount:,.0f}".replace(",", " ") if ev.amount else ""
        items.append({"date": ev.created_at.date(), "kind": "program", "icon": icon, "tone": tone,
                      "title": ev.text, "sub": sub,
                      "who": ev.user.name if ev.user else ""})
    # Kassada shu ism bilan yozilgan, lekin dasturga bog'lanmagan yozuvlar
    known = {t.id for t in payments}
    name = m.full_name.strip()
    if name:
        for t in Transaction.query.filter(func.lower(Transaction.counterparty) == name.lower()).all():
            if t.id in known:
                continue
            incoming = t.kind in ("kirim", "qarz_kirim")
            items.append({"date": t.date, "kind": "pay", "icon": "in" if incoming else "out",
                          "tone": "ok" if incoming else "", "title": t.kind_name + (f" · {t.category.name}" if t.category else ""),
                          "amount": t.amount, "cur": t.currency, "sign": "+" if incoming else "−",
                          "sub": " · ".join(x for x in (t.program.name if t.program else "", t.account.name, t.note) if x),
                          "tx": t})
        for d in Debt.query.filter(func.lower(Debt.counterparty) == name.lower()).all():
            items.append({"date": d.date, "kind": "debt", "icon": "book", "tone": "warn",
                          "title": "Qarz berildi" if d.direction == "berilgan" else "Qarz olindi",
                          "amount": d.amount, "cur": d.currency, "sign": "",
                          "sub": ("yopilgan" if d.closed else (f"muddati {d.due_date:%d.%m.%Y}" if d.due_date else "ochiq"))
                                 + (f" · {d.note}" if d.note else ""),
                          "debt": d})
    from core.models import Notification
    kinds = {"dars": "Dars eslatmasi", "qarz": "To'lov eslatmasi", "obuna": "Obuna eslatmasi", "xabar": "Xabar"}
    for n in Notification.query.filter_by(member_id=m.id).order_by(Notification.created_at.desc()).limit(30).all():
        items.append({"date": n.created_at.date(), "kind": "tg", "icon": "send", "tone": "info" if n.status == "sent" else "warn",
                      "title": f"Telegram: {kinds.get(n.kind, 'xabar')}" + ("" if n.status == "sent" else " — yetkazilmadi"),
                      "sub": re.sub(r"<[^>]+>", "", n.text or "")[:120]})
    since = member_since(m, enrs)
    if since:
        items.append({"date": since, "kind": "program", "icon": "user-plus", "tone": "",
                      "title": "Bazaga qo'shildi", "sub": m.business or ""})
    order = {"pay": 0, "debt": 1, "program": 2, "tg": 3}
    items.sort(key=lambda x: (x["date"], -order[x["kind"]]), reverse=True)
    return items


def member_since(m, enrs):
    """A'zo qachondan beri: bazaga qo'shilgan yoki birinchi dasturga yozilgan kun (qaysi biri oldin)."""
    dates = [r["enrollment"].joined_at for r in enrs if r["enrollment"].joined_at]
    if m.created_at:
        dates.append(m.created_at.date())
    return min(dates) if dates else None


@bp.route("/azolar/kartalar")
def cards():
    """QR a'zo kartalari — chop etish uchun (A4 da 8 ta). ?dastur=<id> yoki ?a=<id>,<id>."""
    pid = form_int(request.args.get("dastur"))
    ids = [form_int(x) for x in (request.args.get("a") or "").split(",") if form_int(x)]
    program = db.session.get(Program, pid) if pid else None
    if program:
        members = [e.member for e in program.enrollments.filter(Enrollment.status != "chiqqan").all()]
    elif ids:
        members = Member.query.filter(Member.id.in_(ids)).all()
    else:
        members = Member.query.all()
    members = sorted({m.id: m for m in members}.values(), key=lambda m: m.full_name.lower())
    progs = {}
    for e in Enrollment.query.filter(Enrollment.member_id.in_([m.id for m in members]),
                                     Enrollment.status == "faol").all():
        progs.setdefault(e.member_id, []).append(e.program.name)
    return render_template("pages/cards.html", members=members, program=program, progs=progs)

