# src/load/load.py
"""
Pushes raw API payloads and processed data into the database.
    -   raw.ingests stores exact API responses as JSONB (JSONs as binary not text)
    -   processed tables (fitbit.*, atmotube.*) are populated by load_processed_data(),
        using the row-dicts produced by transform.transform_device_data().

Everything upserts on each table's declared UNIQUE key, so re-pulling overlapping
date ranges (e.g. backfill windows, or a scheduler retry) is safe — rows get
updated in place rather than duplicated. raw.ingests is the one exception: it's
an append-only log of pipeline runs, so every call to load_raw_data() adds new
rows regardless of payload content.
"""

import os
import json
from pathlib import Path
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# ============================================================================================================


ENV_PATH = Path(__file__).resolve().parents[2] / "deploy" / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Maps (device_type, transform.py table_name) -> (sql_table, conflict_cols) for upserting.
# sleep_stages is handled separately (needs session_id FK resolution first).
DESTINATION_TABLES = {
    ("fitbit", "readings"):          ("fitbit.readings",          ("device_id", "data_type", "recorded_at", "metric", "tag")),
    ("fitbit", "states"):            ("fitbit.states",            ("device_id", "data_type", "recorded_at")),
    ("fitbit", "sleep_sessions"):    ("fitbit.sleep_sessions",    ("device_id", "start_at")),
    ("fitbit", "exercise_sessions"): ("fitbit.exercise_sessions", ("device_id", "start_at")),
    ("atmotube", "readings"):        ("atmotube.readings",        ("device_id", "recorded_at")),
}
SLEEP_STAGES_TABLE = "fitbit.sleep_stages"
SLEEP_STAGES_CONFLICT_COLS = ("session_id", "started_at")

# ============================================================================================================


def _get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", 5432),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def load_raw_data(all_data: dict[str, dict[str, dict]]) -> dict[tuple[str, str], int]:
    """
    Pushes raw API payloads into raw.ingests, one row per device per pull.
    all_data shape: { device_type: { device_id: {"payload": ..., "ingest_method": ...} } }
    — matches extract.py's extract_all_devices() output. For CSV backfills
    (extract/scripts/backfill_atmotube.py), the same shape applies with
    ingest_method="csv_manual".

    Returns { (device_type, device_id): ingestion_id } so load_processed_data()
    can stamp every processed row with the raw.ingests row it came from.
    """
    pulled_at = datetime.now(timezone.utc)
    keys, rows = [], []
    for device_type, devices in all_data.items():
        for device_id, entry in devices.items():
            keys.append((device_type, device_id))
            rows.append((device_type, device_id, entry["ingest_method"], pulled_at, json.dumps(entry["payload"])))

    if not rows:
        print("⚠️ No raw data to load.")
        return {}

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            returned = execute_values(
                cur,
                "INSERT INTO raw.ingests (device_type, device_id, ingest_method, pulled_at, payload) VALUES %s RETURNING id",
                rows,
                template="(%s, %s, %s, %s, %s::jsonb)",
                fetch=True,
            )
        conn.commit()
        print(f"✅ Loaded {len(rows)} raw record(s) into raw.ingests")
    except Exception as e:
        conn.rollback()
        print(f"❌ Raw load failed: {e}")
        raise
    finally:
        conn.close()

    # Postgres processes/returns multi-row VALUES+RETURNING in input order, so this
    # zip is safe — each returned id lines up with the key at the same position.
    return {key: returned_row[0] for key, returned_row in zip(keys, returned)}


def _upsert_rows(cur, table: str, rows: list[dict], conflict_cols: tuple, returning: tuple = ("id",)) -> list[dict]:
    """
    Generic upsert: INSERT ... ON CONFLICT (conflict_cols) DO UPDATE, returning the
    requested columns per row (used for FK resolution, e.g. sleep_sessions -> id).
    Every row must share the same set of keys (parser output should guarantee this).
    """
    if not rows:
        return []

    columns = list(rows[0].keys())
    for row in rows:
        if row.keys() != rows[0].keys():
            raise ValueError(f"Inconsistent row columns for {table}: {sorted(row.keys())} vs {sorted(rows[0].keys())}")

    update_cols = [c for c in columns if c not in conflict_cols]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    returning_clause = ", ".join(returning)

    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
        f"ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET {set_clause} "
        f"RETURNING {returning_clause}"
    )
    template = "(" + ", ".join(["%s"] * len(columns)) + ")"
    values = [tuple(row.get(c) for c in columns) for row in rows]

    result_rows = execute_values(cur, sql, values, template=template, fetch=True)
    return [dict(zip(returning, r)) for r in result_rows]


def load_processed_data(
    transformed: dict[str, dict[str, dict]],
    ingestion_ids: dict[tuple[str, str], int],
) -> None:
    """
    Inserts transform.py's output into the processed schema tables (fitbit.*, atmotube.*).

    Parameters
    ----------
    transformed : dict
        { device_type: { device_id: { "data": { table_name: [ {row}, ... ] } } } } —
        output of transform.transform_device_data(). Every table_name's rows are
        list[dict], ready for execute_values() (parsers no longer emit DataFrames).
    ingestion_ids : dict
        { (device_type, device_id): ingestion_id } — output of load_raw_data().
    """
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            for device_type, device_files in transformed.items():
                for device_id, entry in device_files.items():
                    ingestion_id = ingestion_ids.get((device_type, device_id))
                    data = entry.get("data", {})

                    # sleep_sessions must land first — sleep_stages needs the generated
                    # session_id, resolved below via each stage's session_start_at.
                    session_id_by_start = {}
                    if "sleep_sessions" in data and data["sleep_sessions"]:
                        sql_table, conflict_cols = DESTINATION_TABLES[("fitbit", "sleep_sessions")]
                        rows = [{**r, "ingestion_id": ingestion_id} for r in data["sleep_sessions"]]
                        returned = _upsert_rows(cur, sql_table, rows, conflict_cols, returning=("id", "start_at"))
                        session_id_by_start = {r["start_at"]: r["id"] for r in returned}
                        print(f"   ✅ Loaded {len(rows)} row(s) into {sql_table} for {device_type}/{device_id}")

                    for table_name, rows in data.items():
                        if table_name == "sleep_sessions" or not rows:
                            continue

                        if table_name == "sleep_stages":
                            resolved = []
                            for row in rows:
                                row = dict(row)  # don't mutate the parser's own output
                                session_start = row.pop("session_start_at", None)
                                row.pop("device_id", None)  # join key only — not a sleep_stages column
                                session_id = session_id_by_start.get(session_start)
                                if session_id is None:
                                    print(f"   ⚠️ No matching sleep_session for stage at "
                                          f"{row.get('started_at')} ({device_type}/{device_id}) — skipping.")
                                    continue
                                row["session_id"] = session_id
                                resolved.append(row)
                            if resolved:
                                _upsert_rows(cur, SLEEP_STAGES_TABLE, resolved, SLEEP_STAGES_CONFLICT_COLS)
                                print(f"   ✅ Loaded {len(resolved)} row(s) into {SLEEP_STAGES_TABLE} for {device_type}/{device_id}")
                            continue

                        key = (device_type, table_name)
                        if key not in DESTINATION_TABLES:
                            print(f"   ⚠️ No destination table registered for {key} — skipping {len(rows)} row(s).")
                            continue
                        sql_table, conflict_cols = DESTINATION_TABLES[key]
                        tagged_rows = [{**r, "ingestion_id": ingestion_id} for r in rows]
                        _upsert_rows(cur, sql_table, tagged_rows, conflict_cols)
                        print(f"   ✅ Loaded {len(tagged_rows)} row(s) into {sql_table} for {device_type}/{device_id}")

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"❌ Processed load failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    from extract.extract import extract_all_devices
    from transform.transform import transform_device_data

    raw = extract_all_devices()
    ingestion_ids = load_raw_data(raw)
    transformed = transform_device_data(raw)
    load_processed_data(transformed, ingestion_ids)