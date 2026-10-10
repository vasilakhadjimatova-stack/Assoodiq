"""Hijriy taqvim (jadval usuli, Kuwaiti algoritmi).

Hisoblangan sana oy ko'rinishiga qarab e'lon qilinadigan sanadan ±1–2 kun
farq qilishi mumkin — zakot sanasini rejalash uchun yetarli, ibodat sanalari
uchun esa rasmiy e'longa qaraladi.
"""
import math
from datetime import date

ISLAMIC_EPOCH = 1948439.5

MONTHS = [
    "Muharram", "Safar", "Rabiul-avval", "Rabius-soniy", "Jumodul-avval",
    "Jumodus-soniy", "Rajab", "Sha'bon", "Ramazon", "Shavvol", "Zulqa'da",
    "Zulhijja",
]


def _islamic_to_jd(year, month, day):
    return (day + math.ceil(29.5 * (month - 1)) + (year - 1) * 354
            + math.floor((3 + 11 * year) / 30) + ISLAMIC_EPOCH) - 1


def _date_to_jd(d):
    return d.toordinal() + 1721424.5


def _jd_to_date(jd):
    return date.fromordinal(int(math.floor(jd - 1721424.5 + 0.5)))


def to_hijri(d):
    """Grigorian sana → (yil, oy, kun)."""
    jd = math.floor(_date_to_jd(d)) + 0.5
    year = math.floor((30 * (jd - ISLAMIC_EPOCH) + 10646) / 10631)
    month = min(12, math.ceil((jd - (29 + _islamic_to_jd(year, 1, 1))) / 29.5) + 1)
    day = int(jd - _islamic_to_jd(year, month, 1) + 1)
    return int(year), int(month), day


def from_hijri(year, month, day):
    """(yil, oy, kun) hijriy → Grigorian sana."""
    return _jd_to_date(_islamic_to_jd(year, month, day))


def format_hijri(d):
    y, m, dd = to_hijri(d)
    return f"{dd} {MONTHS[m - 1]} {y}"


def next_hawl(start, today=None):
    """Havl boshlangan sanadan keyingi eng yaqin hijriy yillik (bugun yoki keyin)."""
    today = today or date.today()
    y, m, d = to_hijri(start)
    while True:
        y += 1
        candidate = from_hijri(y, m, d)
        if candidate >= today:
            return candidate
