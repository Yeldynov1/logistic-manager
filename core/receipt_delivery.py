"""Спільні правила формування та безпечної видачі чека через TurboSMS."""
from __future__ import annotations

import utils


CHECKBOX_RECEIPT_HOST = "check.checkbox.ua/"
CHECK_SMS_PREFIX = "Magazin Alius. Vash chek: "


def receipt_sms_text(link: str) -> str:
    return CHECK_SMS_PREFIX + str(link or "").strip()


def receipt_sms_prefill() -> str:
    return CHECK_SMS_PREFIX


def default_receipt_sms_text(row) -> str:
    """Колонка «Чек» є джерелом правди для посилання в SMS."""
    if utils.row_receipt_not_required(row):
        return ""
    msg = str(row.get("Повідомлення", "")).strip()
    link = str(row.get("Чек", "")).strip()
    has_link = bool(link and len(link) > 5 and link.lower() != "nan")
    if has_link:
        if len(msg) > 5 and msg.lower() != "nan" and link in msg:
            return msg
        return receipt_sms_text(link)
    if len(msg) > 5 and msg.lower() != "nan":
        if CHECKBOX_RECEIPT_HOST in msg.lower():
            return receipt_sms_prefill()
        return msg
    return receipt_sms_prefill()


def receipt_sms_text_for_send(row) -> str:
    """Фінальний текст: власне повідомлення або шаблон із точним URL чека."""
    text = str(row.get("Повідомлення", "")).strip()
    if len(text) <= 5 or text.lower() == "nan":
        text = default_receipt_sms_text(row)
    else:
        link = str(row.get("Чек", "")).strip()
        if link and link not in text:
            filled = default_receipt_sms_text(row)
            if filled:
                text = filled
    return text.strip()


def row_ready_for_turbosms(row, *, allow_completed: bool = False) -> bool:
    """Тільки вручення покупцю + чек + коректний український номер."""
    if utils.row_receipt_not_required(row):
        return False
    service = str(row.get("Служба", "") or "").strip().lower()
    invoice = utils.normalize_invoice_number(row.get("Номер накладної", ""))
    if service == "meest" and not invoice:
        return False
    if not allow_completed and utils.sms_status_is_done(row.get("Статус СМС", "")):
        return False
    if not utils.checkout_status_is_ready(row):
        return False
    receipt = str(row.get("Чек", "")).strip()
    if not receipt or len(receipt) < 5 or receipt.lower() == "nan":
        return False
    if len(receipt_sms_text_for_send(row)) < 2:
        return False
    phone = utils.clean_phone(row.get("Телефон"))
    return len(phone) == 12 and phone.startswith("380")
