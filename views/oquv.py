"""O'quv dasturi (xodimlar): bo'limlar, mavzular, Bunny Stream'ga video yuklash, ilova sozlamalari va taklif."""
from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for
from markupsafe import Markup

from core import audit, bunny
from core import finance as F
from core import prayer as P
from core import student as S
from core import telegram as T
from core.attendance import qr_svg
from core.extensions import db
from core.models import (LECTURE_KINDS, VIDEO_STATUS, Enrollment, Lecture, LectureProgress, Member, Module,
                         Program, StudentAccess)
from views import form_int, require_role, safe_next

bp = Blueprint("oquv", __name__, url_prefix="/oquv")


def app_url(path="/app/"):
    """Ilovaning tashqi manzili (Telegram Mini App faqat https bilan ishlaydi)."""
    base = (F.get_setting("tg_webhook") or request.host_url).rstrip("/")
    if base.startswith("http://") and not any(h in base for h in ("localhost", "127.0.0.1")):
        base = "https://" + base[len("http://"):]
    return base + path


# ── Ro'yxat va tahrirlash sahifasi ──────────────────────────────────────────

def readiness(x):
    """Mavzuning tayyorligi: tayyor | jarayon | xato | kerak (video yo'q yoki qo'llanma bo'sh)."""
    if x.kind == "matn":
        return "tayyor" if (x.body or "").strip() else "kerak"
    if not x.video_id:
        return "kerak"
    return {"tayyor": "tayyor", "xato": "xato"}.get(x.video_status, "jarayon")


def fmt_minutes(m):
    """Daqiqa → «4 soat 11 daq» (0 bo'lsa — «—»)."""
    m = int(m or 0)
    if not m:
        return "—"
    h, mm = divmod(m, 60)
    return f"{h} soat {mm} daq" if h and mm else (f"{h} soat" if h else f"{mm} daq")


def program_stats(p, lectures=None):
    lectures = lectures if lectures is not None else [x for m in p.modules for x in m.lectures]
    students = p.enrollments.filter(Enrollment.status == "faol").count()
    pub = [x for x in lectures if x.published]
    ready = [x for x in lectures if readiness(x) == "tayyor"]
    done = dict(db.session.query(LectureProgress.lecture_id, db.func.count())
                .filter(LectureProgress.lecture_id.in_([x.id for x in pub]), LectureProgress.done.is_(True))
                .group_by(LectureProgress.lecture_id).all()) if pub else {}
    learn = round(sum(done.values()) / (len(pub) * students) * 100) if pub and students else None
    return {"modules": p.modules.count(), "lectures": len(lectures), "ready": len(ready),
            "need": sum(1 for x in lectures if readiness(x) == "kerak"),
            "errors": sum(1 for x in lectures if readiness(x) == "xato"),
            "hidden": sum(1 for x in lectures if not x.published),
            "videos": sum(1 for x in lectures if x.kind == "video"),
            "minutes": sum(x.duration or 0 for x in lectures) // 60, "students": students, "learn": learn,
            "done": done, "ready_pct": round(len(ready) / len(lectures) * 100) if lectures else 0}


@bp.route("/")
def index():
    progs = Program.query.filter(Program.status != "yakunlangan").all()
    stats = {p.id: program_stats(p) for p in progs}
    progs.sort(key=lambda p: (not stats[p.id]["lectures"], -stats[p.id]["students"], p.name))
    total = {k: sum(s[k] for s in stats.values()) for k in ("lectures", "ready", "need", "minutes")}
    learns = [s["learn"] for s in stats.values() if s["learn"] is not None]
    total["learn"] = round(sum(learns) / len(learns)) if learns else None
    active = StudentAccess.query.filter(StudentAccess.last_seen.isnot(None)).count()
    return render_template("pages/oquv_index.html", progs=progs, stats=stats, total=total, active=active,
                           app_link=app_url(), bunny_on=bunny.enabled(), fmt_minutes=fmt_minutes)


@bp.route("/<int:pid>")
def program(pid):
    from core.models import Transcript
    p = db.get_or_404(Program, pid)
    modules = p.modules.all()
    lectures = [x for m in modules for x in m.lectures]
    st = program_stats(p, lectures)
    texts = {t.lecture_id: t for t in Transcript.query.filter(
        Transcript.lecture_id.in_([x.id for x in lectures] or [0])).order_by(Transcript.id)}
    return render_template("pages/oquv.html", p=p, modules=modules, st=st, done=st["done"], students=st["students"],
                           kinds=LECTURE_KINDS, vstatus=VIDEO_STATUS, bunny_on=bunny.enabled(), readiness=readiness,
                           fmt_minutes=fmt_minutes, texts=texts, total_minutes=st["minutes"])


def _back(pid, anchor=""):
    return redirect(url_for("oquv.program", pid=pid) + anchor)


def _next_pos(items):
    return (max((x.position for x in items), default=-1)) + 1


@bp.route("/<int:pid>/bolim", methods=["POST"])
@bp.route("/bolim/<int:mid>/saqlash", methods=["POST"])
def module_save(pid=None, mid=None):
    mod = db.get_or_404(Module, mid) if mid else Module(program_id=db.get_or_404(Program, pid).id)
    title = (request.form.get("title") or "").strip()[:160]
    if not title:
        flash("Bo'lim nomini yozing.", "bad")
        return _back(mod.program_id)
    if not mid:
        mod.position = _next_pos(Module.query.filter_by(program_id=mod.program_id).all())
        db.session.add(mod)
    mod.title = title
    db.session.commit()
    return _back(mod.program_id, f"#m{mod.id}")


@bp.route("/bolim/<int:mid>/ochirish", methods=["POST"])
def module_delete(mid):
    mod = db.get_or_404(Module, mid)
    pid = mod.program_id
    for lec in mod.lectures:
        bunny.delete_video(lec.video_id)
    audit.log("content_delete", f"O'quv bo'limi: {mod.title} ({len(mod.lectures)} mavzu)")
    db.session.delete(mod)
    db.session.commit()
    flash("Bo'lim o'chirildi.", "ok")
    return _back(pid)


def _swap(items, obj, direction):
    items = sorted(items, key=lambda x: (x.position, x.id))
    for i, x in enumerate(items):
        x.position = i
    i = items.index(obj)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(items):
        items[i].position, items[j].position = items[j].position, items[i].position
    db.session.commit()


@bp.route("/bolim/<int:mid>/surish", methods=["POST"])
def module_move(mid):
    mod = db.get_or_404(Module, mid)
    _swap(Module.query.filter_by(program_id=mod.program_id).all(), mod, request.form.get("dir"))
    return _back(mod.program_id, f"#m{mod.id}")


@bp.route("/<int:pid>/mavzu", methods=["POST"])
@bp.route("/mavzu/<int:lid>/saqlash", methods=["POST"])
def lecture_save(pid=None, lid=None):
    f = request.form
    if lid:
        lec = db.get_or_404(Lecture, lid)
    else:
        mod = db.get_or_404(Module, form_int(f.get("module_id")) or 0)
        lec = Lecture(module_id=mod.id, position=_next_pos(mod.lectures))
        db.session.add(lec)
    title = (f.get("title") or "").strip()[:160]
    if not title:
        flash("Mavzu nomini yozing.", "bad")
        return _back(pid or lec.module.program_id)
    lec.title = title
    lec.kind = f.get("kind") if f.get("kind") in LECTURE_KINDS else "video"
    lec.body = (f.get("body") or "").strip()[:20000]
    lec.published = bool(f.get("published"))
    lec.free = bool(f.get("free"))
    mins = f.get("minutes", "").strip()
    if mins and not lec.video_id:
        try:
            lec.duration = int(float(mins.replace(",", ".")) * 60)
        except ValueError:
            pass
    db.session.commit()
    flash("Mavzu saqlandi." if lid else "Mavzu qo'shildi.", "ok")
    return _back(lec.module.program_id, f"#l{lec.id}")


@bp.route("/mavzu/<int:lid>/ochirish", methods=["POST"])
def lecture_delete(lid):
    lec = db.get_or_404(Lecture, lid)
    pid = lec.module.program_id
    bunny.delete_video(lec.video_id)
    audit.log("content_delete", f"Mavzu: {lec.title}")
    db.session.delete(lec)
    db.session.commit()
    flash("Mavzu o'chirildi.", "ok")
    return _back(pid)


@bp.route("/mavzu/<int:lid>/surish", methods=["POST"])
def lecture_move(lid):
    lec = db.get_or_404(Lecture, lid)
    _swap(list(lec.module.lectures), lec, request.form.get("dir"))
    return _back(lec.module.program_id, f"#l{lec.id}")


# ── Video (Bunny Stream) ────────────────────────────────────────────────────

@bp.route("/mavzu/<int:lid>/video", methods=["POST"])
def video_start(lid):
    """Bunny'da yangi video yaratadi va brauzerga yuklash imzosini beradi."""
    lec = db.get_or_404(Lecture, lid)
    if not bunny.enabled():
        return jsonify(ok=False, error="Bunny Stream sozlanmagan — Sozlamalar → O'quvchi ilovasi."), 400
    ok, guid = bunny.create_video(f"{lec.module.program.name} — {lec.title}")
    if not ok:
        return jsonify(ok=False, error=guid), 502
    bunny.delete_video(lec.video_id)  # almashtirilsa — eskisi o'chadi
    lec.video_id, lec.video_status, lec.duration = guid, "yuklanmoqda", 0
    db.session.commit()
    ticket = bunny.upload_ticket(guid)
    return jsonify(ok=True, **ticket, title=lec.title)


@bp.route("/mavzu/<int:lid>/holat")
def video_status(lid):
    lec = db.get_or_404(Lecture, lid)
    if lec.video_id and bunny.enabled():
        info = bunny.video_info(lec.video_id)
        if info:
            # Brauzer yuklashni tugatgan bo'lsa ham Bunny hali «yuklanmoqda» ko'rsatishi mumkin
            if not (info["status"] == "yuklanmoqda" and request.args.get("uploaded")):
                lec.video_status = info["status"]
            else:
                lec.video_status = "ishlanmoqda"
            if info["duration"]:
                lec.duration = info["duration"]
            db.session.commit()
            return jsonify(ok=True, status=lec.video_status, label=VIDEO_STATUS.get(lec.video_status),
                           progress=info["progress"], minutes=lec.minutes)
    return jsonify(ok=True, status=lec.video_status, label=VIDEO_STATUS.get(lec.video_status, ""), minutes=lec.minutes)


@bp.route("/mavzu/<int:lid>/video/ochirish", methods=["POST"])
def video_delete(lid):
    lec = db.get_or_404(Lecture, lid)
    bunny.delete_video(lec.video_id)
    lec.video_id, lec.video_status, lec.duration = "", "", 0
    db.session.commit()
    flash("Video olib tashlandi.", "ok")
    return _back(lec.module.program_id, f"#l{lec.id}")


@bp.route("/mavzu/<int:lid>/korish")
def preview(lid):
    lec = db.get_or_404(Lecture, lid)
    embed = bunny.embed_url(lec.video_id) if lec.video_id and bunny.enabled() else None
    return render_template("pages/oquv_preview.html", lec=lec, embed=embed,
                           paras=[x.strip() for x in (lec.body or "").split("\n\n") if x.strip()])


# ── Ilova sozlamalari (rahbar / buxgalter) ──────────────────────────────────

@bp.route("/sozla", methods=["POST"])
def configure():
    require_role("rahbar", "buxgalter")
    f = request.form
    F.set_setting("bunny_library", (f.get("bunny_library") or "").strip()[:20])
    for key in ("bunny_key", "bunny_token_key"):
        val = (f.get(key) or "").strip()
        if val:
            F.set_setting(key, val[:200])
        elif f.get(f"{key}_clear"):
            F.set_setting(key, "")
    if f.get("prayer_method") in P.METHODS:
        F.set_setting("prayer_method", f["prayer_method"])
    if f.get("prayer_asr") in P.ASR:
        F.set_setting("prayer_asr", f["prayer_asr"])
    if f.get("app_city") in P.CITIES:
        F.set_setting("app_city", f["app_city"])
    offs = []
    for k, _ in P.PRAYERS:
        try:
            offs.append(str(max(-30, min(30, int(float(f.get(f"off_{k}") or 0))))))
        except ValueError:
            offs.append("0")
    F.set_setting("prayer_offsets", ",".join(offs))
    audit.log("settings", "O'quvchi ilovasi sozlamalari")
    db.session.commit()
    if bunny.enabled():
        ok, res = bunny.api("GET", "/videos?page=1&itemsPerPage=1")
        flash("Saqlandi. Bunny Stream ulandi ✓" if ok else f"Saqlandi, lekin Bunny javob bermadi: {res}",
              "ok" if ok else "warn")
    else:
        flash("Ilova sozlamalari saqlandi.", "ok")
    return redirect(url_for("sozlama.index", bolim="ilova"))


# ── O'quvchini ilovaga taklif qilish ────────────────────────────────────────

@bp.route("/taklif/<int:mid>", methods=["POST"])
def invite(mid):
    m = db.get_or_404(Member, mid)
    link = app_url(f"/app/k/{S.issue_invite(m)}")
    audit.log("app_access", f"Ilovaga taklif havolasi: {m.full_name}")
    db.session.commit()
    return jsonify(ok=True, link=link, qr=str(Markup(qr_svg(link))))


@bp.route("/taklif/<int:mid>/telegram", methods=["POST"])
def invite_telegram(mid):
    m = db.get_or_404(Member, mid)
    back = safe_next(url_for("dastur.member", mid=m.id))
    url = app_url()
    if not (m.telegram and m.telegram.active):
        flash("O'quvchi Telegram'ga ulanmagan.", "bad")
        return redirect(back)
    text = (f"📱 <b>{F.get_setting('org_name') or 'Assoodiq'} ilovasi</b>\n\n"
            "Kurslaringiz, video darslar, dars jadvali, to'lovlar, namoz vaqtlari, qibla va zakot kalkulyatori — "
            "bitta joyda. Pastdagi tugmani bosing 👇")
    kb = ({"inline_keyboard": [[{"text": "📱 Ilovani ochish", "web_app": {"url": url}}]]}
          if url.startswith("https://") else None)
    if kb is None:
        text += f"\n\n{url}k/{S.issue_invite(m)}"
    r = T.deliver(m, text, "xabar", None, g.user.id) if kb is None else _send_kb(m, text, kb)
    flash("Telegram'ga yuborildi." if r == "sent" else "Yuborib bo'lmadi — Sozlamalar → Telegram'ni tekshiring.",
          "ok" if r == "sent" else "bad")
    return redirect(back)


def _send_kb(m, text, kb):
    ok, _ = T.send(m.telegram.chat_id, text, kb)
    return "sent" if ok else "failed"


@bp.route("/taklif/<int:mid>/bekor", methods=["POST"])
def invite_revoke(mid):
    m = db.get_or_404(Member, mid)
    S.revoke_all(m)
    audit.log("app_access", f"Ilovadan chiqarildi (barcha qurilmalar): {m.full_name}")
    db.session.commit()
    flash("O'quvchi barcha qurilmalardan chiqarildi, eski havola o'chdi.", "ok")
    return redirect(safe_next(url_for("dastur.member", mid=m.id)))

