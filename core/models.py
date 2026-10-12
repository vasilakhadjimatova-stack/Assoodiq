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


LESSON_STATUS = {"rejada": "Rejada", "otdi": "O'tdi", "bekor": "Bekor qilindi"}


class Lesson(db.Model):
    """Kalendardagi dars / mashg'ulot. Takrorlanuvchi darslar bitta series_id bilan bog'lanadi."""

    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey("program.id"), nullable=False, index=True)
    title = db.Column(db.String(160), default="")
    date = db.Column(db.Date, nullable=False, index=True)
    start = db.Column(db.Time, nullable=False)
    end = db.Column(db.Time, nullable=False)
    location = db.Column(db.String(120), default="")   # zal yoki onlayn havola
    teacher = db.Column(db.String(120), default="")    # mentor / ustoz
    note = db.Column(db.String(500), default="")
    status = db.Column(db.String(10), nullable=False, default="rejada")
    series_id = db.Column(db.String(32), index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=_now)

    program = db.relationship("Program", backref=db.backref("lessons", lazy="dynamic"))

    @property
    def minutes(self):
        return (self.end.hour * 60 + self.end.minute) - (self.start.hour * 60 + self.start.minute)

    @property
    def status_name(self):
        return LESSON_STATUS.get(self.status, self.status)


ATTENDANCE = {"keldi": "Keldi", "kechikdi": "Kechikdi", "kelmadi": "Kelmadi", "sababli": "Sababli"}


class Attendance(db.Model):
    """Darsdagi davomat: kim keldi / kechikdi / kelmadi / sababli. method — qo'lda yoki skaner."""

    __table_args__ = (db.UniqueConstraint("lesson_id", "member_id", name="uq_attendance_lesson_member"),)

    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lesson.id", ondelete="CASCADE"), nullable=False, index=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False, default="keldi")
    method = db.Column(db.String(10), nullable=False, default="qolda")  # qolda | skaner | kamera
    marked_at = db.Column(db.DateTime, default=_now)
    marked_by = db.Column(db.Integer, db.ForeignKey("user.id"))

    lesson = db.relationship("Lesson", backref=db.backref("attendance", lazy="dynamic", cascade="all, delete-orphan"))
    member = db.relationship("Member")

    @property
    def status_name(self):
        return ATTENDANCE.get(self.status, self.status)


class TelegramLink(db.Model):
    """A'zoning Telegram chati (bot orqali ulangan). Bitta chatga bir nechta a'zo ulanishi mumkin."""

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False, unique=True)
    chat_id = db.Column(db.String(32), nullable=False, index=True)
    username = db.Column(db.String(64), default="")
    first_name = db.Column(db.String(120), default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    linked_at = db.Column(db.DateTime, default=_now)

    member = db.relationship("Member", backref=db.backref("telegram", uselist=False))


class Notification(db.Model):
    """Yuborilgan Telegram xabarlari jurnali. dedup — avtomatik eslatma ikki marta ketmasligi uchun."""

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), index=True)
    chat_id = db.Column(db.String(32), default="")
    kind = db.Column(db.String(16), nullable=False, default="xabar")  # dars | obuna | qarz | xabar
    text = db.Column(db.Text, default="")
    status = db.Column(db.String(10), nullable=False, default="pending")  # pending | sent | failed
    error = db.Column(db.String(255), default="")
    dedup = db.Column(db.String(80), unique=True)
    created_at = db.Column(db.DateTime, default=_now, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))

    member = db.relationship("Member")


# ── O'quvchi ilovasi: o'quv dasturi va video darslar ───────────────────────

class Module(db.Model):
    """O'quv dasturining bo'limi (masalan, «1-modul. Halol savdo asoslari»)."""

    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey("program.id"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=_now)

    program = db.relationship("Program", backref=db.backref("modules", lazy="dynamic", order_by="Module.position"))


LECTURE_KINDS = {"video": "Video dars", "matn": "Matn / qo'llanma"}
VIDEO_STATUS = {"": "Video yo'q", "yuklanmoqda": "Yuklanmoqda", "ishlanmoqda": "Tayyorlanmoqda",
                "tayyor": "Tayyor", "xato": "Xato"}


class Lecture(db.Model):
    """Bo'lim ichidagi mavzu: Bunny Stream'dagi video yoki matnli qo'llanma."""

    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey("module.id"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(10), nullable=False, default="video")
    body = db.Column(db.Text, default="")                 # tavsif yoki qo'llanma matni
    video_id = db.Column(db.String(64), default="")       # Bunny Stream GUID
    video_status = db.Column(db.String(12), default="")
    duration = db.Column(db.Integer, default=0)           # soniya
    position = db.Column(db.Integer, nullable=False, default=0)
    published = db.Column(db.Boolean, nullable=False, default=True)
    free = db.Column(db.Boolean, nullable=False, default=False)  # obuna tugagan bo'lsa ham ochiq
    created_at = db.Column(db.DateTime, default=_now)

    module = db.relationship("Module", backref=db.backref("lectures", order_by="Lecture.position",
                                                          cascade="all, delete-orphan"))

    @property
    def minutes(self):
        return round((self.duration or 0) / 60)


class LectureProgress(db.Model):
    """O'quvchi mavzuni qayergacha ko'rgani va tugatgani."""

    __table_args__ = (db.UniqueConstraint("member_id", "lecture_id"),)
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False, index=True)
    lecture_id = db.Column(db.Integer, db.ForeignKey("lecture.id"), nullable=False, index=True)
    position = db.Column(db.Integer, default=0)   # soniya
    done = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, default=_now, index=True)

    lecture = db.relationship("Lecture", backref=db.backref("progress", cascade="all, delete-orphan"))


class StudentAccess(db.Model):
    """O'quvchining ilovaga kirishi: taklif havolasi (xeshi) va sessiyalar versiyasi."""

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False, unique=True)
    token_hash = db.Column(db.String(64), unique=True)
    version = db.Column(db.Integer, nullable=False, default=1)  # oshirilsa — barcha qurilmalardan chiqadi
    created_at = db.Column(db.DateTime, default=_now)
    last_seen = db.Column(db.DateTime)

    member = db.relationship("Member", backref=db.backref("app_access", uselist=False))


class LoginCode(db.Model):
    """Telegram orqali yuborilgan bir martalik kirish kodi."""

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False, index=True)
    code_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    used = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=_now, index=True)


# ── Sun'iy intellekt (core/ai.py): xodimlar uchun Telegram yordamchi va tahlil ─────

class StaffLink(db.Model):
    """Xodimning Telegram chati (kassaga yozish va hisobot uchun). token — bir martalik ulash kodi."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)
    chat_id = db.Column(db.String(32), index=True)
    token = db.Column(db.String(40), unique=True)
    active = db.Column(db.Boolean, nullable=False, default=False)
    linked_at = db.Column(db.DateTime)

    user = db.relationship("User", backref=db.backref("staff_link", uselist=False))


class AiDraft(db.Model):
    """Sun'iy intellekt tayyorlagan, xodim tasdiqlashini kutayotgan kassa yozuvi."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    chat_id = db.Column(db.String(32), default="")
    source = db.Column(db.String(10), default="matn")      # matn | rasm
    request = db.Column(db.Text, default="")               # xodim yozgan matn
    payload = db.Column(db.Text, default="{}")             # tekshirilgan maydonlar (JSON)
    status = db.Column(db.String(10), nullable=False, default="pending")  # pending | saved | cancelled
    transaction_id = db.Column(db.Integer, db.ForeignKey("transaction.id"))
    created_at = db.Column(db.DateTime, default=_now, index=True)

    user = db.relationship("User")


class AiReport(db.Model):
    """Haftalik moliyaviy tahlil (period — masalan 2026-W42; qo'lda so'ralgani — vaqt bilan)."""

    id = db.Column(db.Integer, primary_key=True)
    period = db.Column(db.String(32), unique=True, nullable=False)
    text = db.Column(db.Text, default="")
    data = db.Column(db.Text, default="{}")   # tahlilga berilgan raqamlar (tekshirish uchun)
    created_at = db.Column(db.DateTime, default=_now, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))


class AiUsage(db.Model):
    """Har bir sun'iy intellekt so'rovi: tokenlar va taxminiy narx (xarajat nazorati)."""

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=_now, index=True)
    feature = db.Column(db.String(20), default="")   # kassa | savol | hisobot
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    input_tokens = db.Column(db.Integer, default=0)
    output_tokens = db.Column(db.Integer, default=0)
    cost_usd = db.Column(db.Float, default=0)
    ok = db.Column(db.Boolean, default=True)


# ── Shartnoma tekshiruvi: bilimlar bazasi va natijalar (core/contract.py) ──────

KNOWLEDGE_KINDS = {"qoida": "Qoida / hukm", "standart": "Standart (AAOIFI va b.)", "ustoz": "Ustoz fikri",
                   "misol": "Keys / hikoya", "namuna": "Namuna band", "dars": "Dars materiali"}
KNOWLEDGE_TOPICS = {"umumiy": "Umumiy", "savdo": "Savdo (bay')", "murobaha": "Murobaha", "ijara": "Ijara",
                    "mushoraka": "Mushoraka", "mudoraba": "Mudoraba", "salam": "Salam va istisno'",
                    "qarz": "Qarz, kafolat va garov", "vakolat": "Vakolat (vakola)"}


class KnowledgeDoc(db.Model):
    """Bilimlar bazasidagi bitta material: shartnoma faqat shular asosida tekshiriladi."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(12), nullable=False, default="qoida")
    topic = db.Column(db.String(16), nullable=False, default="umumiy")
    source = db.Column(db.String(200), default="")      # masalan: «AAOIFI 8-standart, 4/1/3» yoki «Ustoz Abdulloh, 3-dars»
    body = db.Column(db.Text, default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=_now)
    updated_at = db.Column(db.DateTime, default=_now)

    @property
    def kind_name(self):
        return KNOWLEDGE_KINDS.get(self.kind, self.kind)

    @property
    def topic_name(self):
        return KNOWLEDGE_TOPICS.get(self.topic, self.topic)


CONTRACT_VERDICTS = {"mos": "Islom moliyasiga mos", "shartli": "Tuzatish bilan mos",
                     "mos_emas": "Mos emas", "aniqlanmadi": "Aniqlab bo'lmadi"}


class ContractCheck(db.Model):
    """Shartnoma tekshiruvi: sun'iy intellekt xulosasi va ustozning yakuniy so'zi."""

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=_now, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))         # xodim yuborgan bo'lsa
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), index=True)  # o'quvchi yuborgan bo'lsa
    title = db.Column(db.String(200), default="")
    source_kind = db.Column(db.String(10), default="matn")             # pdf | rasm | docx | matn
    status = db.Column(db.String(10), nullable=False, default="navbatda")  # navbatda | tayyor | xato
    error = db.Column(db.String(300), default="")
    verdict = db.Column(db.String(12), default="")
    contract_type = db.Column(db.String(80), default="")
    result = db.Column(db.Text, default="{}")
    review_verdict = db.Column(db.String(12), default="")
    review_text = db.Column(db.Text, default="")
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    reviewed_at = db.Column(db.DateTime)

    member = db.relationship("Member")
    user = db.relationship("User", foreign_keys=[user_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

    @property
    def verdict_name(self):
        return CONTRACT_VERDICTS.get(self.review_verdict or self.verdict, "")


TRANSCRIPT_STATUS = {"navbatda": "Navbatda", "audio": "Audio tayyorlanmoqda", "matn": "Matnga aylantirilmoqda",
                     "tayyor": "Tayyor", "xato": "Xato"}


class Transcript(db.Model):
    """Video yoki audio darsning matni (vaqt belgilari bilan) — bilim kartochkalari shundan olinadi."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(255), default="")
    lecture_id = db.Column(db.Integer, db.ForeignKey("lecture.id"), index=True)
    source = db.Column(db.String(10), default="fayl")        # fayl (OpenAI) | srt (tayyor subtitr / matn)
    model = db.Column(db.String(40), default="")
    status = db.Column(db.String(10), nullable=False, default="navbatda")
    error = db.Column(db.String(300), default="")
    duration = db.Column(db.Integer, default=0)               # soniya
    chunks_total = db.Column(db.Integer, default=0)
    chunks_done = db.Column(db.Integer, default=0)
    segments = db.Column(db.Text, default="[]")               # [{"s": 0.0, "e": 240.0, "t": "..."}]
    cost_usd = db.Column(db.Float, default=0)
    cards_status = db.Column(db.String(10), default="")       # "" | navbatda | tayyor | xato
    cards_error = db.Column(db.String(300), default="")
    summary = db.Column(db.Text, default="")
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=_now, index=True)
    finished_at = db.Column(db.DateTime)

    lecture = db.relationship("Lecture")
    user = db.relationship("User")

    @property
    def status_name(self):
        return TRANSCRIPT_STATUS.get(self.status, self.status)


CARD_STATUS = {"taklif": "Ko'rib chiqilmagan", "tasdiq": "Tasdiqlangan", "rad": "Rad etilgan"}


class KnowledgeCard(db.Model):
    """Dars matnidan ajratilgan bilim kartochkasi. Ustoz tasdiqlasa — bilimlar bazasiga (KnowledgeDoc) o'tadi."""

    id = db.Column(db.Integer, primary_key=True)
    transcript_id = db.Column(db.Integer, db.ForeignKey("transcript.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(12), nullable=False, default="ustoz")
    topic = db.Column(db.String(16), nullable=False, default="umumiy")
    body = db.Column(db.Text, default="")
    quote = db.Column(db.Text, default="")                    # darsdan aynan iqtibos
    start = db.Column(db.Integer, default=0)                  # soniya
    end = db.Column(db.Integer, default=0)
    similar_id = db.Column(db.Integer)                        # bazadagi o'xshash material (takror bo'lishi mumkin)
    status = db.Column(db.String(8), nullable=False, default="taklif")
    doc_id = db.Column(db.Integer, db.ForeignKey("knowledge_doc.id"))
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=_now)

    transcript = db.relationship("Transcript", backref=db.backref("cards", order_by="KnowledgeCard.start",
                                                                  cascade="all, delete-orphan"))
    doc = db.relationship("KnowledgeDoc")

    @property
    def kind_name(self):
        return KNOWLEDGE_KINDS.get(self.kind, self.kind)

    @property
    def topic_name(self):
        return KNOWLEDGE_TOPICS.get(self.topic, self.topic)


class KbPassage(db.Model):
    """Dars matnining ~1–2 daqiqalik parchasi: qidiruvda ustozning aynan so'zi sifatida topiladi."""

    id = db.Column(db.Integer, primary_key=True)
    transcript_id = db.Column(db.Integer, db.ForeignKey("transcript.id"), nullable=False, index=True)
    start = db.Column(db.Integer, default=0)
    end = db.Column(db.Integer, default=0)
    approx = db.Column(db.Boolean, nullable=False, default=False)
    text = db.Column(db.Text, nullable=False)

    transcript = db.relationship("Transcript", backref=db.backref("passages", cascade="all, delete-orphan",
                                                                  order_by="KbPassage.start"))


class KbVector(db.Model):
    """Qidiruv indeksi: material yoki dars parchasining ma'no vektori (float32)."""

    __table_args__ = (db.UniqueConstraint("kind", "ref_id"),)
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(8), nullable=False)         # doc | passage
    ref_id = db.Column(db.Integer, nullable=False)
    model = db.Column(db.String(40), nullable=False)
    text_hash = db.Column(db.String(40), nullable=False)
    vec = db.Column(db.LargeBinary, nullable=False)
    updated_at = db.Column(db.DateTime, default=_now)


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
