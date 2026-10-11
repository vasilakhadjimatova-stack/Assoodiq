"""Bunny Stream: video yaratish, brauzerdan to'g'ridan-to'g'ri (TUS) yuklash va himoyalangan ko'rish.

Video fayl serverimiz orqali o'tmaydi: server faqat Bunny'da bo'sh video yaratadi va
imzo beradi, brauzer faylni o'zi Bunny'ga yuklaydi. Ko'rish havolasi muddatli token bilan
imzolanadi (Bunny'da «Embed view token authentication» yoqilgan bo'lsa, havolani
boshqaga berib bo'lmaydi).
"""
import hashlib
import json
import time
import urllib.error
import urllib.request

from core import finance as F

API = "https://video.bunnycdn.com"
TUS_ENDPOINT = "https://video.bunnycdn.com/tusupload"
EMBED = "https://iframe.mediadelivery.net/embed"

# Bunny video holati → bizning holat
STATUS = {0: "yuklanmoqda", 1: "ishlanmoqda", 2: "ishlanmoqda", 3: "ishlanmoqda",
          4: "tayyor", 5: "xato", 6: "xato", 7: "ishlanmoqda", 8: "xato"}


def conf():
    return {"library": (F.get_setting("bunny_library") or "").strip(),
            "key": (F.get_setting("bunny_key") or "").strip(),
            "token_key": (F.get_setting("bunny_token_key") or "").strip()}


def enabled():
    c = conf()
    return bool(c["library"] and c["key"])


def api(method, path, payload=None, timeout=15):
    """(ok, natija yoki xato matni)"""
    c = conf()
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{API}/library/{c['library']}{path}", data=data, method=method,
                                 headers={"AccessKey": c["key"], "Accept": "application/json",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode() or "{}"
            return True, json.loads(body)
    except urllib.error.HTTPError as e:
        return False, f"Bunny {e.code}: {e.read().decode(errors='ignore')[:160]}"
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return False, f"Bunny bilan aloqa yo'q: {e}"


def create_video(title):
    ok, res = api("POST", "/videos", {"title": title[:200]})
    return (True, res.get("guid")) if ok and res.get("guid") else (False, res if not ok else "GUID qaytmadi")


def upload_ticket(video_id, ttl=6 * 3600):
    """Brauzer TUS yuklashi uchun sarlavhalar. API kalitning o'zi brauzerga berilmaydi."""
    c = conf()
    expire = int(time.time()) + ttl
    sig = hashlib.sha256(f"{c['library']}{c['key']}{expire}{video_id}".encode()).hexdigest()
    return {"endpoint": TUS_ENDPOINT,
            "headers": {"AuthorizationSignature": sig, "AuthorizationExpire": str(expire),
                        "VideoId": video_id, "LibraryId": c["library"]}}


def video_info(video_id):
    ok, res = api("GET", f"/videos/{video_id}")
    if not ok:
        return None
    return {"status": STATUS.get(res.get("status"), "ishlanmoqda"), "duration": int(res.get("length") or 0),
            "progress": res.get("encodeProgress") or 0}


def delete_video(video_id):
    if video_id and enabled():
        api("DELETE", f"/videos/{video_id}")


def embed_url(video_id, ttl=4 * 3600, now=None):
    c = conf()
    url = f"{EMBED}/{c['library']}/{video_id}"
    params = "autoplay=false&preload=true&responsive=true"
    if c["token_key"]:
        expires = int(now or time.time()) + ttl
        token = hashlib.sha256(f"{c['token_key']}{video_id}{expires}".encode()).hexdigest()
        params = f"token={token}&expires={expires}&" + params
    return f"{url}?{params}"
