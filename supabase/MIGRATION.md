# Перехід на Supabase (Streamlit Cloud, 2 користувачі)

## 1. Створити проєкт Supabase (безкоштовно)

1. Зайди на [supabase.com](https://supabase.com) → **Start your project** → GitHub.
2. **New project** → назва `logistic-manager`, регіон **Frankfurt** (ближче до України).
3. Задай пароль БД (збережи в менеджері паролів — для ручного доступу через SQL).
4. Дочекайся статусу **Active** (~2 хв).

## 2. Таблиці

1. У проєкті: **SQL Editor** → **New query**.
2. Встав вміст файлу [`schema.sql`](./schema.sql) → **Run**.
3. **Table Editor** — мають з’явитись `orders`, `up_shipments`, `audit_log`, `ui_settings`.

## 3. Ключі для Streamlit

1. **Project Settings** → **API**.
2. Скопіюй:
   - **Project URL** → `SUPABASE_URL`
   - **service_role** (secret) → `SUPABASE_SERVICE_KEY`  
     ⚠️ Ніколи не публікуй у фронтенді. Тільки Streamlit Secrets (як `gcp_service_account`).

## 4. Secrets у Streamlit Cloud

У [share.streamlit.io](https://share.streamlit.io) → твій app → **Settings** → **Secrets**, додай:

```toml
SUPABASE_URL = "https://xxxxx.supabase.co"
SUPABASE_SERVICE_KEY = "eyJhbGciOi..."
DATA_BACKEND = "supabase"
```

`DATA_BACKEND = "supabase"` вмикає БД. Без цього рядка — як раніше, Google Sheets.

Під час міграції можна тимчасово лишити `DATA_BACKEND = "sheets"` і лише імпортувати дані скриптом.

## 5. Імпорт даних з Google Sheets (один раз)

**Найпростіше — у додатку (Streamlit Cloud):**

1. Додай у Secrets лише `SUPABASE_URL` і `SUPABASE_SERVICE_KEY` (без `DATA_BACKEND`).
2. Перезапусти додаток, увійди як **admin**.
3. У лівій панелі: **🗄 Перехід на Supabase** → **Імпортувати з Google Sheets**.

Альтернатива — локально в терміналі:

```bash
cd logistic-manager
pip install supabase
python scripts/migrate_sheets_to_supabase.py
```

Скрипт читає Orders / UP_Shipments / LogisticAudit і записує в Supabase.

## 6. Увімкнути Supabase в проді

1. Переконайся, що імпорт пройшов (кількість рядків у Table Editor).
2. У Secrets: `DATA_BACKEND = "supabase"`.
3. **Reboot app** у Streamlit Cloud.
4. Перевір: таблиця замовлень, журнал УП, створення ТТН.

## 7. Google Sheets після переходу

- Аркуші **не видаляй** — залиш як бекап.
- Опційно: раз на тиждень експорт з Supabase (пізніше — кнопка в додатку).

## Відкат

У Secrets зміни на:

```toml
DATA_BACKEND = "sheets"
```

Додаток знову читатиме Google Sheets. Дані в Supabase лишаться.

## Чому service_role, а не RLS

Вхід у додаток — власний (`auth_users` + bcrypt). Supabase використовується як **сховище**, не як публічний API. Для 2 внутрішніх користувачів це простіше за політики RLS.
