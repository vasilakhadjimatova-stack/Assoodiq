from datetime import date, datetime, timezone

from urllib.parse import urlsplit

from flask import Flask, abort, g, redirect, request, session, url_for

from config import Config
from core import hijri
from core.extensions import db
from core.finance import MONTHS_FULL, get_setting
from core.models import User

# Rol → kirish mumkin bo'lgan bo'limlar (blueprint nomlari)
ROLE_SECTIONS = {
    "rahbar": {"main", "kassa", "dastur", "qarz", "islomiy", "hisobot", "sozlama"},
    "buxgalter": {"main", "kassa", "dastur", "qarz", "islomiy", "hisobot", "sozlama"},
    "menejer": {"kassa", "dastur"},
}


def fmt_num(value, decimals=0):
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return value
    s = f"{abs(v):,.{decimals}f}".replace(",", " ")
    return ("−" if v < 0 else "") + s


def fmt_money(value, currency="UZS"):
    if currency == "USD":
        return "$" + fmt_num(value, 2 if value and float(value) % 1 else 0)
    return fmt_num(value)


def fmt_short(value):
    """Grafik o'qlari uchun: 12.5 mln, 850 ming."""
    v = float(value or 0)
    a = abs(v)
    if a >= 1e9:
        s = f"{v / 1e9:.1f} mlrd"
    elif a >= 1e8:
        s = f"{v / 1e6:.0f} mln"
    elif a >= 1e6:
        s = f"{v / 1e6:.1f} mln"
    elif a >= 1e3:
        s = f"{v / 1e3:.0f} ming"
    else:
        s = f"{v:.0f}"
    return s.replace(".0 ", " ").replace("-", "−")


def fmt_date(d, style="short"):
    if not d:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    if style == "long":
        return f"{d.day} {MONTHS_FULL[d.month - 1].lower()} {d.year}"
    return d.strftime("%d.%m.%Y")


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    db.init_app(app)

    from views import register
    register(app)

    from core.finance import nice_scale
    app.jinja_env.globals["nice_scale"] = nice_scale
    app.jinja_env.filters.update(
        num=fmt_num, money=fmt_money, short=fmt_short, d=fmt_date,
        hijri=lambda d: hijri.format_hijri(d) if d else "",
        pct=lambda v: f"{(v or 0) * 100:.0f}%",
        # bazada UTC saqlanadi — ekranda server mintaqasi (Toshkent) vaqti
        localdt=lambda dt: dt.replace(tzinfo=timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M") if dt else "",
    )

    @app.before_request
    def same_origin_only():
        """CSRF himoyasi: o'zgartiruvchi so'rov boshqa saytdan kelsa — rad etiladi."""
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        source = request.headers.get("Origin") or request.headers.get("Referer")
        if source and urlsplit(source).netloc != request.host:
            abort(403)
        return None

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.endpoint and not request.endpoint.startswith("static"):
            resp.headers.setdefault("Cache-Control", "no-store")  # moliyaviy sahifalar keshda qolmasin
        return resp

    @app.before_request
    def load_user():
        g.user = None
        uid = session.get("uid")
        if uid:
            u = db.session.get(User, uid)
            if u and u.active:
                g.user = u
        if request.endpoint in (None, "static") or (request.endpoint or "").startswith("auth."):
            return None
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        section = request.blueprint
        if section and section not in ROLE_SECTIONS.get(g.user.role, set()):
            return redirect(url_for(home_endpoint(g.user)))
        return None

    @app.context_processor
    def inject():
        return {
            "today": date.today(),
            "org_name": get_setting("org_name") if g.get("user") else "Assoodiq",
            "demo_mode": bool(g.get("user")) and get_setting("demo_loaded") == "1",
            "can": lambda section: bool(g.get("user")) and section in ROLE_SECTIONS.get(g.user.role, set()),
        }

    with app.app_context():
        db.create_all()
        if not app.testing:
            from core.bootstrap import base_setup, secret_key
            base_setup()
            if not app.config.get("SECRET_KEY"):
                app.config["SECRET_KEY"] = secret_key()

    return app


def home_endpoint(user):
    return "main.dashboard" if "main" in ROLE_SECTIONS.get(user.role, set()) else "dastur.programs"


if __name__ == "__main__":
    create_app().run(debug=True, port=5070)
