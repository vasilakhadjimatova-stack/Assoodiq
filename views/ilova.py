"""O'quvchi ilovasi (/app): PWA va Telegram Mini App. Xodimlar kirishidan alohida sessiya kaliti (sid)."""
import time
from datetime import date, datetime, timedelta, timezone

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)

from core import finance as F
from core import prayer as P
from core import student as S
from core import telegram as T
from core.extensions import db
from core.models import Attendance, Lecture, Lesson, Member, Transaction

bp = Blueprint("ilova", __name__, url_prefix="/app")

CONTRACT_SOURCE = {"pdf": "PDF", "rasm": "Rasm", "docx": "Word", "matn": "Matn"}
PUBLIC = {"ilova.login", "ilova.login_code", "ilova.tg_login", "ilova.invite", "ilova.manifest",
          "ilova.service_worker", "ilova.offline", "ilova.prayer_api"}
WD = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr",
          "noyabr", "dekabr"]

# Telefon raqami bo'yicha kod so'rashni sekinlashtirish (IP bo'yicha)
_tries = {}
MAX_TRIES, WINDOW = 10, 10 * 60


def _ip_blocked():
    ip = (request.access_route or [request.remote_addr or ""])[-1]
    now = time.time()
    if len(_tries) > 5000:
        _tries.clear()
    _tries[ip] = [t for t in _tries.get(ip, []) if now - t < WINDOW]
    if len(_tries[ip]) >= MAX_TRIES:
        return True
    _tries[ip].append(now)
    return False


@bp.before_request
def need_student():
    g.me = S.current()
    if g.me is None and request.endpoint not in PUBLIC:
        return redirect(url_for("ilova.login"))
    return None


@bp.context_processor
def inject():
    from core.calendar import color_for
    return {"me": g.get("me"), "wd": WD, "months": MONTHS, "color_for": color_for, "org_name": F.get_setting("org_name") or "Assoodiq",
            "first_name": (g.me.full_name.split() or [""])[0] if g.get("me") else ""}


# ── Kirish ──────────────────────────────────────────────────────────────────

@bp.route("/kirish", methods=["GET", "POST"])
def login():
    if g.me:
        return redirect(url_for("ilova.home"))
    step = "phone"
    if request.method == "POST":
        if _ip_blocked():
            flash("Juda ko'p urinish. 10 daqiqadan keyin qayta urinib ko'ring.", "bad")
        else:
            res, m = S.send_code(request.form.get("phone", ""))
            if res == "sent":
                session["pending_sid"] = m.id
                step = "code"
            elif res == "limit":
                flash("Kod yaqinda yuborilgan. Telegram'ni tekshiring yoki birozdan keyin urinib ko'ring.", "warn")
                session["pending_sid"] = m.id
                step = "code"
            else:
                flash("Kod yuborib bo'lmadi: raqam ro'yxatda yo'q yoki Telegram botga ulanmagan. "
                      "Administratordan ilovaga taklif havolasini so'rang.", "bad")
    return render_template("app/login.html", step=step, bot=T.bot_username(), tg_enabled=T.enabled())


@bp.route("/kirish/kod", methods=["POST"])
def login_code():
    mid = session.get("pending_sid")
    if not mid:
        return redirect(url_for("ilova.login"))
    if S.check_code(mid, request.form.get("code", "")):
        session.pop("pending_sid", None)
        S.login(db.session.get(Member, mid))
        return redirect(url_for("ilova.home"))
    flash("Kod noto'g'ri yoki muddati o'tgan.", "bad")
    return render_template("app/login.html", step="code", bot=T.bot_username(), tg_enabled=T.enabled())


@bp.route("/tg", methods=["POST"])
def tg_login():
    """Telegram Mini App ichidan avtomatik kirish (initData imzosi bot tokeni bilan tekshiriladi)."""
    user = S.check_init_data((request.get_json(silent=True) or {}).get("initData", ""), T.token())
    if not user:
        return jsonify(ok=False, reason="invalid"), 400
    m = S.member_by_telegram(user.get("id"))
    if m is None:
        return jsonify(ok=False, reason="nolink", bot=T.bot_username())
    S.login(m)
    return jsonify(ok=True, next=url_for("ilova.home"))


@bp.route("/k/<token>")
def invite(token):
    m = S.member_by_invite(token)
    if m is None:
        flash("Havola eskirgan yoki noto'g'ri. Administratordan yangisini so'rang.", "bad")
        return redirect(url_for("ilova.login"))
    S.login(m)
    return redirect(url_for("ilova.home"))


@bp.route("/chiqish", methods=["POST"])
def logout():
    S.logout()
    return redirect(url_for("ilova.login"))


# ── Bosh sahifa ─────────────────────────────────────────────────────────────

def _prayer_ctx(now=None):
    ps = P.settings()
    lat, lng = P.CITIES[ps["city"]]
    now = now or datetime.now()
    kw = {"method": ps["method"], "asr": ps["asr"], "offsets": ps["offsets"]}
    nxt = P.next_prayer(now, lat, lng, **kw)
    return {"city": ps["city"], "times": P.day_schedule(now.date(), lat, lng, **kw),
            "next": {"key": nxt[0], "name": nxt[1], "at": nxt[2], "iso": P.iso_at(nxt[2])} if nxt else None,
            "qibla": P.qibla(lat, lng), "settings": ps}


def _upcoming(member, days=21, limit=None):
    pids = [e.program_id for e in S.enrollments(member) if e.status == "faol"]
    if not pids:
        return []
    q = (Lesson.query.filter(Lesson.program_id.in_(pids), Lesson.date >= date.today(),
                             Lesson.date <= date.today() + timedelta(days=days))
         .order_by(Lesson.date, Lesson.start))
    now = datetime.now()
    rows = [x for x in q.all() if not (x.date == now.date() and x.end < now.time())]
    return rows[:limit] if limit else rows


@bp.route("/")
def home():
    me = g.me
    courses = S.courses(me)
    lec, prog = S.continue_item(me)
    if lec is None:
        nxt = next((c for c in courses if c["next"] and not c["locked"]), None)
        lec = nxt["next"] if nxt else None
    return render_template("app/home.html", tab="home", courses=courses, cont=lec, cont_prog=prog,
                           upcoming=_upcoming(me, limit=3), pr=_prayer_ctx(),
                           due=sum(c["due"] for c in courses if c["enrollment"].status != "chiqqan"))


# ── Kurslar va darslar ──────────────────────────────────────────────────────

@bp.route("/kurslar")
def courses():
    return render_template("app/courses.html", tab="kurs", courses=S.courses(g.me))


@bp.route("/kurs/<int:pid>")
def course(pid):
    me = g.me
    c = next((x for x in S.courses(me) if x["program"].id == pid), None)
    if c is None:
        flash("Bu kursga yozilmagansiz.", "warn")
        return redirect(url_for("ilova.courses"))
    p = c["program"]
    lectures = S.published_lectures(p.id)
    prog = S.progress_map(me.id, [x.id for x in lectures])
    modules = []
    for mod in p.modules.all():
        items = [x for x in mod.lectures if x.published]
        if items:
            modules.append({"module": mod, "lectures": items,
                            "done": sum(1 for x in items if prog.get(x.id) and prog[x.id].done)})
    return render_template("app/course.html", tab="kurs", c=c, p=p, modules=modules, prog=prog)


@bp.route("/dars/<int:lid>")
def lecture(lid):
    me = g.me
    lec = db.get_or_404(Lecture, lid)
    ok, why = S.can_view(me, lec)
    if not ok and why == "enroll":
        flash("Bu dars sizning kurslaringizda yo'q.", "warn")
        return redirect(url_for("ilova.courses"))
    from core import bunny
    embed = bunny.embed_url(lec.video_id) if ok and lec.kind == "video" and lec.video_id and bunny.enabled() else None
    prev, nxt, num, total = S.neighbours(lec)
    p = S.progress_map(me.id, [lec.id]).get(lec.id)
    return render_template("app/lecture.html", tab="kurs", lec=lec, ok=ok, why=why, embed=embed, prog=p,
                           prev=prev, nxt=nxt, num=num, total=total, program=lec.module.program,
                           paras=[x.strip() for x in (lec.body or "").split("\n\n") if x.strip()])


@bp.route("/dars/<int:lid>/progress", methods=["POST"])
def lecture_progress(lid):
    lec = db.get_or_404(Lecture, lid)
    if not S.can_view(g.me, lec)[0]:
        return jsonify(ok=False), 403
    d = request.get_json(silent=True) or {}

    def num(k):
        try:
            return float(d[k]) if d.get(k) is not None else None
        except (TypeError, ValueError):
            return None
    p = S.save_progress(g.me, lec, position=num("position"), duration=num("duration"),
                        done=d.get("done") if isinstance(d.get("done"), bool) else None)
    return jsonify(ok=True, done=p.done)


# ── Jadval ──────────────────────────────────────────────────────────────────

@bp.route("/jadval")
def schedule():
    me = g.me
    days = {}
    for les in _upcoming(me, days=28):
        days.setdefault(les.date, []).append(les)
    from core.attendance import member_rate
    from core.models import ATTENDANCE
    history = (Attendance.query.join(Lesson, Attendance.lesson_id == Lesson.id)
               .filter(Attendance.member_id == me.id).order_by(Lesson.date.desc(), Lesson.start.desc())
               .limit(12).all())
    rates = []
    for e in S.enrollments(me):
        came, total = member_rate(me.id, e.program_id)
        if total:
            rates.append({"program": e.program, "came": came, "total": total, "pct": came / total})
    return render_template("app/schedule.html", tab="jadval", days=days, history=history, rates=rates,
                           att_names=ATTENDANCE)


# ── Ibodat: namoz vaqtlari, qibla, zakot ────────────────────────────────────

@bp.route("/ibodat")
def ibodat():
    pr = _prayer_ctx()
    lat, lng = P.CITIES[pr["city"]]
    s = pr["settings"]
    week = P.week(date.today(), lat, lng, method=s["method"], asr=s["asr"], offsets=s["offsets"])
    return render_template("app/ibodat.html", tab="ibodat", pr=pr, week=week, cities=P.CITIES,
                           method_name=P.METHODS[s["method"]]["name"], compass=P.compass_word(pr["qibla"][0]))


@bp.route("/zakot")
def zakat():
    return render_template("app/zakot.html", tab="ibodat",
                           gold=F.setting_float("gold_price_g"), silver=F.setting_float("silver_price_g"),
                           grams=F.NISOB_GRAMS, rate=F.ZAKAT_RATE)


@bp.route("/api/namoz")
def prayer_api():
    """Tanlangan shahar yoki koordinata bo'yicha namoz vaqtlari va qibla (ilova JS'i chaqiradi)."""
    s = P.settings()
    city = request.args.get("city")
    try:
        if city in P.CITIES:
            lat, lng = P.CITIES[city]
            request_tz = P.TZ_DEFAULT  # ro'yxatdagi shaharlar — O'zbekiston vaqti
        else:
            request_tz = None
            lat, lng = float(request.args["lat"]), float(request.args["lng"])
            if not (-66 <= lat <= 66 and -180 <= lng <= 180):
                raise ValueError
            city = None
        tz = request_tz if request_tz is not None else float(request.args.get("tz", P.TZ_DEFAULT))
        if not -12 <= tz <= 14:
            raise ValueError
    except (KeyError, ValueError):
        lat, lng = P.CITIES[s["city"]]
        city, tz = s["city"], P.TZ_DEFAULT
    kw = {"method": s["method"], "asr": s["asr"], "offsets": s["offsets"]}
    now = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=tz)
    nxt = P.next_prayer(now, lat, lng, tz, **kw)
    deg, km = P.qibla(lat, lng)
    days = request.args.get("days", "1")
    days = min(max(int(days), 1), 31) if days.isdigit() else 1
    return jsonify(city=city, lat=round(lat, 4), lng=round(lng, 4),
                   today=P.day_schedule(now.date(), lat, lng, tz, **kw),
                   next={"key": nxt[0], "name": nxt[1], "at": P.iso_at(nxt[2], tz), "time": nxt[2].strftime("%H:%M"),
                         "in": int((nxt[2] - now).total_seconds())} if nxt else None,
                   week=[{"date": w["date"].isoformat(), "times": w["times"]}
                         for w in P.week(now.date(), lat, lng, tz, days=days, **kw)] if days > 1 else None,
                   qibla={"deg": deg, "km": km, "word": P.compass_word(deg)})


# ── Profil ──────────────────────────────────────────────────────────────────

@bp.route("/profil")
def profile():
    me = g.me
    courses = S.courses(me)
    eids = [c["enrollment"].id for c in courses]
    payments = (Transaction.query.filter(Transaction.enrollment_id.in_(eids), Transaction.kind == "kirim")
                .order_by(Transaction.date.desc(), Transaction.id.desc()).limit(30).all()) if eids else []
    from core.attendance import member_code
    return render_template("app/profile.html", tab="profil", courses=courses, payments=payments,
                           code=member_code(me.id), tg=me.telegram, bot=T.bot_username(),
                           paid=sum(c["paid"] for c in courses),
                           due=sum(c["due"] for c in courses if c["enrollment"].status != "chiqqan"))


# ── Shartnoma tekshiruvi ────────────────────────────────────────────────────

def _contracts_open():
    from core import ai
    from core.models import KnowledgeDoc
    return (F.get_setting("contract_students") == "1" and ai.enabled()
            and KnowledgeDoc.query.filter_by(active=True).count() > 0)


def _contract_quota(member):
    from core.models import ContractCheck
    try:
        limit = max(int(float(F.get_setting("contract_student_daily") or 3)), 1)
    except ValueError:
        limit = 3
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    used = ContractCheck.query.filter(ContractCheck.member_id == member.id, ContractCheck.created_at >= since).count()
    return limit - used, limit


@bp.route("/shartnoma", methods=["GET", "POST"])
def contracts():
    from core import contract as C
    from core.models import ContractCheck
    me = g.me
    if request.method == "POST":
        if not _contracts_open():
            flash("Shartnoma tekshiruvi hozircha yopiq.", "warn")
            return redirect(url_for("ilova.contracts"))
        left, _ = _contract_quota(me)
        if left <= 0:
            flash("Bugungi tekshiruvlar soni tugadi. Ertaga qayta urinib ko'ring.", "warn")
            return redirect(url_for("ilova.contracts"))
        text, files, kind, err = C.read_upload(request.files.getlist("files"), request.form.get("text", ""))
        if err:
            flash(err, "bad")
            return redirect(url_for("ilova.contracts"))
        title = (request.form.get("title") or "").strip()[:200] or "Shartnoma"
        check = ContractCheck(member_id=me.id, title=title, source_kind=kind)
        db.session.add(check)
        db.session.commit()
        C.start(current_app._get_current_object(), check.id, text, files)
        return redirect(url_for("ilova.contract", cid=check.id))
    checks = (ContractCheck.query.filter_by(member_id=me.id).order_by(ContractCheck.created_at.desc()).limit(30).all())
    left, limit = _contract_quota(me)
    from core.models import CONTRACT_VERDICTS
    return render_template("app/contracts.html", tab="kurs", checks=checks, open=_contracts_open(), left=left,
                           limit=limit, verdicts=CONTRACT_VERDICTS, sources=CONTRACT_SOURCE)


def _own_check(cid):
    from core.models import ContractCheck
    check = db.get_or_404(ContractCheck, cid)
    if check.member_id != g.me.id:
        abort(404)
    return check


@bp.route("/shartnoma/<int:cid>")
def contract(cid):
    from views.shartnoma import report_context
    return render_template("app/contract.html", tab="kurs", **report_context(_own_check(cid), staff=False))


@bp.route("/shartnoma/<int:cid>/holat")
def contract_status(cid):
    check = _own_check(cid)
    return jsonify(status=check.status)


# ── PWA ─────────────────────────────────────────────────────────────────────

@bp.route("/manifest.webmanifest")
def manifest():
    name = F.get_setting("org_name") or "Assoodiq"
    resp = jsonify({
        "name": f"{name} — o'quvchi", "short_name": name, "start_url": "/app/", "scope": "/app/",
        "display": "standalone", "background_color": "#043A2E", "theme_color": "#065A47", "lang": "uz",
        "description": "Kurslar, video darslar, dars jadvali, namoz vaqtlari, qibla va zakot kalkulyatori",
        "icons": [
            {"src": url_for("static", filename="img/app-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="img/app-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": url_for("static", filename="img/app-maskable.png"), "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    })
    resp.mimetype = "application/manifest+json"
    return resp


@bp.route("/sw.js")
def service_worker():
    resp = send_from_directory(current_app.static_folder, "js/sw.js", mimetype="application/javascript", max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/offline")
def offline():
    return render_template("app/offline.html")

