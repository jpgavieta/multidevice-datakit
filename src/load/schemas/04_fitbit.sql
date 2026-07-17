-- src/load/schemas/04_fitbit.sql
-- Heterogeneous — generic table for scalars tables for anything with real nested internal structure.

CREATE TABLE IF NOT EXISTS fitbit.readings (
    id             BIGSERIAL PRIMARY KEY,
    device_id      TEXT NOT NULL REFERENCES study.devices(id),
    data_type      TEXT NOT NULL,       -- e.g. "steps", "daily-resting-heart-rate"
    recorded_at    TIMESTAMPTZ NOT NULL,
    value_numeric  DOUBLE PRECISION,
    value_text     TEXT,
    ingestion_id   BIGINT REFERENCES raw.ingests(id),
    UNIQUE (device_id, data_type, recorded_at, metric, tag)
);

CREATE INDEX IF NOT EXISTS idx_fitbit_readings_device_type_time
    ON fitbit.readings (device_id, data_type, recorded_at DESC);

-- fitbit.sleep_sessions — one row per sleep record
CREATE TABLE IF NOT EXISTS fitbit.sleep_sessions (
    id                        BIGSERIAL PRIMARY KEY,
    device_id                 TEXT NOT NULL REFERENCES study.devices(id),
    start_at                  TIMESTAMPTZ NOT NULL,
    end_at                    TIMESTAMPTZ NOT NULL,
    sleep_type                TEXT,            -- "STAGES", etc.
    is_nap                    BOOLEAN,
    minutes_in_sleep_period   INTEGER,
    minutes_after_wakeup      INTEGER,
    minutes_to_fall_asleep    INTEGER,
    minutes_asleep            INTEGER,
    minutes_awake             INTEGER,
    ingestion_id              BIGINT REFERENCES raw.ingests(id),
    UNIQUE (device_id, start_at)
);

-- fitbit.sleep_stages — child table, one row per stage within a session
CREATE TABLE IF NOT EXISTS fitbit.sleep_stages (
    id          BIGSERIAL PRIMARY KEY,
    session_id  BIGINT NOT NULL REFERENCES fitbit.sleep_sessions(id), -- ForiegnKey (FK) is "which sleep session I belong to" which is fitbit.sleep_session's `id`
    start_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ NOT NULL,
    stage_type  TEXT NOT NULL,   -- AWAKE / LIGHT / DEEP / REM
    UNIQUE (session_id, start_at)
);

CREATE INDEX IF NOT EXISTS idx_fitbit_sleep_sessions_device_time
    ON fitbit.sleep_sessions (device_id, start_at DESC);

-- fitbit.exercise_sessions — one row per exercise event, metricsSummary flattened
CREATE TABLE IF NOT EXISTS fitbit.exercise_sessions (
    id                       BIGSERIAL PRIMARY KEY,
    device_id                TEXT NOT NULL REFERENCES study.devices(id),
    start_at                 TIMESTAMPTZ NOT NULL,
    end_at                   TIMESTAMPTZ NOT NULL,
    exercise_type            TEXT,            -- "WALKING", etc.
    display_name             TEXT,
    calories_kcal            DOUBLE PRECISION,
    distance_mm              DOUBLE PRECISION,
    steps                    INTEGER,
    avg_pace_sec_per_meter   DOUBLE PRECISION,
    avg_heart_rate_bpm       INTEGER,
    light_time_sec           INTEGER,
    moderate_time_sec        INTEGER,
    vigorous_time_sec        INTEGER,
    peak_time_sec            INTEGER,
    ingestion_id             BIGINT REFERENCES raw.ingests(id),
    UNIQUE (device_id, start_at)
);

CREATE INDEX IF NOT EXISTS idx_fitbit_exercise_sessions_device_time
    ON fitbit.exercise_sessions (device_id, start_at DESC);
    
CREATE TABLE IF NOT EXISTS fitbit.profile (
    device_id              TEXT PRIMARY KEY REFERENCES study.devices(id),
    age                    INTEGER,
    membership_start_date  DATE,
    walking_stride_mm      INTEGER,
    running_stride_mm      INTEGER
);