"""Telegram: o'quvchilarga eslatma va xabarlar (bot orqali).

Ulash: o'quvchi botga havola orqali kiradi (t.me/<bot>?start=AQ0000231) yoki telefon raqamini
ulashadi — raqam bazadagi a'zo bilan solishtiriladi. Shundan keyin dars, obuna va to'lov
eslatmalari keladi; botda «📅 Jadval» va «💳 To'lov» ni o'zi ko'radi.

Avtomatik eslatmalar fon oqimida har daqiqada tekshiriladi; har biri `Notification.dedup`
kaliti bilan faqat bir marta ketadi (bir nechta jarayon bo'lsa ham).
"""
import hashlib
import html
import json
import logging
import os
import re
import threading
import time as _time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from core import finance as F
from core.attendance import member_code, parse_code
from core.extensions import db
from core.models import Enrollment, Lesson, Member, Notification, TelegramLink

log = logging.getLogger("assoodiq.telegram")
API = "https://api.telegram.org/bot{token}/{method}"
WD = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr",
          "noyabr", "dekabr"]

DEFAULT_TEMPLATES = {
    "dars": "📚 Assalomu alaykum, {ism}!\n\n{kun} soat <b>{vaqt}</b> da «{dastur}» darsi: <b>{dars}</b>.\n📍 {joy}\n\nKutib qolamiz!",
    "qarz": "💳 Assalomu alaykum, {ism}!\n\n«{dastur}» bo'yicha to'lov qoldig'ingiz: <b>{qoldiq} so'm</b>.\nIltimos, imkon qadar to'lovni amalga oshiring. Rahmat!",
    "obuna": "🔔 Assalomu alaykum, {ism}!\n\n«{dastur}» obunangiz <b>{sana}</b> da tugaydi. Uzaytirish uchun biz bilan bog'laning.",
}
PLACEHOLDERS = {
    "dars": "{ism} {dars} {dastur} {kun} {sana} {vaqt} {joy} {ustoz}",
    "qarz": "{ism} {dastur} {qoldiq}",
    "obuna": "{ism} {dastur} {sana}",
}
MENU = {"keyboard": [[{"text": "📅 Jadval"}, {"text": "💳 To'lov"}]], "resize_keyboard": True}


# ── Sozlama va API ──────────────────────────────────────────────────────────

def token():
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or F.get_setting("tg_token") or "").strip()


def enabled():
    return bool(token())


def webhook_secret(tok=None):
    tok = tok or token()
    return hashlib.sha256(("assoodiq-tg:" + tok).encode()).hexdigest()[:32] if tok else ""


def api(method, payload=None, tok=None, timeout=10):
    """Telegram Bot API chaqiruvi. Natija: (ok, result_yoki_xato_matni)."""
    tok = tok or token()
    if not tok:
        return False, "Bot tokeni kiritilmagan"
    req = urllib.request.Request(API.format(token=tok, method=method),
                                 data=json.dumps(payload or {}).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode())
        except Exception:  # noqa: BLE001
            return False, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 — tarmoq xatosi
        return False, f"Telegram bilan aloqa yo'q: {e.__class__.__name__}"
    if data.get("ok"):
        return True, data.get("result")
    return False, data.get("description", "Noma'lum xato")


def send(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = keyboard
    return api("sendMessage", payload)


FILE_API = "https://api.telegram.org/file/bot{token}/{path}"


def download_file(file_id, limit=10_000_000):
    """Telegram'dagi fayl (chek rasmi) baytlari yoki None."""
    ok, res = api("getFile", {"file_id": file_id})
    if not ok or not res.get("file_path") or (res.get("file_size") or 0) > limit:
        return None
    try:
        with urllib.request.urlopen(FILE_API.format(token=token(), path=res["file_path"]), timeout=20) as r:
            data = r.read(limit + 1)
    except Exception:  # noqa: BLE001 — tarmoq xatosi
        return None
    return data if len(data) <= limit else None


def bot_username():
    return F.get_setting("tg_bot") or ""


def app_url():
    """O'quvchi ilovasi (Telegram Mini App) manzili — faqat https bo'lsa."""
    base = (F.get_setting("tg_webhook") or "").rstrip("/")
    return base + "/app/" if base.startswith("https://") else ""


def app_button(text="📱 Ilovani ochish"):
    url = app_url()
    return {"inline_keyboard": [[{"text": text, "web_app": {"url": url}}]]} if url else None


def deep_link(member_id):
    bot = bot_username()
    return f"https://t.me/{bot}?start={member_code(member_id)}" if bot else ""


# ── Shablonlar ──────────────────────────────────────────────────────────────

def template(kind):
    return F.get_setting(f"tg_tpl_{kind}") or DEFAULT_TEMPLATES[kind]


def render(tpl, **values):
    """{ism} kabi joylarni xavfsiz (HTML-escape) qiymatlar bilan to'ldiradi."""
    safe = {k: html.escape(str(v if v is not None else "")) for k, v in values.items()}
    return re.sub(r"\{(\w+)\}", lambda m: safe.get(m.group(1), m.group(0)), tpl)


def _fmt_money(v):
    return f"{v:,.0f}".replace(",", " ")


def _day_word(d, today=None):
    today = today or date.today()
    if d == today:
        return "Bugun"
    if d == today + timedelta(days=1):
        return "Ertaga"
    return f"{WD[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"


def lesson_values(les, member):
    return {"ism": member.full_name.split()[0], "dars": les.title, "dastur": les.program.name,
            "kun": _day_word(les.date), "sana": f"{les.date.day} {MONTHS[les.date.month - 1]}",
            "vaqt": les.start.strftime("%H:%M"), "joy": les.location or "markazimizda", "ustoz": les.teacher or ""}


# ── Yuborish (jurnal bilan) ─────────────────────────────────────────────────

def deliver(member, text, kind="xabar", dedup=None, user_id=None):
    """A'zoga yuborish. Natija: 'sent' | 'failed' | 'nolink' | 'dup'."""
    link = member.telegram if member else None
    if not link or not link.active:
        return "nolink"
    note = Notification(member_id=member.id, chat_id=link.chat_id, kind=kind, text=text, dedup=dedup,
                        created_by=user_id)
    db.session.add(note)
    try:
        db.session.commit()
    except IntegrityError:  # bu eslatma allaqachon yuborilgan (yoki boshqa jarayon yubormoqda)
        db.session.rollback()
        return "dup"
    ok, res = send(link.chat_id, text)
    note.status = "sent" if ok else "failed"
    if not ok:
        note.error = str(res)[:255]
        if "blocked" in str(res).lower() or "chat not found" in str(res).lower():
            link.active = False  # botni bloklagan — keyingi safar urinmaymiz
        else:
            note.dedup = None  # tarmoq xatosi — avtomatik eslatma keyingi daqiqada qayta urinadi
    db.session.commit()
    return note.status


def summarize(results):
    c = {k: results.count(k) for k in ("sent", "failed", "nolink", "dup")}
    parts = [f"{c['sent']} ta yuborildi"]
    if c["nolink"]:
        parts.append(f"{c['nolink']} tasi Telegram'ga ulanmagan")
    if c["dup"]:
        parts.append(f"{c['dup']} tasiga avval yuborilgan")
    if c["failed"]:
        parts.append(f"{c['failed']} tasida xato")
    return ", ".join(parts) + ".", c


def lesson_members(les):
    return [e.member for e in Enrollment.query.filter(Enrollment.program_id == les.program_id,
                                                      Enrollment.status == "faol").all()
            if not e.joined_at or e.joined_at <= les.date]


def remind_lesson(les, user_id=None):
    tpl = template("dars")
    return [deliver(m, render(tpl, **lesson_values(les, m)), "dars", f"dars:{les.id}:{m.id}", user_id)
            for m in lesson_members(les)]


# ── Avtomatik eslatmalar ────────────────────────────────────────────────────

def run_due(now=None):
    """Vaqti kelgan eslatmalarni yuboradi (fon oqimi har daqiqada chaqiradi)."""
    if not enabled():
        return 0
    now = now or datetime.now()
    today, sent = now.date(), 0
    if F.get_setting("tg_auto_lessons") == "1":
        lead = timedelta(hours=float(F.get_setting("tg_lead_hours") or 3))
        lessons = Lesson.query.filter(Lesson.status == "rejada", Lesson.date >= today,
                                      Lesson.date <= (now + lead).date()).all()
        for les in lessons:
            start = datetime.combine(les.date, les.start)
            if now < start <= now + lead:
                sent += remind_lesson(les).count("sent")
    if F.get_setting("tg_auto_expiry") == "1":
        target = today + timedelta(days=int(float(F.get_setting("tg_expiry_days") or 3)))
        tpl = template("obuna")
        for e in Enrollment.query.filter(Enrollment.status == "faol", Enrollment.valid_until == target).all():
            text = render(tpl, ism=e.member.full_name.split()[0], dastur=e.program.name,
                          sana=f"{target.day} {MONTHS[target.month - 1]}")
            sent += deliver(e.member, text, "obuna", f"obuna:{e.id}:{target.isoformat()}") == "sent"
    pay_day = int(float(F.get_setting("tg_pay_day") or 0))
    if F.get_setting("tg_auto_pay") == "1" and pay_day and today.day == pay_day and now.hour >= 10:
        sent += sum(r == "sent" for r in remind_debtors(dedup_month=today.strftime("%Y-%m")))
    return sent


def remind_debtors(program_id=None, dedup_month=None, user_id=None):
    paid_map = F.enrollment_paid_map()
    q = Enrollment.query.filter(Enrollment.status != "chiqqan")
    if program_id:
        q = q.filter(Enrollment.program_id == program_id)
    tpl, out = template("qarz"), []
    for e in q.all():
        due = F.enrollment_row(e, paid_map)["due"]
        if due <= 0.01:
            continue
        text = render(tpl, ism=e.member.full_name.split()[0], dastur=e.program.name, qoldiq=_fmt_money(due))
        out.append(deliver(e.member, text, "qarz", f"qarz:{e.id}:{dedup_month}" if dedup_month else None, user_id))
    return out


_thread = None


def start_scheduler(app, interval=60):
    """Fon oqimi: har daqiqada run_due(). Bitta jarayonda bir marta ishga tushadi."""
    global _thread
    if _thread is not None or os.environ.get("TELEGRAM_SCHEDULER", "1") == "0":
        return

    def loop():
        _time.sleep(15)
        while True:
            try:
                with app.app_context():
                    run_due()
            except Exception:  # noqa: BLE001
                log.exception("Telegram eslatmalari xatosi")
            try:
                with app.app_context():
                    from core import ai_report
                    ai_report.run_due()
            except Exception:  # noqa: BLE001
                log.exception("Haftalik tahlil xatosi")
            finally:
                with app.app_context():
                    db.session.remove()
            _time.sleep(interval)

    _thread = threading.Thread(target=loop, name="tg-reminders", daemon=True)
    _thread.start()


# ── Bot: kelgan xabarlarni qayta ishlash (webhook) ──────────────────────────

def _digits(s):
    return re.sub(r"\D", "", s or "")[-9:]


def link_member(member, chat_id, user):
    link = TelegramLink.query.filter_by(member_id=member.id).first() or TelegramLink(member_id=member.id)
    link.chat_id, link.active = str(chat_id), True
    link.username = (user.get("username") or "")[:64]
    link.first_name = (user.get("first_name") or "")[:120]
    link.linked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.add(link)
    db.session.commit()
    return link


def chat_members(chat_id):
    return [lk.member for lk in TelegramLink.query.filter_by(chat_id=str(chat_id), active=True).all()]


def schedule_text(members):
    today = date.today()
    pids = {e.program_id for m in members for e in m.enrollments.filter_by(status="faol").all()}
    lessons = (Lesson.query.filter(Lesson.program_id.in_(pids), Lesson.date >= today, Lesson.status == "rejada")
               .order_by(Lesson.date, Lesson.start).limit(6).all()) if pids else []
    if not lessons:
        return "📅 Yaqin kunlarda rejalashtirilgan dars yo'q."
    rows = [f"• <b>{_day_word(x.date)}</b>, {x.start:%H:%M} — {html.escape(x.title)}\n   <i>{html.escape(x.program.name)}"
            f"{' · ' + html.escape(x.location) if x.location else ''}</i>" for x in lessons]
    return "📅 <b>Yaqin darslar</b>\n\n" + "\n".join(rows)


def dues_text(members):
    paid_map = F.enrollment_paid_map()
    rows, total = [], 0
    for m in members:
        for e in m.enrollments.filter(Enrollment.status != "chiqqan").all():
            r = F.enrollment_row(e, paid_map)
            if r["due"] > 0.01:
                total += r["due"]
                rows.append(f"• {html.escape(e.program.name)}: <b>{_fmt_money(r['due'])} so'm</b>")
    if not rows:
        return "✅ Qarzdorligingiz yo'q. Rahmat!"
    return "💳 <b>To'lov qoldig'i</b>\n\n" + "\n".join(rows) + f"\n\nJami: <b>{_fmt_money(total)} so'm</b>"


def handle_update(upd):
    from core import staff_bot
    if upd.get("callback_query"):
        staff_bot.handle_callback(upd["callback_query"])
        return
    msg = upd.get("message") or {}
    chat = msg.get("chat") or {}
    if chat.get("type") != "private" or not chat.get("id"):
        return
    chat_id, user = chat["id"], msg.get("from") or {}
    text = (msg.get("text") or "").strip()
    # Xodimlar: /start X<token> — ulash; ulangan chat — kassa yordamchisi rejimi
    param = text[6:].strip() if text.startswith("/start") else ""
    if param.startswith("X"):
        link = staff_bot.link_by_token(param[1:], chat_id, user)
        if link:
            send(chat_id, f"✅ Ulandi: <b>{html.escape(link.user.name)}</b>\n\n" + staff_bot.HELP,
                 {"remove_keyboard": True})
        else:
            send(chat_id, "Havola eskirgan yoki noto'g'ri. Saytdan yangisini oling.")
        return
    staff = staff_bot.for_chat(chat_id)
    if staff:
        staff_bot.handle_message(msg, staff)
        return
    members = chat_members(chat_id)
    org = F.get_setting("org_name") or "Assoodiq"

    if text.startswith("/start"):
        mid = parse_code(text[6:])
        m = db.session.get(Member, mid) if mid else None
        if m:
            link_member(m, chat_id, user)
            send(chat_id, f"Assalomu alaykum, <b>{html.escape(m.full_name)}</b>! 🌿\n\n{html.escape(org)} botiga ulandingiz. "
                          "Endi dars, obuna va to'lov eslatmalari shu yerga keladi.\n\n"
                          "📅 Jadval — yaqin darslaringiz\n💳 To'lov — to'lov qoldig'i", MENU)
            if app_button():
                send(chat_id, "📱 Kurslar, video darslar, namoz vaqtlari va qibla — ilovada:", app_button())
        elif members:
            send(chat_id, "Siz allaqachon ulangansiz ✅", MENU)
        else:
            send(chat_id, f"Assalomu alaykum! {html.escape(org)} botiga xush kelibsiz.\n\n"
                          "Sizni topishimiz uchun pastdagi tugma orqali telefon raqamingizni yuboring 👇",
                 {"keyboard": [[{"text": "📱 Raqamni yuborish", "request_contact": True}]],
                  "resize_keyboard": True, "one_time_keyboard": True})
        return

    contact = msg.get("contact")
    if contact:
        if contact.get("user_id") and contact.get("user_id") != user.get("id"):
            send(chat_id, "Iltimos, o'zingizning raqamingizni yuboring.")
            return
        digits = _digits(contact.get("phone_number"))
        found = [m for m in Member.query.filter(Member.phone != "").all() if digits and _digits(m.phone) == digits]
        if not found:
            send(chat_id, "Afsuski, bu raqam bazamizda topilmadi. Administratorga murojaat qiling yoki "
                          "o'quvchi kartangizdagi havola orqali kiring.", {"remove_keyboard": True})
            return
        for m in found:
            link_member(m, chat_id, user)
        names = ", ".join(html.escape(m.full_name) for m in found)
        send(chat_id, f"Rahmat, <b>{names}</b>! Ulandingiz ✅\nEndi eslatmalar shu yerga keladi.", MENU)
        return

    if not members:
        send(chat_id, "Avval ulaning: /start ni bosing va telefon raqamingizni yuboring.")
        return
    low = text.lower()
    if low in ("/jadval", "📅 jadval", "jadval"):
        send(chat_id, schedule_text(members), MENU)
    elif low in ("/tolov", "/qarz", "💳 to'lov", "to'lov"):
        send(chat_id, dues_text(members), MENU)
    elif low in ("/ilova", "/app", "📱 ilova", "ilova"):
        kb = app_button()
        send(chat_id, "📱 Ilovani oching:" if kb else "Ilova hali sozlanmagan.", kb or MENU)
    elif low == "/stop":
        for lk in TelegramLink.query.filter_by(chat_id=str(chat_id)).all():
            lk.active = False
        db.session.commit()
        send(chat_id, "Eslatmalar to'xtatildi. Qayta ulash uchun /start ni bosing.", {"remove_keyboard": True})
    else:
        send(chat_id, "Quyidagi tugmalardan foydalaning:\n📅 Jadval — yaqin darslar\n💳 To'lov — to'lov qoldig'i\n"
                      "/stop — eslatmalarni to'xtatish", MENU)
