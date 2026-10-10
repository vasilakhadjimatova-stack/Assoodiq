import time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from core.models import User

bp = Blueprint("auth", __name__)

# 6 xonali kodni tanlab topishga urinishni sekinlashtirish (IP bo'yicha)
MAX_FAILS, WINDOW = 8, 10 * 60
_fails = {}


def _blocked(ip):
    now = time.time()
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < WINDOW]
    return len(_fails[ip]) >= MAX_FAILS


@bp.route("/kirish", methods=["GET", "POST"])
def login():
    # Proksi (Railway) qo'shgan oxirgi manzil — mijoz o'zi yozgan qiymatni hisobga olmaymiz
    ip = (request.access_route or [request.remote_addr or ""])[-1]
    if request.method == "POST" and _blocked(ip):
        flash("Juda ko'p noto'g'ri urinish. 10 daqiqadan keyin qayta urinib ko'ring.", "bad")
    elif request.method == "POST":
        code = "".join(ch for ch in request.form.get("code", "") if ch.isdigit())
        user = next((u for u in User.query.filter_by(active=True).all() if u.check_code(code)), None)
        if user:
            session.clear()
            session.permanent = True
            session["uid"] = user.id
            from app import home_endpoint
            nxt = request.args.get("next") or ""
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for(home_endpoint(user)))
        _fails.setdefault(ip, []).append(time.time())
        flash("Kod noto'g'ri. Qaytadan urinib ko'ring.", "bad")
    return render_template("pages/login.html")


@bp.route("/chiqish", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
