#!/usr/bin/env python3
"""
Capture Kite request_token via localhost redirect (no copy-paste).

You still sign in with your Zerodha credentials in a normal browser window.
This script only listens on 127.0.0.1 and exchanges the token for access_token.

Kite Connect app settings must list this exact redirect URL (including port):
  http://127.0.0.1:<PORT>/
Default PORT is 8765, or set KITE_REDIRECT_PORT in .env.

Requires in .env: API_KEY, API_SECRET
"""

from __future__ import annotations

import argparse
import os
import socketserver
import sys
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv

import kite_data as kd


def _parse_port() -> int:
    load_dotenv(override=True)
    raw = os.getenv("KITE_REDIRECT_PORT", "8765")
    return int(raw, 10)


class _OAuthHandler(BaseHTTPRequestHandler):
    server_version = "KiteOAuth/1"

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        srv: _Server = self.server  # type: ignore[assignment]
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/favicon.ico", "/robots.txt"):
            self.send_response(204)
            self.end_headers()
            return

        qs = urllib.parse.parse_qs(parsed.query)
        status = (qs.get("status") or [""])[0]
        rt = (qs.get("request_token") or [None])[0]

        if rt:
            srv.captured_token = rt
            body = "<p>Login received. You can close this tab.</p>"
        elif status and status != "success":
            srv.captured_error = f"Kite returned status={status!r}"
            body = f"<p>{srv.captured_error}</p>"
        else:
            body = "<p>Waiting for redirect from Zerodha…</p>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            f"<!doctype html><html><head><meta charset=utf-8><title>Kite</title></head><body>{body}</body></html>".encode(
                "utf-8"
            )
        )


class _Server(socketserver.TCPServer):
    allow_reuse_address = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.captured_token: str | None = None
        self.captured_error: str | None = None


def run_browser_login(*, port: int, timeout_s: float, open_browser: bool) -> int:
    login_url = kd.kite_login_url()
    httpd = _Server(("127.0.0.1", port), _OAuthHandler)
    httpd.timeout = 1.0

    print(f"Listening on http://127.0.0.1:{port}/ — set this as your app redirect URL in Kite Connect.", flush=True)
    if open_browser:
        webbrowser.open(login_url)
    else:
        print("Open this URL in your browser:\n", login_url, flush=True)

    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            httpd.handle_request()
            if httpd.captured_token:
                kd.exchange_request_token(httpd.captured_token)
                print("Saved access token to .kite_access_token", flush=True)
                return 0
            if httpd.captured_error:
                print(httpd.captured_error, file=sys.stderr, flush=True)
                return 1
    finally:
        httpd.server_close()

    print("Timed out waiting for redirect (complete login in the browser).", file=sys.stderr, flush=True)
    return 2


def main() -> None:
    p = argparse.ArgumentParser(description="Kite browser login with localhost token capture.")
    p.add_argument("--port", type=int, default=None, help="Redirect port (default: env KITE_REDIRECT_PORT or 8765)")
    p.add_argument("--timeout", type=float, default=300.0, help="Seconds to wait for redirect")
    p.add_argument("--no-browser", action="store_true", help="Only print login URL; do not open a browser")
    args = p.parse_args()
    port = args.port if args.port is not None else _parse_port()
    raise SystemExit(
        run_browser_login(port=port, timeout_s=args.timeout, open_browser=not args.no_browser)
    )


if __name__ == "__main__":
    main()
