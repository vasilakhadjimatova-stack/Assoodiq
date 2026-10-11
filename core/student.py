"""O'quvchi ilovasi: kirish (taklif havolasi, Telegram kodi, Telegram Mini App) va o'quv ma'lumotlari."""
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl

from flask import current_app, session

from core import finance as F
from core.extensions import db
from core.models import (Enrollment, Lecture, LectureProgress, LoginCode, Member, Module, StudentAccess,
                         TelegramLink)

CODE_TTL = timedelta(minutes=10)
CODE_ATTEMPTS = 5
CODES_PER_WINDOW = 3  # 10 daqiqada bir a'zoga ko'pi bilan 3 ta kod


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


# ── Sessiya ─────────────────────────────────────────────────────────────────

def access_for(member):
    acc = StudentAccess.query.filter_by(member_id=member.id).first()
    if acc is None:
        acc = StudentAccess(member_id=member.id)
        db.session.add(acc)
        db.session.flush()
    return acc


def login(member):
    acc = access_for(member)
    acc.last_seen = _utcnow()
    db.session.commit()
    session.permanent = True
    session["sid"], session["sv"] = member.id, acc.version


def logout():
    session.pop("sid", None)
    session.pop("sv", None)


def current():
    mid = session.get("sid")
    if not mid:
        return None
    acc = StudentAccess.query.filter_by(member_id=mid).first()
    if acc is None or acc.version != session.get("sv"):
        logout()
        return None
    if not acc.last_seen or _utcnow() - acc.last_seen > timedelta(minutes=10):
        acc.last_seen = _utcnow()
        db.session.commit()
    return acc.member


def revoke_all(member):
    """Barcha qurilmalardagi kirishni bekor qiladi (va eski taklif havolasini ham)."""
    acc = access_for(member)
    acc.version += 1
    acc.token_hash = None
    db.session.commit()


# ── Taklif havolasi ─────────────────────────────────────────────────────────

def issue_invite(member):
    """Yangi taklif tokeni (ochiq ko'rinishi faqat shu yerda qaytadi, bazada xeshi saqlanadi)."""
    token = secrets.token_urlsafe(24)
    acc = access_for(member)
    acc.token_hash = _sha(token)
    db.session.commit()
    return token


def member_by_invite(token):
    if not token or len(token) > 100:
        return None
    acc = StudentAccess.query.filter_by(token_hash=_sha(token)).first()
    return acc.member if acc else None


# ── Telegram orqali bir martalik kod ────────────────────────────────────────

def _digits(s):
    return re.sub(r"\D", "", s or "")[-9:]


def find_by_phone(phone):
    d = _digits(phone)
    if len(d) < 9:
        return []
    return [m for m in Member.query.filter(Member.phone != "").all() if _digits(m.phone) == d]


def _code_hash(member_id, code):
    key = (current_app.secret_key or "assoodiq").encode() if isinstance(current_app.secret_key, str) \
        else (current_app.secret_key or b"assoodiq")
    return hmac.new(key, f"{member_id}:{code}".encode(), hashlib.sha256).hexdigest()


def send_code(phone):
    """('sent'|'notfound'|'nolink'|'limit'|'failed', member)"""
    from core import telegram as T
    found = find_by_phone(phone)
    if not found:
        return "notfound", None
    linked = [m for m in found if m.telegram and m.telegram.active]
    if not linked or not T.enabled():
        return "nolink", found[0]
    m = linked[0]
    recent = LoginCode.query.filter(LoginCode.member_id == m.id,
                                    LoginCode.created_at >= _utcnow() - CODE_TTL).count()
    if recent >= CODES_PER_WINDOW:
        return "limit", m
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.session.add(LoginCode(member_id=m.id, code_hash=_code_hash(m.id, code), expires_at=_utcnow() + CODE_TTL))
    db.session.commit()
    ok = T.send(m.telegram.chat_id, f"🔐 Ilovaga kirish kodi: <b>{code}</b>\n\n10 daqiqa amal qiladi. "
                                    "Kodni hech kimga bermang.")[0]
    return ("sent" if ok else "failed"), m


def check_code(member_id, code):
    code = re.sub(r"\D", "", code or "")
    row = (LoginCode.query.filter(LoginCode.member_id == member_id, LoginCode.used.is_(False),
                                  LoginCode.expires_at > _utcnow())
           .order_by(LoginCode.id.desc()).first())
    if row is None or row.attempts >= CODE_ATTEMPTS:
        return False
    if hmac.compare_digest(row.code_hash, _code_hash(member_id, code)):
        row.used = True
        db.session.commit()
        return True
    row.attempts += 1
    db.session.commit()
    return False


# ── Telegram Mini App ───────────────────────────────────────────────────────

def check_init_data(init_data, token, max_age=24 * 3600, now=None):
    """Telegram WebApp initData imzosini tekshiradi; to'g'ri bo'lsa — foydalanuvchi (dict)."""
    if not init_data or not token:
        return None
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    got = data.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not got or not hmac.compare_digest(calc, got):
        return None
    try:
        if (now or time.time()) - int(data.get("auth_date", 0)) > max_age:
            return None
        return json.loads(data.get("user") or "{}") or None
    except ValueError:
        return None


def member_by_telegram(user_id):
    link = (TelegramLink.query.filter_by(chat_id=str(user_id), active=True)
            .order_by(TelegramLink.linked_at.desc()).first())
    return link.member if link else None


# ── O'quv ma'lumotlari ──────────────────────────────────────────────────────

def enrollments(member):
    return (member.enrollments.filter(Enrollment.status != "chiqqan")
            .order_by(Enrollment.joined_at.desc()).all())


def is_locked(enr, today=None):
    """Obuna muddati o'tgan bo'lsa — yopiq (tekin mavzulardan tashqari)."""
    today = today or date.today()
    return bool(enr.valid_until and enr.valid_until < today)


def published_lectures(program_id):
    return (Lecture.query.join(Module, Lecture.module_id == Module.id)
            .filter(Module.program_id == program_id, Lecture.published.is_(True))
            .order_by(Module.position, Module.id, Lecture.position, Lecture.id).all())


def progress_map(member_id, lecture_ids=None):
    q = LectureProgress.query.filter_by(member_id=member_id)
    if lecture_ids is not None:
        if not lecture_ids:
            return {}
        q = q.filter(LectureProgress.lecture_id.in_(lecture_ids))
    return {p.lecture_id: p for p in q.all()}


def courses(member, paid_map=None):
    """O'quvchining dasturlari: o'quv dasturi bo'yicha progress va to'lov holati."""
    paid_map = paid_map if paid_map is not None else F.enrollment_paid_map()
    out = []
    for e in enrollments(member):
        lectures = published_lectures(e.program_id)
        prog = progress_map(member.id, [x.id for x in lectures])
        done = sum(1 for x in lectures if prog.get(x.id) and prog[x.id].done)
        nxt = next((x for x in lectures if not (prog.get(x.id) and prog[x.id].done)), None)
        row = F.enrollment_row(e, paid_map)
        out.append({"enrollment": e, "program": e.program, "lectures": len(lectures), "done": done,
                    "pct": done / len(lectures) if lectures else 0, "next": nxt, "locked": is_locked(e),
                    "minutes": sum(x.duration or 0 for x in lectures) // 60,
                    "paid": row["paid"], "due": row["due"], "price": row["price"]})
    return out


def can_view(member, lecture):
    """(ruxsat, sabab). Sabab: 'enroll' — dasturda yo'q, 'expired' — obuna tugagan."""
    if not lecture.published:
        return False, "enroll"
    enr = (member.enrollments.filter(Enrollment.program_id == lecture.module.program_id,
                                     Enrollment.status != "chiqqan").order_by(Enrollment.joined_at.desc()).first())
    if enr is None:
        return False, "enroll"
    if is_locked(enr) and not lecture.free:
        return False, "expired"
    return True, ""


def save_progress(member, lecture, position=None, duration=None, done=None):
    p = LectureProgress.query.filter_by(member_id=member.id, lecture_id=lecture.id).first()
    if p is None:
        p = LectureProgress(member_id=member.id, lecture_id=lecture.id)
        db.session.add(p)
    if position is not None:
        p.position = max(0, int(position))
    if duration and not lecture.duration:
        lecture.duration = int(duration)
    if done is not None:
        p.done = bool(done)
    elif position and (duration or lecture.duration):
        if position >= 0.9 * (duration or lecture.duration):
            p.done = True  # 90% ko'rilgan bo'lsa — tugatilgan
    p.updated_at = _utcnow()
    db.session.commit()
    return p


def continue_item(member):
    """Oxirgi ko'rilayotgan (tugatilmagan) mavzu yoki birinchi kursdagi keyingi mavzu."""
    p = (LectureProgress.query.filter_by(member_id=member.id, done=False)
         .order_by(LectureProgress.updated_at.desc()).first())
    if p and can_view(member, p.lecture)[0]:
        return p.lecture, p
    return None, None


def neighbours(lecture):
    items = published_lectures(lecture.module.program_id)
    ids = [x.id for x in items]
    i = ids.index(lecture.id) if lecture.id in ids else -1
    prev = items[i - 1] if i > 0 else None
    nxt = items[i + 1] if 0 <= i < len(items) - 1 else None
    return prev, nxt, i + 1, len(items)
