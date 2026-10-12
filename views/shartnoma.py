"""Shartnoma tekshiruvi (xodimlar): bilimlar bazasi, tekshiruvlar va ustoz xulosasi."""
from datetime import datetime, timezone

from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import or_

from core import ai, audit
from core import contract as C
from core.extensions import db
from core.models import (CONTRACT_VERDICTS, KNOWLEDGE_KINDS, KNOWLEDGE_TOPICS, ContractCheck, KnowledgeDoc)
from views import form_int

bp = Blueprint("shartnoma", __name__, url_prefix="/shartnoma")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def report_context(check):
    res = C.result_of(check)
    ids = {s for f in res.get("findings", []) for s in f.get("sources", [])}
    kb = {d.id: d for d in KnowledgeDoc.query.filter(KnowledgeDoc.id.in_(ids)).all()} if ids else {}
    counts = {k: sum(1 for f in res.get("findings", []) if f["severity"] == k) for k in C.SEVERITY}
    return {"c": check, "res": res, "kb": kb, "counts": counts, "cats": C.CATEGORIES, "sev": C.SEVERITY,
            "verdicts": CONTRACT_VERDICTS}


# ── Tekshiruvlar ────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    C.stale_to_error()
    seg = request.args.get("holat", "")
    q = ContractCheck.query
    if seg == "kutilmoqda":
        q = q.filter(ContractCheck.status == "tayyor", ContractCheck.review_verdict == "")
    elif seg == "oquvchi":
        q = q.filter(ContractCheck.member_id.isnot(None))
    checks = q.order_by(ContractCheck.created_at.desc()).limit(100).all()
    waiting = ContractCheck.query.filter(ContractCheck.status == "tayyor", ContractCheck.review_verdict == "").count()
    return render_template("pages/shartnoma.html", checks=checks, seg=seg, waiting=waiting, ai_on=ai.enabled(),
                           kb_count=KnowledgeDoc.query.filter_by(active=True).count(), verdicts=CONTRACT_VERDICTS)


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


@bp.route("/<int:cid>/ochirish", methods=["POST"])
def delete(cid):
    check = db.get_or_404(ContractCheck, cid)
    audit.log("content_delete", f"Shartnoma tekshiruvi: {check.title}")
    db.session.delete(check)
    db.session.commit()
    flash("Tekshiruv o'chirildi.", "ok")
    return redirect(url_for("shartnoma.index"))


# ── Bilimlar bazasi ─────────────────────────────────────────────────────────

@bp.route("/bilimlar")
def kb_list():
    topic, kind, q_text = request.args.get("mavzu", ""), request.args.get("tur", ""), (request.args.get("q") or "").strip()
    q = KnowledgeDoc.query
    if topic in KNOWLEDGE_TOPICS:
        q = q.filter(KnowledgeDoc.topic == topic)
    if kind in KNOWLEDGE_KINDS:
        q = q.filter(KnowledgeDoc.kind == kind)
    if q_text:
        like = f"%{q_text}%"
        q = q.filter(or_(KnowledgeDoc.title.ilike(like), KnowledgeDoc.body.ilike(like), KnowledgeDoc.source.ilike(like)))
    docs = q.order_by(KnowledgeDoc.topic, KnowledgeDoc.id).all()
    allc = KnowledgeDoc.query.filter_by(active=True).all()
    size = sum(len(d.body or "") for d in allc)
    by_topic = {t: sum(1 for d in allc if d.topic == t) for t in KNOWLEDGE_TOPICS}
    return render_template("pages/shartnoma_kb.html", docs=docs, topics=KNOWLEDGE_TOPICS, kinds=KNOWLEDGE_KINDS,
                           topic=topic, kind=kind, q=q_text, size=size, budget=C.KB_CHAR_BUDGET, by_topic=by_topic,
                           total=len(allc))


@bp.route("/bilimlar/yangi")
@bp.route("/bilimlar/<int:did>")
def kb_edit(did=None):
    doc = db.get_or_404(KnowledgeDoc, did) if did else None
    return render_template("pages/shartnoma_kb_edit.html", doc=doc, topics=KNOWLEDGE_TOPICS, kinds=KNOWLEDGE_KINDS,
                           preset_topic=request.args.get("mavzu", "umumiy"))


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
    db.session.delete(doc)
    db.session.commit()
    flash("Material o'chirildi.", "ok")
    return redirect(url_for("shartnoma.kb_list"))
