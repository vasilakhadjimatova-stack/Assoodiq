import os
import time

from dotenv import load_dotenv

load_dotenv()

# Server (Railway) UTC'da ishlaydi — "bugun" Toshkent vaqti bo'yicha bo'lishi kerak
os.environ.setdefault("TZ", "Asia/Tashkent")
if hasattr(time, "tzset"):
    time.tzset()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _db_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///" + os.path.join(BASE_DIR, "assoodiq.db")
    # Railway/Heroku eski "postgres://" prefiksini beradi
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


class Config:
    # Bo'sh bo'lsa ilova bazada saqlanadigan tasodifiy kalitni oladi (core/bootstrap.py)
    SECRET_KEY = os.environ.get("SECRET_KEY") or None
    SQLALCHEMY_DATABASE_URI = _db_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14  # 14 kun
    # Boshqa saytdan POST so'rov yuborib bo'lmasin (CSRF'dan himoya)
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "") == "1"


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
