"""Автогенерація текстів SMS для таблиці замовлень."""
from __future__ import annotations

import utils
from tabs.tab1_checkout import check_sms_text, tab1_sms_prefill


def ensure_messages_exist(df):
    for i, row in df.iterrows():
        if utils.row_receipt_not_required(row):
            continue
        msg_val = str(row["Повідомлення"]).strip()
        is_sent = str(row["Статус СМС"]) == "Отправлено"
        current_status = str(row["Статус"]).lower()
        link = str(row["Чек"]).strip()

        if is_sent:
            continue
        if not utils.status_has_any(current_status, utils.DELIVERED_STATUS_KEYWORDS):
            continue

        short = len(msg_val) <= 5 or msg_val.lower() == "nan"
        has_link = link and len(link) > 5 and link.lower() != "nan"
        if has_link:
            if short or link not in msg_val:
                df.at[i, "Повідомлення"] = check_sms_text(link)
                if len(str(row["Телефон"])) > 5:
                    df.at[i, "Статус СМС"] = "Не отправлено"
        elif short:
            df.at[i, "Повідомлення"] = tab1_sms_prefill()
            if len(str(row["Телефон"])) > 5:
                df.at[i, "Статус СМС"] = "Не отправлено"
    return df
