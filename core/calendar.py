"""Dars jadvali (kalendar): takrorlash, kun ichida joylashtirish, to'qnashuvlar.

Hafta dushanbadan boshlanadi. Har dastur o'z rangida ko'rinadi (id bo'yicha barqaror).
"""
from datetime import date, datetime, time, timedelta

from core.models import Lesson

WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
WEEKDAYS_SHORT = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr",
          "oktabr", "noyabr", "dekabr"]

# Brend bilan uyg'un, bir-biridan aniq ajraladigan ranglar (oq matn uchun yetarli kontrast)
COLORS = ["#0B8F68", "#2B7FB8", "#B8862B", "#7A5AC8", "#C9563F", "#1B8E9A", "#B54A7F", "#4E6FB0",
          "#5E7A2E", "#8A6A3B"]

MAX_REPEAT = 120  # bitta seriyada eng ko'p dars


def color_for(program_id):
    return COLORS[(program_id or 0) % len(COLORS)]


def week_start(d):
    return d - timedelta(days=d.weekday())


def parse_time(raw, default=None):
    try:
        h, m = (int(x) for x in (raw or "").strip().split(":")[:2])
        return time(h, m)
    except (ValueError, TypeError):
        return default


def minutes(t):
    return t.hour * 60 + t.minute


def expand_weekly(start, weekdays, until=None, count=None):
    """Haftalik takrorlash sanalari: start'dan boshlab tanlangan hafta kunlarida,
    `until` sanasigacha yoki `count` ta bo'lguncha (eng ko'pi MAX_REPEAT)."""
    weekdays = sorted(set(weekdays)) or [start.weekday()]
    limit = min(count or MAX_REPEAT, MAX_REPEAT)
    if until is None and not count:
        until = start + timedelta(weeks=12)
    out, d = [], start
    while len(out) < limit and (until is None or d <= until) and d <= start + timedelta(days=730):
        if d.weekday() in weekdays:
            out.append(d)
        d += timedelta(days=1)
    return out


def layout_day(lessons, day_start_min):
    """Kun ustunidagi darslar: kesishganlari yonma-yon (Google Calendar kabi).

    Natija: [{lesson, top, height, col, cols}] — top/height daqiqada (kun boshidan).
    """
    items = sorted(lessons, key=lambda x: (minutes(x.start), -x.minutes))
    out, cluster, cluster_end = [], [], -1

    def flush():
        cols = []  # har ustunning oxirgi tugash vaqti
        for it in cluster:
            s = minutes(it["lesson"].start)
            for i, end in enumerate(cols):
                if end <= s:
                    it["col"], cols[i] = i, minutes(it["lesson"].end)
                    break
            else:
                it["col"] = len(cols)
                cols.append(minutes(it["lesson"].end))
        for it in cluster:
            it["cols"] = len(cols)
        out.extend(cluster)

    for les in items:
        s, e = minutes(les.start), minutes(les.end)
        if cluster and s >= cluster_end:
            flush()
            cluster, cluster_end = [], -1
        cluster.append({"lesson": les, "top": s - day_start_min, "height": max(e - s, 20)})
        cluster_end = max(cluster_end, e)
    if cluster:
        flush()
    return out


def conflicts(lesson):
    """Shu vaqtda xuddi shu joyda yoki shu o'qituvchida boshqa dars bormi."""
    if lesson.status == "bekor":
        return []
    q = Lesson.query.filter(Lesson.date == lesson.date, Lesson.status != "bekor", Lesson.start < lesson.end,
                            Lesson.end > lesson.start)
    if lesson.id:
        q = q.filter(Lesson.id != lesson.id)
    found = []
    for other in q.all():
        loc = lesson.location.strip().lower() if lesson.location else ""
        who = lesson.teacher.strip().lower() if lesson.teacher else ""
        if loc and other.location and other.location.strip().lower() == loc:
            found.append((other, f"«{other.location}» band"))
        elif who and other.teacher and other.teacher.strip().lower() == who:
            found.append((other, f"{other.teacher} boshqa darsda"))
    return found


def fmt_range(a, b):
    """'6 – 12 oktabr 2026' yoki '29 sentabr – 5 oktabr 2026'."""
    if a.year != b.year:
        return f"{a.day} {MONTHS[a.month - 1]} {a.year} – {b.day} {MONTHS[b.month - 1]} {b.year}"
    if a.month != b.month:
        return f"{a.day} {MONTHS[a.month - 1]} – {b.day} {MONTHS[b.month - 1]} {b.year}"
    return f"{a.day} – {b.day} {MONTHS[a.month - 1]} {b.year}"


def month_grid(d):
    """Oy ko'rinishi uchun 6 hafta × 7 kun (dushanbadan)."""
    first = d.replace(day=1)
    start = week_start(first)
    return [[start + timedelta(days=w * 7 + i) for i in range(7)] for w in range(6)]


def now_local():
    return datetime.now()
