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
