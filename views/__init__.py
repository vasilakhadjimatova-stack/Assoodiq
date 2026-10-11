from datetime import date, datetime

from flask import abort, g

from core.finance import parse_money


def register(app):
    from views import auth, dastur, hisobot, islomiy, kalendar, kassa, main, qarz, qidiruv, sozlama, telegram

    for mod in (auth, main, kassa, dastur, kalendar, qarz, islomiy, hisobot, sozlama, qidiruv, telegram):
        app.register_blueprint(mod.bp)


def require_role(*roles):
    if g.user is None or g.user.role not in roles:
        abort(403)


def form_date(raw, default=None):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return default if default is not None else date.today()


def form_date_opt(raw):
    raw = (raw or "").strip()
    return form_date(raw) if raw else None


def form_int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


money = parse_money


def safe_next(default):
    from flask import request
    nxt = request.form.get("next") or request.args.get("next") or ""
    return nxt if is_local_path(nxt) else default


def is_local_path(url):
    """Faqat shu saytdagi yo'l. "//evil.com" va "/\\evil.com" (brauzer // deb tushunadi) rad etiladi."""
    return (url.startswith("/") and not url.startswith("//") and "\\" not in url
            and not any(ord(ch) < 32 for ch in url))
