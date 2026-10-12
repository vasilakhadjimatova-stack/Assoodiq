"""Sun'iy intellekt (Claude) bilan ishlash: so'rov, xarajat hisobi va limitlar.

Kalit: muhit o'zgaruvchisi ANTHROPIC_API_KEY yoki Sozlamalar → Sun'iy intellekt.
Har bir so'rov AiUsage jadvaliga yoziladi (tokenlar va taxminiy narx).
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from core import finance as F
from core.extensions import db
from core.models import AiUsage

log = logging.getLogger("assoodiq.ai")

MODEL = "claude-opus-5-5"
# 1 million token uchun AQSh dollarida (Claude Opus 5.5). Faqat taxminiy hisob uchun.
PRICE = {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00}


class AiError(Exception):
    """Foydalanuvchiga ko'rsatiladigan tushunarli xato."""


def api_key():
    return (os.environ.get("ANTHROPIC_API_KEY") or F.get_setting("ai_key") or "").strip()


def enabled():
    return bool(api_key())


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=api_key(), timeout=90, max_retries=2)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def used_today():
    start = _utcnow() - timedelta(hours=24)
    return AiUsage.query.filter(AiUsage.created_at >= start).count()


def daily_limit():
    try:
        return max(int(float(F.get_setting("ai_daily_limit") or 100)), 1)
    except ValueError:
        return 100


def month_cost():
    start = _utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return db.session.query(db.func.coalesce(db.func.sum(AiUsage.cost_usd), 0)).filter(AiUsage.created_at >= start).scalar()


def _cost(u):
    return ((u.get("input", 0) * PRICE["input"] + u.get("output", 0) * PRICE["output"]
             + u.get("cache_read", 0) * PRICE["cache_read"] + u.get("cache_write", 0) * PRICE["cache_write"]) / 1e6)


def _record(feature, user_id, usage=None, ok=True):
    u = {}
    if usage is not None:
        u = {"input": getattr(usage, "input_tokens", 0) or 0, "output": getattr(usage, "output_tokens", 0) or 0,
             "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
             "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0}
    db.session.add(AiUsage(feature=feature, user_id=user_id, ok=ok,
                           input_tokens=u.get("input", 0) + u.get("cache_read", 0) + u.get("cache_write", 0),
                           output_tokens=u.get("output", 0), cost_usd=round(_cost(u), 5)))
    db.session.commit()


def ask(system, content, *, feature, user_id=None, schema=None, effort="low", max_tokens=8000, stream=False,
        cache_ttl=None):
    """Claude'ga bitta so'rov. schema berilsa — JSON (dict), aks holda matn qaytaradi.

    system — o'zgarmas ko'rsatma (keshlanadi); content — foydalanuvchi qismi (matn yoki bloklar ro'yxati).
    """
    if not enabled():
        raise AiError("Sun'iy intellekt ulanmagan — Sozlamalar → Sun'iy intellekt bo'limida kalitni kiriting.")
    if used_today() >= daily_limit():
        raise AiError("Bugungi so'rovlar limiti tugadi. Ertaga yoki limitni oshirib qayta urinib ko'ring.")
    import anthropic
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    cache = {"type": "ephemeral", **({"ttl": cache_ttl} if cache_ttl else {})}
    kwargs = dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": cache}],
        messages=[{"role": "user", "content": content}],
        output_config=output_config,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    try:
        if stream:  # uzun tahlil — HTTP vaqt chegarasiga tushmaslik uchun oqim bilan
            with _client().beta.messages.stream(**kwargs) as s:
                resp = s.get_final_message()
        else:
            resp = _client().beta.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        _record(feature, user_id, ok=False)
        raise AiError("Sun'iy intellekt kaliti noto'g'ri — Sozlamalarda tekshiring.")
    except anthropic.PermissionDeniedError:
        _record(feature, user_id, ok=False)
        raise AiError("Kalitga ruxsat yo'q (hisobda mablag' yoki ruxsatlarni tekshiring).")
    except anthropic.RateLimitError:
        _record(feature, user_id, ok=False)
        raise AiError("Juda ko'p so'rov — bir daqiqadan keyin qayta urinib ko'ring.")
    except anthropic.APIStatusError as e:
        _record(feature, user_id, ok=False)
        log.warning("Claude xatosi %s: %s", e.status_code, getattr(e, "message", e))
        raise AiError("Sun'iy intellekt vaqtincha javob bermadi. Birozdan keyin qayta urinib ko'ring.")
    except anthropic.APIConnectionError:
        _record(feature, user_id, ok=False)
        raise AiError("Sun'iy intellekt bilan aloqa yo'q. Internetni tekshiring.")
    _record(feature, user_id, resp.usage, ok=resp.stop_reason != "refusal")
    if resp.stop_reason == "refusal":
        raise AiError("Bu so'rovni bajarib bo'lmadi. Boshqacha yozib ko'ring.")
    if resp.stop_reason == "max_tokens":
        raise AiError("Javob juda uzun bo'lib ketdi. So'rovni qisqartiring.")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if schema:
        try:
            return json.loads(text)
        except ValueError:
            raise AiError("Javobni tushunib bo'lmadi. Qayta urinib ko'ring.")
    return text


def check_key(key):
    """Kalitni tekshirish (Sozlamalarda saqlashdan oldin). (ok, xabar)"""
    import anthropic
    try:
        anthropic.Anthropic(api_key=key, timeout=20, max_retries=0).models.retrieve(MODEL)
        return True, ""
    except anthropic.AuthenticationError:
        return False, "Kalit noto'g'ri."
    except anthropic.APIConnectionError:
        return False, "Anthropic bilan aloqa yo'q."
    except anthropic.APIStatusError as e:
        return False, f"Anthropic xatosi: {e.status_code}"
