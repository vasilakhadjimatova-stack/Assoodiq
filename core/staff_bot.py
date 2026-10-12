"""Telegram bot — xodimlar rejimi: kassaga matn yoki chek rasmi bilan yozish, moliyaviy savollar.

O'quvchilar bilan bir bot ishlatiladi: chat xodimga ulangan bo'lsa (StaffLink), xabar shu yerga keladi.
"""
import html
import secrets

from core import ai
from core import ai_kassa as K
from core import ai_report as R
from core import finance as F
from core import telegram as T
from core.extensions import db
from core.models import AiDraft, StaffLink

HELP = ("🤖 <b>Kassa yordamchisi</b>\n\n"
        "Oddiy so'z bilan yozing — men kassaga yozuv tayyorlayman, siz tasdiqlaysiz:\n"
        "• <i>Akmaldan 1.5 mln naqd kurs to'lovi oldim</i>\n"
        "• <i>Kecha ofis ijarasi 4 mln bankdan</i>\n"
        "• <i>Payme'dan bank hisobiga 10 mln o'tkazdim</i>\n"
        "• 📷 Chek yoki nakladnoy rasmini yuboring\n\n"
        "Savol ham bering: <i>Bu oy nega zarar?</i>, <i>Kim ko'p qarz?</i>\n\n"
        "/balans — hisoblar qoldig'i\n/hisobot — haftalik tahlil hozir")
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}


def new_token(user):
    link = StaffLink.query.filter_by(user_id=user.id).first() or StaffLink(user_id=user.id)
    link.token = secrets.token_urlsafe(18).replace("-", "a").replace("_", "b")
    db.session.add(link)
    db.session.commit()
    return link.token


def deep_link(token):
    bot = T.bot_username()
    return f"https://t.me/{bot}?start=X{token}" if bot and token else ""


def link_by_token(token, chat_id, tg_user):
    link = StaffLink.query.filter_by(token=token).first() if token else None
    if link is None or not link.user or not link.user.active:
        return None
    link.chat_id, link.active, link.token = str(chat_id), True, None
    link.linked_at = ai._utcnow()
    db.session.commit()
    return link


def for_chat(chat_id):
    link = StaffLink.query.filter_by(chat_id=str(chat_id), active=True).first()
    return link if link and link.user and link.user.active else None


def _buttons(draft_id):
    return {"inline_keyboard": [[{"text": "✅ Saqlash", "callback_data": f"ai:ok:{draft_id}"},
                                 {"text": "✖️ Bekor", "callback_data": f"ai:no:{draft_id}"}]]}


def _balances_text():
    rows = F.accounts_with_balance()
    lines = [f"• {html.escape(r['account'].name)}: <b>{K._money(r['balance'], r['account'].currency)}</b>" for r in rows]
    return "💰 <b>Hisoblar qoldig'i</b>\n\n" + "\n".join(lines) + \
        f"\n\nJami: <b>{K._money(F.total_balance_uzs(), 'UZS')}</b>"


def _file(msg):
    """Xabardagi rasm/PDF: (file_id, mime) yoki None."""
    if msg.get("photo"):
        sizes = [p for p in msg["photo"] if (p.get("file_size") or 0) <= 5_000_000] or msg["photo"][:1]
        return sizes[-1]["file_id"], "image/jpeg"
    doc = msg.get("document")
    if doc and doc.get("mime_type") in IMAGE_TYPES and (doc.get("file_size") or 0) <= 10_000_000:
        return doc["file_id"], doc["mime_type"]
    return None


def handle_message(msg, link):
    user, chat_id = link.user, msg["chat"]["id"]
    text = (msg.get("text") or msg.get("caption") or "").strip()
    low = text.lower()
    if low in ("/start", "/yordam", "/help") or low.startswith("/start "):
        T.send(chat_id, f"Assalomu alaykum, {html.escape(user.name)}! 👋\n\n" + HELP)
        return
    if low in ("/balans", "balans"):
        if user.role == "menejer":
            T.send(chat_id, "Hisoblar qoldig'i faqat rahbar va buxgalter uchun.")
        else:
            T.send(chat_id, _balances_text())
        return
    if msg.get("voice") or msg.get("audio") or msg.get("video_note"):
        T.send(chat_id, "🎙 Hozircha ovozli xabarni tushunmayman — matn yoki chek rasmini yuboring.")
        return
    if not ai.enabled():
        T.send(chat_id, "Sun'iy intellekt ulanmagan — Sozlamalar → Sun'iy intellekt bo'limida kalitni kiriting.")
        return
    T.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    try:
        if low in ("/hisobot", "hisobot"):
            if user.role == "menejer":
                T.send(chat_id, "Hisobot faqat rahbar va buxgalter uchun.")
                return
            T.send(chat_id, R.weekly(user_id=user.id).text)
            return
        f = _file(msg)
        image = None
        if f:
            image = T.download_file(f[0])
            if image is None:
                T.send(chat_id, "Faylni yuklab bo'lmadi (juda katta bo'lishi mumkin). Boshqa rasm yuboring.")
                return
            image = (image, f[1])
        elif not text:
            T.send(chat_id, HELP)
            return
        res = K.understand(text=text, image=image, user_id=user.id)
        if res["intent"] == "savol":
            if user.role == "menejer":
                T.send(chat_id, "Moliyaviy savollar faqat rahbar va buxgalter uchun. Kassaga yozuv yuborishingiz mumkin.")
                return
            T.send(chat_id, R.answer(res["reply"] or text, user_id=user.id))
            return
        if res["intent"] == "yozuv" and res["entries"]:
            entries = res["entries"]
            if user.role == "menejer" and any(e["kind"] != "kirim" for e in entries):
                T.send(chat_id, "Menejer faqat kirim yozishi mumkin. Chiqim va o'tkazmani rahbar yoki buxgalter yozadi.")
                return
            draft = K.create_draft(user, chat_id, text, entries, source="rasm" if image else "matn")
            T.send(chat_id, "🧾 <b>Tekshiring:</b>\n\n" + K.describe(entries) + "\n\nTo'g'rimi?", _buttons(draft.id))
            return
        T.send(chat_id, html.escape(res["reply"]) if res["reply"] else HELP)
    except ai.AiError as e:
        T.send(chat_id, f"⚠️ {html.escape(str(e))}")


def handle_callback(cq):
    data = cq.get("data") or ""
    msg = cq.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    link = for_chat(chat_id) if chat_id else None

    def toast(text):
        T.api("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": text[:190]})

    if not data.startswith("ai:") or link is None:
        toast("Ruxsat yo'q.")
        return
    try:
        _, action, did = data.split(":")
        draft = db.session.get(AiDraft, int(did))
    except ValueError:
        draft = None
    if draft is None:
        toast("Yozuv topilmadi.")
        return
    original = msg.get("text") or ""
    if action == "ok":
        ok, result = K.save_draft(draft, link.user)
    else:
        ok = K.cancel_draft(draft, link.user)
        result = "✖️ Bekor qilindi." if ok else "Bu yozuvni bekor qilib bo'lmaydi."
    toast(result)
    if ok:  # tugmalar olib tashlanadi, natija xabarga qo'shiladi
        body = html.escape(original.replace("To'g'rimi?", "").strip())
        T.api("editMessageText", {"chat_id": chat_id, "message_id": msg.get("message_id"),
                                  "text": f"{body}\n\n<b>{html.escape(result)}</b>", "parse_mode": "HTML"})

