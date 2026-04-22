"""Exchange a request_token for an access token and save to .kite_access_token."""

import os
import sys

from dotenv import load_dotenv

import kite_data as kd

load_dotenv()
req = os.getenv("REQUEST_TOKEN")
if not req and len(sys.argv) > 1:
    req = sys.argv[1]
if not req:
    print(
        "Set REQUEST_TOKEN in .env or pass the token as the first argument "
        "(value of request_token= in the URL after Kite login)."
    )
    sys.exit(1)

kd.exchange_request_token(req)
print("Saved access token to .kite_access_token")
