# transform/parsers/fitbit_parser.py
"""
Parses raw Fitbit / Google Health API responses (from extract/clients/fitbit_client.py)
into row-dicts matching fitbit.readings / fitbit.states / fitbit.sleep_sessions /
fitbit.sleep_stages / fitbit.exercise_sessions — ready for execute_values(), not DataFrames.

Timestamps: 'sample' and 'interval' grain fields (startTime/endTime/physicalTime)
are already Z-normalized UTC — parsed directly, no conversion. 'daily' grain
fields are a bare {year, month, day} with no offset — these are localized to
midnight in the DEVICE'S declared timezone (from study.devices / devices.yml),
then converted to UTC. civilStartTime/civilEndTime are never used for timestamps.
"""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .registry.fitbit_registry import FITBIT_REGISTRY, BESPOKE_DATA_TYPES, UNMAPPED_DATA_TYPES


def _to_camel(data_type: str) -> str:
    """'daily-resting-heart-rate' -> 'dailyRestingHeartRate' — matches the
    nested key Fitbit wraps each data point's payload in."""
    head, *rest = data_type.split("-")
    return head + "".join(w.capitalize() for w in rest)


def _get_points(payload: dict) -> list:
    if not payload:
        return []
    return payload.get("dataPoints") or payload.get("rollupDataPoints") or []


def _get(d: dict, path: str) -> Any:
    """Dotted-path lookup, tolerant of missing keys at any depth."""
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _start_end(nested: dict, grain: str, tz_name: str):
    if grain == "sample":
        start = pd.to_datetime(_get(nested, "sampleTime.physicalTime"), utc=True)
        return start, None

    if grain == "interval":
        start = pd.to_datetime(_get(nested, "interval.startTime"), utc=True)
        end = pd.to_datetime(_get(nested, "interval.endTime"), utc=True)
        return start, end

    if grain == "daily":
        d = nested.get("date", {})
        local_midnight = datetime(d["year"], d["month"], d["day"], tzinfo=ZoneInfo(tz_name))
        local_next = local_midnight + timedelta(days=1)
        return (
            pd.Timestamp(local_midnight).tz_convert("UTC"),
            pd.Timestamp(local_next).tz_convert("UTC"),
        )

    raise ValueError(f"Unknown grain: {grain}")


def _parse_registry_type(data_type: str, points: list, device_id: str, tz_name: str, rules: dict):
    """Generic engine for the ~15 data types that reduce to a lookup rule."""
    camel = _to_camel(data_type)
    rows = []
    grain = rules["grain"]

    for point in points:
        nested = point.get(camel, {})
        start, end = _start_end(nested, grain, tz_name)
        base = {"device_id": device_id, "data_type": data_type, "grain": grain,
                "recorded_at": start, "end_at": end}

        if rules["destination"] == "states":
            label = (_get(nested, rules["state_field"])
                      if rules["state_field"] else rules["constant_label"])
            rows.append({**base, "state_value": label})
            continue

        kind = rules["kind"]

        if kind == "scalar":
            val = _get(nested, rules["value_field"])
            rows.append({**base, "metric": rules["metric"], "tag": None, "value_numeric": val})

        elif kind == "tagged_scalar":
            val = _get(nested, rules["value_field"])
            tag = _get(nested, rules["tag_field"])
            rows.append({**base, "metric": rules["metric"], "tag": tag, "value_numeric": val})

        elif kind == "list_fanout":
            for item in _get(nested, rules["list_field"]) or []:
                rows.append({**base, "metric": rules["metric"],
                            "tag": item.get(rules["tag_field"]),
                            "value_numeric": item.get(rules["value_field"])})

        elif kind == "tag_map":
            for field, tag in rules["tag_map"].items():
                val = nested.get(field)
                if val is None:
                    continue
                rows.append({**base, "metric": rules["metric"], "tag": tag, "value_numeric": val})

        elif kind == "field_map":
            for field, (metric, _unit, _dtype) in rules["fields"].items():
                val = nested.get(field)
                if val is None:
                    continue
                rows.append({**base, "metric": metric, "tag": None, "value_numeric": val})

    return rows


def _parse_hr_zones(points: list, device_id: str, tz_name: str) -> list:
    """daily-heart-rate-zones — calibration data, one row per (zone, bound)."""
    rows = []
    for point in points:
        nested = point.get("dailyHeartRateZones", {})
        start, end = _start_end(nested, "daily", tz_name)
        base = {"device_id": device_id, "data_type": "daily-heart-rate-zones",
                "grain": "daily", "recorded_at": start, "end_at": end, "metric": "hr_zone_bpm"}
        for zone in nested.get("heartRateZones", []):
            zone_name = zone.get("heartRateZoneType")
            for bound, suffix in (("minBeatsPerMinute", "min"), ("maxBeatsPerMinute", "max")):
                rows.append({**base, "tag": f"{zone_name}_{suffix}", "value_numeric": zone.get(bound)})
    return rows


def _parse_respiratory_sleep_summary(points: list, device_id: str, tz_name: str) -> list:
    """respiratory-rate-sleep-summary — 4 sleep stages x 3 metrics each, tagged by stage."""
    stage_keys = {"deepSleepStats": "deep", "lightSleepStats": "light",
                  "remSleepStats": "rem", "fullSleepStats": "full"}
    field_metrics = {
        "breathsPerMinute": "respiratory_rate_brpm",
        "standardDeviation": "respiratory_rate_stddev",
        "signalToNoise": "respiratory_rate_snr",
    }
    rows = []
    for point in points:
        nested = point.get("respiratoryRateSleepSummary", {})
        start, _ = _start_end(nested, "sample", tz_name)
        base = {"device_id": device_id, "data_type": "respiratory-rate-sleep-summary",
                "grain": "sample", "recorded_at": start, "end_at": None}
        for stage_key, stage_tag in stage_keys.items():
            stage = nested.get(stage_key, {})
            for field, metric in field_metrics.items():
                if field not in stage:
                    continue
                rows.append({**base, "metric": metric, "tag": stage_tag, "value_numeric": stage[field]})
    return rows


def _parse_sleep(points: list, device_id: str) -> tuple[list, list]:
    """sleep — one session row + N stage child rows per record."""
    sessions, stages = [], []
    for point in points:
        nested = point.get("sleep", {})
        start = pd.to_datetime(_get(nested, "interval.startTime"), utc=True)
        end = pd.to_datetime(_get(nested, "interval.endTime"), utc=True)
        summary = nested.get("summary", {})
        sessions.append({
            "device_id": device_id, "started_at": start, "end_at": end,
            "sleep_type": nested.get("type"),
            "is_nap": (nested.get("metadata") or {}).get("nap"),
            "minutes_in_sleep_period": summary.get("minutesInSleepPeriod"),
            "minutes_after_wakeup": summary.get("minutesAfterWakeUp"),
            "minutes_to_fall_asleep": summary.get("minutesToFallAsleep"),
            "minutes_asleep": summary.get("minutesAsleep"),
            "minutes_awake": summary.get("minutesAwake"),
        })
        for stage in nested.get("stages", []):
            stages.append({
                "device_id": device_id,          # resolved to session_id in load.py, after the session insert
                "session_started_at": start,       # join key back to the parent session row
                "started_at": pd.to_datetime(stage["startTime"], utc=True),
                "ended_at": pd.to_datetime(stage["endTime"], utc=True),
                "stage_type": stage.get("type"),
            })
    return sessions, stages


def _parse_exercise(points: list, device_id: str) -> list:
    """exercise — one row per event, metricsSummary flattened."""
    rows = []
    for point in points:
        nested = point.get("exercise", {})
        start = pd.to_datetime(_get(nested, "interval.startTime"), utc=True)
        end = pd.to_datetime(_get(nested, "interval.endTime"), utc=True)
        summary = nested.get("metricsSummary", {})
        zone_durations = summary.get("heartRateZoneDurations", {})
        rows.append({
            "device_id": device_id, "started_at": start, "end_at": end,
            "exercise_type": nested.get("exerciseType"),
            "display_name": nested.get("displayName"),
            "calories_kcal": summary.get("caloriesKcal"),
            "distance_mm": summary.get("distanceMillimeters"),
            "steps": summary.get("steps"),
            "avg_pace_sec_per_meter": summary.get("averagePaceSecondsPerMeter"),
            "avg_heart_rate_bpm": summary.get("averageHeartRateBeatsPerMinute"),
            "light_time_sec": zone_durations.get("lightTime"),
            "moderate_time_sec": zone_durations.get("moderateTime"),
            "vigorous_time_sec": zone_durations.get("vigorousTime"),
            "peak_time_sec": zone_durations.get("peakTime"),
        })
    return rows


def parse(raw_data: dict, device_id: str, timezone: str) -> dict:
    """
    Takes the raw dict from extract.clients.fitbit_client.extract_raw_data(),
    plus the device's declared timezone (from study.devices — needed only for
    'daily' grain records), returns row-dicts keyed by destination table, ready
    for execute_values() — NOT DataFrames:
    {"readings": [ {...}, ... ], "states": [...], "sleep_sessions": [...],
     "sleep_stages": [...], "exercise_sessions": [...]} — a key is omitted if
    that device's pull had no rows for that destination.
    """
    readings_rows, states_rows = [], []
    sleep_sessions, sleep_stages, exercise_rows = [], [], []

    for data_type, payload in raw_data.items():
        if data_type == "profile":
            continue
        points = _get_points(payload)
        if not points:
            continue

        if data_type in FITBIT_REGISTRY:
            rules = FITBIT_REGISTRY[data_type]
            rows = _parse_registry_type(data_type, points, device_id, timezone, rules)
            (states_rows if rules["destination"] == "states" else readings_rows).extend(rows)

        elif data_type == "daily-heart-rate-zones":
            readings_rows.extend(_parse_hr_zones(points, device_id, timezone))

        elif data_type == "respiratory-rate-sleep-summary":
            readings_rows.extend(_parse_respiratory_sleep_summary(points, device_id, timezone))

        elif data_type == "sleep":
            s, st = _parse_sleep(points, device_id)
            sleep_sessions.extend(s)
            sleep_stages.extend(st)

        elif data_type == "exercise":
            exercise_rows.extend(_parse_exercise(points, device_id))

        elif data_type in UNMAPPED_DATA_TYPES:
            print(f"⚠️ '{data_type}' has data but no registry mapping yet — skipping {len(points)} point(s).")

        else:
            print(f"⚠️ '{data_type}' is unrecognized — not in FITBIT_REGISTRY, BESPOKE, or UNMAPPED sets.")

    result = {}
    if readings_rows:
        result["readings"] = readings_rows
    if states_rows:
        result["states"] = states_rows
    if sleep_sessions:
        result["sleep_sessions"] = sleep_sessions
    if sleep_stages:
        result["sleep_stages"] = sleep_stages
    if exercise_rows:
        result["exercise_sessions"] = exercise_rows

    return result