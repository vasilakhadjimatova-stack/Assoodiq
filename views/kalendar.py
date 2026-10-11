"""Dars jadvali — Google Calendar uslubida: hafta, kun, oy va ro'yxat ko'rinishlari."""
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import or_

from core import attendance as A
from core import calendar as C
from core import hijri
from core.extensions import db
from core.models import ATTENDANCE, LESSON_STATUS, Attendance, Lesson, Program
from views import form_date, form_int, safe_next

bp = Blueprint("kalendar", __name__, url_prefix="/kalendar")

# Ko'rinishlar: hafta — chiptalar doskasi, soatlar — vaqt to'ri, oy, yo'l xaritasi (kurs bo'yicha)
VIEWS = {"hafta": ("Hafta", "dashboard"), "soat": ("Soatlar", "clock"), "oy": ("Oy", "calendar"),
         "yol": ("Yo'l xaritasi", "up")}


def _date_arg():
    raw = request.args.get("d", "")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return date.today()


def _hijri_short(x):
    parts = hijri.format_hijri(x).split()
    return " ".join(parts[:2])  # "28 Rabius-soniy"


@bp.route("/")
def index():
    view = request.args.get("v", "hafta")
    view = {"royxat": "hafta"}.get(view, view)  # eski havolalar
    view = view if view in VIEWS or view == "kun" else "hafta"
    d = _date_arg()
    today = date.today()
    now = C.now_local()

    if view in ("hafta", "soat"):
        start = C.week_start(d)
        days = [start + timedelta(days=i) for i in range(7)]
        step, title = 7, C.fmt_range(days[0], days[-1])
    elif view == "kun":
        days, step = [d], 1
        title = f"{d.day} {C.MONTHS[d.month - 1]} {d.year}"
    elif view == "oy":
        weeks = C.month_grid(d)
        days, step = [x for w in weeks for x in w], None
        title = f"{C.MONTHS[d.month - 1].capitalize()} {d.year}"
    else:  # yol — butun kurslar bo'yicha, sana oralig'i yo'q
        days, step, title = [], None, "Kurslar yo'li"

    if days:
        lessons = (Lesson.query.filter(Lesson.date >= days[0], Lesson.date <= days[-1])
                   .order_by(Lesson.date, Lesson.start).all())
    else:
        lessons = []
    by_day = {x: [] for x in days}
    for les in lessons:
        by_day.setdefault(les.date, []).append(les)

    # Soatlar to'ri: 08:00–21:00, darslar shundan chiqsa kengayadi
    h0, h1 = 8, 21
    if view in ("soat", "kun") and lessons:
        h0 = min(h0, min(les.start.hour for les in lessons))
        h1 = max(h1, max(les.end.hour + (1 if les.end.minute else 0) for les in lessons))
    columns = {x: C.layout_day(by_day.get(x, []), h0 * 60) for x in days} if view in ("soat", "kun") else {}

    if step:
        prev_d, next_d = d - timedelta(days=step), d + timedelta(days=step)
    else:
        m = d.replace(day=1)
        prev_d = (m - timedelta(days=1)).replace(day=1)
        next_d = (m + timedelta(days=32)).replace(day=1)

    programs = [p for p in Program.query.order_by(Program.status, Program.name).all()
                if p.status != "yakunlangan" or p.id in {les.program_id for les in lessons}]
    counts = {}
    for les in lessons:
        if les.status != "bekor":
            counts[les.program_id] = counts.get(les.program_id, 0) + 1

    # Yo'l xaritasi: har dastur darslari boshidan oxirigacha
    tracks = []
    if view == "yol":
        for p in programs:
            items = p.lessons.order_by(Lesson.date, Lesson.start).all()
            if not items:
                continue
            live = [x for x in items if x.status != "bekor"]
            done = sum(1 for x in live if x.status == "otdi" or x.date < today)
            nxt = next((x for x in live if (x.date, x.end) >= (today, now.time()) and x.status == "rejada"), None)
            tracks.append({"program": p, "lessons": items, "total": len(live), "done": done, "next": nxt,
                           "pct": done / len(live) if live else 0})

    # Banner: keyingi dars va shu davr bo'yicha holat
    nxt_lesson = (Lesson.query.filter(Lesson.status == "rejada",
                                      or_(Lesson.date > today, (Lesson.date == today) & (Lesson.end > now.time())))
                  .order_by(Lesson.date, Lesson.start).first())
    scope = [x for x in lessons if x.status != "bekor"]
    period = {"total": len(scope), "done": sum(1 for x in scope if x.status == "otdi"),
              "hours": round(sum(x.minutes for x in scope) / 60, 1)}
    if view == "yol":  # yo'l xaritasida — barcha kurslar bo'yicha
        live = [x for tr in tracks for x in tr["lessons"] if x.status != "bekor"]
        period = {"total": len(live), "done": sum(tr["done"] for tr in tracks),
                  "hours": round(sum(x.minutes for x in live) / 60, 1)}
    locations = [x for (x,) in db.session.query(Lesson.location).filter(Lesson.location != "").distinct().limit(40)]
    teachers = [x for (x,) in db.session.query(Lesson.teacher).filter(Lesson.teacher != "").distinct().limit(40)]
    return render_template(
        "pages/kalendar.html", view=view, views=VIEWS, d=d, days=days, by_day=by_day, columns=columns,
        h0=h0, h1=h1, title=title, prev_d=prev_d, next_d=next_d, programs=programs, counts=counts,
        color_for=C.color_for, wd=C.WEEKDAYS, wd_short=C.WEEKDAYS_SHORT, months=C.MONTHS,
        statuses=LESSON_STATUS, lessons=lessons, tracks=tracks, nxt=nxt_lesson, period=period,
        hijri_short=_hijri_short, hijri_title=_hijri_short(days[0]) + (" – " + _hijri_short(days[-1]) if len(days) > 1 else "") if days else "",
        now=now, locations=locations, teachers=teachers, today=today,
        att=A.lesson_counts([x.id for x in lessons]),
        open_program=form_int(request.args.get("yangi")),
    )


def _fields(f, base=None):
    """Formadan dars maydonlari; xato bo'lsa (None, xabar)."""
    prog = db.session.get(Program, form_int(f.get("program_id")) or 0)
    if prog is None:
        return None, "Dasturni tanlang."
    start = C.parse_time(f.get("start"))
    end = C.parse_time(f.get("end"))
    if start is None or end is None or C.minutes(end) <= C.minutes(start):
        return None, "Boshlanish va tugash vaqtini to'g'ri kiriting (tugash boshlanishdan keyin)."
    return {
        "program_id": prog.id, "start": start, "end": end,
        "date": form_date(f.get("date"), base.date if base else None),
        "title": (f.get("title") or "").strip()[:160],
        "location": (f.get("location") or "").strip()[:120],
        "teacher": (f.get("teacher") or "").strip()[:120],
        "note": (f.get("note") or "").strip()[:500],
    }, None


def _warn_conflicts(lessons):
    shown = 0
    for les in lessons:
        for other, why in C.conflicts(les):
            if shown < 3:
                flash(f"To'qnashuv: {les.date:%d.%m} {les.start:%H:%M} — {why} "
                      f"(«{other.program.name}», {other.start:%H:%M}–{other.end:%H:%M}).", "warn")
            shown += 1
    if shown > 3:
        flash(f"Yana {shown - 3} ta to'qnashuv bor — jadvalni tekshiring.", "warn")


@bp.route("/saqlash", methods=["POST"])
def save():
    f = request.form
    back = safe_next(url_for("kalendar.index"))
    les = db.session.get(Lesson, form_int(f.get("lesson_id")) or 0)
    fields, err = _fields(f, les)
    if err:
        flash(err, "bad")
        return redirect(back)

    if les is not None:  # tahrirlash
        if f.get("scope") == "series" and les.series_id:
            group = Lesson.query.filter(Lesson.series_id == les.series_id, Lesson.date >= les.date).all()
            for x in group:
                for k in ("program_id", "start", "end", "location", "teacher", "note"):
                    setattr(x, k, fields[k])
            les.date = fields["date"]
            les.title = fields["title"] or les.title
            db.session.commit()
            _warn_conflicts(group)
            flash(f"Seriyadagi {len(group)} ta dars yangilandi.", "ok")
        else:
            for k, v in fields.items():
                setattr(les, k, v)
            if not les.title:
                les.title = "Dars"
            db.session.commit()
            _warn_conflicts([les])
            flash("Dars yangilandi.", "ok")
        return redirect(back)

    # yangi dars yoki takrorlanuvchi seriya
    dates = [fields["date"]]
    if f.get("repeat") == "weekly":
        weekdays = [int(x) for x in f.getlist("weekdays") if x.isdigit() and 0 <= int(x) <= 6]
        until = form_date(f.get("until")) if (f.get("until") or "").strip() else None
        count = form_int(f.get("count"))
        dates = C.expand_weekly(fields["date"], weekdays or [fields["date"].weekday()], until, count)
        if not dates:
            flash("Tanlangan kunlarda sana chiqmadi — hafta kunlari va muddatni tekshiring.", "bad")
            return redirect(back)
    series = uuid.uuid4().hex if len(dates) > 1 else None
    title = fields.pop("title")
    n0 = Lesson.query.filter_by(program_id=fields["program_id"]).filter(Lesson.status != "bekor").count()
    created = []
    for i, day in enumerate(dates):
        data = dict(fields, date=day)
        created.append(Lesson(title=title or f"{n0 + i + 1}-dars", series_id=series, created_by=g.user.id, **data))
    db.session.add_all(created)
    db.session.commit()
    _warn_conflicts(created)
    flash(f"{len(created)} ta dars jadvalga qo'shildi." if len(created) > 1 else "Dars jadvalga qo'shildi.", "ok")
    return redirect(back)


@bp.route("/<int:lid>/kochirish", methods=["POST"])
def move(lid):
    """Sudrab ko'chirish / cho'zish (JS): yangi sana va vaqt."""
    les = db.get_or_404(Lesson, lid)
    data = request.get_json(silent=True) or {}
    try:
        day = datetime.strptime(data.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        return jsonify(ok=False, error="Sana noto'g'ri"), 400
    start, end = C.parse_time(data.get("start")), C.parse_time(data.get("end"))
    if start is None or end is None or C.minutes(end) <= C.minutes(start):
        return jsonify(ok=False, error="Vaqt noto'g'ri"), 400
    les.date, les.start, les.end = day, start, end
    db.session.commit()
    clash = [f"{why} («{o.program.name}», {o.start:%H:%M}–{o.end:%H:%M})" for o, why in C.conflicts(les)]
    return jsonify(ok=True, conflicts=clash)


@bp.route("/<int:lid>/holat", methods=["POST"])
def status(lid):
    les = db.get_or_404(Lesson, lid)
    st = request.form.get("status")
    if st in LESSON_STATUS:
        les.status = st
        db.session.commit()
        flash(f"«{les.title}»: {LESSON_STATUS[st].lower()}.", "ok")
    return redirect(safe_next(url_for("kalendar.index")))


@bp.route("/<int:lid>/ochirish", methods=["POST"])
def delete(lid):
    les = db.get_or_404(Lesson, lid)
    if request.form.get("scope") == "series" and les.series_id:
        group = Lesson.query.filter(Lesson.series_id == les.series_id, Lesson.date >= les.date)
        n = group.count()
        ids = [x.id for x in group.all()]
        Attendance.query.filter(Attendance.lesson_id.in_(ids)).delete(synchronize_session=False)
        group.delete(synchronize_session=False)
        msg = f"Seriyadagi {n} ta dars o'chirildi (shu kundan boshlab)."
    else:
        db.session.delete(les)
        msg = "Dars o'chirildi."
    db.session.commit()
    flash(msg, "ok")
    return redirect(safe_next(url_for("kalendar.index")))


def upcoming_for(program_id, limit=6):
    return (Lesson.query.filter(Lesson.program_id == program_id, Lesson.date >= date.today())
            .order_by(Lesson.date, Lesson.start).limit(limit).all())


# ── Davomat ─────────────────────────────────────────────────────────────────

@bp.route("/<int:lid>/davomat")
def attendance(lid):
    les = db.get_or_404(Lesson, lid)
    rows = A.roster(les)
    st = A.stats(les, rows)
    siblings = (Lesson.query.filter(Lesson.program_id == les.program_id, Lesson.status != "bekor")
                .order_by(Lesson.date, Lesson.start).all())
    idx = next((i for i, x in enumerate(siblings) if x.id == les.id), 0)
    prev_l = siblings[idx - 1] if idx > 0 else None
    next_l = siblings[idx + 1] if idx + 1 < len(siblings) else None
    return render_template("pages/davomat.html", les=les, rows=rows, st=st, statuses=ATTENDANCE,
                           color=C.color_for(les.program_id), code_for=A.member_code, late=A.LATE_MINUTES,
                           prev_l=prev_l, next_l=next_l, number=idx + 1, of=len(siblings),
                           wd=C.WEEKDAYS, months=C.MONTHS)


def _att_json(les, member_id, extra=None):
    st = A.stats(les)
    att = Attendance.query.filter_by(lesson_id=les.id, member_id=member_id).first()
    data = {"ok": True, "member_id": member_id, "status": att.status if att else "",
            "time": att.marked_at.replace(tzinfo=timezone.utc).astimezone().strftime("%H:%M") if att and att.marked_at else "",
            "method": att.method if att else "",
            "stats": {k: st[k] for k in ("keldi", "kechikdi", "kelmadi", "sababli", "present", "total", "unmarked")},
            "pct": round(st["pct"] * 100), "lesson_status": les.status}
    data.update(extra or {})
    return jsonify(data)


@bp.route("/<int:lid>/davomat/belgi", methods=["POST"])
def attendance_mark(lid):
    les = db.get_or_404(Lesson, lid)
    data = request.get_json(silent=True) or {}
    mid = form_int(data.get("member_id"))
    status = data.get("status") or ""
    if not A.find_member(mid) or (status and status not in ATTENDANCE):
        return jsonify(ok=False, error="Noto'g'ri so'rov"), 400
    A.mark(les, mid, status, "qolda", g.user.id)
    db.session.commit()
    return _att_json(les, mid)


@bp.route("/<int:lid>/davomat/skaner", methods=["POST"])
def attendance_scan(lid):
    """Skaner (yoki kamera) o'qigan kod: a'zo topilsa — keldi/kechikdi deb belgilanadi."""
    les = db.get_or_404(Lesson, lid)
    data = request.get_json(silent=True) or {}
    method = "kamera" if data.get("via") == "kamera" else "skaner"
    mid = A.parse_code(data.get("code"))
    m = A.find_member(mid)
    if m is None:
        return jsonify(ok=False, error="Kod tanilmadi — kartani qayta skaner qiling"), 200
    enrolled = any(r["member"].id == m.id and r["enrollment"] for r in A.roster(les))
    if not enrolled and not data.get("force"):
        return jsonify(ok=False, need_force=True, member_id=m.id, name=m.full_name,
                       error=f"{m.full_name} bu dasturga yozilmagan"), 200
    prev = Attendance.query.filter_by(lesson_id=les.id, member_id=m.id).first()
    already = bool(prev and prev.status in A.PRESENT)
    if not already:
        A.mark(les, m.id, A.auto_status(les), method, g.user.id)
        db.session.commit()
    return _att_json(les, m.id, {"name": m.full_name, "already": already, "business": m.business or ""})


@bp.route("/<int:lid>/davomat/hammasi", methods=["POST"])
def attendance_bulk(lid):
    """Belgilanmaganlarning hammasini bitta holatga (keldi yoki kelmadi)."""
    les = db.get_or_404(Lesson, lid)
    status = request.form.get("status")
    if status in ("keldi", "kelmadi"):
        n = 0
        for r in A.roster(les):
            if r["att"] is None and r["enrollment"] is not None:
                A.mark(les, r["member"].id, status, "qolda", g.user.id)
                n += 1
        db.session.commit()
        flash(f"{n} ta a'zo «{ATTENDANCE[status].lower()}» deb belgilandi.", "ok")
    return redirect(url_for("kalendar.attendance", lid=lid))

