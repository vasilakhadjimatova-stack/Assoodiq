"""Telegram: webhook (bot), sozlamalar va qo'lda xabar yuborish."""
import hmac
from html import escape

from flask import Blueprint, abort, flash, g, jsonify, redirect, request, url_for

from core import audit
from core import finance as F
from core import telegram as T
from core.extensions import db
from core.models import Enrollment, Lesson, Member, Program
from views import form_int, require_role, safe_next

bp = Blueprint("telegram", __name__, url_prefix="/telegram")


@bp.route("/hook/<secret>", methods=["POST"])
def hook(secret):
    """Telegram serveridan keladigan yangilanishlar (kirish talab qilinmaydi, maxfiy kalit bilan)."""
    expected = T.webhook_secret()
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not expected or not hmac.compare_digest(secret, expected) or not hmac.compare_digest(header, expected):
        abort(404)
    try:
        T.handle_update(request.get_json(silent=True) or {})
    except Exception:  # noqa: BLE001 — Telegram qayta-qayta yubormasin
        db.session.rollback()
        T.log.exception("Telegram yangilanishini qayta ishlashda xato")
    return jsonify(ok=True)


# ── Sozlamalar (rahbar / buxgalter) ─────────────────────────────────────────

def _settings_back():
    return redirect(url_for("sozlama.index", bolim="telegram"))


@bp.route("/sozla", methods=["POST"])
def configure():
    require_role("rahbar", "buxgalter")
    f = request.form
    tok = (f.get("token") or "").strip()
    if tok and tok != F.get_setting("tg_token"):
        ok, res = T.api("getMe", tok=tok)
        if not ok:
            flash(f"Token ishlamadi: {res}", "bad")
            return _settings_back()
        F.set_setting("tg_token", tok)
        F.set_setting("tg_bot", res.get("username", ""))
        F.set_setting("tg_webhook", "")
        flash(f"Bot ulandi: @{res.get('username')}. Endi «Botni saytga ulash» tugmasini bosing.", "ok")
    for key in ("tg_auto_lessons", "tg_auto_expiry", "tg_auto_pay"):
        F.set_setting(key, "1" if f.get(key) else "0")
    for key, lo, hi in (("tg_lead_hours", 0.5, 72), ("tg_expiry_days", 1, 30), ("tg_pay_day", 1, 28)):
        try:
            v = min(max(float((f.get(key) or "").replace(",", ".")), lo), hi)
            F.set_setting(key, f"{v:g}")
        except ValueError:
            pass
    for kind in T.DEFAULT_TEMPLATES:
        text = (f.get(f"tg_tpl_{kind}") or "").strip()
        F.set_setting(f"tg_tpl_{kind}", "" if text == T.DEFAULT_TEMPLATES[kind] else text[:1500])
    audit.log("settings", "Telegram sozlamalari")
    db.session.commit()
    if not tok or tok == F.get_setting("tg_token"):
        flash("Telegram sozlamalari saqlandi.", "ok")
    return _settings_back()


@bp.route("/webhook", methods=["POST"])
def connect_webhook():
    require_role("rahbar", "buxgalter")
    if not T.enabled():
        flash("Avval bot tokenini kiriting.", "bad")
        return _settings_back()
    base = (request.form.get("base") or request.url_root).rstrip("/")
    if base.startswith("http://") and "localhost" not in base and "127.0.0.1" not in base:
        base = "https://" + base[len("http://"):]  # Railway proksi ortida — Telegram faqat https qabul qiladi
    url = f"{base}{url_for('telegram.hook', secret=T.webhook_secret())}"
    ok, res = T.api("setWebhook", {"url": url, "secret_token": T.webhook_secret(),
                                   "allowed_updates": ["message"], "drop_pending_updates": True})
    if ok:
        F.set_setting("tg_webhook", base)
        T.api("setMyCommands", {"commands": [{"command": "jadval", "description": "Yaqin darslar"},
                                             {"command": "tolov", "description": "To'lov qoldig'i"},
                                             {"command": "ilova", "description": "O'quvchi ilovasi"},
                                             {"command": "stop", "description": "Eslatmalarni to'xtatish"}]})
        if base.startswith("https://"):  # bot menyusida «Ilova» tugmasi — Telegram Mini App
            T.api("setChatMenuButton", {"menu_button": {"type": "web_app", "text": "Ilova",
                                                        "web_app": {"url": f"{base}/app/"}}})
        db.session.commit()
        flash("Bot saytga ulandi — o'quvchilar endi /start orqali ulana oladi.", "ok")
    else:
        flash(f"Webhook o'rnatilmadi: {res}", "bad")
    return _settings_back()


@bp.route("/uzish", methods=["POST"])
def disconnect():
    require_role("rahbar", "buxgalter")
    T.api("deleteWebhook", {})
    for key in ("tg_token", "tg_bot", "tg_webhook"):
        F.set_setting(key, "")
    audit.log("settings", "Telegram bot uzildi")
    db.session.commit()
    flash("Telegram bot uzildi.", "ok")
    return _settings_back()


# ── Qo'lda yuborish ─────────────────────────────────────────────────────────

@bp.route("/yuborish", methods=["POST"])
def broadcast():
    """Xabar: bitta a'zoga, dastur a'zolariga yoki faqat qarzdorlarga."""
    f = request.form
    back = safe_next(url_for("dastur.programs"))
    if not T.enabled():
        flash("Telegram bot ulanmagan — Sozlamalar → Telegram.", "bad")
        return redirect(back)
    scope = f.get("scope")
    if scope == "qarzdorlar":
        results = T.remind_debtors(form_int(f.get("program_id")), user_id=g.user.id)
    else:
        text = (f.get("text") or "").strip()
        if not text:
            flash("Xabar matnini yozing.", "bad")
            return redirect(back)
        if scope == "azo":
            m = db.session.get(Member, form_int(f.get("member_id")) or 0)
            members = [m] if m else []
            program = None
        else:
            program = db.session.get(Program, form_int(f.get("program_id")) or 0)
            members = [e.member for e in program.enrollments.filter(Enrollment.status == "faol").all()] if program else []
        results = [T.deliver(m, T.render(escape(text, quote=False), ism=m.full_name.split()[0],
                                         dastur=program.name if program else ""), "xabar", None, g.user.id)
                   for m in {x.id: x for x in members}.values()]
    msg, c = T.summarize(results)
    flash(("Telegram: " + msg) if results else "Yuboriladigan a'zo topilmadi.", "ok" if c["sent"] else "warn")
    return redirect(back)


@bp.route("/dars/<int:lid>", methods=["POST"])
def lesson_reminder(lid):
    les = db.get_or_404(Lesson, lid)
    back = safe_next(url_for("kalendar.attendance", lid=lid))
    if not T.enabled():
        flash("Telegram bot ulanmagan — Sozlamalar → Telegram.", "bad")
        return redirect(back)
    msg, c = T.summarize(T.remind_lesson(les, g.user.id))
    flash("Dars eslatmasi: " + msg, "ok" if c["sent"] or c["dup"] else "warn")
    return redirect(back)
