"""Boshlang'ich sozlama va (ixtiyoriy) namuna ma'lumot.

    python seed.py            # faqat hisoblar, kategoriyalar, xodimlar (bo'sh baza uchun)
    python seed.py --demo     # + 12 oylik namuna: kurslar, klub, a'zolar, kirim-chiqim
    python seed.py --reset    # bazani tozalab qaytadan (ehtiyot bo'ling!)
"""
import sys

from app import create_app
from core.bootstrap import base_setup
from core.demo import demo
from core.extensions import db
from core.models import Transaction

# Lokal sinov uchun kodlar — prod'da ishlatilmaydi
DEMO_USERS = [("Rahbar", "rahbar", "100100"), ("Buxgalter", "buxgalter", "200200"), ("Menejer", "menejer", "300300")]


if __name__ == "__main__":
    import os
    os.environ.setdefault("ADMIN_CODE", "100100")  # namuna rahbari standart kod bilan
    app = create_app()
    with app.app_context():
        if "--reset" in sys.argv:
            db.drop_all()
            db.create_all()
        base_setup(users=DEMO_USERS)
        if "--demo" in sys.argv:
            if Transaction.query.count():
                print("Bazada allaqachon yozuvlar bor — namuna qo'shilmadi (--reset bilan qayta urining).")
            else:
                demo()
                print("Namuna ma'lumot qo'shildi.")
        print("Tayyor. Kirish kodlari: rahbar 100100 · buxgalter 200200 · menejer 300300")
