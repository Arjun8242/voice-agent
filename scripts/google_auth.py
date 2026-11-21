"""Get GOOGLE_REFRESH_TOKEN for the Google Calendar backend (CALENDAR_BACKEND=google). Run once, by hand.

    pip install google-auth-oauthlib
    python scripts/google_auth.py

Put the OAuth client file you downloaded from Google Cloud ("Desktop app" client) next to this script as
client_secret.json; it is git-ignored. A browser opens to grant calendar access, then the token is printed:
copy it into .env. Not part of the server or the tests.
"""

from __future__ import annotations

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.freebusy",
]
CLIENT_SECRET = Path(__file__).resolve().parent / "client_secret.json"

flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("GOOGLE_REFRESH_TOKEN=" + str(creds.refresh_token))
