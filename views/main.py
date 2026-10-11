from datetime import date

from flask import Blueprint, render_template

from core import attendance as A
from core import finance as F
from core import hijri
from core.models import Program, Transaction
from views.kassa import form_context

bp = Blueprint("main", __name__)


@bp.route("/")
def dashboard():
    today = date.today()
    m_start, m_end = F.month_bounds(today)
    p_start, p_end = F.month_bounds(F.shift_month(today, -1))
    cur = F.period_totals(m_start, m_end)
    prev = F.period_totals(p_start, p_end)

    def delta(a, b):
        return (a - b) / abs(b) if b else None

    series = F.monthly_series(12, today)
    paid_map = F.enrollment_paid_map()
    programs = [F.program_stats(p, paid_map) for p in
                Program.query.filter(Program.status != "rejada").all()]
    programs.sort(key=lambda s: -s["collected"])

    hawl_raw = F.get_setting("hawl_start")
    hawl = None
    if hawl_raw:
        start = date.fromisoformat(hawl_raw)
        nxt = hijri.next_hawl(start, today)
        hawl = {"date": nxt, "days": (nxt - today).days}

    defaults = F.zakat_defaults()
    nisob = F.nisob_value()
    zakat = F.zakat_compute(nisob=nisob, **defaults)

    lessons_today = A.today_lessons()
    return render_template(
        "pages/dashboard.html", lt=lessons_today,
        cur=cur, prev=prev,
        d_income=delta(cur["income"], prev["income"]),
        d_expense=delta(cur["expense"], prev["expense"]),
        d_profit=delta(cur["profit"], prev["profit"]),
        month_name=F.MONTHS_FULL[today.month - 1],
        accounts=F.accounts_with_balance(),
        total=F.total_balance_uzs(),
        series=series,
        expenses=F.breakdown("chiqim", m_start, m_end, limit=6),
        programs=programs[:5],
        member_due=F.receivables_from_members(),
        debts=F.debts_summary(),
        expiring=F.expiring_memberships(7, today),
        purif=F.purification_fund(),
        zakat=zakat, nisob=nisob, hawl=hawl,
        **form_context(),
        recent=Transaction.query.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(7).all(),
    )
