"""Shartnoma tekshiruvi (xodimlar): bilimlar bazasi, tekshiruvlar va ustoz xulosasi."""
from datetime import datetime, timezone

import os
from types import SimpleNamespace

from flask import (Blueprint, Response, current_app, flash, g, jsonify, redirect, render_template, request,
                   url_for)
from sqlalchemy import or_

from core import ai, audit
from core import finance as F
from core import contract as C
from core import kb_search as S
from core import transcribe as STT
from core import video_cards as VC
from core.extensions import db
from core.models import (CARD_STATUS, CONTRACT_VERDICTS, KNOWLEDGE_KINDS, KNOWLEDGE_TOPICS, ContractCheck,
                         KbPassage, KnowledgeCard, KnowledgeDoc, Lecture, Member, Module, Transcript)
from views import form_int

bp = Blueprint("shartnoma", __name__, url_prefix="/shartnoma")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def report_context(check, staff=True):
    res = C.result_of(check)
    findings = res.get("findings", [])
    if not staff:   # o'quvchiga ustoz «noto'g'ri» degan masalalar ko'rsatilmaydi
        findings = [f for f in findings if f.get("ustoz") != "rad"]
        res = dict(res, findings=findings)
    ids = {s for f in findings for s in f.get("sources", [])} | \
        {s for f in findings for s in (f.get("ustoz_case") or {}).get("sources", [])}
    kb = {d.id: d for d in KnowledgeDoc.query.filter(KnowledgeDoc.id.in_(ids)).all()} if ids else {}
    pids = [i - S.PASSAGE_BASE for i in ids if i >= S.PASSAGE_BASE]
    for p in (KbPassage.query.filter(KbPassage.id.in_(pids)).all() if pids else []):
        kb[S.PASSAGE_BASE + p.id] = SimpleNamespace(title="Dars parchasi — ustozning so'zi", source=S.passage_source(p),
                                                    kind_name="Dars parchasi", topic_name="avtomatik matn",
                                                    body=p.text)
    counts = {k: sum(1 for f in findings if f["severity"] == k) for k in C.SEVERITY}
    judged = sum(1 for f in findings if f.get("ustoz"))
    return {"c": check, "res": res, "kb": kb, "counts": counts, "cats": C.CATEGORIES, "sev": C.SEVERITY,
            "verdicts": CONTRACT_VERDICTS, "staff": staff, "judged": judged}


def _issue_counts(check):
    if check.status != "tayyor":
        return {}
    fs = [f for f in C.result_of(check).get("findings", []) if f.get("ustoz") != "rad"]
    return {k: sum(1 for f in fs if f.get("severity") == k) for k in ("jiddiy", "orta")}


SH_SEGS = (("", "Hammasi"), ("kutmoqda", "Ustoz kutmoqda"), ("tasdiqlangan", "Ustoz ko'rgan"), ("oquvchi", "O'quvchilardan"))
SH_PER_PAGE = 25


# ── Tekshiruvlar ────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    C.stale_to_error()
    seg = request.args.get("holat", "") if request.args.get("holat") in dict(SH_SEGS) else ""
    q_text = (request.args.get("q") or "").strip()[:100]
    page = max(form_int(request.args.get("sahifa")) or 1, 1)
    base = ContractCheck.query
    if q_text:
        base = base.outerjoin(Member, ContractCheck.member_id == Member.id).filter(
            or_(ContractCheck.title.ilike(f"%{q_text}%"), ContractCheck.contract_type.ilike(f"%{q_text}%"),
                Member.full_name.ilike(f"%{q_text}%")))
    waiting_q = (ContractCheck.status == "tayyor") & (ContractCheck.review_verdict == "")
    seg_filters = {"kutmoqda": waiting_q, "tasdiqlangan": ContractCheck.review_verdict != "",
                   "oquvchi": ContractCheck.member_id.isnot(None)}
    counts = {k: (base.filter(seg_filters[k]).count() if k else base.count()) for k, _ in SH_SEGS}
    q = base.filter(seg_filters[seg]) if seg else base
    found = counts[seg]
    pages = max((found + SH_PER_PAGE - 1) // SH_PER_PAGE, 1)
    checks = q.order_by(ContractCheck.created_at.desc()).offset((page - 1) * SH_PER_PAGE).limit(SH_PER_PAGE).all()
    waiting = ContractCheck.query.filter(waiting_q).count()

    def url_with(**over):
        args = {k: v for k, v in {"holat": seg, "q": q_text}.items() if v}
        args.update({k: v for k, v in over.items() if v})
        for k, v in over.items():
            if not v:
                args.pop(k, None)
        return url_for("shartnoma.index", **args)
    return render_template("pages/shartnoma.html", checks=checks, seg=seg, segs=SH_SEGS, counts=counts, q=q_text,
                           waiting=waiting, ai_on=ai.enabled(), page=page, pages=pages, found=found,
                           kb_count=KnowledgeDoc.query.filter_by(active=True).count(), verdicts=CONTRACT_VERDICTS,
                           issues={c.id: _issue_counts(c) for c in checks}, url_with=url_with)


@bp.route("/yangi", methods=["POST"])
def create():
    text, files, kind, err = C.read_upload(request.files.getlist("files"), request.form.get("text", ""))
    if err:
        flash(err, "bad")
        return redirect(url_for("shartnoma.index"))
    if not ai.enabled():
        flash("Sun'iy intellekt ulanmagan — Sozlamalar → Sun'iy intellekt.", "bad")
        return redirect(url_for("shartnoma.index"))
    title = (request.form.get("title") or "").strip()[:200] or \
        next((f.filename for f in request.files.getlist("files") if f and f.filename), "") or "Shartnoma"
    check = ContractCheck(user_id=g.user.id, title=title, source_kind=kind)
    db.session.add(check)
    db.session.commit()
    C.start(current_app._get_current_object(), check.id, text, files, g.user.id)
    return redirect(url_for("shartnoma.view", cid=check.id))


@bp.route("/<int:cid>")
def view(cid):
    check = db.get_or_404(ContractCheck, cid)
    return render_template("pages/shartnoma_view.html", **report_context(check))


@bp.route("/<int:cid>/holat")
def status(cid):
    check = db.get_or_404(ContractCheck, cid)
    return jsonify(status=check.status, error=check.error)


@bp.route("/<int:cid>/xulosa", methods=["POST"])
def review(cid):
    check = db.get_or_404(ContractCheck, cid)
    verdict = request.form.get("verdict")
    if verdict not in CONTRACT_VERDICTS:
        flash("Xulosani tanlang.", "bad")
        return redirect(url_for("shartnoma.view", cid=cid))
    check.review_verdict = verdict
    check.review_text = (request.form.get("text") or "").strip()[:5000]
    check.reviewed_by, check.reviewed_at = g.user.id, _now()
    db.session.commit()
    if check.member and request.form.get("notify"):
        from core import telegram as T
        if T.enabled():
            import html as _h
            msg = (f"📄 <b>Shartnomangiz ko'rib chiqildi</b>\n«{_h.escape(check.title)}»\n\n"
                   f"Ustoz xulosasi: <b>{CONTRACT_VERDICTS[verdict]}</b>"
                   + (f"\n\n{_h.escape(check.review_text[:1500])}" if check.review_text else "")
                   + "\n\nBatafsil — ilovada: Shartnoma tekshiruvi.")
            T.deliver(check.member, msg, "xabar", None, g.user.id)
    flash("Ustoz xulosasi saqlandi.", "ok")
    return redirect(url_for("shartnoma.view", cid=cid))


@bp.route("/<int:cid>/masala/<int:idx>", methods=["POST"])
def judge(cid, idx):
    """Ustozning har bir masala bo'yicha bahosi: ok — to'g'ri, rad — noto'g'ri (o'quvchiga ko'rsatilmaydi)."""
    import json
    check = db.get_or_404(ContractCheck, cid)
    res = C.result_of(check)
    findings = res.get("findings", [])
    if not 0 <= idx < len(findings):
        return jsonify(ok=False), 404
    v = request.form.get("v", "")
    findings[idx]["ustoz"] = v if v in ("ok", "rad") else ""
    check.result = json.dumps(res, ensure_ascii=False)
    db.session.commit()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(ok=True, v=findings[idx]["ustoz"], judged=sum(1 for f in findings if f.get("ustoz")),
                       total=len(findings))
    return redirect(url_for("shartnoma.view", cid=cid) + f"#f{idx}")


@bp.route("/<int:cid>/ochirish", methods=["POST"])
def delete(cid):
    check = db.get_or_404(ContractCheck, cid)
    audit.log("content_delete", f"Shartnoma tekshiruvi: {check.title}")
    db.session.delete(check)
    db.session.commit()
    flash("Tekshiruv o'chirildi.", "ok")
    return redirect(url_for("shartnoma.index"))


# ── Bilimlar bazasi ─────────────────────────────────────────────────────────

KB_PER_PAGE = 30
KB_SORTS = {"yangi": "Avval yangilari", "mavzu": "Mavzu bo'yicha", "nom": "Nomi bo'yicha"}
KB_ORIGINS = {"dars": "Darslardan", "qolda": "Qo'lda kiritilgan"}
KIND_HINTS = {
    "qoida": "Umumiy hukm: nima joiz, nima joiz emas va nega",
    "ustoz": "Ustozning shaxsiy pozitsiyasi yoki amaliy maslahati",
    "misol": "Real holat, hikoya yoki raqamli misol — tushuntirish uchun",
    "standart": "AAOIFI va boshqa standartlardan aniq band",
    "namuna": "Shartnomaga qo'yiladigan tayyor, to'g'ri band",
    "dars": "Tushuncha, ta'rif yoki umumiy tushuntirish",
}


def _terms(q):
    import re
    return [w for w in re.findall(r"[\w'ʻ‘’]+", (q or "").lower()) if len(w) >= 3][:8]


def kb_highlight(text, q):
    """Matnni xavfsiz qilib, qidiruv so'zlarini <mark> bilan ajratadi."""
    import re

    from markupsafe import Markup, escape
    out = str(escape(text or ""))
    terms = _terms(q)
    if terms:
        rx = re.compile("(" + "|".join(re.escape(str(escape(t))) for t in sorted(terms, key=len, reverse=True)) + ")",
                        re.IGNORECASE)
        out = rx.sub(r"<mark>\1</mark>", out)
    return Markup(out)


def kb_snippet(text, q, size=230):
    """Qidiruv so'zi atrofidagi parcha (bo'lmasa — boshidan)."""
    text = " ".join((text or "").split())
    low, pos = text.lower(), -1
    for t in _terms(q):
        pos = low.find(t)
        if pos >= 0:
            break
    if pos < 0 or len(text) <= size:
        return text[:size] + ("…" if len(text) > size else "")
    start = max(pos - size // 3, 0)
    return ("…" if start else "") + text[start:start + size] + ("…" if start + size < len(text) else "")


def _lesson_docs():
    """Darsdan (kartochkadan) kelgan materiallar: doc_id → (transkript, soniya)."""
    rows = (db.session.query(KnowledgeCard.doc_id, KnowledgeCard.transcript_id, KnowledgeCard.start)
            .filter(KnowledgeCard.doc_id.isnot(None)).all())
    return {d: (t, s) for d, t, s in rows}


def _kb_args(**over):
    """Joriy filtrlar + o'zgartirish (None — olib tashlash) → url_for argumentlari."""
    keys = ("q", "mavzu", "tur", "manba", "holat", "tartib")
    args = {k: request.args.get(k) for k in keys if request.args.get(k)}
    for k, v in over.items():
        if v is None:
            args.pop(k, None)
        else:
            args[k] = v
    return args


@bp.route("/bilimlar")
def kb_list():
    a = request.args
    q_text = (a.get("q") or "").strip()[:200]
    topic = a.get("mavzu") if a.get("mavzu") in KNOWLEDGE_TOPICS else ""
    kind = a.get("tur") if a.get("tur") in KNOWLEDGE_KINDS else ""
    origin = a.get("manba") if a.get("manba") in KB_ORIGINS else ""
    state = a.get("holat") if a.get("holat") in ("faol", "ochiq") else ""
    sort = a.get("tartib") if a.get("tartib") in KB_SORTS else "yangi"
    page = max(form_int(a.get("sahifa")) or 1, 1)

    lesson = _lesson_docs()
    base = KnowledgeDoc.query
    if topic:
        base = base.filter(KnowledgeDoc.topic == topic)
    if kind:
        base = base.filter(KnowledgeDoc.kind == kind)
    if state:
        base = base.filter(KnowledgeDoc.active.is_(state == "faol"))
    if origin == "dars":
        base = base.filter(KnowledgeDoc.id.in_(list(lesson) or [0]))
    elif origin == "qolda":
        base = base.filter(KnowledgeDoc.id.notin_(list(lesson) or [0]))
    order = {"yangi": [KnowledgeDoc.updated_at.desc(), KnowledgeDoc.id.desc()],
             "mavzu": [KnowledgeDoc.topic, KnowledgeDoc.id], "nom": [KnowledgeDoc.title]}[sort]

    sem_ids, passages, sem_error = [], [], ""
    if q_text:
        like = f"%{q_text}%"
        text_q = base.filter(or_(KnowledgeDoc.title.ilike(like), KnowledgeDoc.body.ilike(like),
                                 KnowledgeDoc.source.ilike(like)))
        if S.enabled():
            try:
                hits = S.resolve(S.search([q_text], k=60, per_query=60, user_id=g.user.id))
                allowed = {d.id for d in base.with_entities(KnowledgeDoc.id)} if (topic or kind or state or origin) else None
                sem_ids = [o.id for k, o, _ in hits if k == "doc" and (allowed is None or o.id in allowed)][:30]
                passages = [o for k, o, _ in hits if k == "passage"][:6]
            except ai.AiError as e:
                sem_error = str(e)
        text_ids = [d.id for d in text_q.order_by(*order).with_entities(KnowledgeDoc.id).limit(500)]
        ids = sem_ids + [i for i in text_ids if i not in set(sem_ids)]
        found = len(ids)
        page_ids = ids[(page - 1) * KB_PER_PAGE: page * KB_PER_PAGE]
        by_id = {d.id: d for d in KnowledgeDoc.query.filter(KnowledgeDoc.id.in_(page_ids or [0]))}
        docs = [by_id[i] for i in page_ids if i in by_id]
    else:
        found = base.count()
        docs = base.order_by(*order).offset((page - 1) * KB_PER_PAGE).limit(KB_PER_PAGE).all()
    pages = max((found + KB_PER_PAGE - 1) // KB_PER_PAGE, 1)

    def counts(col):
        return dict(db.session.query(col, db.func.count(KnowledgeDoc.id)).group_by(col).all())
    total_all = KnowledgeDoc.query.count()
    active_n = KnowledgeDoc.query.filter_by(active=True).count()
    transcripts = {t.id: t for t in Transcript.query.filter(
        Transcript.id.in_({lesson[d.id][0] for d in docs if d.id in lesson} or {0}))}
    origin_of = {d.id: (transcripts.get(lesson[d.id][0]), lesson[d.id][1]) for d in docs if d.id in lesson}
    chips = [(f"«{q_text}»", _kb_args(q=None))] if q_text else []
    chips += [(lbl, _kb_args(**{key: None})) for key, lbl in (
        ("mavzu", KNOWLEDGE_TOPICS.get(topic)), ("tur", KNOWLEDGE_KINDS.get(kind)), ("manba", KB_ORIGINS.get(origin)),
        ("holat", {"faol": "Faol", "ochiq": "O'chirilgan"}.get(state))) if lbl]
    return render_template(
        "pages/shartnoma_kb.html", docs=docs, topics=KNOWLEDGE_TOPICS, kinds=KNOWLEDGE_KINDS, kind_hints=KIND_HINTS,
        origins=KB_ORIGINS, sorts=KB_SORTS, topic=topic, kind=kind, origin=origin, state=state, sort=sort, q=q_text,
        page=page, pages=pages, found=found, per_page=KB_PER_PAGE, sem_ids=set(sem_ids), passages=passages,
        sem_error=sem_error, chips=chips, kb_args=_kb_args, hl=kb_highlight, snippet=kb_snippet, origin_of=origin_of,
        by_topic=counts(KnowledgeDoc.topic), by_kind=counts(KnowledgeDoc.kind), total_all=total_all, active_n=active_n,
        from_lessons=len(lesson), pending=KnowledgeCard.query.filter_by(status="taklif").count(),
        size=C.docs_chars(), budget=C.KB_CHAR_BUDGET, idx=S.status(), passages_on=S.passages_enabled(),
        source_of=S.passage_source, fmt=STT.fmt_time)


@bp.route("/bilimlar/indeks", methods=["POST"])
def kb_index():
    if not S.enabled():
        flash("Indeks uchun OpenAI kaliti kerak — Sozlamalar → Sun'iy intellekt.", "bad")
    else:
        S.sync_async(current_app._get_current_object(), g.user.id)
        flash("Indeks yangilanmoqda — katta bazada bir necha daqiqa olishi mumkin.", "ok")
    return redirect(url_for("shartnoma.kb_list"))


@bp.route("/bilimlar/parchalar", methods=["POST"])
def kb_passages_toggle():
    on = request.form.get("on") == "1"
    F.set_setting("kb_passages", "1" if on else "0")
    audit.log("settings", "Shartnoma tekshiruvida dars parchalari: " + ("yoqildi" if on else "o'chirildi"))
    db.session.commit()
    flash("Dars parchalari tekshiruvda ishlatiladi." if on else "Endi faqat tasdiqlangan materiallar ishlatiladi.", "ok")
    return redirect(url_for("shartnoma.kb_list"))


@bp.route("/bilimlar/yangi")
@bp.route("/bilimlar/<int:did>")
def kb_edit(did=None):
    doc = db.get_or_404(KnowledgeDoc, did) if did else None
    card = KnowledgeCard.query.filter_by(doc_id=doc.id).first() if doc else None
    return render_template("pages/shartnoma_kb_edit.html", doc=doc, topics=KNOWLEDGE_TOPICS, kinds=KNOWLEDGE_KINDS,
                           kind_hints=KIND_HINTS, card=card, fmt=STT.fmt_time,
                           preset_topic=request.args.get("mavzu", "umumiy"),
                           preset_kind=request.args.get("tur") if request.args.get("tur") in KNOWLEDGE_KINDS else "qoida")


@bp.route("/bilimlar/saqlash", methods=["POST"])
def kb_save():
    f = request.form
    did = form_int(f.get("id"))
    doc = db.get_or_404(KnowledgeDoc, did) if did else KnowledgeDoc(created_by=g.user.id)
    body = (f.get("body") or "").strip()
    up = request.files.get("file")
    if up and up.filename:
        extracted = C.text_from_upload(up.filename, up.read())
        if not extracted:
            flash("Fayldan matn o'qib bo'lmadi (skaner qilingan PDF bo'lishi mumkin) — matnni qo'lda kiriting.", "bad")
            return redirect(url_for("shartnoma.kb_edit", did=did) if did else url_for("shartnoma.kb_edit"))
        body = (body + "\n\n" + extracted).strip() if body else extracted
    title = (f.get("title") or "").strip()[:200]
    if not title or not body:
        flash("Sarlavha va matnni kiriting.", "bad")
        return redirect(url_for("shartnoma.kb_edit", did=did) if did else url_for("shartnoma.kb_edit"))
    doc.title, doc.body = title, body[:200_000]
    doc.kind = f.get("kind") if f.get("kind") in KNOWLEDGE_KINDS else "qoida"
    doc.topic = f.get("topic") if f.get("topic") in KNOWLEDGE_TOPICS else "umumiy"
    doc.source = (f.get("source") or "").strip()[:200]
    doc.active = bool(f.get("active")) if did else True
    doc.updated_at = _now()
    db.session.add(doc)
    db.session.commit()
    flash("Material saqlandi." if did else "Material bilimlar bazasiga qo'shildi.", "ok")
    return redirect(url_for("shartnoma.kb_list", mavzu=doc.topic))


@bp.route("/bilimlar/<int:did>/ochirish", methods=["POST"])
def kb_delete(did):
    doc = db.get_or_404(KnowledgeDoc, did)
    audit.log("content_delete", f"Bilimlar bazasi: {doc.title}")
    KnowledgeCard.query.filter_by(doc_id=did).update({"doc_id": None, "status": "rad"})
    db.session.delete(doc)
    db.session.commit()
    flash("Material o'chirildi.", "ok")
    return redirect(url_for("shartnoma.kb_list"))


# ── Video darslardan bilim ──────────────────────────────────────────────────

def _lectures():
    return (Lecture.query.join(Module, Lecture.module_id == Module.id)
            .order_by(Module.program_id, Module.position, Lecture.position).all())


@bp.route("/video")
def video_list():
    STT.stale_to_error()
    items = Transcript.query.order_by(Transcript.created_at.desc()).limit(200).all()
    pending = dict(db.session.query(KnowledgeCard.transcript_id, db.func.count(KnowledgeCard.id))
                   .filter(KnowledgeCard.status == "taklif").group_by(KnowledgeCard.transcript_id).all())
    return render_template("pages/video.html", items=items, pending=pending, lectures=_lectures(),
                           stt_on=STT.enabled(), ai_on=ai.enabled(), model=STT.model(), models=STT.MODELS,
                           price=STT.price_per_min(), max_mb=STT.MAX_UPLOAD // 1024 ** 2,
                           media_ext=",".join(STT.MEDIA_EXT + STT.TEXT_EXT), pre_lecture=form_int(request.args.get("dars")))


QUEUE_LIMIT = 3   # yuklangan, lekin hali boshlanmagan fayllar (vaqtinchalik diskda turadi)


def _xhr():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _upload_fail(msg):
    if _xhr():
        return jsonify(error=msg), 400
    flash(msg, "bad")
    return redirect(url_for("shartnoma.video_list"))


def _upload_done(tid):
    url = url_for("shartnoma.video_view", tid=tid)
    return jsonify(url=url) if _xhr() else redirect(url)


@bp.route("/video/yuklash", methods=["POST"])
def video_upload():
    request.max_content_length = STT.MAX_UPLOAD + 1024 ** 2
    fs = request.files.get("file")
    if not fs or not fs.filename:
        return _upload_fail("Video, audio yoki subtitr faylini tanlang.")
    name = fs.filename
    ext = os.path.splitext(name.lower())[1]
    lecture = db.session.get(Lecture, form_int(request.form.get("lecture_id")) or 0)
    title = (request.form.get("title") or "").strip()[:200] or (lecture.title if lecture else "") or \
        os.path.splitext(name)[0][:200]
    want_cards = bool(request.form.get("cards"))
    if ext in STT.TEXT_EXT:
        segs = STT.parse_subtitles(STT.decode_text(fs.read()))
        if not segs:
            return _upload_fail("Fayldan matn o'qib bo'lmadi.")
        import json
        t = Transcript(title=title, filename=name[:255], lecture_id=lecture.id if lecture else None, source="srt",
                       status="tayyor", segments=json.dumps(segs, ensure_ascii=False), created_by=g.user.id,
                       duration=int(max((s["e"] for s in segs), default=0)), finished_at=_now())
        db.session.add(t)
        db.session.commit()
        S.build_passages(t)
        S.sync_async(current_app._get_current_object(), g.user.id)
        if want_cards and ai.enabled():
            VC.start(current_app._get_current_object(), t.id, g.user.id)
        return _upload_done(t.id)
    if ext not in STT.MEDIA_EXT:
        return _upload_fail("Bu fayl turini o'qib bo'lmaydi. Video (MP4, MOV…), audio (MP3, M4A…) yoki SRT/VTT/TXT yuklang.")
    if not STT.enabled():
        return _upload_fail("OpenAI kaliti kiritilmagan — Sozlamalar → Sun'iy intellekt.")
    if Transcript.query.filter_by(status="navbatda").count() >= QUEUE_LIMIT:
        msg = "Navbatda allaqachon bir nechta dars bor — ular boshlangach keyingisini yuklang."
        return (jsonify(error=msg, busy=True), 429) if _xhr() else _upload_fail(msg)
    workdir = STT.new_workdir()
    src = os.path.join(workdir, "source" + ext)
    fs.save(src)
    t = Transcript(title=title, filename=name[:255], lecture_id=lecture.id if lecture else None, source="fayl",
                   model=STT.model(), created_by=g.user.id)
    db.session.add(t)
    db.session.commit()
    STT.start(current_app._get_current_object(), t.id, src, workdir, g.user.id, cards=want_cards)
    return _upload_done(t.id)


@bp.route("/video/<int:tid>")
def video_view(tid):
    STT.stale_to_error()
    t = db.get_or_404(Transcript, tid)
    segs = STT.segments_of(t)
    return render_template("pages/video_view.html", t=t, segs=segs, timed=STT.timed(t), cards=t.cards,
                           counts=VC.counts(t), kinds=KNOWLEDGE_KINDS, topics=KNOWLEDGE_TOPICS, card_status=CARD_STATUS,
                           can_retry=STT.can_retry(t), ai_on=ai.enabled(), fmt=STT.fmt_time, lectures=_lectures(),
                           busy=t.status in STT.ACTIVE or t.cards_status == "navbatda")


@bp.route("/video/<int:tid>/holat")
def video_status(tid):
    t = db.get_or_404(Transcript, tid)
    return jsonify(status=t.status, done=t.chunks_done, total=t.chunks_total, cards=t.cards_status,
                   busy=t.status in STT.ACTIVE or t.cards_status == "navbatda")


@bp.route("/video/<int:tid>/matn.txt")
def video_text(tid):
    t = db.get_or_404(Transcript, tid)
    body = f"{t.title}\n\n{STT.full_text(t)}\n"
    fname = "".join(ch for ch in t.title if ch.isalnum() or ch in " -_")[:60].strip() or f"dars-{t.id}"
    return Response(body, mimetype="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.txt"'})


@bp.route("/video/<int:tid>/kartochkalar", methods=["POST"])
def video_cards(tid):
    t = db.get_or_404(Transcript, tid)
    if t.status != "tayyor":
        flash("Avval matn tayyor bo'lsin.", "bad")
    elif not ai.enabled():
        flash("Sun'iy intellekt (Claude) ulanmagan — Sozlamalar → Sun'iy intellekt.", "bad")
    elif t.cards_status != "navbatda":
        VC.start(current_app._get_current_object(), t.id, g.user.id)
    return redirect(url_for("shartnoma.video_view", tid=tid))


@bp.route("/video/<int:tid>/qayta", methods=["POST"])
def video_retry(tid):
    t = db.get_or_404(Transcript, tid)
    if STT.can_retry(t):
        STT.retry(current_app._get_current_object(), t, g.user.id)
    else:
        flash("Qayta urinib bo'lmaydi — faylni qaytadan yuklang.", "bad")
    return redirect(url_for("shartnoma.video_view", tid=tid))


@bp.route("/video/<int:tid>/tahrir", methods=["POST"])
def video_edit(tid):
    t = db.get_or_404(Transcript, tid)
    t.title = (request.form.get("title") or "").strip()[:200] or t.title
    lecture = db.session.get(Lecture, form_int(request.form.get("lecture_id")) or 0)
    t.lecture_id = lecture.id if lecture else None
    db.session.commit()
    flash("Saqlandi.", "ok")
    return redirect(url_for("shartnoma.video_view", tid=tid))


@bp.route("/video/<int:tid>/ochirish", methods=["POST"])
def video_delete(tid):
    t = db.get_or_404(Transcript, tid)
    if t.status in STT.ACTIVE:
        flash("Jarayon tugashini kuting.", "bad")
        return redirect(url_for("shartnoma.video_view", tid=tid))
    audit.log("content_delete", f"Dars matni: {t.title}")
    db.session.delete(t)
    db.session.commit()
    flash("Dars matni o'chirildi. Bazaga o'tgan materiallar saqlanib qoldi.", "ok")
    return redirect(url_for("shartnoma.video_list"))


@bp.route("/kartochka/<int:cid>", methods=["POST"])
def card_action(cid):
    card = db.get_or_404(KnowledgeCard, cid)
    action, f = request.form.get("action"), request.form
    if action == "tasdiq":
        if not (f.get("title") or "").strip() or not (f.get("body") or "").strip():
            flash("Sarlavha va matn bo'sh bo'lmasin.", "bad")
        else:
            VC.approve(card, g.user.id, f.get("title"), f.get("body"), f.get("kind"), f.get("topic"))
    elif action == "rad":
        VC.reject(card, g.user.id)
    elif action == "qaytar":
        VC.reopen(card)
    nxt = next((c.id for c in card.transcript.cards if c.status == "taklif" and c.id != card.id), None)
    return redirect(url_for("shartnoma.video_view", tid=card.transcript_id) + (f"#k{nxt}" if nxt else "#kartochkalar"))
