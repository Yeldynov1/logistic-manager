"""Автогенерація текстів SMS для таблиці замовлень."""
from __future__ import annotations

import utils
from core.receipt_delivery import receipt_sms_prefill, receipt_sms_text


def ensure_messages_exist(df):
    for i, row in df.iterrows():
        if utils.row_receipt_not_required(row):
            continue
        msg_val = str(row["Повідомлення"]).strip()
        is_sent = utils.sms_status_is_done(row["Статус СМС"])
        link = str(row["Чек"]).strip()

        if is_sent:
            continue
        if not utils.checkout_status_is_ready(row):
            continue

        short = len(msg_val) <= 5 or msg_val.lower() == "nan"
        has_link = link and len(link) > 5 and link.lower() != "nan"
        if has_link:
            if short or link not in msg_val:
                df.at[i, "Повідомлення"] = receipt_sms_text(link)
                if len(str(row["Телефон"])) > 5:
                    df.at[i, "Статус СМС"] = "Не отправлено"
        elif short:
            df.at[i, "Повідомлення"] = receipt_sms_prefill()
            if len(str(row["Телефон"])) > 5:
                df.at[i, "Статус СМС"] = "Не отправлено"
    return df
