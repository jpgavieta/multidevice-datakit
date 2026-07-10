# src/extract/extract.py
"""
The API Pull logic is device-agnostic. 
Is threaded per-device pulls with rate-limit awareness.
Invoked by scheduler/jobs.py.

"""

from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# from .utils import get_date_range # removed becos only get_date_range was in it

from general.device_registry import load_devices
from extract.clients import fitbit_client
# from extract.clients import atmotube_client   # no API key yet
# from extract.clients import ponyopi_client     # confirm still in scope

CLIENT_REGISTRY = {
    "fitbit": fitbit_client.extract_raw_data,
}

# ============================================================================================================

def get_date_range(device_start_date: str | None = None, end_date=None) -> tuple[date, date]:
    """
    Returns (start, end) as date objects for one device's pull.
    -   If device_start_date is set: pulls from that date forward (covers both first-ever backfill and normal runs 
        (*Postgres upserts mean re-pulling old dates is safe, just wasteful once history's already loaded).
    -   If device_start_date is unset: defaults to yesterday-only, for regular scheduled runs.
    """
    end = end_date or date.today()
    if device_start_date is not None:
        device_start_date = str(device_start_date)
        start = date.fromisoformat(device_start_date)
    else:
        start = end - timedelta(days=1)

    return start, end

def _pull_one_device(device_type: str, device_id: str, start_date: str, end_date: str):
    """Returns (device_id, raw_payload, error). raw_payload is untouched — no parsing here."""
    client_fn = CLIENT_REGISTRY.get(device_type)
    if client_fn is None:
        return device_id, None, NotImplementedError(f"No client registered for device_type={device_type}")
    try:
        return device_id, client_fn(device_id, start_date, end_date), None
    except Exception as e:
        return device_id, None, e


def extract_all_devices(
    config_path: str = "config/devices.yml",
    start_date: str | None = None,
    end_date: str | None = None,
    max_workers: int = 16
) -> dict[str, dict[str, dict]]:
    """Pulls raw API data for every device in the registry: device_type -> device_id -> raw_payload."""
    devices = load_devices(config_path)
    if not devices:
        print(f"❌ No devices found in {config_path}")
        return {}

    if end_date is None:
        end_date = date.today().isoformat()
    if start_date is None:
        start_date = (date.today() - timedelta(days=1)).isoformat()

    all_data: dict[str, dict[str, dict]] = {}
    print_lock = Lock()

    def safe_print(msg):
        with print_lock:
            print(msg)

    print(f"--- Pulling {len(devices)} device(s) from registry [{start_date} → {end_date}] ---")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_device = {
            executor.submit(
                _pull_one_device,
                d["type"], d["id"],
                *map(str, get_date_range(d.get("start_date")))
            ): d
            for d in devices
        }
        for future in as_completed(future_to_device):
            device = future_to_device[future]
            device_type, device_id = device["type"], device["id"]
            _, raw_payload, error = future.result()

            if raw_payload is None:
                safe_print(f"   ❌ Failed {device_id} [{device_type}]: {error}")
                continue

            all_data.setdefault(device_type, {})[device_id] = raw_payload
            safe_print(f"   ✅ Pulled {device_id} [{device_type}]")

    for device_type in list(all_data.keys()):
        print(f"  ✅ {device_type}: {len(all_data[device_type])} device_id(s) pulled")

    registered_types = {d["type"] for d in devices}
    for device_type in registered_types - all_data.keys():
        print(f"  ⚠️ {device_type}: No successful pulls")

    return all_data

# Example: data = extract_all_devices()