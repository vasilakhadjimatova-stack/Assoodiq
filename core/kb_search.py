"""Katta bilimlar bazasidan ma'no bo'yicha qidirish (200+ soatlik darslar uchun).

- Manbalar: ustoz tasdiqlagan materiallar (KnowledgeDoc) va dars matnining ~1–2 daqiqalik parchalari
  (KbPassage — ustozning aynan so'zi, vaqti bilan).
- Har biri uchun OpenAI embedding (ma'no vektori) hisoblanadi va Postgres'da saqlanadi (KbVector).
  Matn o'zgarsa — vektor qayta hisoblanadi; o'chirilsa — indeksdan chiqadi.
- Qidiruv: so'rovlar vektori bilan kosinus o'xshashlik (numpy, xotirada keshlanadi). Bir nechta so'rov
  natijalari tartib bo'yicha birlashtiriladi (reciprocal rank fusion).
"""
import hashlib
import logging
import threading

from core import ai
from core import finance as F
from core import transcribe as STT
from core.extensions import db
from core.models import AiUsage, KbPassage, KbVector, KnowledgeDoc, Transcript

log = logging.getLogger("assoodiq.kb_search")

EMBED_MODEL = "text-embedding-3-large"
DIMS = 768
PRICE = 0.13                      # $ / 1 mln token (taxminiy)
PASSAGE_CHARS = 1100              # parcha uzunligi (~1–2 daqiqa nutq)
PASSAGE_SPAN = 150                # parcha ko'pi bilan shuncha soniyani qamraydi
PASSAGE_BASE = 1_000_000          # shartnoma natijasida parcha id'si: PASSAGE_BASE + KbPassage.id
BATCH = 96

_CACHE = {"sig": None, "keys": [], "mat": None}
_SYNC_LOCK = threading.Lock()


def passages_enabled():
    return F.get_setting("kb_passages") == "1"


def enabled():
    return STT.enabled()


# ── Dars parchalari ──

def build_passages(t):
    """Transkript segmentlaridan parchalar (eski parchalar almashtiriladi)."""
    for p in list(t.passages):
        t.passages.remove(p)
    cur, out = [], []

    def flush():
        if cur:
            text = " ".join(s["t"] for s in cur).strip()
            if text:
                out.append(KbPassage(start=int(cur[0]["s"]), end=int(max(s["e"] for s in cur)),
                                     approx=bool(cur[0].get("a")), text=text))
        cur.clear()

    for s in STT.segments_of(t):
        if cur and (sum(len(x["t"]) for x in cur) >= PASSAGE_CHARS or
                    (s["e"] and s["s"] - cur[0]["s"] > PASSAGE_SPAN)):
            flush()
        cur.append(s)
    flush()
    t.passages.extend(out)
    db.session.commit()
    return len(out)


def passage_source(p):
    t = p.transcript
    name = f"Dars: {t.lecture.title}" if t.lecture else f"Video: {t.title}"
    timed = p.start or p.end
    return name + (f" · {'≈' if p.approx else ''}{STT.fmt_time(p.start)}" if timed else "")


# ── Embedding ──

def _hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _doc_text(d):
    return f"{d.title}\n{d.body or ''}"[:6000]


def embed(texts, user_id=None):
    """Matnlar → normallashgan float32 vektorlar (n × DIMS)."""
    import numpy as np
    import openai
    if not texts:
        return np.zeros((0, DIMS), dtype=np.float32)
    client, rows, tokens = STT._client(), [], 0
    try:
        for i in range(0, len(texts), BATCH):
            resp = client.embeddings.create(model=EMBED_MODEL, input=[x[:8000] or " " for x in texts[i:i + BATCH]],
                                            dimensions=DIMS)
            rows += [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
            tokens += getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0
    except openai.AuthenticationError:
        raise ai.AiError("OpenAI kaliti noto'g'ri — Sozlamalar → Sun'iy intellekt.")
    except openai.RateLimitError as e:
        raise ai.AiError("OpenAI hisobida mablag' tugagan." if "quota" in str(e).lower()
                         else "OpenAI: juda ko'p so'rov. Birozdan keyin qayta urinib ko'ring.")
    except openai.APIStatusError as e:
        raise ai.AiError(f"OpenAI indeks xatosi ({e.status_code}): {STT.error_text(e)}")
    except openai.APIConnectionError:
        raise ai.AiError("OpenAI bilan aloqa yo'q.")
    finally:
        if tokens:
            db.session.add(AiUsage(feature="indeks", user_id=user_id, ok=True, input_tokens=tokens,
                                   cost_usd=round(tokens / 1e6 * PRICE, 5)))
            db.session.commit()
    mat = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.where(norms == 0, 1, norms)


def _wanted():
    """Indeksda bo'lishi kerak bo'lgan narsalar: {(kind, id): matn}."""
    want = {("doc", d.id): _doc_text(d) for d in KnowledgeDoc.query.filter_by(active=True).all()}
    for pid, text in db.session.query(KbPassage.id, KbPassage.text).all():
        want[("passage", pid)] = text
    return want


def missing_passages():
    have = db.session.query(KbPassage.transcript_id).distinct()
    return Transcript.query.filter(Transcript.status == "tayyor", Transcript.id.notin_(have)).all()


def sync(user_id=None):
    """Indeksni yangilaydi: yangi/o'zgargan matnlar uchun vektor, o'chirilganlarini olib tashlaydi."""
    with _SYNC_LOCK:
        for t in missing_passages():
            build_passages(t)
        want = _wanted()
        have = {(k, r): (vid, h, m) for vid, k, r, h, m in
                db.session.query(KbVector.id, KbVector.kind, KbVector.ref_id, KbVector.text_hash, KbVector.model).all()}
        stale = [vid for key, (vid, _, _) in have.items() if key not in want]
        if stale:
            for i in range(0, len(stale), 500):
                KbVector.query.filter(KbVector.id.in_(stale[i:i + 500])).delete(synchronize_session=False)
            db.session.commit()
        todo = [key for key, text in want.items()
                if key not in have or have[key][1] != _hash(text) or have[key][2] != EMBED_MODEL]
        added = 0
        if todo and enabled():
            for i in range(0, len(todo), BATCH * 4):
                part = todo[i:i + BATCH * 4]
                vecs = embed([want[k] for k in part], user_id)
                for key, v in zip(part, vecs):
                    row = db.session.get(KbVector, have[key][0]) if key in have else KbVector(kind=key[0], ref_id=key[1])
                    row.model, row.text_hash, row.vec = EMBED_MODEL, _hash(want[key]), v.tobytes()
                    row.updated_at = STT._utcnow()
                    db.session.add(row)
                db.session.commit()
                added += len(part)
        return {"added": added, "removed": len(stale), "pending": 0 if enabled() else len(todo), "total": len(want)}


def status():
    docs = KnowledgeDoc.query.filter_by(active=True).count()
    passages = KbPassage.query.count()
    indexed = KbVector.query.filter_by(model=EMBED_MODEL).count()
    return {"docs": docs, "passages": passages, "indexed": indexed, "total": docs + passages,
            "ready": enabled() and indexed > 0, "behind": max(docs + passages - indexed, 0) + len(missing_passages())}


def sync_async(app, user_id=None):
    def go():
        with app.app_context():
            try:
                sync(user_id)
            except ai.AiError as e:
                log.warning("Indeks: %s", e)
            except Exception:  # noqa: BLE001
                log.exception("Indeks xatosi")
            finally:
                db.session.remove()

    if app.testing:
        go()
    else:
        threading.Thread(target=go, daemon=True, name="kb-sync").start()


# ── Qidiruv ──

def _matrix():
    import numpy as np
    sig = db.session.query(db.func.count(KbVector.id), db.func.max(KbVector.updated_at), db.func.max(KbVector.id)) \
        .filter(KbVector.model == EMBED_MODEL).one()
    if _CACHE["sig"] != tuple(sig):
        rows = db.session.query(KbVector.kind, KbVector.ref_id, KbVector.vec).filter(KbVector.model == EMBED_MODEL).all()
        _CACHE["keys"] = [(k, r) for k, r, _ in rows]
        _CACHE["mat"] = np.frombuffer(b"".join(v for _, _, v in rows), dtype=np.float32).reshape(len(rows), DIMS) \
            if rows else np.zeros((0, DIMS), dtype=np.float32)
        _CACHE["sig"] = tuple(sig)
    return _CACHE["keys"], _CACHE["mat"]


def search(queries, k=60, kinds=("doc", "passage"), per_query=15, user_id=None):
    """So'rovlar → [((kind, id), ball)] eng mosdan boshlab. Indeks bo'lmasa — bo'sh ro'yxat."""
    import numpy as np
    queries = [q.strip()[:2000] for q in queries if q and q.strip()][:60]
    if not queries or not enabled():
        return []
    keys, mat = _matrix()
    if not len(keys):
        return []
    mask = np.array([key[0] in kinds for key in keys])
    qv = embed(queries, user_id)
    sims = qv @ mat.T                                        # (so'rovlar × materiallar)
    sims[:, ~mask] = -1
    scores = {}
    for row in sims:
        top = np.argsort(-row)[:per_query]
        for rank, j in enumerate(top):
            if row[j] <= 0:
                break
            boost = 1.3 if keys[j][0] == "doc" else 1.0     # tasdiqlangan material ustun
            scores[keys[j]] = scores.get(keys[j], 0) + boost / (20 + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])[:k]


def resolve(hits):
    """[(kind, id), …] → mavjud obyektlar (o'chirilganlari tashlab ketiladi), tartib saqlanadi."""
    doc_ids = [i for (k, i), _ in hits if k == "doc"]
    pas_ids = [i for (k, i), _ in hits if k == "passage"]
    docs = {d.id: d for d in KnowledgeDoc.query.filter(KnowledgeDoc.id.in_(doc_ids), KnowledgeDoc.active.is_(True))} \
        if doc_ids else {}
    pas = {p.id: p for p in KbPassage.query.filter(KbPassage.id.in_(pas_ids))} if pas_ids else {}
    out = []
    for (k, i), score in hits:
        obj = docs.get(i) if k == "doc" else pas.get(i)
        if obj is not None:
            out.append((k, obj, score))
    return out
