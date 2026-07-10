# src/extract/config/tokens.py
"""
Central credential resolver for all device APIs.

Each service (Fitbit, Atmotube, ...) has its own auth module with its own logic, since auth mechanisms differ (OAuth vs. static API key). 
This file is just the single import surface clients use, so fitbit_client.py and atmotube_client.py don't need to know which specific module their credentials come from.

TO ADD A NEW DEVICE API:
    1. Create a new module in extract/config/ for that device's auth logic.
    2. Add a new function here that calls the new module's credential getter.
    3. Update the device config (devices.yml) to include any new secrets needed.
"""

from .fitbit_tokens import get_access_token as _fitbit_get_access_token
# from .atmotube_tokens import get_api_key as get_atmotube_key   # uncomment once built


def get_fitbit_token(device_id: str, allow_interactive: bool = False) -> str:
    return _fitbit_get_access_token(device_id, allow_interactive=allow_interactive)


# def get_atmotube_token(device_id: str) -> str:
#     from extract.config.atmotube_tokens import get_access_token as _atmotube_get_access_token
#     return _atmotube_get_access_token(device_id)