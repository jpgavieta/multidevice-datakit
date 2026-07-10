# src/extract/scripts/onboard_new_fitbit.py
"""
One-time setup for a new Fitbit device: runs the Google OAuth consent flow
and saves the resulting token so future pulls run silently.

Run this ONCE per new device, after:
    1.  The device's Google account must first be added as a Test User in the
        Google Cloud Console (OAuth consent screen > Audience).
    2.  You must know the device_id you're about to assign it (check config
        conventions, e.g. fitbit_kol_08).

USAGE:
    python -m extract.scripts.onboard_new_fitbit fitbit_kol_08

A browser window will open — sign in to THIS DEVICE'S Google account
(not personal account), and approve the requested permissions.
"""

import sys

from extract.config.tokens import get_fitbit_token
from extract.clients.fitbit_client import get_profile


def main():
    if len(sys.argv) != 2:
        print("Usage: python -m extract.scripts.onboard_new_fitbit <device_id>")
        sys.exit(1)

    device_id = sys.argv[1]

    print(f"\nOnboarding '{device_id}' — a browser window should open shortly.")
    print("Sign in to THIS DEVICE'S Google account, not your own.\n")

    try:
        access_token = get_fitbit_token(device_id, allow_interactive=True) # This is the ONlY way to onboard a device and launch OAuth
    except Exception as e:
        print(f"\n❌ OAuth flow failed for '{device_id}': {e}")
        sys.exit(1)

    try:
        profile = get_profile(access_token)
        print(f"\n✅ Token saved and verified for '{device_id}'.")
        print(f"   Profile check OK: {profile.get('displayName', '(no name field)')}")
    except Exception as e:
        print(f"\n⚠️ Token saved, but profile check failed: {e}")
        print("   Token may still be valid for data pulls — check manually if concerned.")

    print(f"\nNext: add '{device_id}' to config/devices.yaml if not already present.")


if __name__ == "__main__":
    main()