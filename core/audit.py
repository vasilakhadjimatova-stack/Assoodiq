"""O'zgarishlar tarixi: muhim amallar AuditLog'ga yoziladi (commit chaqiruvchida)."""
from flask import g

from core.extensions import db
from core.models import AuditLog

ACTIONS = {
    "tx_delete": "Kassa yozuvi o'chirildi",
    "tx_update": "Kassa yozuvi tahrirlandi",
    "tx_import": "Sheets/Excel'dan yozuvlar ko'chirildi",
    "data_clear": "Barcha yozuvlar tozalandi",
    "demo_load": "Namuna ma'lumot yuklandi",
    "settings": "Sozlamalar o'zgartirildi",
    "user_add": "Xodim qo'shildi",
    "user_code": "Xodimga yangi kod berildi",
    "user_toggle": "Xodim holati o'zgardi",
    "program_save": "Dastur saqlandi",
    "transfer": "A'zo boshqa dasturga o'tkazildi",
    "refund": "O'quvchiga pul qaytarildi",
    "debt_toggle": "Qarz holati o'zgardi",
}


def log(action, details=""):
    user = g.get("user")
    db.session.add(AuditLog(user_id=user.id if user else None, action=action, details=str(details)[:500]))


def describe_tx(tx):
    cur = "$" if tx.account and tx.account.currency == "USD" else "so'm"
    who = tx.counterparty or (tx.category.name if tx.category else "")
    amount = f"{tx.amount:,.0f}".replace(",", " ")
    return f"#{tx.id} {tx.kind_name} {amount} {cur}, {tx.date:%d.%m.%Y}, {who}"
