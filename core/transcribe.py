"""Video/audio darsni matnga aylantirish (OpenAI) — vaqt belgilari bilan.

Bosqichlar:
1. ffmpeg: videodan audio (mono, 16 kHz, 48 kbit/s mp3 — soatiga ~20 MB) va jimlik joylari.
2. ~4 daqiqalik bo'laklar, iloji boricha jimlikda kesiladi (so'z o'rtasida emas).
3. Har bo'lak OpenAI'ga yuboriladi; oldingi bo'lak oxiri va atamalar ro'yxati kontekst sifatida beriladi.
4. Natija — [{"s": boshlanish, "e": tugash, "t": matn, "a": taxminiymi}] segmentlar.

Bo'lak boshlanish vaqti aniq ma'lum. Bo'lak ichidagi gaplarning vaqti matn uzunligiga qarab taxminan
hisoblanadi («≈»). whisper-1 tanlansa — model bergan aniq segment vaqtlari ishlatiladi.
Tayyor .srt / .vtt / .txt (masalan, bepul Whisper'dan) ham qabul qilinadi — OpenAI'siz.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta, timezone

from core import ai
from core import finance as F
from core.extensions import db
from core.models import AiUsage, Transcript

log = logging.getLogger("assoodiq.transcribe")

# Narx — 1 daqiqa audio uchun AQSh dollarida (taxminiy, OpenAI narxlari bo'yicha)
MODELS = {
    "gpt-transcribe": {"name": "gpt-transcribe — eng aniq (tavsiya)", "price": 0.0045},
    "gpt-4o-transcribe": {"name": "gpt-4o-transcribe", "price": 0.006},
    "gpt-4o-mini-transcribe": {"name": "gpt-4o-mini-transcribe — arzonroq", "price": 0.003},
    "whisper-1": {"name": "whisper-1 — eskiroq, lekin aniq vaqt belgilari", "price": 0.006},
}
MEDIA_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".3gp", ".mpeg", ".mpg",
             ".mp3", ".m4a", ".wav", ".ogg", ".oga", ".opus", ".flac", ".aac", ".wma", ".amr")
TEXT_EXT = (".srt", ".vtt", ".txt")
MAX_UPLOAD = 2 * 1024 ** 3          # 2 GB — uzun video uchun ham yetadi (audio yuklash tavsiya)
CHUNK = 240                         # bo'lak uzunligi, soniya
WINDOW = 45                         # kesish joyini shu oraliqda jimlikdan qidiradi
ACTIVE = {"navbatda", "audio", "matn"}

_LOCK = threading.Lock()            # bir vaqtda bitta transkripsiya (CPU va xotira)
_RUNNING = set()                    # navbatda yoki ishlayotgan id'lar (bitta gunicorn worker)
_WORK = {}                          # xato bo'lsa — qayta urinish uchun saqlangan audio: id -> papka


class SttError(ai.AiError):
    pass


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Sozlamalar ──

def api_key():
    return (os.environ.get("OPENAI_API_KEY") or F.get_setting("openai_key") or "").strip()


def enabled():
    return bool(api_key())


def model():
    m = F.get_setting("stt_model") or "gpt-transcribe"
    return m if m in MODELS else "gpt-transcribe"


def languages():
    return [x for x in re.split(r"[\s,;]+", (F.get_setting("stt_languages") or "").lower()) if re.fullmatch(r"[a-z]{2}", x)][:5]


def keywords():
    words = [w.strip() for w in re.split(r"[,\n;]+", F.get_setting("stt_keywords") or "") if w.strip()]
    return [w[:60] for w in words][:100]


def _client(key=None):
    import openai
    return openai.OpenAI(api_key=key or api_key(), timeout=300, max_retries=3)


def check_key(key, model_name=None):
    """(ok, xabar): kalit ishlaydimi va tanlangan model hisobda bormi."""
    import openai
    try:
        _client(key).models.retrieve(model_name or model())
        return True, ""
    except openai.AuthenticationError:
        return False, "kalit noto'g'ri"
    except openai.NotFoundError:
        return False, "bu model hisobingizda yo'q — boshqa modelni tanlang"
    except openai.PermissionDeniedError:
        return False, "kalitga ruxsat yo'q (loyiha ruxsatlarini tekshiring)"
    except openai.APIConnectionError:
        return False, "OpenAI bilan aloqa yo'q (internet)"
    except openai.APIStatusError as e:
        return False, f"OpenAI xatosi ({e.status_code})"


def fmt_time(sec):
    sec = int(sec or 0)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def price_per_min(m=None):
    return MODELS.get(m or model(), MODELS["gpt-transcribe"])["price"]


# ── ffmpeg ──

def ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        raise SttError("Serverda ffmpeg topilmadi — videodan audio ajratib bo'lmaydi.")


def _hms(h, m, s):
    return int(h) * 3600 + int(m) * 60 + float(s)


def prepare_audio(src, workdir):
    """Videodan audio (mp3) + davomiylik + jimliklar [(boshi, oxiri)]."""
    out = os.path.join(workdir, "audio.mp3")
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-y", "-i", src, "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000",
           "-af", "silencedetect=noise=-35dB:d=0.4", "-c:a", "libmp3lame", "-b:a", "48k", out]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="ignore", timeout=3 * 3600)
    except subprocess.TimeoutExpired:
        raise SttError("Audio ajratish juda uzoq davom etdi — faylni qisqaroq qismlarga bo'lib yuklang.")
    err = p.stderr or ""
    if p.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 1000:
        log.warning("ffmpeg xatosi: %s", err[-800:])
        if "does not contain any stream" in err or "Output file does not contain" in err or "matches no streams" in err:
            raise SttError("Faylda ovoz topilmadi.")
        raise SttError("Faylni o'qib bo'lmadi — video yoki audio fayl ekanini tekshiring.")
    times = re.findall(r"time=(\d+):(\d+):([\d.]+)", err)
    duration = _hms(*times[-1]) if times else 0.0
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if not duration and m:
        duration = _hms(*m.groups())
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    silences = list(zip(starts, ends))
    if duration < 1:
        raise SttError("Faylda ovoz topilmadi.")
    return out, duration, silences


def plan_chunks(duration, silences, target=CHUNK, window=WINDOW):
    """Bo'laklar [(boshi, oxiri)] — har biri ~target soniya, kesish jimlikka to'g'ri keladi."""
    mids = sorted((a + b) / 2 for a, b in silences if b > a)
    cuts, pos = [0.0], 0.0
    while duration - pos > target + window:
        goal = pos + target
        near = [m for m in mids if goal - window <= m <= goal + window]
        cut = min(near, key=lambda m: abs(m - goal)) if near else goal
        cuts.append(round(cut, 2))
        pos = cut
    cuts.append(round(duration, 2))
    return list(zip(cuts, cuts[1:]))


def cut(audio, start, end, out):
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-y", "-ss", f"{start:.2f}", "-i", audio, "-t", f"{end - start:.2f}",
           "-c", "copy", out]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="ignore", timeout=600)
    if p.returncode != 0 or not os.path.exists(out):
        raise SttError("Audio bo'lagini kesib bo'lmadi.")
    return out


# ── OpenAI ──

def _split(text, start, end, size=320):
    """Bo'lak matnini gaplar guruhiga bo'lib, vaqtini uzunlikka qarab taxminlaydi."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    sents = re.split(r"(?<=[.!?…])\s+", text)
    groups, cur = [], ""
    for s in sents:
        cur = f"{cur} {s}".strip()
        if len(cur) >= size:
            groups.append(cur)
            cur = ""
    if cur:
        if groups and len(cur) < size / 3:
            groups[-1] += " " + cur
        else:
            groups.append(cur)
    total, pos, out = sum(len(g) for g in groups), 0, []
    for g in groups:
        s = start + (end - start) * pos / total
        pos += len(g)
        out.append({"s": round(s, 1), "e": round(start + (end - start) * pos / total, 1), "t": g, "a": True})
    out[0]["a"] = False  # bo'lak boshi — aniq
    return out


def _context(prev_text):
    text = (prev_text or "").strip()
    if len(text) <= 400:
        return text
    tail = text[-400:]
    return tail.split(" ", 1)[1] if " " in tail else tail   # kesilgan yarim so'zsiz


def transcribe_chunk(client, path, start, end, prev_text="", model_name=None):
    """Bitta bo'lak → segmentlar (vaqti butun fayl bo'yicha)."""
    import openai
    m = model_name or model()
    langs, kws = languages(), keywords()
    kw = {"model": m}
    if m == "gpt-transcribe":
        kw.update(response_format="json", prompt=_context(prev_text) or "Islom moliyasi darsi.")
        if langs:
            kw["languages"] = langs
        if kws:
            kw["keywords"] = kws
    else:
        glossary = ("Islom moliyasi darsi. Atamalar: " + ", ".join(kws[:40]) + ". ") if kws else ""
        kw["prompt"] = (glossary + _context(prev_text))[-900:]
        if len(langs) == 1:
            kw["language"] = langs[0]
        if m == "whisper-1":
            kw.update(response_format="verbose_json", timestamp_granularities=["segment"])
        else:
            kw["response_format"] = "json"
    try:
        with open(path, "rb") as f:
            resp = client.audio.transcriptions.create(file=f, **kw)
    except openai.AuthenticationError:
        raise SttError("OpenAI kaliti noto'g'ri — Sozlamalar → Sun'iy intellekt.")
    except openai.PermissionDeniedError:
        raise SttError("OpenAI kalitiga ruxsat yo'q (loyiha ruxsatlarini tekshiring).")
    except openai.RateLimitError as e:
        if "quota" in str(e).lower():
            raise SttError("OpenAI hisobida mablag' tugagan — platform.openai.com → Billing.")
        raise SttError("OpenAI: juda ko'p so'rov. Birozdan keyin «Qayta urinish»ni bosing.")
    except openai.BadRequestError as e:
        log.warning("OpenAI 400: %s", e)
        raise SttError(f"OpenAI so'rovni qabul qilmadi ({m}). Boshqa modelni tanlab ko'ring.")
    except openai.APIStatusError as e:
        log.warning("OpenAI xatosi %s: %s", e.status_code, e)
        raise SttError("OpenAI vaqtincha javob bermadi. Birozdan keyin «Qayta urinish»ni bosing.")
    except openai.APIConnectionError:
        raise SttError("OpenAI bilan aloqa yo'q. Birozdan keyin «Qayta urinish»ni bosing.")
    segs = getattr(resp, "segments", None)
    if segs:
        return [{"s": round(start + float(getattr(s, "start", 0)), 1), "e": round(start + float(getattr(s, "end", 0)), 1),
                 "t": (getattr(s, "text", "") or "").strip(), "a": False} for s in segs if (getattr(s, "text", "") or "").strip()]
    return _split(getattr(resp, "text", "") or "", start, end)


# ── Tayyor subtitr / matn ──

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _ts(h, m, s, ms):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_subtitles(raw, merge=25):
    """SRT/VTT → segmentlar (qisqa satrlar ~25 soniyalik bo'laklarga birlashtiriladi). TXT → vaqtsiz paragraflar."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    cues, cur = [], None
    for line in text.split("\n"):
        m = _TS.search(line)
        if m:
            g = m.groups()
            cur = {"s": _ts(*g[:4]), "e": _ts(*g[4:]), "t": []}
            cues.append(cur)
        elif not line.strip():
            cur = None
        elif cur is not None and not line.strip().isdigit():
            cur["t"].append(re.sub(r"<[^>]+>", "", line).strip())
    if not cues:
        paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if len(paras) == 1:
            paras = [g["t"] for g in _split(paras[0], 0, 0, size=600)]
        return [{"s": 0, "e": 0, "t": p, "a": False} for p in paras]
    out = []
    for c in cues:
        t = " ".join(x for x in c["t"] if x)
        if not t:
            continue
        if out and c["s"] - out[-1]["s"] < merge:
            if not out[-1]["t"].endswith(t):  # VTT'da takrorlanuvchi satrlar
                out[-1]["t"] += " " + t
            out[-1]["e"] = round(c["e"], 1)
        else:
            out.append({"s": round(c["s"], 1), "e": round(c["e"], 1), "t": t, "a": False})
    return out


def decode_text(data):
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


# ── Natija ──

def segments_of(t):
    try:
        return json.loads(t.segments or "[]")
    except ValueError:
        return []


def full_text(t, times=True):
    lines = []
    for s in segments_of(t):
        lines.append((f"[{'≈' if s.get('a') else ''}{fmt_time(s['s'])}] " if times and (s["s"] or s["e"]) else "") + s["t"])
    return "\n".join(lines)


def timed(t):
    return any(s.get("e") for s in segments_of(t))


# ── Ish oqimi ──

def _record_cost(t, seconds, user_id):
    cost = round(seconds / 60 * price_per_min(t.model), 5)
    t.cost_usd = round((t.cost_usd or 0) + cost, 5)
    db.session.add(AiUsage(feature="transkripsiya", user_id=user_id, ok=True, cost_usd=cost))


def process(tid, src, workdir, user_id=None):
    """Bitta fayl: audio → bo'laklar → OpenAI. Xato bo'lsa audio qayta urinish uchun saqlanadi."""
    t = db.session.get(Transcript, tid)
    audio = os.path.join(workdir, "audio.mp3")
    plan_file = os.path.join(workdir, "plan.json")
    if os.path.exists(plan_file) and os.path.exists(audio):        # qayta urinish: audio tayyor
        chunks = [tuple(c) for c in json.load(open(plan_file))]
    else:
        t.status = "audio"
        db.session.commit()
        audio, duration, silences = prepare_audio(src, workdir)
        if src and os.path.exists(src):
            os.remove(src)                                         # katta video endi kerak emas
        chunks = plan_chunks(duration, silences, CHUNK, WINDOW)
        json.dump(chunks, open(plan_file, "w"))
        t.duration, t.chunks_total, t.chunks_done, t.segments = int(round(duration)), len(chunks), 0, "[]"
    t.status = "matn"
    db.session.commit()
    client = _client()
    segs = segments_of(t)
    billed = 0.0
    try:
        for i in range(t.chunks_done or 0, len(chunks)):
            start, end = chunks[i]
            part = cut(audio, start, end, os.path.join(workdir, f"part{i:03d}.mp3"))
            prev = " ".join(s["t"] for s in segs[-3:])
            segs += transcribe_chunk(client, part, start, end, prev, t.model)
            os.remove(part)
            billed += end - start
            t.chunks_done, t.segments = i + 1, json.dumps(segs, ensure_ascii=False)
            db.session.commit()
    finally:
        if billed:
            _record_cost(t, billed, user_id)
            db.session.commit()
    if not any(s["t"] for s in segs):
        raise SttError("Matn chiqmadi — audioda nutq topilmadi.")
    t.status, t.error, t.finished_at = "tayyor", "", _utcnow()
    db.session.commit()


def start(app, tid, src, workdir, user_id=None, cards=True):
    """Fon oqimida: transkripsiya, so'ng (ixtiyoriy) bilim kartochkalari."""
    _RUNNING.add(tid)

    def run():
        ok = False
        with _LOCK, app.app_context():
            try:
                process(tid, src, workdir, user_id)
                ok = True
            except ai.AiError as e:
                db.session.rollback()
                t = db.session.get(Transcript, tid)
                t.status, t.error = "xato", str(e)[:300]
                db.session.commit()
            except Exception:  # noqa: BLE001
                log.exception("Transkripsiya xatosi")
                db.session.rollback()
                t = db.session.get(Transcript, tid)
                t.status, t.error = "xato", "Kutilmagan xato. «Qayta urinish»ni bosing."
                db.session.commit()
            finally:
                if ok or not os.path.exists(os.path.join(workdir, "plan.json")):
                    shutil.rmtree(workdir, ignore_errors=True)
                    _WORK.pop(tid, None)
                else:
                    _WORK[tid] = workdir
                _RUNNING.discard(tid)
            if ok and cards and ai.enabled():
                from core import video_cards
                video_cards.run(tid, user_id)
            db.session.remove()

    if app.testing:
        run()
    else:
        threading.Thread(target=run, daemon=True, name=f"stt-{tid}").start()


def can_retry(t):
    return t.status == "xato" and t.id in _WORK and os.path.isdir(_WORK[t.id])


def retry(app, t, user_id=None):
    t.status, t.error = "navbatda", ""
    db.session.commit()
    start(app, t.id, None, _WORK.pop(t.id), user_id)


def new_workdir():
    return tempfile.mkdtemp(prefix="aq-stt-")


def stale_to_error():
    """Server qayta ishga tushsa, yarim qolgan ishlar — xato (fayl vaqtinchalik papkada edi)."""
    changed = False
    for t in Transcript.query.filter(Transcript.status.in_(ACTIVE)).all():
        if t.id not in _RUNNING and (t.created_at or _utcnow()) < _utcnow() - timedelta(minutes=2):
            t.status, t.error = "xato", "Jarayon yakunlanmadi (server qayta ishga tushgan). Faylni qayta yuklang."
            changed = True
    if changed:
        db.session.commit()
