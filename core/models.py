"""Ma'lumotlar modeli.

Hamma pul harakati bitta daftarda — `Transaction`. Hisob balansi, foyda-zarar,
kurs iqtisodiyoti, qarz qoldig'i va tozalash fondi shu daftardan hisoblanadi,
shuning uchun hech bir raqam ikki joyda qo'lda yozilmaydi.
"""
from datetime import date, datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from core.extensions import db

# ── Lug'atlar (kod → o'zbekcha nom) ─────────────────────────────────────────

ROLES = {
    "rahbar": "Rahbar",
    "buxgalter": "Buxgalter",
    "menejer": "Menejer",
}

ACCOUNT_KINDS = {
    "naqd": "Naqd",
    "karta": "Karta",
    "bank": "Bank hisobi",
    "payme": "Payme",
    "click": "Click",
    "uzum": "Uzum",
    "boshqa": "Boshqa",
}

CURRENCIES = {"UZS": "so'm", "USD": "$"}

# Daftardagi yozuv turlari. Foyda-zararga faqat kirim/chiqim kiradi;
# o'tkazma va qarz harakatlari faqat balansni o'zgartiradi.
TX_KINDS = {
    "kirim": "Kirim",
    "chiqim": "Chiqim",
    "otkazma": "O'tkazma",
    "qarz_kirim": "Qarz (kirim)",
    "qarz_chiqim": "Qarz (chiqim)",
}
TX_IN = ("kirim", "qarz_kirim")
TX_OUT = ("chiqim", "qarz_chiqim")

# Daromad qaysi aqd (shartnoma) asosida olingan
AQD_TYPES = {
    "savdo": "Savdo (bay')",
    "xizmat": "Xizmat (ijara al-a'mol)",
    "ijara": "Ijara",
    "murobaha": "Murobaha",
    "mushoraka": "Mushoraka",
    "mudoraba": "Mudoraba",
    "hadya": "Hadya / xayriya",
    "boshqa": "Boshqa",
}

SHARIAT = {
    "halol": "Halol",
    "shubhali": "Shubhali",
    "nohalol": "Nohalol",
}

PROGRAM_KINDS = {
    "kurs": "Kurs",
    "klub": "Klub",
    "tadbir": "Tadbir",
    "konsalting": "Konsalting",
}
PROGRAM_STATUS = {
    "rejada": "Rejada",
    "faol": "Faol",
    "yakunlangan": "Yakunlangan",
}
BILLING = {
    "bir_martalik": "Bir martalik",
    "oylik": "Oylik obuna",
    "yillik": "Yillik obuna",
}

DEBT_DIRECTIONS = {
    "berilgan": "Biz bergan qarz",
    "olingan": "Biz olgan qarz",
}

# Tizim kategoriyalari: kod orqali topiladi (nomi o'zgartirilsa ham ishlaydi)
SYSTEM_CATEGORIES = {
    "zakot": "Zakot",
    "tozalash": "Tozalash (nohalol tushumdan)",
    "sadaqa": "Sadaqa va xayriya",
}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="menejer")
    code_hash = db.Column(db.String(256), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=_now)

    def set_code(self, code):
        self.code_hash = generate_password_hash(code)

    def check_code(self, code):
        return check_password_hash(self.code_hash, code)

    @property
    def role_name(self):
        return ROLES.get(self.role, self.role)


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="naqd")
    currency = db.Column(db.String(3), nullable=False, default="UZS")
    opening_balance = db.Column(db.Float, nullable=False, default=0)
    active = db.Column(db.Boolean, default=True, nullable=False)
    sort = db.Column(db.Integer, default=0)

    @property
    def kind_name(self):
        return ACCOUNT_KINDS.get(self.kind, self.kind)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(10), nullable=False)  # kirim | chiqim
    group = db.Column(db.String(60), nullable=False, default="Boshqa")
    system_code = db.Column(db.String(20), unique=True)  # zakot | tozalash | sadaqa
    # Dastur to'lovi qabul qilinganda shu turdagi dastur uchun avtomatik tanlanadi
    program_kind = db.Column(db.String(20))
    active = db.Column(db.Boolean, default=True, nullable=False)
    sort = db.Column(db.Integer, default=0)


class Program(db.Model):
    """Kurs, klub, tadbir yoki konsalting — daromad keladigan har bir yo'nalish."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="kurs")
    billing = db.Column(db.String(20), nullable=False, default="bir_martalik")
    price = db.Column(db.Float, nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default="UZS")
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    capacity = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default="faol")
    description = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=_now)

    enrollments = db.relationship("Enrollment", backref="program", lazy="dynamic")

    @property
    def kind_name(self):
        return PROGRAM_KINDS.get(self.kind, self.kind)

    @property
    def status_name(self):
        return PROGRAM_STATUS.get(self.status, self.status)

    @property
    def billing_name(self):
        return BILLING.get(self.billing, self.billing)


class Member(db.Model):
    """O'quvchi yoki klub a'zosi (odatda biznes egasi)."""

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40), default="")
    business = db.Column(db.String(160), default="")  # biznesi / sohasi
    city = db.Column(db.String(80), default="")
    note = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=_now)

    enrollments = db.relationship("Enrollment", backref="member", lazy="dynamic")


class Enrollment(db.Model):
    """A'zoning dasturga yozilishi: kelishilgan narx va (klub uchun) amal muddati."""

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey("program.id"), nullable=False)
    price = db.Column(db.Float, nullable=False, default=0)  # chegirmadan keyingi summa
    joined_at = db.Column(db.Date, default=date.today)
    valid_until = db.Column(db.Date)  # klub obunasi tugash sanasi
    status = db.Column(db.String(20), nullable=False, default="faol")  # faol | tugatgan | chiqqan
    note = db.Column(db.String(255), default="")


class MemberEvent(db.Model):
    """A'zo tarixidagi voqealar (to'lov va yozilish o'z jadvalidan olinadi):
    obuna uzaytirildi, dasturdagi holati o'zgardi, dasturga yozildi."""

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False, index=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("enrollment.id"))
    kind = db.Column(db.String(20), nullable=False)  # renew | status
    text = db.Column(db.String(255), default="")
    amount = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=_now)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    enrollment = db.relationship("Enrollment")
    user = db.relationship("User")


class Debt(db.Model):
    """Qarz daftari (Baqara 282). Qarzga foiz qo'shilmaydi."""

    id = db.Column(db.Integer, primary_key=True)
    direction = db.Column(db.String(10), nullable=False)  # berilgan | olingan
    counterparty = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40), default="")
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="UZS")
    date = db.Column(db.Date, nullable=False, default=date.today)
    due_date = db.Column(db.Date)
    witness = db.Column(db.String(160), default="")  # guvoh(lar)
    note = db.Column(db.Text, default="")
    closed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=_now)

    @property
    def direction_name(self):
        return DEBT_DIRECTIONS.get(self.direction, self.direction)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    kind = db.Column(db.String(12), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)  # hisob valyutasida
    # Yozilgan paytdagi kurs bo'yicha so'mdagi qiymati — hisobotlar shundan
    # olinadi, kurs keyin o'zgarsa ham o'tgan oylar raqami siljimaydi.
    amount_uzs = db.Column(db.Float, nullable=False, default=0)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    # O'tkazma: qaysi hisobga va (valyuta farq qilsa) qancha tushdi
    to_account_id = db.Column(db.Integer, db.ForeignKey("account.id"))
    to_amount = db.Column(db.Float)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"))
    program_id = db.Column(db.Integer, db.ForeignKey("program.id"))
    enrollment_id = db.Column(db.Integer, db.ForeignKey("enrollment.id"))
    debt_id = db.Column(db.Integer, db.ForeignKey("debt.id"))
    counterparty = db.Column(db.String(160), default="")
    aqd = db.Column(db.String(20), default="")
    shariat = db.Column(db.String(10), nullable=False, default="halol")
    note = db.Column(db.String(500), default="")
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=_now)

    account = db.relationship("Account", foreign_keys=[account_id])
    to_account = db.relationship("Account", foreign_keys=[to_account_id])
    category = db.relationship("Category")
    program = db.relationship("Program")
    enrollment = db.relationship("Enrollment", backref=db.backref("payments", lazy="dynamic"))
    debt = db.relationship("Debt", backref=db.backref("moves", lazy="dynamic"))
    author = db.relationship("User")

    @property
    def currency(self):
        return self.account.currency if self.account else "UZS"

    @property
    def kind_name(self):
        return TX_KINDS.get(self.kind, self.kind)


class Setting(db.Model):
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.String(500), nullable=False, default="")


class ZakatSnapshot(db.Model):
    """Zakot hisob-kitobining saqlangan nusxasi (har havl uchun tarix)."""

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    hijri = db.Column(db.String(40), default="")
    cash = db.Column(db.Float, default=0)
    receivables = db.Column(db.Float, default=0)
    inventory = db.Column(db.Float, default=0)
    other_assets = db.Column(db.Float, default=0)
    liabilities = db.Column(db.Float, default=0)
    nisob_basis = db.Column(db.String(10), default="oltin")
    nisob_value = db.Column(db.Float, default=0)
    base = db.Column(db.Float, default=0)
    due = db.Column(db.Float, default=0)
    note = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=_now)


class AuditLog(db.Model):
    """Kim, qachon, nima qildi — o'chirish, tahrirlash, tozalash, sozlama va xodimlar."""

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=_now, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(40), nullable=False)
    details = db.Column(db.String(500), default="")

    user = db.relationship("User")
