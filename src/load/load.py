# src/load/load.py
"""
Pushes raw API payloads into the database. No transform/parsing here —
raw.api_pulls stores exact API responses as JSONB (JSONs as binary not text); processed tables are
populated separately, later, by the transform step.
"""

import os
import json
from pathlib import Path
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / "deploy" / ".env"
load_dotenv(dotenv_path=ENV_PATH)


def _get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", 5432),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def load_raw_data(all_data: dict[str, dict[str, dict]]) -> None:
    """
    Pushes raw API payloads into raw.api_pulls, one row per device per pull.
    all_data shape: { device_type: { device_id: raw_payload } }
    """
    pulled_at = datetime.now(timezone.utc)
    rows = [
        (device_type, device_id, pulled_at, json.dumps(payload))
        for device_type, devices in all_data.items()
        for device_id, payload in devices.items()
    ]

    if not rows:
        print("⚠️ No raw data to load.")
        return

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            execute_values(
                cur,
                "INSERT INTO raw.api_pulls (device_type, device_id, pulled_at, payload) VALUES %s",
                rows,
                template="(%s, %s, %s, %s::jsonb)",
            )
        conn.commit()
        print(f"✅ Loaded {len(rows)} raw record(s) into raw.api_pulls")
    except Exception as e:
        conn.rollback()
        print(f"❌ Load failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    from extract.extract import extract_all_devices

    data = extract_all_devices()
    load_raw_data(data)