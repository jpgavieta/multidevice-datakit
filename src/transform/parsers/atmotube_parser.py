# transform/parsers/atmotube_parser.py
"""
Parses raw Atmotube API responses (from extract/clients/atmotube_client.py,
live or replayed via backfill_atmotube.py) into a single DataFrame matching
atmotube.readings.

date is already true UTC ISO 8601 — no timezone conversion needed here,
unlike Fitbit's daily-grain records.

location is NOT built as a geometry object in pandas — that's fragile and
unnecessary. This parser emits plain 'latitude'/'longitude' columns; load.py
builds the PostGIS point at insert time via ST_SetSRID(ST_MakePoint(...)).
"""

import pandas as pd

from .atmotube_registry import ATMOTUBE_REGISTRY


def parse(raw_data: dict, device_id: str) -> dict:
    """
    Takes the raw dict returned by extract.clients.atmotube_client.extract_raw_data()
    (or the equivalent reconstructed by backfill_atmotube.py), returns
    {"readings": DataFrame} shaped to match atmotube.readings' columns exactly
    (minus id/ingestion_id, which load.py fills in once the raw row is inserted).
    """
    records = raw_data.get("merged_data", [])
    if not records:
        return {"readings": pd.DataFrame()}

    df = pd.DataFrame(records)

    # recorded_at — already UTC, just needs parsing
    df["recorded_at"] = pd.to_datetime(df["date"], utc=True)

    # lat/lon kept as plain columns — geometry built later, in load.py's SQL
    df["latitude"] = df.get("lat")
    df["longitude"] = df.get("lon")

    out = pd.DataFrame({"recorded_at": df["recorded_at"],
                        "latitude": df["latitude"],
                        "longitude": df["longitude"]})

    for raw_key, (standard_name, _unit, dtype, _category) in ATMOTUBE_REGISTRY.items():
        if raw_key not in df.columns:
            out[standard_name] = pd.Series([pd.NA] * len(df), dtype=dtype)
            continue
        out[standard_name] = df[raw_key].astype(dtype)

    out["device_id"] = device_id

    return {"readings": out}