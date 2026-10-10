"""Boshlang'ich sozlama va (ixtiyoriy) namuna ma'lumot.

    python seed.py            # faqat hisoblar, kategoriyalar, xodimlar (bo'sh baza uchun)
    python seed.py --demo     # + 12 oylik namuna: kurslar, klub, a'zolar, kirim-chiqim
    python seed.py --reset    # bazani tozalab qaytadan (ehtiyot bo'ling!)
"""
import random
import sys
from datetime import date, timedelta

from app import create_app
from core import finance as F
from core import hijri
from core.extensions import db
from core.models import (
    Account, Category, Debt, Enrollment, Member, Program, Transaction, User, ZakatSnapshot,
)

ACCOUNTS = [
    ("Asosiy kassa", "naqd", "UZS", 4_000_000),
    ("Korporativ karta", "karta", "UZS", 6_500_000),
    ("Bank hisobi", "bank", "UZS", 42_000_000),
    ("Payme", "payme", "UZS", 0),
    ("Click", "click", "UZS", 0),
    ("Dollar kassa", "naqd", "USD", 1_200),
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

USERS = [("Rahbar", "rahbar", "100100"), ("Buxgalter", "buxgalter", "200200"), ("Menejer", "menejer", "300300")]

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


def base_setup():
    if Account.query.count() == 0:
        for i, (n, k, c, ob) in enumerate(ACCOUNTS):
            db.session.add(Account(name=n, kind=k, currency=c, opening_balance=ob, sort=i))
    if Category.query.count() == 0:
        for i, (n, k, grp, code, pk) in enumerate(CATEGORIES):
            db.session.add(Category(name=n, kind=k, group=grp, system_code=code, program_kind=pk, sort=i))
    if User.query.count() == 0:
        for n, r, c in USERS:
            u = User(name=n, role=r)
            u.set_code(c)
            db.session.add(u)
    db.session.commit()


def demo(today=None):
    rnd = random.Random(7)
    today = today or date.today()
    acc = {a.name: a for a in Account.query.all()}
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

    F.set_setting("hawl_start", (today - timedelta(days=290)).isoformat())
    F.set_setting("inventory_value", "14000000")
    snap_date = today - timedelta(days=290)
    db.session.add(ZakatSnapshot(date=snap_date, hijri=hijri.format_hijri(snap_date),
                                 cash=96_000_000, receivables=21_000_000, inventory=12_000_000,
                                 liabilities=0, nisob_basis="oltin", nisob_value=85 * 1_150_000,
                                 base=129_000_000, due=3_225_000, note="O'tgan havl hisobi"))
    spend("Zakot", 3_225_000, snap_date + timedelta(days=2), who="Ehtiyojmand oilalar")
    db.session.commit()


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        if "--reset" in sys.argv:
            db.drop_all()
            db.create_all()
        base_setup()
        if "--demo" in sys.argv:
            if Transaction.query.count():
                print("Bazada allaqachon yozuvlar bor — namuna qo'shilmadi (--reset bilan qayta urining).")
            else:
                demo()
                print("Namuna ma'lumot qo'shildi.")
        print("Tayyor. Kirish kodlari: rahbar 100100 · buxgalter 200200 · menejer 300300")
