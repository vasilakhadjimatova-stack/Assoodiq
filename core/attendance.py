"""Davomat: a'zo QR kodi, dars ro'yxati, belgilash va statistika.

A'zo kodi: "AQ" + 6 xonali a'zo raqami + Luhn nazorat raqami (masalan AQ0000231).
Bazada alohida saqlanmaydi — chop etilgan kartalar doim amal qiladi; nazorat raqami
skanerdagi yoki qo'lda yozishdagi xatoni ushlaydi.
"""
import re
from datetime import date, datetime, timedelta, timezone

from markupsafe import Markup

from core.extensions import db
from core.models import Attendance, Enrollment, Lesson, Member

PREFIX = "AQ"
LATE_MINUTES = 10  # dars boshlanganidan shuncha daqiqa keyin — «kechikdi»
PRESENT = ("keldi", "kechikdi")


def _luhn(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            n = n - 9 if n > 9 else n
        total += n
    return str((10 - total % 10) % 10)


def member_code(member_id):
    base = f"{member_id:06d}"
    return f"{PREFIX}{base}{_luhn(base)}"


def parse_code(raw):
    """Skanerdan kelgan matn → a'zo id (yoki None). Havola ichida bo'lsa ham topadi."""
    s = re.sub(r"[\s-]", "", (raw or "").upper())
    m = re.search(PREFIX + r"(\d{6})(\d)", s)
    if not m or _luhn(m.group(1)) != m.group(2):
        return None
    return int(m.group(1))


def qr_svg(data, css_class="qr"):
    """QR kod — ichki SVG (chop etishda ham aniq)."""
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1,
                      error_correction=qrcode.constants.ERROR_CORRECT_M)
    svg = img.to_string(encoding="unicode")
    svg = re.sub(r"^<\?xml[^>]*>\s*", "", svg)
    svg = re.sub(r'\swidth="[^"]*"|\sheight="[^"]*"', "", svg, count=2)
    return Markup(svg.replace("<svg", f'<svg class="{css_class}" role="img" aria-label="QR kod"', 1))


def roster(lesson):
    """Darsga kutiladiganlar: shu dasturga yozilgan (chiqmagan) va dars kunigacha qo'shilganlar.

    Natija: [{member, enrollment, att, expired}] — ism bo'yicha.
    """
    enrs = (Enrollment.query.filter(Enrollment.program_id == lesson.program_id, Enrollment.status != "chiqqan")
            .all())
    marks = {a.member_id: a for a in lesson.attendance.all()}
    rows, seen = [], set()
    for e in enrs:
        if e.joined_at and e.joined_at > lesson.date and e.member_id not in marks:
            continue
        if e.member_id in seen:
            continue
        seen.add(e.member_id)
        rows.append({"member": e.member, "enrollment": e, "att": marks.get(e.member_id),
                     "expired": bool(e.valid_until and e.valid_until < lesson.date)})
    # ro'yxatda yo'q, lekin belgilangan (masalan, mehmon sifatida skaner qilingan)
    for mid, a in marks.items():
        if mid not in seen:
            rows.append({"member": a.member, "enrollment": None, "att": a, "expired": False})
    rows.sort(key=lambda r: r["member"].full_name.lower())
    return rows


def auto_status(lesson, now=None):
    now = now or datetime.now()
    start = datetime.combine(lesson.date, lesson.start)
    if lesson.date == now.date() and now > start + timedelta(minutes=LATE_MINUTES):
        return "kechikdi"
    return "keldi"


def mark(lesson, member_id, status, method="qolda", user_id=None):
    """Belgilash (status bo'sh — belgini olib tashlash). Dars o'tgan bo'lsa «o'tdi» bo'ladi."""
    att = Attendance.query.filter_by(lesson_id=lesson.id, member_id=member_id).first()
    if not status:
        if att:
            db.session.delete(att)
        return None
    if att is None:
        att = Attendance(lesson_id=lesson.id, member_id=member_id)
        db.session.add(att)
    att.status, att.method, att.marked_by = status, method, user_id
    att.marked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if lesson.status == "rejada" and lesson.date <= date.today() and status in PRESENT:
        lesson.status = "otdi"
    return att


def stats(lesson, rows=None):
    rows = rows if rows is not None else roster(lesson)
    c = {k: 0 for k in ("keldi", "kechikdi", "kelmadi", "sababli")}
    for r in rows:
        if r["att"]:
            c[r["att"].status] = c.get(r["att"].status, 0) + 1
    present = c["keldi"] + c["kechikdi"]
    total = len(rows)
    return dict(c, present=present, total=total, unmarked=total - sum(c.values()),
                pct=present / total if total else 0)


def lesson_counts(lesson_ids):
    """{lesson_id: (kelganlar, belgilanganlar)} — kalendar chiptalari uchun bitta so'rov."""
    if not lesson_ids:
        return {}
    out = {}
    for lid, st in db.session.query(Attendance.lesson_id, Attendance.status).filter(
            Attendance.lesson_id.in_(lesson_ids)).all():
        p, n = out.get(lid, (0, 0))
        out[lid] = (p + (1 if st in PRESENT else 0), n + 1)
    return out


def member_rate(member_id, program_id):
    """A'zoning dastur bo'yicha davomati: (kelgan, davomat olingan darslar)."""
    taken = (db.session.query(Lesson.id).join(Attendance, Attendance.lesson_id == Lesson.id)
             .filter(Lesson.program_id == program_id).distinct().subquery())
    total = db.session.query(db.func.count()).select_from(taken).scalar() or 0
    came = (Attendance.query.join(Lesson, Attendance.lesson_id == Lesson.id)
            .filter(Lesson.program_id == program_id, Attendance.member_id == member_id,
                    Attendance.status.in_(PRESENT)).count())
    return came, total


def find_member(member_id):
    return db.session.get(Member, member_id) if member_id else None
