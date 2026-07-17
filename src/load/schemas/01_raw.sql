CREATE TABLE IF NOT EXISTS raw.ingestions (
    id                BIGSERIAL PRIMARY KEY,
    device_type       TEXT NOT NULL,
    device_id         TEXT NOT NULL REFERENCES study.devices(id),
    ingestion_method  TEXT NOT NULL CHECK (ingestion_method IN ('api_auto', 'api_manual', 'csv_manual')),
    pulled_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload           JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_ingestions_device
    ON raw.ingestions (device_type, device_id, pulled_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_ingestions_payload_gin
    ON raw.ingestions USING GIN (payload);