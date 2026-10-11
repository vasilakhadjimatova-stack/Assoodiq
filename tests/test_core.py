from datetime import date, timedelta

import pytest

from app import create_app
from config import TestConfig
from core import finance as F
from core import hijri
from core.extensions import db
from core.models import Account, Category, Debt, Enrollment, Member, Program, Transaction, User
from core.bootstrap import base_setup
from seed import DEMO_USERS


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        base_setup(users=DEMO_USERS)
        yield app
        db.session.remove()
        db.drop_all()


def login(client, code):
    return client.post("/kirish", data={"code": code})


def acc(name):
    return Account.query.filter_by(name=name).one()


def cat(name):
    return Category.query.filter_by(name=name).one()


# ── Hijriy taqvim ──

def test_hijri_roundtrip():
    d = date(2024, 1, 1)
    for _ in range(800):
        assert hijri.from_hijri(*hijri.to_hijri(d)) == d
        d += timedelta(days=3)


def test_hijri_known_date():
    # 1 Ramazon 1445 ≈ 11 mart 2024 (jadval usuli ±1 kun)
    assert abs((hijri.from_hijri(1445, 9, 1) - date(2024, 3, 11)).days) <= 1


def test_next_hawl_is_one_lunar_year():
    start = date(2025, 3, 1)
    nxt = hijri.next_hawl(start, today=start + timedelta(days=1))
    assert 353 <= (nxt - start).days <= 356


# ── Zakot ──

def test_zakat_below_nisob_is_zero():
    r = F.zakat_compute(cash=50_000_000, receivables=0, inventory=0, other_assets=0,
                        liabilities=0, nisob=100_000_000)
    assert r["due"] == 0 and not r["reached"]


def test_zakat_deducts_liabilities_and_takes_quarter_tenth():
    r = F.zakat_compute(cash=200_000_000, receivables=40_000_000, inventory=10_000_000,
                        other_assets=0, liabilities=50_000_000, nisob=100_000_000)
    assert r["base"] == 200_000_000
    assert r["due"] == 5_000_000


def test_zakat_defaults_exclude_purification_fund(app):
    F.record("kirim", 1_000_000, acc("Asosiy kassa"), category_id=cat("Boshqa kirim").id, shariat="nohalol")
    db.session.commit()
    d = F.zakat_defaults()
    assert d["cash"] == F.total_balance_uzs() - 1_000_000


# ── Daftar va balans ──

def test_balances_and_pnl_ignore_transfers_and_debts(app):
    kassa, bank, usd = acc("Asosiy kassa"), acc("Bank hisobi"), acc("Dollar kassa")
    start_kassa = F.account_balances()[kassa.id]
    F.record("kirim", 5_000_000, kassa, category_id=cat("Kurs to'lovlari").id)
    F.record("chiqim", 1_000_000, kassa, category_id=cat("Ofis ijarasi").id)
    F.record("otkazma", 2_000_000, kassa, to_account_id=bank.id, to_amount=2_000_000)
    F.record("qarz_chiqim", 500_000, kassa)
    F.record("kirim", 100, usd, category_id=cat("Konsalting").id)
    db.session.commit()

    bal = F.account_balances()
    assert bal[kassa.id] == start_kassa + 5_000_000 - 1_000_000 - 2_000_000 - 500_000
    t = F.period_totals(date.today() - timedelta(days=1), date.today())
    assert t["income"] == 5_000_000 + 100 * F.usd_rate()
    assert t["expense"] == 1_000_000


def test_amount_uzs_frozen_at_record_rate(app):
    F.set_setting("usd_rate", "12000")
    tx = F.record("kirim", 100, acc("Dollar kassa"), category_id=cat("Konsalting").id)
    db.session.commit()
    F.set_setting("usd_rate", "13000")
    db.session.commit()
    assert tx.amount_uzs == 1_200_000


def test_parse_money_handles_spaces_and_commas():
    assert F.parse_money("1 500 000") == 1_500_000
    assert F.parse_money("1 250,5") == 1250.5
    assert F.parse_money("abc") == 0


# ── Dasturlar ──

def test_enrollment_due_and_program_profit(app):
    p = Program(name="Kurs", kind="kurs", price=4_000_000)
    m = Member(full_name="Test A'zo")
    db.session.add_all([p, m])
    db.session.flush()
    e = Enrollment(member_id=m.id, program_id=p.id, price=4_000_000)
    db.session.add(e)
    db.session.flush()
    F.record("kirim", 1_500_000, acc("Payme"), enrollment_id=e.id, program_id=p.id,
             category_id=cat("Kurs to'lovlari").id)
    F.record("chiqim", 600_000, acc("Korporativ karta"), program_id=p.id,
             category_id=cat("Reklama (Instagram, Telegram)").id)
    db.session.commit()
    assert F.enrollment_row(e)["due"] == 2_500_000
    s = F.program_stats(p)
    assert s["profit"] == 900_000
    assert s["cac"] == 600_000


def test_club_renew_extends_period_and_bills(app):
    client = app.test_client()
    login(client, "100100")
    p = Program(name="Klub", kind="klub", billing="oylik", price=1_000_000)
    m = Member(full_name="Klub a'zosi")
    db.session.add_all([p, m])
    db.session.commit()
    client.post(f"/dasturlar/{p.id}/yozish", data={"member_id": m.id, "joined_at": date.today().isoformat()})
    e = Enrollment.query.one()
    first_until = e.valid_until
    client.post(f"/yozilish/{e.id}/uzaytirish")
    db.session.refresh(e)
    assert e.price == 2_000_000
    assert 27 <= (e.valid_until - first_until).days <= 31


# ── Qarz daftari ──

def test_debt_repayment_closes_debt(app):
    client = app.test_client()
    login(client, "100100")
    bank = acc("Bank hisobi")
    client.post("/qarz/yangi", data={"direction": "berilgan", "counterparty": "Hamkor",
                                     "amount": "3 000 000", "account_id": bank.id})
    d = Debt.query.one()
    assert F.debt_remaining(d) == 3_000_000
    client.post(f"/qarz/{d.id}/qaytarish", data={"amount": "1 000 000", "account_id": bank.id})
    assert not db.session.get(Debt, d.id).closed
    client.post(f"/qarz/{d.id}/qaytarish", data={"amount": "2 000 000", "account_id": bank.id})
    d = db.session.get(Debt, d.id)
    assert d.closed and F.debt_remaining(d) == 0
    # qarz foyda-zararga kirmaydi
    assert F.period_totals(date.today(), date.today())["income"] == 0


# ── Halollik ──

def test_purification_fund(app):
    F.record("kirim", 400_000, acc("Bank hisobi"), category_id=cat("Boshqa kirim").id, shariat="nohalol")
    F.record("chiqim", 150_000, acc("Bank hisobi"), category_id=F.system_category("tozalash").id)
    db.session.commit()
    assert F.purification_fund() == {"flagged": 400_000, "paid": 150_000, "remaining": 250_000}


# ── Kirish va rollar ──

def test_login_required_and_wrong_code(app):
    client = app.test_client()
    assert client.get("/").status_code == 302
    r = login(client, "999999")
    assert "noto" in r.get_data(as_text=True)


def test_login_rate_limited(app):
    from views import auth
    auth._fails.clear()
    client = app.test_client()
    for _ in range(auth.MAX_FAILS):
        login(client, "000000")
    r = login(client, "100100")  # to'g'ri kod ham bloklanadi
    assert r.status_code == 200 and "Juda ko" in r.get_data(as_text=True)
    auth._fails.clear()


def test_manager_permissions(app):
    client = app.test_client()
    login(client, "300300")
    assert client.get("/zakot").status_code == 302
    assert client.get("/dasturlar").status_code == 200
    r = client.post("/kassa/yangi", data={"kind": "chiqim", "amount": "1000", "account_id": acc("Asosiy kassa").id})
    assert r.status_code == 302
    assert Transaction.query.count() == 0


def test_all_pages_render_with_demo_data(app):
    from seed import demo
    demo()
    client = app.test_client()
    login(client, "100100")
    pid, mid, did = Program.query.first().id, Member.query.first().id, Debt.query.first().id
    for url in ["/", "/kassa/", "/kassa/?tur=qarz", "/dasturlar", f"/dasturlar/{pid}", "/azolar",
                f"/azolar/{mid}", "/qarz/", f"/qarz/{did}", "/zakot", "/halollik", "/hisobot/",
                "/hisobot/excel", "/sozlamalar/", "/sozlamalar/?bolim=xodimlar"]:
        assert client.get(url).status_code == 200, url


def test_new_user_code_shown_once_and_works(app):
    client = app.test_client()
    login(client, "100100")
    r = client.post("/sozlamalar/xodim", data={"name": "Yangi menejer", "role": "menejer"}, follow_redirects=True)
    text = r.get_data(as_text=True)
    import re
    code = re.search(r"Kirish kodi: (\d{6})", text).group(1)
    u = User.query.filter_by(name="Yangi menejer").one()
    assert u.check_code(code)


def test_first_run_creates_single_admin_from_env(monkeypatch):
    monkeypatch.setenv("ADMIN_CODE", "482915")
    app = create_app(TestConfig)
    with app.app_context():
        base_setup()
        users = User.query.all()
        assert [(u.role, u.check_code("482915")) for u in users] == [("rahbar", True)]
        assert Account.query.count() and Category.query.filter_by(system_code="zakot").count() == 1
        base_setup()  # qayta chaqirish hech narsani takrorlamaydi
        assert User.query.count() == 1
        db.drop_all()


def test_secret_key_persisted_in_db():
    from core.bootstrap import secret_key
    app = create_app(TestConfig)
    with app.app_context():
        k1 = secret_key()
        assert len(k1) == 64 and secret_key() == k1
        db.drop_all()


# ── Test rejimi: namuna yuklash va tozalash ──

def test_demo_load_and_clear(app):
    client = app.test_client()
    login(client, "100100")
    client.post("/sozlamalar/namuna")
    assert Transaction.query.count() > 100 and Program.query.count() == 8
    assert F.get_setting("demo_loaded") == "1"
    assert "Test rejimi" in client.get("/").get_data(as_text=True)

    before = Transaction.query.count()
    r = client.post("/sozlamalar/namuna", follow_redirects=True)  # ikkinchi marta yuklanmaydi
    assert Transaction.query.count() == before and "allaqachon" in r.get_data(as_text=True)

    client.post("/sozlamalar/tozalash", data={"tasdiq": "xato"})  # tasdiqsiz o'chmaydi
    assert Transaction.query.count() == before

    users, cats = User.query.count(), Category.query.count()
    client.post("/sozlamalar/tozalash", data={"tasdiq": "TOZALASH"})
    assert Transaction.query.count() == Program.query.count() == Member.query.count() == Debt.query.count() == 0
    assert User.query.count() == users and Category.query.count() == cats
    assert F.total_balance_uzs() == 0
    assert "Test rejimi" not in client.get("/").get_data(as_text=True)


def test_demo_controls_only_for_rahbar(app):
    client = app.test_client()
    login(client, "200200")  # buxgalter
    assert client.post("/sozlamalar/namuna").status_code == 403
    assert client.post("/sozlamalar/tozalash", data={"tasdiq": "TOZALASH"}).status_code == 403
    assert Transaction.query.count() == 0


# ── Audit: tuzatishlar va yangi imkoniyatlar ──

def test_pnl_excludes_non_halal_income_and_purification(app):
    F.record("kirim", 1_000_000, acc("Bank hisobi"), category_id=cat("Kurs to'lovlari").id)
    F.record("kirim", 300_000, acc("Bank hisobi"), category_id=cat("Boshqa kirim").id, shariat="nohalol")
    F.record("chiqim", 300_000, acc("Bank hisobi"), category_id=F.system_category("tozalash").id)
    db.session.commit()
    t = F.period_totals(date.today(), date.today())
    assert t == {"income": 1_000_000, "expense": 0, "profit": 1_000_000}
    assert F.pnl_table(date.today().year)["profit_total"] == 1_000_000


def test_edit_transaction_and_audit_log(app):
    from core.models import AuditLog
    client = app.test_client()
    login(client, "100100")
    tx = F.record("chiqim", 500_000, acc("Asosiy kassa"), category_id=cat("Ofis ijarasi").id)
    db.session.commit()
    client.post("/kassa/yangi", data={"tx_id": tx.id, "kind": "chiqim", "amount": "750 000",
                                      "account_id": acc("Bank hisobi").id, "category_id": cat("Ofis ijarasi").id,
                                      "date": date.today().isoformat(), "note": "tuzatildi"})
    tx = db.session.get(Transaction, tx.id)
    assert (tx.amount, tx.account.name, tx.note, tx.amount_uzs) == (750_000, "Bank hisobi", "tuzatildi", 750_000)
    assert Transaction.query.count() == 1
    assert AuditLog.query.filter_by(action="tx_update").count() == 1
    client.post(f"/kassa/{tx.id}/ochirish")
    assert AuditLog.query.filter_by(action="tx_delete").count() == 1
    assert "Kassa yozuvi tahrirlandi" in client.get("/sozlamalar/?bolim=tarix").get_data(as_text=True)


def test_manager_cannot_edit_or_change_programs(app):
    client = app.test_client()
    tx = F.record("kirim", 100, acc("Asosiy kassa"))
    db.session.commit()
    login(client, "300300")
    client.post("/kassa/yangi", data={"tx_id": tx.id, "kind": "kirim", "amount": "999", "account_id": tx.account_id})
    assert db.session.get(Transaction, tx.id).amount == 100
    assert client.post("/dasturlar/saqlash", data={"name": "X", "price": "1"}).status_code == 403
    assert client.get("/kassa/excel").status_code == 302


def test_deleting_repayment_reopens_debt(app):
    client = app.test_client()
    login(client, "100100")
    bank = acc("Bank hisobi")
    client.post("/qarz/yangi", data={"direction": "berilgan", "counterparty": "H", "amount": "1000", "account_id": bank.id})
    d = Debt.query.one()
    client.post(f"/qarz/{d.id}/qaytarish", data={"amount": "1000", "account_id": bank.id})
    assert db.session.get(Debt, d.id).closed
    repay = Transaction.query.filter_by(debt_id=d.id, kind="qarz_kirim").one()
    client.post(f"/kassa/{repay.id}/ochirish")
    assert not db.session.get(Debt, d.id).closed


def test_cross_site_post_rejected_and_headers(app):
    client = app.test_client()
    login(client, "100100")
    r = client.post("/kassa/yangi", data={"kind": "kirim", "amount": "1", "account_id": acc("Payme").id},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and Transaction.query.count() == 0
    r = client.post("/kassa/yangi", data={"kind": "kirim", "amount": "1", "account_id": acc("Payme").id},
                    headers={"Origin": "http://localhost"})
    assert Transaction.query.count() == 1
    h = client.get("/").headers
    assert h["X-Frame-Options"] == "DENY" and h["Cache-Control"] == "no-store"


def test_open_redirect_blocked():
    from views import is_local_path
    assert is_local_path("/kassa/?oy=2026-10")
    for bad in ("//evil.com", "/\\evil.com", "https://evil.com", "/\tx"):
        assert not is_local_path(bad)


def test_exports_are_valid_xlsx(app):
    from io import BytesIO
    from openpyxl import load_workbook
    from core.demo import demo
    demo()
    client = app.test_client()
    login(client, "100100")
    for url, sheets in (("/kassa/excel", 1), ("/sozlamalar/zaxira", 5), ("/hisobot/excel", 1)):
        r = client.get(url)
        assert r.status_code == 200, url
        wb = load_workbook(BytesIO(r.data))
        assert len(wb.sheetnames) == sheets and wb.worksheets[0].max_row > 1


def test_global_search_respects_roles(app):
    from core.demo import demo
    demo()
    client = app.test_client()
    login(client, "100100")
    page = client.get("/qidiruv/?q=Karim").get_data(as_text=True)
    assert "Karimov" in page and "Kassa yozuvlari" in page and "natija" in page
    login(client, "300300")
    page = client.get("/qidiruv/?q=Karim").get_data(as_text=True)
    assert "Qarzlar" not in page  # menejer qarz daftarini ko'rmaydi


# ── Kassa: Sheets uslubi ──

def test_ledger_running_balance_per_account_and_total(app):
    kassa, bank = acc("Asosiy kassa"), acc("Bank hisobi")
    month = date.today().replace(day=1)
    prev = month - timedelta(days=1)
    F.record("kirim", 1_000_000, kassa, date=prev)  # oldingi oy — boshlang'ich qoldiqqa kiradi
    a = F.record("kirim", 500_000, kassa, date=month)
    b = F.record("otkazma", 200_000, kassa, date=month, to_account_id=bank.id, to_amount=200_000)
    c = F.record("chiqim", 100_000, kassa, date=month)
    db.session.commit()
    rows = [a, b, c]
    opening, cur, flows = F.ledger_rows(rows, account=kassa, start=month)
    assert (opening, cur) == (1_000_000, "UZS")
    assert [flows[t.id]["bal"] for t in rows] == [1_500_000, 1_300_000, 1_200_000]
    # barcha hisoblar: o'tkazma umumiy qoldiqni o'zgartirmaydi va jamiga kirmaydi
    opening, cur, flows = F.ledger_rows(rows, start=month)
    assert [flows[t.id]["bal"] for t in rows] == [1_500_000, 1_500_000, 1_400_000]
    assert flows[b.id]["move"] and not flows[a.id]["move"]
    assert flows[c.id]["bal"] == F.total_balance_uzs()


def test_kassa_table_filters_and_hints(app):
    client = app.test_client()
    login(client, "100100")
    F.record("kirim", 750_000, acc("Asosiy kassa"), counterparty="Alisher Karimov", category_id=cat("Konsalting").id)
    F.record("chiqim", 90_000, acc("Asosiy kassa"), counterparty="Instagram", category_id=cat("Reklama (Instagram, Telegram)").id)
    db.session.commit()
    page = client.get("/kassa/").get_data(as_text=True)
    assert "Oy boshidagi qoldiq" in page and 'data-qe' in page
    assert '<option value="Alisher Karimov">' in page  # avto-to'ldirish ro'yxati
    page = client.get(f"/kassa/?kat={cat('Konsalting').id}").get_data(as_text=True)
    assert "Jami: 1 ta yozuv (filtr bo&#39;yicha)" in page or "Jami: 1 ta yozuv (filtr bo'yicha)" in page


def test_quick_entry_returns_focus_to_row(app):
    client = app.test_client()
    login(client, "100100")
    r = client.post("/kassa/yangi", data={"kind": "kirim", "amount": "1 200 000", "account_id": acc("Payme").id,
                                          "category_id": cat("Kurs to'lovlari").id, "counterparty": "Javohir",
                                          "date": date.today().isoformat(), "quick": "1", "next": "/kassa/?oy=2026-10"})
    tx = Transaction.query.one()
    assert tx.amount == 1_200_000 and tx.account.name == "Payme"
    assert r.headers["Location"].endswith(f"/kassa/?oy=2026-10&tez=1&belgi={tx.id}")


def test_sheet_parsers():
    from core.sheets import detect_header, parse_amount, parse_date, parse_kind
    assert parse_amount("1 500 000") == parse_amount("1,500,000") == parse_amount("1.500.000") == 1_500_000
    assert parse_amount("-250 000 so'm") == -250_000 and parse_amount("1500,50") == 1500.5 and parse_amount("abc") is None
    assert parse_date("05.10.2026") == parse_date("2026-10-05") == parse_date("5/10/26") == date(2026, 10, 5)
    assert parse_date("10/25/2026") == date(2026, 10, 25) and parse_date("31.02.2026") is None
    assert parse_kind("Kirim") == "kirim" and parse_kind("Xarajat") == "chiqim" and parse_kind("O'tkazma") == "skip"
    assert detect_header(["Sana", "Izoh", "Kirim", "Chiqim", "Qoldiq"]) == {0: "date", 1: "note", 2: "income", 3: "expense"}
    assert detect_header(["05.10.2026", "Kirim", "500000", "Asosiy kassa"]) is None


def test_import_from_sheets_preview_save_and_skip_duplicates(app):
    from core.models import AuditLog
    client = app.test_client()
    login(client, "100100")
    text = ("Sana\tKimdan / kimga\tKategoriya\tKirim\tChiqim\tQoldiq\tIzoh\n"
            "01.10.2026\tAlisher\tKurs to'lovlari\t1 500 000\t\t1 500 000\t3-potok\n"
            "02.10.2026\tInstagram\treklama\t\t450 000\t1 050 000\tOktabr\n"
            "03.10.2026\tNoma'lum\tYangi modda\t\t50 000\t1 000 000\t\n"
            "xato sana\tKimdir\t\t100\t\t\t\n")
    form = {"text": text, "default_account": acc("Asosiy kassa").id, "default_kind": "kirim"}
    page = client.post("/kassa/import", data=dict(form, action="preview")).get_data(as_text=True)
    assert "3 ta yangi" in page and "1 ta xato" in page and Transaction.query.count() == 0
    r = client.post("/kassa/import", data=dict(form, action="save"))
    assert r.status_code == 302 and "oy=2026-10" in r.headers["Location"]
    rows = Transaction.query.order_by(Transaction.date).all()
    assert [(t.kind, t.amount, t.counterparty) for t in rows] == [
        ("kirim", 1_500_000, "Alisher"), ("chiqim", 450_000, "Instagram"), ("chiqim", 50_000, "Noma'lum")]
    assert rows[1].category.name == "Reklama (Instagram, Telegram)"
    assert rows[2].category is None  # noma'lum kategoriya — "Boshqa" chiqim moddasi yo'q, kategoriyasiz qoladi
    assert AuditLog.query.filter_by(action="tx_import").count() == 1
    # qayta qo'yilsa — takror deb belgilanadi, ikki marta yozilmaydi
    page = client.post("/kassa/import", data=dict(form, action="save")).get_data(as_text=True)
    assert Transaction.query.count() == 3 and "3 ta bazada bor" in page


def test_import_xlsx_roundtrip_and_manager_blocked(app):
    from io import BytesIO
    client = app.test_client()
    login(client, "100100")
    tpl = client.get("/kassa/import/namuna.xlsx")
    assert tpl.status_code == 200
    r = client.post("/kassa/import", data={"action": "save", "default_account": acc("Asosiy kassa").id,
                                          "file": (BytesIO(tpl.data), "shablon.xlsx")},
                    content_type="multipart/form-data")
    assert r.status_code == 302 and Transaction.query.count() == 2
    login(client, "300300")
    assert client.get("/kassa/import").status_code == 302


# ── O'quvchi kartasi ──

def test_member_card_shows_full_history(app):
    from core.models import MemberEvent
    client = app.test_client()
    login(client, "100100")
    club = Program(name="Biznes klub", kind="klub", billing="oylik", price=1_000_000)
    course = Program(name="Kurs 9", kind="kurs", price=3_000_000)
    m = Member(full_name="Sardor Aliyev", phone="+998901112233", business="Savdo")
    db.session.add_all([club, course, m])
    db.session.commit()
    client.post(f"/dasturlar/{club.id}/yozish", data={"member_id": m.id, "joined_at": date.today().isoformat()})
    client.post(f"/azolar/{m.id}/yozish", data={"program_id": course.id, "price": "2 500 000"})
    e_club = Enrollment.query.filter_by(program_id=club.id).one()
    e_course = Enrollment.query.filter_by(program_id=course.id).one()
    assert e_course.price == 2_500_000 and e_course.member_id == m.id
    client.post("/kassa/yangi", data={"kind": "kirim", "amount": "1 000 000", "account_id": acc("Payme").id,
                                      "enrollment_id": e_club.id, "note": "1-oy"})
    client.post(f"/yozilish/{e_club.id}/uzaytirish")
    client.post(f"/yozilish/{e_course.id}/holat", data={"status": "tugatgan"})
    F.record("kirim", 200_000, acc("Asosiy kassa"), counterparty="sardor aliyev")  # dasturga bog'lanmagan
    db.session.add(Debt(direction="berilgan", counterparty="Sardor Aliyev", amount=500_000))
    db.session.commit()
    assert MemberEvent.query.filter_by(member_id=m.id).count() == 2
    page = client.get(f"/azolar/{m.id}").get_data(as_text=True)
    for text in ("Barcha tarix", "To&#39;lov qabul qilindi", "dasturiga yozildi", "uzaytirildi", "dasturni tugatdi",
                 "Qarz berildi", "200\u00a0000", "Dasturga yozish"):
        assert text in page or text.replace("&#39;", "'") in page, text
    # a'zolar paneli — kartochkalar, dastur sahifasida qator kartaga olib boradi
    page = client.get("/azolar").get_data(as_text=True)
    assert 'class="mcard' in page and f'/azolar/{m.id}' in page
    assert f'data-href="/azolar/{m.id}"' in client.get(f"/dasturlar/{club.id}").get_data(as_text=True)


def test_transfer_between_clubs_moves_payments(app):
    from core.models import AuditLog, MemberEvent
    client = app.test_client()
    login(client, "100100")
    a = Program(name="Klub A", kind="klub", billing="oylik", price=1_000_000)
    b = Program(name="Klub B", kind="klub", billing="oylik", price=1_500_000)
    m = Member(full_name="Jasur Karimov")
    db.session.add_all([a, b, m])
    db.session.commit()
    client.post(f"/dasturlar/{a.id}/yozish", data={"member_id": m.id})
    e = Enrollment.query.filter_by(program_id=a.id).one()
    client.post("/kassa/yangi", data={"kind": "kirim", "amount": "1 000 000", "account_id": acc("Payme").id,
                                      "enrollment_id": e.id})
    total_before = F.total_balance_uzs()
    r = client.post("/yozilish/otkazish", data={"eid": e.id, "program_id": b.id, "price": "1 500 000",
                                                "date": date.today().isoformat(), "note": "vaqti mos emas"})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/azolar/{m.id}")
    e = db.session.get(Enrollment, e.id)
    new = Enrollment.query.filter_by(program_id=b.id).one()
    assert e.status == "chiqqan" and new.status == "faol" and new.price == 1_500_000 and new.valid_until
    paid_map = F.enrollment_paid_map()
    assert F.enrollment_row(new, paid_map)["due"] == 500_000          # 1.5 mln − o'tgan 1 mln
    assert F.program_stats(a)["collected"] == 0 and F.program_stats(b)["collected"] == 1_000_000
    assert F.total_balance_uzs() == total_before                      # kassa o'zgarmaydi
    assert MemberEvent.query.filter_by(kind="transfer").count() == 1
    assert AuditLog.query.filter_by(action="transfer").count() == 1
    page = client.get(f"/azolar/{m.id}").get_data(as_text=True)
    assert "ga o&#39;tkazildi" in page or "ga o'tkazildi" in page
    # yopilgan yozilishni qayta o'tkazib bo'lmaydi; menejerga ruxsat yo'q
    client.post("/yozilish/otkazish", data={"eid": e.id, "program_id": b.id})
    assert Enrollment.query.count() == 2
    login(client, "300300")
    client.post("/yozilish/otkazish", data={"eid": new.id, "program_id": a.id})
    assert db.session.get(Enrollment, new.id).status == "faol"


def test_refund_reduces_income_not_expense(app):
    from core.models import AuditLog
    client = app.test_client()
    login(client, "100100")
    p = Program(name="Kurs R", kind="kurs", price=4_000_000)
    m = Member(full_name="Bobur Aliyev")
    db.session.add_all([p, m])
    db.session.commit()
    client.post(f"/dasturlar/{p.id}/yozish", data={"member_id": m.id})
    e = Enrollment.query.one()
    payme = acc("Payme")
    client.post("/kassa/yangi", data={"kind": "kirim", "amount": "4 000 000", "account_id": payme.id,
                                      "category_id": cat("Kurs to'lovlari").id, "enrollment_id": e.id})
    bal0, today = F.account_balances()[payme.id], date.today()
    # to'langanidan ko'p qaytarib bo'lmaydi
    client.post("/yozilish/qaytarish", data={"eid": e.id, "amount": "5 000 000", "account_id": payme.id})
    assert Transaction.query.count() == 1
    # qisman qaytarish — chegirma: narx kamayadi, qarz paydo bo'lmaydi
    client.post("/yozilish/qaytarish", data={"eid": e.id, "amount": "1 000 000", "account_id": payme.id,
                                             "then": "chegirma", "note": "chegirma berildi"})
    e = db.session.get(Enrollment, e.id)
    row = F.enrollment_row(e)
    assert (e.price, row["paid"], row["due"], e.status) == (3_000_000, 3_000_000, 0, "faol")
    t = F.period_totals(today, today)
    assert t["income"] == 3_000_000 and t["expense"] == 0           # xarajat emas — kirim kamaydi
    assert F.account_balances()[payme.id] == bal0 - 1_000_000
    assert F.program_stats(p)["collected"] == 3_000_000
    # kassa daftarida chiqim ustunida
    refund_tx = Transaction.query.filter(Transaction.amount < 0).one()
    _, _, flows = F.ledger_rows([refund_tx], account=payme, start=today.replace(day=1))
    assert (flows[refund_tx.id]["inc"], flows[refund_tx.id]["out"]) == (0, 1_000_000)
    # to'liq qaytarish — dasturdan chiqadi
    client.post("/yozilish/qaytarish", data={"eid": e.id, "amount": "3 000 000", "account_id": payme.id, "then": "chiqdi"})
    assert db.session.get(Enrollment, e.id).status == "chiqqan" and F.program_stats(p)["collected"] == 0
    assert AuditLog.query.filter_by(action="refund").count() == 2
    page = client.get(f"/azolar/{m.id}").get_data(as_text=True)
    assert "Pul qaytarildi" in page and "Qaytarildi" in client.get("/kassa/").get_data(as_text=True)
    login(client, "300300")
    client.post("/yozilish/qaytarish", data={"eid": e.id, "amount": "1", "account_id": payme.id})
    assert Transaction.query.filter(Transaction.amount < 0).count() == 2


# ── Kassa auditi ──

def test_kassa_kirim_linked_to_student_reduces_debt(app):
    client = app.test_client()
    login(client, "100100")
    p = Program(name="Kurs L", kind="kurs", price=2_000_000)
    m = Member(full_name="Otabek Nazarov")
    db.session.add_all([p, m])
    db.session.commit()
    client.post(f"/dasturlar/{p.id}/yozish", data={"member_id": m.id})
    e = Enrollment.query.one()
    page = client.get("/kassa/").get_data(as_text=True)
    assert "data-members=" in page and '<option value="Otabek Nazarov">' in page  # ism ro'yxatda, to'lovsiz ham
    # kassadan (tez yozish qatori) o'quvchi to'loviga bog'lab kirim
    client.post("/kassa/yangi", data={"kind": "kirim", "amount": "800 000", "account_id": acc("Click").id,
                                      "counterparty": "Otabek Nazarov", "enrollment_id": e.id, "quick": "1"})
    assert F.enrollment_row(db.session.get(Enrollment, e.id))["due"] == 1_200_000
    tx = Transaction.query.one()
    assert tx.program_id == p.id


def test_kassa_warnings_duplicate_negative_future(app):
    client = app.test_client()
    login(client, "100100")
    data = {"kind": "chiqim", "amount": "300 000", "account_id": acc("Asosiy kassa").id, "counterparty": "Zal",
            "date": date.today().isoformat()}
    client.post("/kassa/yangi", data=data)
    client.post("/kassa/yangi", data=data)
    with client.session_transaction() as sess:
        msgs = [m for cat_, m in sess.get("_flashes", []) if cat_ == "warn"]
    assert any("xuddi shunday yozuv" in m for m in msgs) and any("manfiy" in m for m in msgs)
    client.post("/kassa/yangi", data=dict(data, kind="kirim", amount="1000",
                                          date=(date.today() + timedelta(days=3)).isoformat()))
    with client.session_transaction() as sess:
        assert any("kelajakda" in m for c, m in sess.get("_flashes", []) if c == "warn")


def test_kassa_bulk_category_delete_and_uncategorized_filter(app):
    client = app.test_client()
    login(client, "100100")
    a = F.record("chiqim", 100, acc("Asosiy kassa"))
    b = F.record("chiqim", 200, acc("Asosiy kassa"))
    c = F.record("kirim", 300, acc("Asosiy kassa"))
    db.session.commit()
    page = client.get("/kassa/?kat=yoq").get_data(as_text=True)
    assert "Kategoriyasiz (3)" in page and "Jami: 3 ta yozuv" in page
    office = cat("Ofis ijarasi")
    client.post("/kassa/ommaviy", data={"ids": [a.id, b.id, c.id], "action": "category", "category_id": office.id})
    assert {t.id for t in Transaction.query.filter_by(category_id=office.id)} == {a.id, b.id}  # kirim o'zgarmaydi
    client.post("/kassa/ommaviy", data={"ids": [a.id, c.id], "action": "delete"})
    assert [t.id for t in Transaction.query.all()] == [b.id]
    login(client, "300300")
    client.post("/kassa/ommaviy", data={"ids": [b.id], "action": "delete"})
    assert Transaction.query.count() == 1


def test_kassa_export_has_balance_and_reimports_as_duplicates(app):
    from io import BytesIO
    from openpyxl import load_workbook
    client = app.test_client()
    login(client, "100100")
    kassa = acc("Asosiy kassa")
    F.record("kirim", 1_000_000, kassa, counterparty="Ali", category_id=cat("Konsalting").id)
    F.record("chiqim", 250_000, kassa, counterparty="Zal", category_id=cat("Zal ijarasi").id)
    db.session.commit()
    r = client.get(f"/kassa/excel?hisob={kassa.id}")
    ws = load_workbook(BytesIO(r.data)).active
    head = [c.value for c in ws[1]]
    assert head[7:10] == ["Kirim, so'm", "Chiqim, so'm", "Qoldiq, so'm"]
    assert ws.cell(4, 10).value == 750_000 and str(ws.cell(5, 8).value).startswith("=SUM(")
    r = client.post("/kassa/import", data={"action": "preview", "file": (BytesIO(r.data), "kassa.xlsx")},
                    content_type="multipart/form-data")
    assert "2 ta bazada bor" in r.get_data(as_text=True)


# ── Dars jadvali (kalendar) ──

def test_calendar_helpers():
    from datetime import time
    from core import calendar as C
    from core.models import Lesson
    start = date(2026, 10, 5)  # dushanba
    days = C.expand_weekly(start, [1, 3], count=5)
    assert [d.weekday() for d in days] == [1, 3, 1, 3, 1] and days[0] == date(2026, 10, 6)
    assert C.expand_weekly(start, [0], until=date(2026, 10, 26)) == [date(2026, 10, d) for d in (5, 12, 19, 26)]
    a = Lesson(start=time(9, 0), end=time(11, 0))
    b = Lesson(start=time(10, 0), end=time(12, 0))
    c = Lesson(start=time(13, 0), end=time(14, 0))
    lay = {id(x["lesson"]): x for x in C.layout_day([a, b, c], 8 * 60)}
    assert (lay[id(a)]["col"], lay[id(b)]["col"], lay[id(a)]["cols"]) == (0, 1, 2)  # kesishganlar yonma-yon
    assert (lay[id(c)]["cols"], lay[id(c)]["top"]) == (1, 300)
    assert C.fmt_range(date(2026, 9, 28), date(2026, 10, 4)) == "28 sentabr – 4 oktabr 2026"


def test_calendar_series_edit_move_delete(app):
    from core.models import Lesson
    client = app.test_client()
    login(client, "300300")  # menejer ham jadval tuza oladi
    p = Program(name="Kurs K", kind="kurs", price=1)
    db.session.add(p)
    db.session.commit()
    r = client.post("/kalendar/saqlash", data={"program_id": p.id, "date": "2026-10-06", "start": "19:00", "end": "21:00",
                                               "repeat": "weekly", "weekdays": ["1", "3"], "count": "6",
                                               "location": "Asosiy zal", "teacher": "Ustoz A"})
    assert r.status_code == 302
    les = Lesson.query.order_by(Lesson.date).all()
    assert len(les) == 6 and les[0].title == "1-dars" and les[5].title == "6-dars"
    assert len({x.series_id for x in les}) == 1 and les[1].date == date(2026, 10, 8)
    # xato vaqt
    client.post("/kalendar/saqlash", data={"program_id": p.id, "date": "2026-10-06", "start": "20:00", "end": "19:00"})
    assert Lesson.query.count() == 6
    # seriyani 3-darsdan boshlab tahrirlash — oldingilari o'zgarmaydi
    third = les[2]
    client.post("/kalendar/saqlash", data={"lesson_id": third.id, "scope": "series", "program_id": p.id,
                                           "date": third.date.isoformat(), "start": "18:00", "end": "20:00",
                                           "location": "Kichik zal", "title": third.title})
    les = Lesson.query.order_by(Lesson.date).all()
    assert [x.start.hour for x in les] == [19, 19, 18, 18, 18, 18] and les[5].location == "Kichik zal"
    # to'qnashuv: shu zalda shu vaqtga boshqa dars — ogohlantirish
    client.post("/kalendar/saqlash", data={"program_id": p.id, "date": les[3].date.isoformat(), "start": "19:00",
                                           "end": "20:30", "location": "kichik zal", "title": "Qo'shimcha"})
    with client.session_transaction() as sess:
        assert any("To'qnashuv" in m for c, m in sess.get("_flashes", []) if c == "warn")
    # sudrab ko'chirish (JSON)
    r = client.post(f"/kalendar/{les[0].id}/kochirish", json={"date": "2026-10-07", "start": "10:00", "end": "11:30"})
    assert r.get_json()["ok"] and db.session.get(Lesson, les[0].id).date == date(2026, 10, 7)
    assert client.post(f"/kalendar/{les[0].id}/kochirish", json={"date": "x"}).status_code == 400
    client.post(f"/kalendar/{les[1].id}/holat", data={"status": "otdi"})
    assert db.session.get(Lesson, les[1].id).status == "otdi"
    # seriyani 5-darsdan boshlab o'chirish
    client.post(f"/kalendar/{les[4].id}/ochirish", data={"scope": "series"})
    assert Lesson.query.filter(Lesson.series_id.isnot(None)).count() == 4
    for v in ("hafta", "soat", "kun", "oy", "yol", "royxat"):
        page = client.get(f"/kalendar/?v={v}&d=2026-10-08").get_data(as_text=True)
        assert "Yangi dars" in page, v
    assert "Dars jadvali" in client.get(f"/dasturlar/{p.id}").get_data(as_text=True)


# ── Davomat va QR skaner ──

def test_member_code_roundtrip_and_typos():
    from core.attendance import member_code, parse_code
    for mid in (1, 23, 4567, 999999):
        code = member_code(mid)
        assert len(code) == 9 and parse_code(code) == mid and parse_code(f"  {code.lower()}\n") == mid
        bad = code[:-1] + str((int(code[-1]) + 1) % 10)
        assert parse_code(bad) is None  # nazorat raqami xatoni ushlaydi
    assert parse_code("https://assoodiq.uz/a/" + member_code(5)) == 5 and parse_code("salom") is None


def test_attendance_scan_mark_and_stats(app):
    from datetime import time
    from core.attendance import member_code
    from core.models import Attendance, Lesson
    client = app.test_client()
    login(client, "300300")  # menejer ham davomat oladi
    p = Program(name="Kurs D", kind="kurs", price=1)
    a, b, c = Member(full_name="Ali Valiyev"), Member(full_name="Bobur Sodiqov"), Member(full_name="Mehmon Bek")
    db.session.add_all([p, a, b, c])
    db.session.commit()
    for m in (a, b):
        db.session.add(Enrollment(member_id=m.id, program_id=p.id, price=1, joined_at=date(2026, 1, 1)))
    les = Lesson(program_id=p.id, title="1-dars", date=date.today(), start=time(0, 0), end=time(23, 59))
    db.session.add(les)
    db.session.commit()
    page = client.get(f"/kalendar/{les.id}/davomat").get_data(as_text=True)
    assert "Ali Valiyev" in page and "Bobur Sodiqov" in page and "Skaner" in page
    # skaner: kod → keldi/kechikdi; ikkinchi marta — takror
    r = client.post(f"/kalendar/{les.id}/davomat/skaner", json={"code": member_code(a.id)}).get_json()
    assert r["ok"] and r["status"] in ("keldi", "kechikdi") and not r["already"] and r["stats"]["present"] == 1
    assert client.post(f"/kalendar/{les.id}/davomat/skaner", json={"code": member_code(a.id)}).get_json()["already"]
    assert db.session.get(Lesson, les.id).status == "otdi"
    # noto'g'ri kod va dasturda yo'q a'zo
    assert not client.post(f"/kalendar/{les.id}/davomat/skaner", json={"code": "AQ0000010"}).get_json()["ok"]
    r = client.post(f"/kalendar/{les.id}/davomat/skaner", json={"code": member_code(c.id)}).get_json()
    assert not r["ok"] and r["need_force"]
    r = client.post(f"/kalendar/{les.id}/davomat/skaner", json={"code": member_code(c.id), "force": True}).get_json()
    assert r["ok"] and r["stats"]["total"] == 3  # mehmon ham ro'yxatga qo'shildi
    # qo'lda: kelmadi, keyin belgini olib tashlash
    r = client.post(f"/kalendar/{les.id}/davomat/belgi", json={"member_id": b.id, "status": "kelmadi"}).get_json()
    assert r["stats"]["kelmadi"] == 1
    r = client.post(f"/kalendar/{les.id}/davomat/belgi", json={"member_id": b.id, "status": ""}).get_json()
    assert r["stats"]["kelmadi"] == 0 and r["stats"]["unmarked"] == 1
    client.post(f"/kalendar/{les.id}/davomat/hammasi", data={"status": "keldi"})
    present = Attendance.query.filter(Attendance.lesson_id == les.id, Attendance.status.in_(("keldi", "kechikdi")))
    assert present.count() == 3  # Ali (skaner), mehmon (skaner) va Bobur («qolganlar keldi»)
    # kartalar va o'quvchi kartasidagi davomat
    page = client.get(f"/azolar/kartalar?dastur={p.id}").get_data(as_text=True)
    assert member_code(a.id) in page and "<svg" in page and "Bobur Sodiqov" in page
    assert "Davomat:" in client.get(f"/azolar/{a.id}").get_data(as_text=True)
    # dars o'chirilsa davomati ham o'chadi
    client.post(f"/kalendar/{les.id}/ochirish")
    assert Attendance.query.count() == 0
