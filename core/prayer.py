"""Namoz vaqtlari va qibla yo'nalishi (astronomik hisob, internet talab qilinmaydi).

Algoritm PrayTimes.org usuli asosida: Quyoshning og'ishi va vaqt tenglamasidan
bomdod/xufton burchaklari, asr soya nisbati (Hanafiy — 2, Shofeiy — 1) bo'yicha.
Rasmiy taqvimdan 1–3 daqiqa farq bo'lishi mumkin — Sozlamalarda har namozga
daqiqa tuzatish berish mumkin.
"""
import math
from datetime import datetime, timedelta

KAABA = (21.422487, 39.826206)

# Bomdod va xufton burchaklari; xufton raqam emas, "90min" bo'lsa — shomdan keyin daqiqa
METHODS = {
    "MWL": {"name": "Muslim World League (18° / 17°)", "fajr": 18, "isha": 17},
    "ISNA": {"name": "Shimoliy Amerika — ISNA (15° / 15°)", "fajr": 15, "isha": 15},
    "Egypt": {"name": "Misr (19.5° / 17.5°)", "fajr": 19.5, "isha": 17.5},
    "Makkah": {"name": "Umm al-Quro, Makka (18.5° / 90 daq)", "fajr": 18.5, "isha": "90min"},
    "Karachi": {"name": "Karachi (18° / 18°)", "fajr": 18, "isha": 18},
}
ASR = {"hanafi": 2, "shafii": 1}

PRAYERS = [("bomdod", "Bomdod"), ("quyosh", "Quyosh"), ("peshin", "Peshin"),
           ("asr", "Asr"), ("shom", "Shom"), ("xufton", "Xufton")]

CITIES = {
    "Toshkent": (41.2995, 69.2401), "Samarqand": (39.6542, 66.9597), "Buxoro": (39.7747, 64.4286),
    "Andijon": (40.7821, 72.3442), "Namangan": (40.9983, 71.6726), "Farg'ona": (40.3864, 71.7864),
    "Qo'qon": (40.5286, 70.9425), "Marg'ilon": (40.4711, 71.7247), "Nukus": (42.4600, 59.6100),
    "Urganch": (41.5500, 60.6333), "Xiva": (41.3783, 60.3639), "Qarshi": (38.8600, 65.7900),
    "Termiz": (37.2242, 67.2783), "Jizzax": (40.1158, 67.8422), "Guliston": (40.4897, 68.7842),
    "Navoiy": (40.0844, 65.3792), "Chirchiq": (41.4689, 69.5822), "Angren": (41.0167, 70.1436),
    "Olmaliq": (40.8447, 69.5983), "Shahrisabz": (39.0578, 66.8342),
}

TZ_DEFAULT = 5  # O'zbekiston: UTC+5, yozgi vaqt yo'q


# ── trigonometriya (gradusda) ──
def _sin(d): return math.sin(math.radians(d))
def _cos(d): return math.cos(math.radians(d))
def _tan(d): return math.tan(math.radians(d))
def _asin(x): return math.degrees(math.asin(x))
def _acos(x): return math.degrees(math.acos(x))
def _atan2(y, x): return math.degrees(math.atan2(y, x))
def _acot(x): return math.degrees(math.atan(1 / x))
def _fix(a, b): return a - b * math.floor(a / b)


def _julian(d):
    y, m = d.year, d.month
    if m <= 2:
        y, m = y - 1, m + 12
    a = math.floor(y / 100)
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d.day + 2 - a + math.floor(a / 4) - 1524.5


def _sun(jd):
    """(og'ish, vaqt tenglamasi soatda)"""
    D = jd - 2451545.0
    g = _fix(357.529 + 0.98560028 * D, 360)
    q = _fix(280.459 + 0.98564736 * D, 360)
    L = _fix(q + 1.915 * _sin(g) + 0.020 * _sin(2 * g), 360)
    e = 23.439 - 0.00000036 * D
    ra = _atan2(_cos(e) * _sin(L), _cos(L)) / 15
    eqt = q / 15 - _fix(ra, 24)
    return _asin(_sin(e) * _sin(L)), eqt


def compute(d, lat, lng, tz=TZ_DEFAULT, method="MWL", asr="hanafi", offsets=None):
    """{kalit: soat (float, mahalliy vaqt) yoki None}. offsets — daqiqalar, PRAYERS tartibida."""
    m = METHODS.get(method, METHODS["MWL"])
    jd = _julian(d) - lng / (15 * 24)

    def mid(t):
        return _fix(12 - _sun(jd + t)[1], 24)

    def angle_time(angle, t, ccw=False):
        decl = _sun(jd + t)[0]
        x = (-_sin(angle) - _sin(decl) * _sin(lat)) / (_cos(decl) * _cos(lat))
        if abs(x) > 1:
            return None  # qutbga yaqin hududlar: bu burchakka yetmaydi
        diff = _acos(x) / 15
        return mid(t) + (-diff if ccw else diff)

    def asr_time(factor, t):
        decl = _sun(jd + t)[0]
        return angle_time(-_acot(factor + _tan(abs(lat - decl))), t)

    t = {k: v / 24 for k, v in (("bomdod", 5), ("quyosh", 6), ("peshin", 12), ("asr", 13), ("shom", 18), ("xufton", 18))}
    times = {
        "bomdod": angle_time(m["fajr"], t["bomdod"], ccw=True),
        "quyosh": angle_time(0.833, t["quyosh"], ccw=True),
        "peshin": mid(t["peshin"]),
        "asr": asr_time(ASR.get(asr, 2), t["asr"]),
        "shom": angle_time(0.833, t["shom"]),
    }
    isha = m["isha"]
    if isinstance(isha, str):
        times["xufton"] = times["shom"] + int(isha[:-3]) / 60 if times["shom"] is not None else None
    else:
        times["xufton"] = angle_time(isha, t["xufton"])
    shift = tz - lng / 15
    offsets = offsets or [0] * 6
    out = {}
    for (k, _), off in zip(PRAYERS, offsets):
        v = times[k]
        out[k] = None if v is None else _fix(v + shift + (off or 0) / 60, 24)
    return out


def hhmm(hours):
    if hours is None:
        return "—"
    mins = int(round(hours * 60)) % (24 * 60)
    return f"{mins // 60:02d}:{mins % 60:02d}"


def day_schedule(d, lat, lng, tz=TZ_DEFAULT, **kw):
    """[{key, name, time 'HH:MM', minutes}] — ekranga tayyor ro'yxat."""
    t = compute(d, lat, lng, tz, **kw)
    return [{"key": k, "name": n, "time": hhmm(t[k]),
             "minutes": None if t[k] is None else int(round(t[k] * 60)) % 1440} for k, n in PRAYERS]


def next_prayer(now, lat, lng, tz=TZ_DEFAULT, **kw):
    """Keyingi namoz (quyosh chiqishi hisobga olinmaydi): (kalit, nom, datetime)."""
    for day_shift in (0, 1):
        d = now.date() + timedelta(days=day_shift)
        for item in day_schedule(d, lat, lng, tz, **kw):
            if item["key"] == "quyosh" or item["minutes"] is None:
                continue
            at = datetime.combine(d, datetime.min.time()) + timedelta(minutes=item["minutes"])
            if at > now:
                return item["key"], item["name"], at
    return None


def qibla(lat, lng):
    """Shimoldan soat mili bo'yicha qibla burchagi (gradus) va Ka'bagacha masofa (km)."""
    p1, p2 = math.radians(lat), math.radians(KAABA[0])
    dl = math.radians(KAABA[1] - lng)
    bearing = math.degrees(math.atan2(math.sin(dl), math.cos(p1) * math.tan(p2) - math.sin(p1) * math.cos(dl)))
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    km = 2 * 6371 * math.asin(math.sqrt(a))
    return round(_fix(bearing, 360), 1), round(km)


def iso_at(dt, tz=TZ_DEFAULT):
    """Brauzer to'g'ri sanashi uchun mintaqa bilan: 2026-10-12T04:59+05:00"""
    sign = "+" if tz >= 0 else "-"
    mins = int(round(abs(tz) * 60))
    return dt.strftime("%Y-%m-%dT%H:%M") + f"{sign}{mins // 60:02d}:{mins % 60:02d}"


def compass_word(deg):
    names = ["shimol", "shimoli-sharq", "sharq", "janubi-sharq", "janub", "janubi-g'arb", "g'arb", "shimoli-g'arb"]
    return names[int((deg + 22.5) // 45) % 8]


def settings():
    """Ilova sozlamalaridan hisob parametrlari."""
    from core.finance import get_setting
    try:
        offsets = [int(float(x)) for x in (get_setting("prayer_offsets") or "").split(",")][:6]
    except ValueError:
        offsets = []
    offsets += [0] * (6 - len(offsets))
    method = get_setting("prayer_method") or "MWL"
    asr = get_setting("prayer_asr") or "hanafi"
    city = get_setting("app_city") or "Toshkent"
    return {"method": method if method in METHODS else "MWL", "asr": asr if asr in ASR else "hanafi",
            "offsets": offsets, "city": city if city in CITIES else "Toshkent"}


def week(start, lat, lng, tz=TZ_DEFAULT, days=7, **kw):
    return [{"date": start + timedelta(days=i), "times": day_schedule(start + timedelta(days=i), lat, lng, tz, **kw)}
            for i in range(days)]


