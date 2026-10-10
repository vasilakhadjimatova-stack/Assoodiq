from datetime import date, timedelta

import pytest

from app import create_app
from config import TestConfig
from core import finance as F
from core import hijri
from core.extensions import db
from core.models import Account, Category, Debt, Enrollment, Member, Program, Transaction, User
from seed import base_setup


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        base_setup()
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
