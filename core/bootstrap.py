"""Bo'sh bazani ishga tayyorlash: hisoblar, kategoriyalar, birinchi rahbar va maxfiy kalit.

Ilova har ishga tushganda chaqiriladi va faqat yetishmayotgan narsani yaratadi,
shuning uchun Railway'da qo'lda `seed.py` ishlatish shart emas.
"""
import os
import secrets

from sqlalchemy.exc import IntegrityError

from core.extensions import db
from core.models import Account, Category, Setting, User

ACCOUNTS = [
    ("Asosiy kassa", "naqd", "UZS", 0),
    ("Korporativ karta", "karta", "UZS", 0),
    ("Bank hisobi", "bank", "UZS", 0),
    ("Payme", "payme", "UZS", 0),
    ("Click", "click", "UZS", 0),
    ("Dollar kassa", "naqd", "USD", 0),
]

# (nomi, turi, guruh, tizim kodi, dastur turi)
CATEGORIES = [
    ("Kurs to'lovlari", "kirim", "Ta'lim daromadi", None, "kurs"),
    ("Klub a'zoligi", "kirim", "Ta'lim daromadi", None, "klub"),
    ("Tadbir chiptalari", "kirim", "Tadbirlar", None, "tadbir"),
    ("Konsalting", "kirim", "Konsalting", None, "konsalting"),
    ("Kitob va mahsulot savdosi", "kirim", "Savdo", None, None),
    ("Boshqa kirim", "kirim", "Boshqa", None, None),
    ("Reklama (Instagram, Telegram)", "chiqim", "Marketing", None, None),
    ("Kontent va video", "chiqim", "Marketing", None, None),
    ("Mentorlar haqi", "chiqim", "Jamoa", None, None),
    ("Xodimlar oyligi", "chiqim", "Jamoa", None, None),
    ("Ofis ijarasi", "chiqim", "Ofis", None, None),
    ("Servislar va dasturlar", "chiqim", "Ofis", None, None),
    ("Zal ijarasi", "chiqim", "Tadbirlar", None, None),
    ("Kofe-breyk va tashkiliy", "chiqim", "Tadbirlar", None, None),
    ("Kitob xaridi", "chiqim", "Savdo", None, None),
    ("Soliq va majburiy to'lovlar", "chiqim", "Soliq", None, None),
    ("Bank xizmatlari", "chiqim", "Boshqa", None, None),
    ("Zakot", "chiqim", "Diniy majburiyatlar", "zakot", None),
    ("Tozalash (nohalol tushumdan)", "chiqim", "Diniy majburiyatlar", "tozalash", None),
    ("Sadaqa va xayriya", "chiqim", "Diniy majburiyatlar", "sadaqa", None),
]


def base_setup(users=None):
    """users: [(ism, rol, kod)] — berilmasa faqat bitta rahbar yaratiladi."""
    if Account.query.count() == 0:
        for i, (n, k, c, ob) in enumerate(ACCOUNTS):
            db.session.add(Account(name=n, kind=k, currency=c, opening_balance=ob, sort=i))
    if Category.query.count() == 0:
        for i, (n, k, grp, code, pk) in enumerate(CATEGORIES):
            db.session.add(Category(name=n, kind=k, group=grp, system_code=code, program_kind=pk, sort=i))
    if users is not None:  # lokal namuna: yetishmayotgan xodimlarni qo'shamiz
        existing = {u.name for u in User.query.all()}
        users = [u for u in users if u[0] not in existing]
    elif User.query.count() == 0:
        code = "".join(ch for ch in os.environ.get("ADMIN_CODE", "") if ch.isdigit())
        if len(code) != 6:
            code = f"{secrets.randbelow(900000) + 100000}"
            print(f"[assoodiq] ADMIN_CODE berilmagan. Rahbarning kirish kodi: {code} — "
                  "kirgach Sozlamalar > Xodimlar'da almashtiring.", flush=True)
        users = [("Rahbar", "rahbar", code)]
    for n, r, c in users or []:
        u = User(name=n, role=r)
        u.set_code(c)
        db.session.add(u)
    try:
        db.session.commit()
    except IntegrityError:  # bir vaqtda ishga tushgan boshqa jarayon allaqachon yaratgan
        db.session.rollback()


def secret_key():
    """SECRET_KEY muhitda bo'lmasa — bazada saqlanadigan tasodifiy kalit.

    Repozitoriydagi standart kalit bilan sessiyani soxtalashtirib bo'lmasin, kalit esa
    qayta deployda o'zgarib, hamma tizimdan chiqib ketmasin.
    """
    row = db.session.get(Setting, "secret_key")
    if row:
        return row.value
    db.session.add(Setting(key="secret_key", value=secrets.token_hex(32)))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
    return db.session.get(Setting, "secret_key").value
