"""Namuna (test) ma'lumotlar: 12 oylik kurslar, klub, a'zolar, kirim-chiqim, qarz va zakot.

Jamoa dasturni haqiqiy ko'rinishda sinab ko'rishi uchun. Sozlamalar → Ma'lumotlar
bo'limidan yuklanadi va haqiqiy ishdan oldin `clear_data()` bilan tozalanadi.
"""
import random
from datetime import date, timedelta

from core import finance as F
from core import hijri
from core.extensions import db
from core.models import (
    Account, AiDraft, Attendance, Category, ContractCheck, Debt, KnowledgeDoc, Enrollment, Lecture, LectureProgress, Lesson, LoginCode, Member, MemberEvent,
    Module, Notification, Program, Setting, StudentAccess, TelegramLink, Transaction, User, ZakatSnapshot,
)

# Namuna uchun boshlang'ich qoldiqlar
DEMO_OPENING = {"Asosiy kassa": 4_000_000, "Korporativ karta": 6_500_000, "Bank hisobi": 42_000_000,
                "Dollar kassa": 1_200}

FIRST = ["Akmal", "Bekzod", "Dilshod", "Farrux", "Jasur", "Javohir", "Laziz", "Mirzo", "Nodir", "Otabek",
         "Rustam", "Sardor", "Sherzod", "Shoxrux", "Ulug'bek", "Zafar", "Abdulloh", "Sanjar", "Ibrohim",
         "Doniyor", "Madina", "Nigora", "Zarina", "Kamola", "Dildora", "Gulnoza", "Muslima", "Feruza"]
LAST_M = ["Karimov", "Rahimov", "Tursunov", "Abdullayev", "Yusupov", "Ergashev", "Nazarov", "Saidov",
          "Qodirov", "Mirzayev", "Xolmatov", "Ismoilov", "Sobirov", "Hamidov"]
BIZ = ["Qurilish mollari savdosi", "Kiyim do'koni", "Oziq-ovqat ulgurji", "Mebel ishlab chiqarish",
       "Avto ehtiyot qismlar", "Kafe va restoran", "Logistika", "IT xizmatlari", "Go'zallik saloni",
       "Qishloq xo'jaligi", "Tikuv sexi", "Maishiy texnika", "Dorixona", "Ta'lim markazi", "Poligrafiya",
       "Qandolatchilik", "Turizm agentligi", "Ko'chmas mulk"]
CITIES = ["Toshkent", "Toshkent", "Toshkent", "Samarqand", "Namangan", "Andijon", "Farg'ona", "Buxoro", "Qarshi"]


def demo(today=None):
    rnd = random.Random(7)
    today = today or date.today()
    acc = {a.name: a for a in Account.query.all()}
    for name, ob in DEMO_OPENING.items():
        if name in acc:
            acc[name].opening_balance = ob
    cat = {c.name: c for c in Category.query.all()}
    admin = User.query.filter_by(role="rahbar").first()
    start = F.shift_month(today.replace(day=1), -11)

    def day_in(m_start, lo=1, hi=28):
        d = m_start.replace(day=rnd.randint(lo, hi))
        return min(d, today)

    def pay_acc():
        return acc[rnd.choices(["Payme", "Click", "Korporativ karta", "Bank hisobi", "Asosiy kassa"],
                               [30, 20, 25, 15, 10])[0]]

    def spend(name, amount, d, account="Bank hisobi", program=None, who="", note=""):
        F.record("chiqim", amount, acc[account], date=d, category_id=cat[name].id,
                 program_id=program.id if program else None, counterparty=who, note=note,
                 created_by=admin.id)

    # ── Dasturlar ──
    p4 = Program(name="Halol tijorat asoslari — 4-potok", kind="kurs", price=3_900_000,
                 start_date=start + timedelta(days=10), end_date=start + timedelta(days=70),
                 capacity=35, status="yakunlangan",
                 description="Tijoratda halol va harom, bitimlar fiqhi, narx belgilash odobi.")
    p5 = Program(name="Halol tijorat asoslari — 5-potok", kind="kurs", price=4_400_000,
                 start_date=F.shift_month(start, 4) + timedelta(days=5),
                 end_date=F.shift_month(start, 6) + timedelta(days=10), capacity=40, status="yakunlangan")
    p6 = Program(name="Halol tijorat asoslari — 6-potok", kind="kurs", price=4_900_000,
                 start_date=F.shift_month(today.replace(day=1), -1) + timedelta(days=14),
                 capacity=40, status="faol",
                 description="Yangi potok: amaliy keyslar va mentorlik guruhlari bilan.")
    mur = Program(name="Murobaha va sheriklik amaliyoti", kind="kurs", price=390, currency="USD",
                  start_date=F.shift_month(today.replace(day=1), -2) + timedelta(days=3), capacity=20,
                  status="faol", description="Murobaha, mushoraka, mudoraba shartnomalarini tuzish amaliyoti.")
    club = Program(name="Biznes egalari klubi", kind="klub", billing="oylik", price=1_500_000,
                   start_date=start, capacity=60, status="faol",
                   description="Har oy mastermind, ekspert uchrashuvi va yopiq chat.")
    forum = Program(name="Tijorat odobi forumi", kind="tadbir", price=650_000,
                    start_date=F.shift_month(today.replace(day=1), -3) + timedelta(days=19),
                    capacity=300, status="yakunlangan")
    cons = Program(name="Shaxsiy konsalting", kind="konsalting", price=5_000_000, status="faol",
                   description="Biznesni shariatga moslashtirish bo'yicha individual audit.")
    nxt = Program(name="Halol tijorat asoslari — 7-potok", kind="kurs", price=5_200_000,
                  start_date=F.shift_month(today.replace(day=1), 1) + timedelta(days=9), capacity=40,
                  status="rejada")
    progs = [p4, p5, p6, mur, club, forum, cons, nxt]
    db.session.add_all(progs)
    db.session.flush()

    # ── A'zolar ──
    members = []
    used = set()
    while len(members) < 46:
        f, l = rnd.choice(FIRST), rnd.choice(LAST_M)
        if f in ("Madina", "Nigora", "Zarina", "Kamola", "Dildora", "Gulnoza", "Muslima", "Feruza"):
            l = l + "a"
        if (f, l) in used:
            continue
        used.add((f, l))
        m = Member(full_name=f"{f} {l}", phone=f"+998 9{rnd.randint(0, 9)} {rnd.randint(100, 999)} "
                                                 f"{rnd.randint(10, 99)} {rnd.randint(10, 99)}",
                   business=rnd.choice(BIZ), city=rnd.choice(CITIES))
        members.append(m)
    db.session.add_all(members)
    db.session.flush()

    def enroll(program, member, joined, price=None, paid_share=1.0, parts=1, status="faol"):
        e = Enrollment(member_id=member.id, program_id=program.id, price=price or program.price,
                       joined_at=joined, status=status)
        db.session.add(e)
        db.session.flush()
        total = e.price if program.currency == "UZS" else e.price
        to_pay = round(total * paid_share, -3 if program.currency == "UZS" else 0)
        c = cat["Kurs to'lovlari"] if program.kind == "kurs" else (
            cat["Tadbir chiptalari"] if program.kind == "tadbir" else cat["Konsalting"])
        step = round(to_pay / parts, -3 if program.currency == "UZS" else 0)
        for i in range(parts):
            # oxirgi qism — qoldiq, shunda to'liq to'laganlarda 1 000 so'm "qarz" qolmaydi
            amt = step if i < parts - 1 else to_pay - step * (parts - 1)
            if amt <= 0:
                continue
            d = min(joined + timedelta(days=i * 21), today)
            a = acc["Dollar kassa"] if program.currency == "USD" else pay_acc()
            F.record("kirim", amt, a, date=d, category_id=c.id, program_id=program.id,
                     enrollment_id=e.id, counterparty=member.full_name, aqd="xizmat",
                     note=f"{i + 1}-qism" if parts > 1 else "", created_by=admin.id)
        return e

    pool = members[:]
    rnd.shuffle(pool)
    for m in pool[:31]:
        enroll(p4, m, p4.start_date - timedelta(days=rnd.randint(1, 12)), status="tugatgan",
               price=p4.price - rnd.choice([0, 0, 0, 400_000]))
    for m in pool[8:44]:
        share = 1.0 if rnd.random() > 0.12 else 0.5
        enroll(p5, m, p5.start_date - timedelta(days=rnd.randint(1, 14)), paid_share=share,
               parts=rnd.choice([1, 1, 2]), status="tugatgan")
    for m in pool[14:46]:
        r = rnd.random()
        share = 1.0 if r > 0.45 else (0.5 if r > 0.15 else 0.3)
        enroll(p6, m, p6.start_date - timedelta(days=rnd.randint(0, 16)), paid_share=share,
               parts=rnd.choice([1, 2, 2, 3]))
    for m in pool[2:16]:
        enroll(mur, m, mur.start_date - timedelta(days=rnd.randint(0, 9)),
               paid_share=1.0 if rnd.random() > 0.2 else 0.5)
    for m in pool[:44]:
        if rnd.random() < 0.55:
            enroll(forum, m, forum.start_date - timedelta(days=rnd.randint(2, 25)))
    for m in pool[30:34]:
        enroll(cons, m, F.shift_month(today.replace(day=1), -rnd.randint(1, 7)) + timedelta(days=rnd.randint(1, 20)),
               price=rnd.choice([5_000_000, 7_500_000]), parts=2)

    # Klub: har oy obuna, ba'zilar kechikadi
    for i, m in enumerate(pool[:26]):
        joined = F.shift_month(start, rnd.randint(0, 9)) + timedelta(days=rnd.randint(0, 20))
        e = Enrollment(member_id=m.id, program_id=club.id, price=0, joined_at=joined)
        db.session.add(e)
        db.session.flush()
        d = joined
        paid_through = True
        while d <= today:
            e.price += club.price
            if paid_through and (d < today - timedelta(days=20) or rnd.random() > 0.3):
                F.record("kirim", club.price, pay_acc(), date=d, category_id=cat["Klub a'zoligi"].id,
                         program_id=club.id, enrollment_id=e.id, counterparty=m.full_name, aqd="xizmat",
                         note=f"{F.MONTHS_FULL[d.month - 1]} obunasi", created_by=admin.id)
            else:
                paid_through = False
            d = F.shift_month(d.replace(day=1), 1).replace(day=min(joined.day, 28))
        e.valid_until = d - timedelta(days=1)
        if i in (3, 11):
            e.status = "chiqqan"
            e.price -= club.price  # chiqqan oyi hisoblanmaydi

    # ── Oylik xarajatlar ──
    for i in range(12):
        m0 = F.shift_month(start, i)
        if m0 > today:
            break
        last = 28 if m0.month != today.month or m0.year != today.year else min(today.day, 28)
        spend("Ofis ijarasi", 7_500_000, m0.replace(day=min(3, last)), who="Ijara beruvchi")
        if m0.replace(day=min(5, last)) <= today:
            spend("Xodimlar oyligi", 18_500_000, m0.replace(day=min(5, last)), who="Jamoa (5 kishi)")
        spend("Servislar va dasturlar", rnd.choice([850_000, 920_000, 1_100_000]), day_in(m0, 1, last),
              account="Korporativ karta", who="Zoom, Canva, Telegram Premium")
        spend("Kontent va video", rnd.choice([2_500_000, 3_200_000, 4_000_000]), day_in(m0, 1, last),
              account="Korporativ karta", who="Videograf")
        spend("Soliq va majburiy to'lovlar", rnd.choice([3_800_000, 4_400_000, 5_100_000]),
              m0.replace(day=min(20, last)) if m0.replace(day=min(20, last)) <= today else today)
        spend("Bank xizmatlari", rnd.choice([120_000, 160_000, 210_000]), day_in(m0, 1, last))
        if rnd.random() > 0.4:
            F.record("kirim", rnd.choice([1_800_000, 2_400_000, 3_100_000]), acc["Asosiy kassa"],
                     date=day_in(m0, 1, last), category_id=cat["Kitob va mahsulot savdosi"].id,
                     counterparty="Kitob savdosi", aqd="savdo", note="«Halol tijorat» kitobi",
                     created_by=admin.id)

    # Dastur xarajatlari: reklama, mentor, zal
    for p, ads, mentor in ((p4, 14_000_000, 22_000_000), (p5, 17_500_000, 26_000_000),
                           (p6, 19_000_000, 12_000_000)):
        for k in range(3):
            d = min(p.start_date - timedelta(days=24 - k * 8), today)
            spend("Reklama (Instagram, Telegram)", round(ads / 3, -5), d, account="Korporativ karta", program=p,
                  who="Meta Ads", note="Target reklama")
        spend("Mentorlar haqi", mentor, min(p.start_date + timedelta(days=30), today), program=p,
              who="Mentorlar jamoasi")
    spend("Reklama (Instagram, Telegram)", 4_200_000, mur.start_date - timedelta(days=10),
          account="Korporativ karta", program=mur, who="Meta Ads")
    spend("Mentorlar haqi", 9_000_000, min(mur.start_date + timedelta(days=25), today), program=mur,
          who="Ekspert-murabbiy")
    spend("Zal ijarasi", 24_000_000, forum.start_date - timedelta(days=12), program=forum,
          who="Tadbir zali")
    spend("Kofe-breyk va tashkiliy", 11_500_000, forum.start_date, program=forum, who="Ketering xizmati")
    spend("Reklama (Instagram, Telegram)", 9_000_000, forum.start_date - timedelta(days=20),
          account="Korporativ karta", program=forum, who="Meta Ads")
    for i in range(0, 12, 1):
        m0 = F.shift_month(start, i)
        if m0 > today:
            break
        spend("Kofe-breyk va tashkiliy", 2_200_000, min(m0.replace(day=15), today), program=club,
              who="Klub uchrashuvi")
    spend("Kitob xaridi", 9_600_000, start + timedelta(days=40), account="Bank hisobi", who="Nashriyot")

    # O'tkazmalar: Payme/Click va ortiqcha naqd → bank (inkassatsiya)
    bal = F.account_balances()
    for name, keep in (("Payme", 0.1), ("Click", 0.1), ("Asosiy kassa", 0.12)):
        a = acc[name]
        amount = round(bal[a.id] * (1 - keep), -3)
        if amount > 0:
            F.record("otkazma", amount, a, date=today - timedelta(days=6), to_account_id=acc["Bank hisobi"].id,
                     to_amount=amount, note="Bankka yechib olindi", created_by=admin.id)

    # Shubhali tushum: bank qoldig'iga hisoblangan foiz
    F.record("kirim", 386_000, acc["Bank hisobi"], date=F.shift_month(today.replace(day=1), -2) + timedelta(days=1),
             category_id=cat["Boshqa kirim"].id, counterparty="Bank", aqd="boshqa", shariat="nohalol",
             note="Hisob qoldig'iga foiz hisoblangan", created_by=admin.id)
    F.record("kirim", 1_250_000, acc["Asosiy kassa"], date=today - timedelta(days=17),
             category_id=cat["Boshqa kirim"].id, counterparty="Noma'lum o'tkazma", aqd="boshqa",
             shariat="shubhali", note="Manbasi aniqlanmoqda", created_by=admin.id)
    spend("Tozalash (nohalol tushumdan)", 386_000, today - timedelta(days=40), who="Mehribonlik uyi")
    for k in range(5):
        spend("Sadaqa va xayriya", rnd.choice([1_000_000, 1_500_000, 2_000_000]),
              F.shift_month(today.replace(day=1), -2 * k) + timedelta(days=4), who="Xayriya jamg'armasi")

    # Qarz daftari
    d1 = Debt(direction="berilgan", counterparty="Akmal Karimov (klub a'zosi)", amount=15_000_000,
              date=today - timedelta(days=95), due_date=today - timedelta(days=5), witness="Sardor Nazarov",
              note="Qarzi hasan — do'kon aylanma mablag'i uchun, 3 oyda qaytaradi")
    d2 = Debt(direction="olingan", counterparty="Hamkor ta'sischi", amount=40_000_000,
              date=today - timedelta(days=150), due_date=today + timedelta(days=60),
              note="Forum va 6-potok reklamasi uchun foizsiz qarz")
    d3 = Debt(direction="berilgan", counterparty="Xodim: videograf", amount=3_000_000,
              date=today - timedelta(days=30), due_date=today + timedelta(days=30), witness="Buxgalter")
    db.session.add_all([d1, d2, d3])
    db.session.flush()
    F.record("qarz_chiqim", d1.amount, acc["Bank hisobi"], date=d1.date, debt_id=d1.id,
             counterparty=d1.counterparty, note="Qarz berildi", created_by=admin.id)
    F.record("qarz_kirim", 5_000_000, acc["Korporativ karta"], date=d1.date + timedelta(days=35),
             debt_id=d1.id, counterparty=d1.counterparty, note="Qarz qaytarildi", created_by=admin.id)
    F.record("qarz_kirim", d2.amount, acc["Bank hisobi"], date=d2.date, debt_id=d2.id,
             counterparty=d2.counterparty, note="Qarz olindi", created_by=admin.id)
    F.record("qarz_chiqim", 10_000_000, acc["Bank hisobi"], date=d2.date + timedelta(days=60),
             debt_id=d2.id, counterparty=d2.counterparty, note="Qarz qaytarildi", created_by=admin.id)
    F.record("qarz_chiqim", d3.amount, acc["Asosiy kassa"], date=d3.date, debt_id=d3.id,
             counterparty=d3.counterparty, note="Qarz berildi", created_by=admin.id)

    # ── Dars jadvali (kalendar) ──
    demo_lessons(today, admin, p6=p6, mur=mur, club=club, cons=cons, nxt=nxt)
    demo_curriculum(today, p6=p6, mur=mur)
    from core import demo_knowledge
    demo_knowledge.seed(db, KnowledgeDoc, admin.id)

    F.set_setting("hawl_start", (today - timedelta(days=290)).isoformat())
    F.set_setting("inventory_value", "14000000")
    snap_date = today - timedelta(days=290)
    db.session.add(ZakatSnapshot(date=snap_date, hijri=hijri.format_hijri(snap_date),
                                 cash=96_000_000, receivables=21_000_000, inventory=12_000_000,
                                 liabilities=0, nisob_basis="oltin", nisob_value=85 * 1_150_000,
                                 base=129_000_000, due=3_225_000, note="O'tgan havl hisobi"))
    spend("Zakot", 3_225_000, snap_date + timedelta(days=2), who="Ehtiyojmand oilalar")
    db.session.commit()


TOPICS = ["Kirish: halol savdo asoslari", "Bitim turlari va shartlari", "Riba va uning shakllari",
          "Narx belgilash odobi", "Murobaha", "Ijara", "Salam va istisno", "Mushoraka", "Mudoraba",
          "Qarz va kafolat", "Zakot va biznes", "Amaliy keys: savdo", "Amaliy keys: ishlab chiqarish",
          "Marketing va halollik", "Soliq va shariat", "Yakuniy taqdimot"]


def demo_lessons(today, admin, p6, mur, club, cons, nxt):
    """Namuna darslar: kurslar haftada 2 marta, klub — ikki haftada shanba, konsalting — juma."""
    import uuid
    from datetime import time

    from core.calendar import expand_weekly

    def series(program, start, weekdays, count, t0, t1, place, teacher, topics=None, every=1):
        sid = uuid.uuid4().hex
        days = expand_weekly(start, weekdays, count=count * every)
        if every > 1:
            days = [d for d in days if ((d - days[0]).days // 7) % every == 0][:count]
        for i, d in enumerate(days):
            title = f"{i + 1}-dars: {topics[i % len(topics)]}" if topics else program.name.split(" — ")[0]
            status = "otdi" if d < today else "rejada"
            db.session.add(Lesson(program_id=program.id, title=title, date=d, start=time(*t0), end=time(*t1),
                                  location=place, teacher=teacher, status=status, series_id=sid,
                                  created_by=admin.id))

    series(p6, p6.start_date, [1, 3], 16, (19, 0), (21, 0), "Asosiy zal", "Ustoz Abdulloh", TOPICS)
    series(mur, mur.start_date, [0, 2], 14, (18, 30), (20, 30), "Kichik zal", "Ustoz Sardor",
           ["Murobaha shartnomasi", "Mushoraka", "Mudoraba", "Hujjatlar", "Amaliyot"])
    sat = today - timedelta(days=(today.weekday() - 5) % 7) - timedelta(weeks=8)
    series(club, sat, [5], 10, (10, 0), (13, 0), "Konferens zal", "Rahbar",
           ["Mastermind", "Ekspert uchrashuvi", "Biznes nonushta"], every=2)
    fri = today - timedelta(days=(today.weekday() - 4) % 7) - timedelta(weeks=3)
    series(cons, fri, [4], 8, (15, 0), (16, 30), "Ofis, 2-xona", "Rahbar", ["Individual audit"])
    if nxt.start_date:
        series(nxt, nxt.start_date, [1, 3], 16, (19, 0), (21, 0), "Asosiy zal", "Ustoz Abdulloh", TOPICS)
    # bugun ham bitta uchrashuv bo'lsin — kalendar jonli ko'rinsin
    db.session.add(Lesson(program_id=club.id, title="Mehmon spiker: eksport", date=today, start=time(16, 0),
                          end=time(17, 30), location="Konferens zal", teacher="Mehmon ekspert",
                          created_by=admin.id))
    db.session.add(Lesson(program_id=cons.id, title="Individual audit: savdo", date=today, start=time(10, 0),
                          end=time(11, 30), location="Ofis, 2-xona", teacher="Rahbar", created_by=admin.id))
    db.session.flush()

    # O'tgan darslar uchun davomat (asosan kelgan, ozgina kechikkan/kelmagan)
    rnd = random.Random(11)
    from datetime import datetime as _dt
    for les in Lesson.query.filter(Lesson.date < today, Lesson.status == "otdi").all():
        for e in Enrollment.query.filter(Enrollment.program_id == les.program_id, Enrollment.status != "chiqqan").all():
            if e.joined_at and e.joined_at > les.date:
                continue
            x = rnd.random()
            st = "keldi" if x < .80 else ("kechikdi" if x < .88 else ("kelmadi" if x < .96 else "sababli"))
            mins = rnd.randint(-15, 4) if st == "keldi" else rnd.randint(11, 35)
            at = _dt.combine(les.date, les.start) + timedelta(minutes=mins) - timedelta(hours=5)  # UTC
            db.session.add(Attendance(lesson_id=les.id, member_id=e.member_id, status=st,
                                      method="skaner" if st in ("keldi", "kechikdi") and x < .7 else "qolda",
                                      marked_at=at, marked_by=admin.id))


CURRICULUM = [
    ("1-modul. Halol savdo asoslari", [
        ("Kurs bilan tanishuv: nima o'rganamiz", "video", 9, True),
        ("Halol va harom: savdoda asosiy tamoyillar", "video", 24, False),
        ("Bitim (aqd) rukunlari va shartlari", "video", 31, False),
        ("Qo'llanma: savdo shartnomasi namunasi", "matn", 0, False),
    ]),
    ("2-modul. Riba va undan saqlanish", [
        ("Riba nima va nega taqiqlangan", "video", 27, False),
        ("Bank krediti, nasiya va bo'lib to'lash", "video", 34, False),
        ("Amaliy mashq: shartnomani tekshirish", "matn", 0, False),
    ]),
    ("3-modul. Islomiy moliya mahsulotlari", [
        ("Murobaha: ustama bilan sotish", "video", 29, False),
        ("Ijara va ijara-vaqtincha egalik", "video", 26, False),
        ("Mushoraka va mudoraba: sheriklik", "video", 38, False),
        ("Zakot va biznes: hisoblash amaliyoti", "video", 33, False),
    ]),
]

DEMO_BODY = {
    "matn": ("Ushbu qo'llanmada darsda ko'rilgan mavzu bo'yicha amaliy namuna berilgan.\n\n"
             "1. Tomonlar: sotuvchi va xaridor kimligi, ularning roziligi aniq yozilsin.\n"
             "2. Mahsulot: nomi, miqdori, sifati va topshirish muddati.\n"
             "3. Narx: aniq summa, to'lov muddati. Kechikish uchun foiz (jarima-riba) qo'yilmaydi.\n\n"
             "Savollaringizni keyingi darsda ustozga bering yoki guruhda yozing."),
    "video": ("Darsdan keyin o'zingizga savol bering: bu qoida mening biznesimda qanday qo'llanadi? "
              "Javobingizni daftaringizga yozib qo'ying — keyingi darsda muhokama qilamiz."),
}


def demo_curriculum(today, p6, mur):
    """Namuna o'quv dasturi: bo'limlar, mavzular va o'quvchilar progressi (video fayllarsiz)."""
    from datetime import datetime as _dt
    rnd = random.Random(5)
    for program, mods in ((p6, CURRICULUM), (mur, CURRICULUM[2:] + CURRICULUM[:1])):
        lectures = []
        for mi, (mtitle, items) in enumerate(mods):
            mod = Module(program_id=program.id, title=mtitle, position=mi)
            db.session.add(mod)
            db.session.flush()
            for li, (title, kind, mins, free) in enumerate(items):
                lec = Lecture(module_id=mod.id, title=title, kind=kind, duration=mins * 60, position=li,
                              free=free, body=DEMO_BODY[kind])
                db.session.add(lec)
                lectures.append(lec)
        db.session.flush()
        for e in Enrollment.query.filter(Enrollment.program_id == program.id, Enrollment.status != "chiqqan").all():
            upto = rnd.randint(0, len(lectures))
            for i, lec in enumerate(lectures[:upto + 1]):
                done = i < upto
                if i == upto and i < len(lectures):
                    pos = rnd.randint(60, max(lec.duration // 2, 61)) if lec.duration else 0
                else:
                    pos = lec.duration
                db.session.add(LectureProgress(member_id=e.member_id, lecture_id=lec.id, position=pos, done=done,
                                               updated_at=_dt.combine(today, _dt.min.time()) - timedelta(days=len(lectures) - i)))


def has_records():
    return bool(Transaction.query.first() or Program.query.first() or Member.query.first()
                or Debt.query.first())


def load_demo():
    """Bo'sh bazaga namuna yuklaydi. Yozuvlar bor bo'lsa — hech narsa qilmaydi."""
    if has_records():
        return False
    demo()
    F.set_setting("demo_loaded", "1")
    db.session.commit()
    return True


def clear_data():
    """Barcha moliyaviy yozuvlarni o'chiradi. Xodimlar, hisoblar, kategoriyalar va
    sozlamalar (kurs, nisob narxi) saqlanib qoladi; hisoblar qoldig'i nolga tushadi."""
    AiDraft.query.delete()
    ContractCheck.query.delete()
    from core import demo_knowledge
    from core.models import KnowledgeCard, Transcript
    demo_ids = [d.id for d in KnowledgeDoc.query.filter_by(source=demo_knowledge.SRC).all()]
    if demo_ids:
        KnowledgeCard.query.filter(KnowledgeCard.doc_id.in_(demo_ids)).update({"doc_id": None}, synchronize_session=False)
    KnowledgeDoc.query.filter_by(source=demo_knowledge.SRC).delete()
    Transcript.query.update({"lecture_id": None})  # dars matnlari (pullik ish) saqlanadi, faqat mavzudan uziladi
    Transaction.query.delete()
    LectureProgress.query.delete()
    Lecture.query.delete()
    Module.query.delete()
    StudentAccess.query.delete()
    LoginCode.query.delete()
    Notification.query.delete()
    TelegramLink.query.delete()
    Attendance.query.delete()
    Lesson.query.delete()
    MemberEvent.query.delete()
    Enrollment.query.delete()
    Member.query.delete()
    Program.query.delete()
    Debt.query.delete()
    ZakatSnapshot.query.delete()
    for acc in Account.query.all():
        acc.opening_balance = 0
    for key in ("hawl_start", "demo_loaded"):
        row = db.session.get(Setting, key)
        if row:
            db.session.delete(row)
    F.set_setting("inventory_value", "0")
    db.session.commit()
