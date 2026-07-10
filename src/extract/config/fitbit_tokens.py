# src/extract/config/fitbit_tokens.py
"""
Fitbit / Google Health OAuth — per-device tokens, shared OAuth client.

Each physical device has its own Google account and its own token file.
The OAuth client (client_id/client_secret) is shared across all devices.

Each _tokens.py module NEVER touch each other — ONLY tokens.py
"""

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

# fitbit_tokens.py
CONFIG_DIR = Path(__file__).resolve().parent   # .../src/extract/config
CLIENT_SECRETS_FILE = CONFIG_DIR / "secrets" / "fitbit" / "client_secret.json"
TOKENS_DIR = CONFIG_DIR / "secrets" / "fitbit" / "tokens"

AUTH_PORT = 8765
REDIRECT_URI = f"http://localhost:{AUTH_PORT}"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

SCOPES = [
    # Steps, distance, floors, active minutes, active zone minutes, exercise sessions,
    # VO2 max, calories (total/active), altitude, sedentary periods, heart rate zones
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",

    # Heart rate, HRV, resting heart rate, oxygen saturation (SpO2), respiratory rate,
    # body fat, weight, sleep temperature derivations
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",

    # GPS data tied to a recorded exercise session, exposed in TCX format
    "https://www.googleapis.com/auth/googlehealth.location.readonly",

    # # Nutrition/food log data (participants arent using it)
    # "https://www.googleapis.com/auth/googlehealth.nutrition.readonly",

    # Sleep sessions, stages (awake/light/deep/REM), sleep summary
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",

    # Fitbit user ID + Google user ID + basic profile fields — not a time-series type
    "https://www.googleapis.com/auth/googlehealth.profile.readonly",

    # Irregular Rhythm Notification engagement status (via getIrnProfile) —
    # confirm this actually returns data for your device models before relying on it;
    # IRN is a specific feature not present on all Fitbit hardware.
    "https://www.googleapis.com/auth/googlehealth.irn.readonly",

    # ECG (electrocardiogram) readings — only relevant if your devices are
    # ECG-capable hardware (e.g. Sense/Charge with ECG sensor). Some reporting
    # suggests this may require separate approval beyond standard OAuth consent —
    # worth testing early rather than assuming it'll just work.
    "https://www.googleapis.com/auth/googlehealth.ecg.readonly",
]


def _load_client_secrets():
    raw = json.loads(CLIENT_SECRETS_FILE.read_text())
    web = raw["web"]
    return web["client_id"], web["client_secret"]


def _token_file(device_id: str) -> Path:
    return TOKENS_DIR / f"{device_id}.json"


class _CallbackHandler(BaseHTTPRequestHandler):
    code = None

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        _CallbackHandler.code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        if _CallbackHandler.code:
            self.wfile.write(b"<html><body>Authorized. You can close this tab.</body></html>")
        else:
            error = params.get("error", ["unknown error"])[0]
            self.wfile.write(f"<html><body>Authorization failed: {error}</body></html>".encode())

    def log_message(self, format, *args):
        pass


def _wait_for_code() -> str:
    _CallbackHandler.code = None  # reset between devices — same class, reused sequentially
    server = HTTPServer(("localhost", AUTH_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    thread.join(timeout=180)
    if _CallbackHandler.code is None:
        raise TimeoutError(
            "No redirect received within 3 minutes — did you approve in "
            "the browser, or close the tab without approving?"
        )
    return _CallbackHandler.code


def get_access_token(device_id: str, allow_interactive: bool = True) -> str:
    """
    Returns a valid access token for this device's Google Health account.
    If allow_interactive is False and no token exists yet, raises instead of opening a browser.
    Use this for scheduled/batch pulls where an un-onboarded device should fail loudly, NOT silently launch OAuth.
    """
    token_file = _token_file(device_id)
    if token_file.exists():
        tokens = json.loads(token_file.read_text())
        return _refresh_access_token(device_id, tokens)
    if not allow_interactive:
        raise RuntimeError(
            f"No saved token for '{device_id}' — device not onboarded. "
            f"Run: python -m extract.scripts.onboard_new_fitbit {device_id}"
        )
    return _run_interactive_auth(device_id)


def _run_interactive_auth(device_id: str) -> str:
    client_id, client_secret = _load_client_secrets()

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"{AUTH_ENDPOINT}?{urlencode(params)}"

    print(f"Opening browser to sign in to the Google account for device '{device_id}'...")
    webbrowser.open(auth_url)

    code = _wait_for_code()

    resp = requests.post(TOKEN_ENDPOINT, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    })
    resp.raise_for_status()
    tokens = resp.json()

    token_file = _token_file(device_id)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(json.dumps(tokens, indent=2))
    print(f"✅ Authorized and saved token for '{device_id}'.")
    return tokens["access_token"]


def _refresh_access_token(device_id: str, tokens: dict) -> str:
    client_id, client_secret = _load_client_secrets()
    resp = requests.post(TOKEN_ENDPOINT, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": tokens["refresh_token"],
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    new_tokens = resp.json()
    new_tokens.setdefault("refresh_token", tokens["refresh_token"])
    _token_file(device_id).write_text(json.dumps(new_tokens, indent=2))
    return new_tokens["access_token"]