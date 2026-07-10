-- ============================================================
-- 1. CREATE SCHEMAS (Must happen BEFORE tables)
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS processed;

-- ============================================================
-- 2. RAW SCHEMA — immutable landing zone
CREATE TABLE IF NOT EXISTS raw.api_pulls (
    id           BIGSERIAL PRIMARY KEY,
    device_type  TEXT NOT NULL,
    device_id    TEXT NOT NULL,
    pulled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload      JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_api_pulls_device
    ON raw.api_pulls (device_type, device_id, pulled_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_api_pulls_payload_gin
    ON raw.api_pulls USING GIN (payload);

-- ============================================================
-- 3. PROCESSED SCHEMA — parsed/standardized
CREATE TABLE IF NOT EXISTS processed.devices (
    device_id    TEXT PRIMARY KEY,
    device_type  TEXT NOT NULL,
    site         TEXT
);

CREATE TABLE IF NOT EXISTS processed.readings (
    id             BIGSERIAL PRIMARY KEY,
    device_id      TEXT REFERENCES processed.devices(device_id),
    recorded_at    TIMESTAMPTZ NOT NULL,
    metric         TEXT NOT NULL,
    value          DOUBLE PRECISION,
    location       GEOMETRY(Point, 4326),
    raw_pull_id    BIGINT REFERENCES raw.api_pulls(id)
);

CREATE TABLE IF NOT EXISTS processed.pipeline_runs (
    id            BIGSERIAL PRIMARY KEY,
    device_type   TEXT NOT NULL,
    device_id     TEXT NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL,
    error_message TEXT
);   