"""Dars jadvali — Google Calendar uslubida: hafta, kun, oy va ro'yxat ko'rinishlari."""
import uuid
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from core import calendar as C
from core.extensions import db
from core.models import LESSON_STATUS, Lesson, Program
from views import form_date, form_int, safe_next

bp = Blueprint("kalendar", __name__, url_prefix="/kalendar")

VIEWS = {"hafta": "Hafta", "kun": "Kun", "oy": "Oy", "royxat": "Ro'yxat"}


def _date_arg():
    raw = request.args.get("d", "")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return date.today()


@bp.route("/")
def index():
    view = request.args.get("v", "hafta")
    view = view if view in VIEWS else "hafta"
    d = _date_arg()
    today = date.today()

    if view == "hafta":
        start = C.week_start(d)
        days = [start + timedelta(days=i) for i in range(7)]
        step, title = 7, C.fmt_range(days[0], days[-1])
    elif view == "kun":
        days, step = [d], 1
        title = f"{d.day} {C.MONTHS[d.month - 1]} {d.year}, {C.WEEKDAYS[d.weekday()].lower()}"
    elif view == "oy":
        weeks = C.month_grid(d)
        days, step = [x for w in weeks for x in w], None
        title = f"{C.MONTHS[d.month - 1].capitalize()} {d.year}"
    else:  # royxat — 5 hafta oldinga
        days = [d + timedelta(days=i) for i in range(35)]
        step, title = 35, f"{d.day} {C.MONTHS[d.month - 1]} — {days[-1].day} {C.MONTHS[days[-1].month - 1]} {days[-1].year}"

    lessons = (Lesson.query.filter(Lesson.date >= days[0], Lesson.date <= days[-1])
               .order_by(Lesson.date, Lesson.start).all())
    by_day = {x: [] for x in days}
    for les in lessons:
        by_day.setdefault(les.date, []).append(les)

    # Vaqt to'ri: 08:00–21:00, darslar shundan chiqsa kengayadi
    h0, h1 = 8, 21
    if view in ("hafta", "kun") and lessons:
        h0 = min(h0, min(les.start.hour for les in lessons))
        h1 = max(h1, max(les.end.hour + (1 if les.end.minute else 0) for les in lessons))
    columns = {x: C.layout_day(by_day.get(x, []), h0 * 60) for x in days} if view in ("hafta", "kun") else {}

    if step:
        prev_d, next_d = d - timedelta(days=step), d + timedelta(days=step)
    else:
        m = d.replace(day=1)
        prev_d = (m - timedelta(days=1)).replace(day=1)
        next_d = (m + timedelta(days=32)).replace(day=1)

    # Chap panel: mini oy (darsli kunlar nuqta bilan) va dasturlar
    mini = C.month_grid(d)
    lesson_days = {x for (x,) in db.session.query(Lesson.date).filter(
        Lesson.date >= mini[0][0], Lesson.date <= mini[-1][-1], Lesson.status != "bekor").distinct()}
    used = {les.program_id for les in lessons}
    programs = [p for p in Program.query.order_by(Program.status, Program.name).all()
                if p.status != "yakunlangan" or p.id in used]
    upcoming = (Lesson.query.filter(Lesson.date >= today, Lesson.status == "rejada")
                .order_by(Lesson.date, Lesson.start).limit(5).all())
    week_total = sum(1 for les in lessons if les.status != "bekor")
    locations = [x for (x,) in db.session.query(Lesson.location).filter(Lesson.location != "").distinct().limit(40)]
    teachers = [x for (x,) in db.session.query(Lesson.teacher).filter(Lesson.teacher != "").distinct().limit(40)]
    return render_template(
        "pages/kalendar.html", view=view, views=VIEWS, d=d, days=days, by_day=by_day, columns=columns,
        h0=h0, h1=h1, title=title, prev_d=prev_d, next_d=next_d, mini=mini, lesson_days=lesson_days,
        programs=programs, color_for=C.color_for, wd=C.WEEKDAYS, wd_short=C.WEEKDAYS_SHORT,
        months=C.MONTHS, statuses=LESSON_STATUS, upcoming=upcoming, lessons=lessons, week_total=week_total,
        now=C.now_local(), locations=locations, teachers=teachers, today=today,
        open_program=form_int(request.args.get("yangi")),
        mini_prev=(d.replace(day=1) - timedelta(days=1)).replace(day=1),
        mini_next=(d.replace(day=1) + timedelta(days=32)).replace(day=1),
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

