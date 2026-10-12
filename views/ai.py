"""Sun'iy intellekt: sozlamalar, xodimning Telegram'ini ulash, haftalik tahlilni qo'lda tuzish."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from core import ai, audit
from core import ai_report as R
from core import finance as F
from core import staff_bot as S
from core import telegram as T
from core.attendance import qr_svg
from core.extensions import db
from core.models import AiUsage, StaffLink
from views import require_role, safe_next

bp = Blueprint("ai", __name__, url_prefix="/ai")


def usage_stats():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    q = AiUsage.query.filter(AiUsage.created_at >= now - timedelta(days=30))
    rows = q.all()
    by = {}
    for u in rows:
        b = by.setdefault(u.feature or "boshqa", {"n": 0, "cost": 0.0})
        b["n"] += 1
        b["cost"] += u.cost_usd or 0
    return {"today": ai.used_today(), "limit": ai.daily_limit(), "month_cost": ai.month_cost(),
            "days30": len(rows), "by": by}


@bp.route("/sozla", methods=["POST"])
def configure():
    require_role("rahbar", "buxgalter")
    f = request.form
    key = (f.get("ai_key") or "").strip()
    if key:
        ok, msg = ai.check_key(key)
        if not ok:
            flash(f"Kalit saqlanmadi: {msg}", "bad")
            return redirect(url_for("sozlama.index", bolim="ai"))
        F.set_setting("ai_key", key)
    elif f.get("ai_key_clear"):
        F.set_setting("ai_key", "")
    F.set_setting("ai_weekly", "1" if f.get("ai_weekly") else "0")
    F.set_setting("contract_students", "1" if f.get("contract_students") else "0")
    for k, lo, hi in (("ai_weekly_day", 0, 6), ("ai_weekly_hour", 0, 23), ("ai_daily_limit", 1, 2000),
                      ("contract_student_daily", 1, 50)):
        try:
            F.set_setting(k, str(min(max(int(float(f.get(k) or 0)), lo), hi)))
        except ValueError:
            pass
    audit.log("settings", "Sun'iy intellekt sozlamalari")
    db.session.commit()
    flash("Saqlandi." + (" Kalit tekshirildi ✓" if key else ""), "ok")
    return redirect(url_for("sozlama.index", bolim="ai"))


@bp.route("/openai", methods=["POST"])
def configure_openai():
    """Video darslarni matnga aylantirish: OpenAI kaliti, model, tillar va atamalar."""
    from core import transcribe as STT
    require_role("rahbar", "buxgalter")
    f = request.form
    model = f.get("stt_model") if f.get("stt_model") in STT.MODELS else "gpt-transcribe"
    key = (f.get("openai_key") or "").strip()
    note = ""
    if key:
        ok, msg, avail = STT.check_key(key, model)
        if not ok:
            flash(f"OpenAI kaliti saqlanmadi: {msg}", "bad")
            return redirect(url_for("sozlama.index", bolim="ai") + "#openai")
        F.set_setting("openai_key", key)
        if avail and model not in avail:
            note = f" {model} hisobingizda ko'rinmadi — {avail[0]} tanlandi."
            model = avail[0]
        elif not avail:
            note = " Hisobda transkripsiya modellari ro'yxati ko'rinmadi — «Modellarni sinash»ni bosing."
    elif f.get("openai_key_clear"):
        F.set_setting("openai_key", "")
    F.set_setting("stt_model", model)
    F.set_setting("stt_languages", (f.get("stt_languages") or "").strip()[:40])
    F.set_setting("stt_keywords", (f.get("stt_keywords") or "").strip()[:500])  # Setting.value — 500 belgi
    audit.log("settings", "OpenAI (video matnga) sozlamalari")
    db.session.commit()
    flash("Saqlandi." + (" OpenAI kaliti tekshirildi ✓" if key else "") + note, "bad" if note else "ok")
    return redirect(url_for("sozlama.index", bolim="ai") + "#openai")


def _diag_json(rows):
    """Sinov natijasi sozlamaga sig'sin (500 belgi): xato matnlari kerak bo'lsa qisqartiriladi."""
    import json
    at = datetime.now().strftime("%d.%m.%Y %H:%M")
    for limit in (120, 80, 50, 25, 0):
        raw = json.dumps({"at": at, "rows": [[r["model"], int(r["ok"]), r["variant"], r["error"][:limit]] for r in rows]},
                         ensure_ascii=False)
        if len(raw) <= 500:
            return raw
    return json.dumps({"at": at, "rows": []})


@bp.route("/openai/sinash", methods=["POST"])
def test_openai():
    """Har bir modelni 2 soniyalik sinov ovozi bilan tekshiradi; ishlagan eng yaxshisini tanlaydi."""
    from core import transcribe as STT
    require_role("rahbar", "buxgalter")
    if not STT.enabled():
        flash("Avval OpenAI kalitini kiriting.", "bad")
        return redirect(url_for("sozlama.index", bolim="ai") + "#openai")
    try:
        rows = STT.diagnose()
    except ai.AiError as e:
        flash(str(e), "bad")
        return redirect(url_for("sozlama.index", bolim="ai") + "#openai")
    F.set_setting("stt_diag", _diag_json(rows))
    good = [r["model"] for r in rows if r["ok"]]
    if good and STT.model() not in good:
        F.set_setting("stt_model", good[0])
        flash(f"{STT.MODELS[good[0]]['name'].split(' — ')[0]} ishlaydi va tanlandi.", "ok")
    elif good:
        flash(f"Tanlangan model ishlaydi ✓ ({len(good)} ta model ishlaydi).", "ok")
    else:
        flash("Hech bir model ishlamadi — pastdagi sabablarni ko'ring.", "bad")
    db.session.commit()
    return redirect(url_for("sozlama.index", bolim="ai") + "#openai")


@bp.route("/telegram")
def link_page():
    link = StaffLink.query.filter_by(user_id=g.user.id).first()
    deep = S.deep_link(link.token) if link and link.token else ""
    return render_template("pages/ai_link.html", link=link, deep=deep, qr=qr_svg(deep) if deep else "",
                           tg_on=T.enabled() and bool(T.bot_username()), ai_on=ai.enabled(),
                           hooked=bool(F.get_setting("tg_webhook")))


@bp.route("/telegram/havola", methods=["POST"])
def link_new():
    if not (T.enabled() and T.bot_username()):
        flash("Avval Telegram botni ulang — Sozlamalar → Telegram.", "bad")
        return redirect(url_for("ai.link_page"))
    S.new_token(g.user)
    return redirect(url_for("ai.link_page"))


@bp.route("/telegram/uzish", methods=["POST"])
def link_off():
    link = StaffLink.query.filter_by(user_id=g.user.id).first()
    if link:
        link.active, link.token, link.chat_id = False, None, None
        db.session.commit()
    flash("Telegram uzildi.", "ok")
    return redirect(url_for("ai.link_page"))


@bp.route("/hisobot", methods=["POST"])
def report_now():
    require_role("rahbar", "buxgalter")
    try:
        R.weekly(user_id=g.user.id)
        flash("Tahlil tayyor.", "ok")
    except ai.AiError as e:
        flash(str(e), "bad")
    return redirect(safe_next(url_for("main.dashboard")) + "#ai-report")
