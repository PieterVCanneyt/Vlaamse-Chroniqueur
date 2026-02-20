"""
One-time OAuth 2.0 setup script. Run locally to obtain Google credentials.

Usage:
    python auth_setup.py

Prerequisites:
    1. Create a Google Cloud project and enable the Google Docs and Drive APIs.
    2. Create an OAuth 2.0 client (Desktop app type) in Google Cloud Console.
    3. Download the client secrets JSON and save it as client_secrets.json next
       to this script (never commit that file — it is listed in .gitignore).

After running, copy the printed values to your GitHub Actions secrets and to
your local .env file.
"""

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

CLIENT_SECRETS_FILE = "client_secrets.json"


def main() -> None:
    try:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    except FileNotFoundError:
        print(
            f"Error: {CLIENT_SECRETS_FILE} not found.\n"
            "Download it from Google Cloud Console → APIs & Services → Credentials\n"
            "(OAuth 2.0 Client ID, Desktop app type).",
            file=sys.stderr,
        )
        sys.exit(1)

    creds = flow.run_local_server(port=0)

    print("\n--- Copy these values to your .env and GitHub Actions secrets ---\n")
    print(f"GOOGLE_CLIENT_ID={creds.client_id}")
    print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print("\n------------------------------------------------------------------\n")


if __name__ == "__main__":
    main()
