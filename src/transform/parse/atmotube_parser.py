# transform/parsers/atmotube_parser.py
"""
Parses raw Atmotube API responses (from extract/clients/atmotube_client.py,
live or replayed via backfill_atmotube.py) into row-dicts matching
atmotube.readings — ready for execute_values(), same shape fitbit_parser.py emits.

date is already true UTC ISO 8601 — no explicit parsing happens here or in
load.py; the raw string is passed straight through to psycopg2, and Postgres
does the text -> TIMESTAMPTZ cast implicitly on insert into recorded_at.

latitude/longitude are kept as plain float fields on each row-dict (NOT built
into a geometry object here) — load.py's _build_location() turns them into an
EWKT point string at insert time (wrapped in ST_GeomFromEWKT(...) via the
WKT_COLUMNS mapping in _upsert_rows()), so both keys survive this parser only
to be popped by load.py's _prepare_atmotube_rows() once the geometry's built.
"""

from ..register.atmotube_registry import ATMOTUBE_REGISTRY


def parse(raw_data: dict, device_id: str, timezone: str | None = None) -> dict:
    """
    Takes the raw dict returned by extract.clients.atmotube_client.extract_raw_data()
    (or the equivalent reconstructed by backfill_atmotube.py), returns
    {"readings": [ {row}, ... ]} — one dict per record, keys matching
    atmotube.readings' columns exactly (minus id/ingestion_id/location, which
    load.py fills in: ingest_id once the raw row is inserted, location from
    latitude/longitude via _build_location()).

    timezone is accepted but unused — Atmotube's 'date' field is already true UTC,
    no localization needed. It's here only so transform.py can call every parser
    with the same (payload, device_id, timezone) signature without branching on
    device_type.
    """
    records = raw_data.get("merged_data", [])
    if not records:
        return {"readings": []}

    rows = []
    for record in records:
        row = {
            "device_id": device_id,
            "recorded_at": record.get("date"),   # passed through as-is; Postgres casts on insert
            "latitude": record.get("lat"),
            "longitude": record.get("lon"),
        }
        for raw_key, (standard_name, _unit, _dtype, _category) in ATMOTUBE_REGISTRY.items():
            row[standard_name] = record.get(raw_key)
        rows.append(row)

    return {"readings": rows}