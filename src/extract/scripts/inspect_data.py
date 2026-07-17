# src/extract/scripts/inspect_data.py
"""
Ad-hoc inspector for a single device's raw API response — works across
device types (fitbit, atmotube). Prints record counts and a sample record
so you can confirm response shapes or debug auth/filter errors before
wiring a fix into the real client.

Not part of the pipeline — this is a debugging tool, run manually.

USAGE:
    # Fitbit — inspect one data type
python -m extract.scripts.inspect_data fitbit_kol_01 --data-type daily-resting-heart-rate

    # Fitbit — full response for ONE type, not just first point
python -m extract.scripts.inspect_data fitbit_kol_01 --data-type floors --full

    # Fitbit — one sample record from EVERY non-empty data type (for building
    # the field-mapping registry — much more useful than --full, which dumps
    # every single record across all 21+ types)
python -m extract.scripts.inspect_data fitbit_kol_01 --samples

    # Fitbit — FULL response for EVERY non-empty data type (no --data-type needed)
    # --full alone triggers the multi-type loop, same as --samples, but prints every record instead of just the first per type
python -m extract.scripts.inspect_data fitbit_kol_01 --full
# OR (to save as a JSON file)
python -m extract.scripts.inspect_data fitbit_kol_01 --full > fitbit_kol_01_full.json

    # Fitbit — force dailyRollUp for a type not yet in DAILY_ROLLUP_TYPES
python -m extract.scripts.inspect_data fitbit_kol_01 --data-type floors --rollup

    # Atmotube — no --data-type needed, one data stream per device
python -m extract.scripts.inspect_data atmotube_kol_01

    # Custom date range (default: last 30 days if no --end)
python -m extract.scripts.inspect_data atmotube_kol_01 --start 2026-07-01 --end 2026-07-09
"""

import argparse
import json
from datetime import date, timedelta

from general.device_registry import load_devices

# ============================================================================================================


def _inspect_fitbit(device: dict, args):
    from extract.config.tokens import get_fitbit_token
    from extract.clients.fitbit_client import (
        _get_data_points,
        _get_daily_rollup,
        DAILY_ROLLUP_TYPES,
        extract_raw_data,
    )

    if args.samples or (args.full and not args.data_type):
        raw = extract_raw_data(device, args.start, args.end)
        label = "full response, every data type" if args.full else "one sample per data type"
        print(f"\nfitbit [{device['id']}]: {label} [{args.start} → {args.end}]")

        for data_type, payload in raw.items():
            if data_type == "profile":
                if payload:
                    print(f"\n=== profile ===")
                    print(json.dumps(payload, indent=2))
                else:
                    print(f"\n=== profile === None")
                continue

            points_key = "rollupDataPoints" if data_type in DAILY_ROLLUP_TYPES else "dataPoints"
            points = payload.get(points_key, []) if payload else []
            if not points:
                continue
            print(f"\n=== {data_type} ({len(points)} point(s)) ===")
            if args.full:
                print(json.dumps(points, indent=2))
            else:
                print(json.dumps(points[0], indent=2))
        return

    if not args.data_type:
        print("❌ --data-type is required for fitbit devices (or use --samples / --full for all types)")
        return

    token = get_fitbit_token(device["id"])
    use_rollup = args.rollup or args.data_type in DAILY_ROLLUP_TYPES

    if use_rollup:
        resp = _get_daily_rollup(token, args.data_type, args.start, args.end)
        points = resp.get("rollupDataPoints", [])
    else:
        resp = _get_data_points(token, args.data_type, args.start, args.end)
        points = resp.get("dataPoints", [])

    print(f"\n{args.data_type}: {len(points)} data point(s) [{args.start} → {args.end}]")
    if args.full:
        print(json.dumps(resp, indent=2))
    elif points:
        print(json.dumps(points[0], indent=2))


def _inspect_atmotube(device: dict, args):
    from extract.clients.atmotube_client import extract_raw_data

    result = extract_raw_data(device, args.start, args.end)
    records = result["merged_data"]

    print(f"\natmotube [{device['id']}]: {len(records)} record(s) [{args.start} → {args.end}]")
    print(f"MAC: {result['mac']}")  # never print api_key — only credential-adjacent field worth showing

    if records:
        dates = [r.get("date") for r in records]
        unique_dates = set(dates)
        if len(dates) != len(unique_dates):
            dupes = len(dates) - len(unique_dates)
            print(f"  ❌ Found {dupes} duplicate timestamp(s) — check chunk/cursor-page boundary logic")
        sorted_dates = sorted(dates)
        print(f"  From: {sorted_dates[0]}   To: {sorted_dates[-1]}")

    if args.full:
        print(json.dumps(result, indent=2))
    elif records:
        print(json.dumps(records[0], indent=2))

INSPECTORS = {
    "fitbit": _inspect_fitbit,
    "atmotube": _inspect_atmotube,
}


def main():
    parser = argparse.ArgumentParser(description="Inspect a raw API response for one device.")
    parser.add_argument("device_id")
    parser.add_argument("--data-type", default=None, help="Required for fitbit unless --samples/--full used alone")
    parser.add_argument("--start", default=str(date.today() - timedelta(days=30)))
    parser.add_argument("--end", default=str(date.today()))
    parser.add_argument("--full", action="store_true", help="Print full response(s), not just the first record")
    parser.add_argument("--rollup", action="store_true", help="Fitbit only: force dailyRollUp")
    parser.add_argument("--samples", action="store_true", help="Fitbit only: print one sample record per non-empty data type")
    args = parser.parse_args()

    devices = {d["id"]: d for d in load_devices()}
    device = devices.get(args.device_id)
    if device is None:
        print(f"❌ '{args.device_id}' not found in config/devices.yml")
        return

    inspector = INSPECTORS.get(device["type"])
    if inspector is None:
        print(f"❌ No inspector implemented for device_type='{device['type']}'")
        return

    inspector(device, args)


if __name__ == "__main__":
    main()