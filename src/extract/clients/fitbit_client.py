# src/extract/clients/fitbit_client.py

"""
Fitbit / Google Health API client to conduct the data pull — per device, per date range.
Returns raw API responses;, no participant logic.
"""

from datetime import datetime, timedelta
import requests
from extract.config.tokens import get_fitbit_token

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

MAX_WORKERS_PER_DEVICE = 4  # bounded on purpose — extract.py already threads across devices, 
                            # so an unbounded pool here would multiply out to dozens of simultaneous requests against the same API project

BASE_URL = "https://health.googleapis.com/v4"

# data type identifiers and respective scopes : https://developers.google.com/health/data-types

DATA_TYPES = [
    # scope: activity_and_fitness
    "steps",                        # interval
    "distance",                     # interval
    "altitude",                     # interval
    "sedentary-period",             # interval
    "exercise",                     # session, note: gps coordinates as routes data within ExerciseSessionRecord
    "active-minutes",               # interval, based on montion sensor + heart rate
    "active-zone-minutes",          # interval, note: based on heart rate
    "active-energy-burned",         # interval, note: accelerometer+heart rate, calories burned per min when activity level>"Sedentary",  estimated energy expenditure above resting Basal Metabolic Rate (BMR) calories (the energy burned for just existing)
    "activity-level",               # interval, note: autodetected or manual override, four zones: Sedentary, Lightly Active, Fairly Active, Very Active
    "calories-in-heart-rate-zone",  # interval, note: heart rate+manual profile entry 
    "daily-vo2-max",                # daily, note: cardio fittness score, estimate of max oxygen uptake (ml/kg/min), resting score during sleep (used as baseline); active score during GPS-enabled run/walk
    "floors",                       # interval, note: dataPoints.list unsupported by API — pulled via dailyRollUp instead (see DAILY_ROLLUP_TYPES)

    # scope: health_metrics_and_measurements
    "heart-rate",                   # sample
    "daily-resting-heart-rate",     # daily avg
    "daily-heart-rate-zones",       # daily avg
    "heart-rate-variability",       # sample
    "daily-heart-rate-variability", # daily avg
    "daily-respiratory-rate",       # daily avg
    "oxygen-saturation",            # sample
    "daily-oxygen-saturation",      # daily avg
    "daily-respiratory-rate",       # daily avg
    "respiratory-rate-sleep-summary", # sample
    "core-body-temperature",        # sampe, note: based on skin temp variations over 3 nights of data
    "daily-sleep-temperature-derivations", # daily avg, note: only for night
    "blood-glucose",                 # sample, note: manual profile entry
    "body-fat",                      # sample, note: manual profile entry
    "height",                        # sample, note: manual profile entry 
    "weight",                        # sample, note: manual profile entry

    # scope: sleep
    "sleep",                        # session
    # scope: irn
    "irregular-rhythm-notification",# session
    # scope: ecg
    "electrocardiogram"             # session, note: filter accepts start_time only — API rejects an end_time upper bound
]

# REST field path to filter on for each data type, used in the API request : https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/list

FILTER_FIELDS = {
    # Interval type
    "steps": "steps.interval.start_time",
    "distance": "distance.interval.start_time",
    "altitude": "altitude.interval.start_time",
    # "floors": not used for filtering — floors goes through dailyRollUp, not dataPoints.list
    "sedentary-period": "sedentary_period.interval.start_time",
    "active-minutes": "active_minutes.interval.start_time",
    "active-zone-minutes": "active_zone_minutes.interval.start_time",
    "active-energy-burned": "active_energy_burned.interval.start_time",  
    "activity-level": "activity_level.interval.start_time",              

    # Sample type
    "heart-rate": "heart_rate.sample_time.physical_time",
    "heart-rate-variability": "heart_rate_variability.sample_time.physical_time",
    "oxygen-saturation": "oxygen_saturation.sample_time.physical_time",
    "core-body-temperature": "core_body_temperature.sample_time.physical_time",
    "respiratory-rate-sleep-summary": "respiratory_rate_sleep_summary.sample_time.physical_time",
    "calories-in-heart-rate-zone": "calories_in_heart_rate_zone.sample_time.physical_time",  
    "blood-glucose": "blood_glucose.sample_time.physical_time",  
    "body-fat": "body_fat.sample_time.physical_time",             
    "height": "height.sample_time.physical_time",                 
    "weight": "weight.sample_time.physical_time",                

    # Daily type — API requires a plain civil date ("2026-01-10"), not a full
    # timestamp; confirmed via INVALID_DATA_POINT_FILTER_CIVIL_DATE_TIME_FORMAT
    "daily-resting-heart-rate": "daily_resting_heart_rate.date",
    "daily-heart-rate-variability": "daily_heart_rate_variability.date",
    "daily-heart-rate-zones": "daily_heart_rate_zones.date",
    "daily-oxygen-saturation": "daily_oxygen_saturation.date",
    "daily-respiratory-rate": "daily_respiratory_rate.date",
    "daily-sleep-temperature-derivations": "daily_sleep_temperature_derivations.date",
    "daily-vo2-max": "daily_vo2_max.date",   # ⚠️ UNVERIFIED — assumed daily-civil-date pattern given "daily-" prefix

    # Session type
    "sleep": "sleep.interval.end_time",
    "exercise": "exercise.interval.civil_start_time",
    "irregular-rhythm-notification": "irregular_rhythm_notification.interval.start_time",
    "electrocardiogram": "electrocardiogram.interval.start_time",
}


# Data types whose filter field expects a plain civil date ("2026-01-10"), not a full timestamp 
# Confirmed via API error message.
CIVIL_DATE_TYPES = {
    "daily-resting-heart-rate", "daily-heart-rate-zones",
    "daily-heart-rate-variability", "daily-respiratory-rate",
    "daily-oxygen-saturation", "daily-sleep-temperature-derivations",
    "daily-vo2-max",
}
## testing:
#  python -c "
# from extract.clients.fitbit_client import _extract_timestamp
# dp = {'dailyRestingHeartRate': {'date': {'year': 2026, 'month': 7, 'day': 9}, 'beatsPerMinute': '67'}}
# print(_extract_timestamp('daily-resting-heart-rate', dp))
# "


# Data types that only accept a lower-bound filter — an upper-bound clause causes a 400. 
# Confirmed for ECG via API error message.
START_ONLY_TYPES = {"electrocardiogram"}


# Data types using civil_start_time — bare ISO date/datetime, no UTC "Z" suffix.
# format YYYY-MM-DD[THH:mm:ss], operators >= and < only.
# Confirmed via Google's docs: pattern is {type}.interval.civil_start_time, and API error message
CIVIL_START_TIME_TYPES = {"exercise"}
## testing...
# python -c "
# from extract.config.tokens import get_fitbit_token
# from extract.clients.fitbit_client import _get_data_points
# import json
# token = get_fitbit_token('fitbit_kol_01')
# resp = _get_data_points(token, 'exercise', '2026-01-10', '2026-07-09')
# print(json.dumps(resp['dataPoints'][0], indent=2))
# "

# Data types that don't support dataPoints.list at all — the API rejects
# the "list" action and only supports reconcile/rollUp/dailyRollUp instead.
# Confirmed for floors via API error message. These get pulled through
# _get_daily_rollup() rather than _get_data_points(), and their response
# lives under "rollupDataPoints", not "dataPoints" — handled separately
# in find_earliest_data().
DAILY_ROLLUP_TYPES = {"floors", "calories-in-heart-rate-zone"}
## testing...
# python -c "
# from extract.config.tokens import get_fitbit_token
# from extract.clients.fitbit_client import _get_daily_rollup
# import json
# token = get_fitbit_token('fitbit_kol_01')
# resp = _get_daily_rollup(token, 'floors', '2026-01-10', '2026-07-09')
# print(json.dumps(resp, indent=2)[:2000])
# "

# Max query duration (days) per dailyRollUp data type — confirmed to vary
# per type via API error metadata (floors: 90, calories-in-heart-rate-zone: 14).
# Default conservatively to 14 for any future DAILY_ROLLUP_TYPES entries
# until confirmed otherwise.
ROLLUP_MAX_DURATION_DAYS = {
    "floors": 90,
    "calories-in-heart-rate-zone": 14,
}

# Some data types use a different field for filtering than for reading the
# actual value back out of the response — exercise is filtered via
# civil_start_time but the response only contains startTime/endTime under
# interval, not civilStartTime. floors is pulled via dailyRollUp, whose
# response uses civilStartTime, not any FILTER_FIELDS-listed path (floors
# has no FILTER_FIELDS entry at all, since it never goes through the filter
# query param). This maps data_type -> the real extraction path, overriding
# FILTER_FIELDS for extraction purposes only when it differs.
EXTRACT_FIELD_OVERRIDES = {
    "exercise": "exercise.interval.start_time",
    "floors": "civil_start_time",
    "calories-in-heart-rate-zone": "civil_start_time",
}



def _build_filter_expr(data_type: str, field: str, start_date: str, end_date: str) -> str:
    if data_type in CIVIL_DATE_TYPES:
        end_exclusive = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        return f'{field} >= "{start_date}" AND {field} < "{end_exclusive}"'

    if data_type in CIVIL_START_TIME_TYPES:
        end_exclusive = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        return f'{field} >= "{start_date}" AND {field} < "{end_exclusive}"'

    if data_type in START_ONLY_TYPES:
        return f'{field} >= "{start_date}T00:00:00Z"'

    end_exclusive = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    return f'{field} >= "{start_date}T00:00:00Z" AND {field} < "{end_exclusive}T00:00:00Z"'


def _get_data_points(access_token: str, data_type: str, start_date: str, end_date: str) -> dict:
    field = FILTER_FIELDS.get(data_type)
    if field is None:
        raise ValueError(f"No filter field configured for data type '{data_type}'")

    filter_expr = _build_filter_expr(data_type, field, start_date, end_date)

    resp = requests.get(
        f"{BASE_URL}/users/me/dataTypes/{data_type}/dataPoints",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        params={"filter": filter_expr},
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        print(f"    ↳ '{data_type}' response body: {resp.text}")
        raise
    return resp.json()


def _get_daily_rollup(access_token: str, data_type: str, start_date: str, end_date: str) -> dict:
    """
    Some data types (e.g. floors, calories-in-heart-rate-zone) don't support dataPoints.list — only reconcile/rollUp/dailyRollUp. 
    dailyRollUp caps the queryable duration (window_size_days * page_size) at a per-data-type limit, so wide ranges are chunked accordingly and merged.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    max_days = ROLLUP_MAX_DURATION_DAYS.get(data_type, 14)

    all_rollup_points = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=max_days - 1), end)

        body = {
            "range": {
                "start": {
                    "date": {"year": chunk_start.year, "month": chunk_start.month, "day": chunk_start.day},
                    "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": 0},
                },
                "end": {
                    "date": {"year": chunk_end.year, "month": chunk_end.month, "day": chunk_end.day},
                    "time": {"hours": 23, "minutes": 59, "seconds": 59, "nanos": 0},
                },
            },
            "windowSizeDays": 1,
        }

        resp = requests.post(
            f"{BASE_URL}/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            json=body,
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            print(f"    ↳ '{data_type}' (dailyRollUp) response body: {resp.text}")
            raise

        all_rollup_points.extend(resp.json().get("rollupDataPoints", []))
        chunk_start = chunk_end + timedelta(days=1)

    return {"rollupDataPoints": all_rollup_points}


def _fetch_one_type(access_token: str, data_type: str, start_date: str, end_date: str):
    """Returns (data_type, payload_or_None, error_or_None). Dispatches to the
    rollup or list endpoint depending on DAILY_ROLLUP_TYPES membership."""
    try:
        if data_type in DAILY_ROLLUP_TYPES:
            return data_type, _get_daily_rollup(access_token, data_type, start_date, end_date), None
        return data_type, _get_data_points(access_token, data_type, start_date, end_date), None
    except (requests.HTTPError, ValueError) as e:
        return data_type, None, e


def get_profile(access_token: str) -> dict: # shared between onboarding smoke-test and normal pulls
    resp = requests.get(
        f"{BASE_URL}/users/me/profile",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()


def _to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _extract_timestamp(data_type: str, dp: dict):
    """Pulls the timestamp out of one data point. Uses FILTER_FIELDS as the default source of truth for where it lives in the response, except for
    data types in EXTRACT_FIELD_OVERRIDES where the filter field and the actual response field differ."""
    field_path = EXTRACT_FIELD_OVERRIDES.get(data_type) or FILTER_FIELDS.get(data_type)
    if not field_path:
        return None
    path = [_to_camel(p) for p in field_path.split(".")]

    val = dp
    for key in path:
        if not isinstance(val, dict) or key not in val:
            return None
        val = val[key]
    return val

def _normalize_timestamp(data_type: str, value) -> str | None:
    """
    Converts an extracted timestamp value into a comparable ISO-ish string, regardless of which shape the API returned it in. 
    Handles three cases seen across Fitbit/Google Health responses so far:
        - plain string (interval/sample types, e.g. "2026-07-09T15:31:00Z")
        - flat civil-date dict (daily-* types, e.g. {"year", "month", "day"})
        - nested civil-date dict under "date" (session types like exercise,
        and rollup types like floors, e.g. {"date": {"year", "month", "day"}, "time": {...}})
    Returns None for unrecognized shapes (doesn't abort the scan across all data types) but prints a warning.
    NOTE: An unrecognized shape must stay visibly distinct fto avoid masking a real parsing bug.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and {"year", "month", "day"} <= value.keys():
        return f"{value['year']:04d}-{value['month']:02d}-{value['day']:02d}"
    if isinstance(value, dict) and "date" in value and isinstance(value["date"], dict):
        d = value["date"]
        if {"year", "month", "day"} <= d.keys():
            return f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"

    print(f"    ⚠️ '{data_type}': unrecognized timestamp shape, could not parse: {value!r}")
    return None

def find_earliest_data(device_id: str, start_date: str, end_date: str) -> dict[str, str | None]:
    """Returns {data_type: earliest_date_str_or_None} for this device over the given range."""
    raw = extract_raw_data(device_id, start_date, end_date)
    earliest = {}
    for data_type, payload in raw.items():
        if data_type == "profile":
            continue

        points_key = "rollupDataPoints" if data_type in DAILY_ROLLUP_TYPES else "dataPoints"

        if not payload or not payload.get(points_key):
            earliest[data_type] = None
            continue

        points = payload[points_key]
        raw_values = [_extract_timestamp(data_type, dp) for dp in points]
        timestamps = [_normalize_timestamp(data_type, v) for v in raw_values]
        timestamps = [t for t in timestamps if t is not None]

        if not timestamps and points:
            print(f"    ⚠️ '{data_type}': had {len(points)} data point(s) but none parsed successfully")

        earliest[data_type] = min(timestamps) if timestamps else None
    return earliest


def extract_raw_data(device_id: str, start_date: str, end_date: str, allow_interactive: bool = False) -> dict:
    """
    Pulls all Fitbit data types for one device over one date range.
    Returns raw, unmodified JSON response:
        {"steps": {...}, "heart-rate": {...}, "sleep": {...}, "distance": {...}, "profile": {...}}
    Any single data type failing doesn't stop the others. Data types are
    fetched concurrently, bounded to MAX_WORKERS_PER_DEVICE to avoid stacking on top of extract.py's own per-device threading.
    No parsing here — that's transform's job, later
    """
    try:
        access_token = get_fitbit_token(device_id, allow_interactive=allow_interactive)
    except Exception as e:
        raise NotImplementedError(
            f"Fitbit client not yet wired up for {device_id}: {e}"
        ) from e

    raw = {}
    print_lock = Lock()

    def safe_print(msg):
        with print_lock:
            print(msg)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS_PER_DEVICE) as executor:
        futures = {
            executor.submit(_fetch_one_type, access_token, dt, start_date, end_date): dt
            for dt in DATA_TYPES
        }
        for future in as_completed(futures):
            data_type, payload, error = future.result()
            if error is not None:
                safe_print(f"  ⚠️ '{device_id}' failed to fetch '{data_type}': {error}")
            raw[data_type] = payload

    try:
        raw["profile"] = get_profile(access_token)
    except requests.HTTPError as e:
        print(f"  ⚠️ '{device_id}' failed to fetch profile: {e}")
        raw["profile"] = None

    return raw