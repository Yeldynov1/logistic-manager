-- Запусти в Supabase → SQL Editor → New query → Run
-- Проєкт: logistic-manager (2 користувачі, Streamlit Cloud)

-- Orders (аркуш Orders)
CREATE TABLE IF NOT EXISTS orders (
    id              BIGSERIAL PRIMARY KEY,
    ttn             TEXT NOT NULL DEFAULT '',
    service         TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'Нове',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    phone           TEXT NOT NULL DEFAULT '',
    cost            DOUBLE PRECISION NOT NULL DEFAULT 0,
    invoice_number  TEXT NOT NULL DEFAULT '',
    check_url       TEXT NOT NULL DEFAULT '',
    message         TEXT NOT NULL DEFAULT '',
    sms_status      TEXT NOT NULL DEFAULT '',
    reminder_status TEXT NOT NULL DEFAULT '',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_ttn_unique
    ON orders (ttn) WHERE ttn <> '';

CREATE INDEX IF NOT EXISTS idx_orders_created ON orders (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);

-- Журнал Укрпошти (UP_Shipments)
CREATE TABLE IF NOT EXISTS up_shipments (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    username        TEXT NOT NULL DEFAULT '',
    barcode         TEXT NOT NULL,
    shipment_uuid   TEXT NOT NULL DEFAULT '',
    up_status       TEXT NOT NULL DEFAULT '',
    recipient_name  TEXT NOT NULL DEFAULT '',
    phone           TEXT NOT NULL DEFAULT '',
    tariff          TEXT NOT NULL DEFAULT '',
    delivery_type   TEXT NOT NULL DEFAULT '',
    delivery_price  DOUBLE PRECISION,
    postpay         DOUBLE PRECISION,
    description     TEXT NOT NULL DEFAULT '',
    postcode        TEXT NOT NULL DEFAULT '',
    city            TEXT NOT NULL DEFAULT '',
    api_json        TEXT,
    printed_mark    TEXT NOT NULL DEFAULT '',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE up_shipments
    ADD COLUMN IF NOT EXISTS printed_mark TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_up_shipments_barcode ON up_shipments (barcode);
CREATE INDEX IF NOT EXISTS idx_up_shipments_created ON up_shipments (created_at DESC);

-- LogisticAudit
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    username        TEXT NOT NULL DEFAULT '',
    action          TEXT NOT NULL DEFAULT '',
    ttn             TEXT NOT NULL DEFAULT '',
    detail          TEXT NOT NULL DEFAULT '',
    ship_cost       DOUBLE PRECISION,
    receipt_sum     DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log (created_at DESC);

-- UISettings (порядок колонок)
CREATE TABLE IF NOT EXISTS ui_settings (
    username        TEXT PRIMARY KEY,
    column_order    JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Доступ до вкладок за роллю (admin налаштовує manager у sidebar)
CREATE TABLE IF NOT EXISTS role_settings (
    role            TEXT PRIMARY KEY,
    settings        JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by      TEXT NOT NULL DEFAULT '',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Авто-оновлення updated_at
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS orders_updated_at ON orders;
CREATE TRIGGER orders_updated_at
    BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS up_shipments_updated_at ON up_shipments;
CREATE TRIGGER up_shipments_updated_at
    BEFORE UPDATE ON up_shipments FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS role_settings_updated_at ON role_settings;
CREATE TRIGGER role_settings_updated_at
    BEFORE UPDATE ON role_settings FOR EACH ROW EXECUTE FUNCTION set_updated_at();
