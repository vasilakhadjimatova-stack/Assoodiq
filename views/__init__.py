from datetime import date, datetime

from flask import abort, g

from core.finance import parse_money


def register(app):
    from views import auth, dastur, hisobot, islomiy, kassa, main, qarz, sozlama

    for mod in (auth, main, kassa, dastur, qarz, islomiy, hisobot, sozlama):
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
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else default
