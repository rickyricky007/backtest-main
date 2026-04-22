"""Streamlit helpers: Kite browser login when no saved access token."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import streamlit as st

import kite_data as kd

_BROWSER_LOGIN = Path(__file__).resolve().parent / "browser_login.py"


def _run_browser_login_subprocess() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_BROWSER_LOGIN)],
        cwd=str(_BROWSER_LOGIN.parent),
        capture_output=True,
        text=True,
        timeout=310,
    )


def render_browser_login_button(
    *,
    key: str,
    primary: bool = True,
    spinner_label: str = "Waiting for you to finish login in the browser (up to 5 min)…",
) -> None:
    """Start localhost redirect capture (`browser_login.py`)."""
    btype = "primary" if primary else "secondary"
    if st.button(
        "Browser login — auto-capture token",
        type=btype,
        use_container_width=True,
        key=key,
    ):
        with st.spinner(spinner_label):
            try:
                r = _run_browser_login_subprocess()
            except subprocess.TimeoutExpired:
                st.error("Timed out. Try again and complete login before the wait ends.")
            else:
                if r.returncode == 0:
                    st.cache_data.clear()
                    st.success("Session saved. Reloading…")
                    st.rerun()
                else:
                    out = (r.stdout or "").strip()
                    err = (r.stderr or "").strip()
                    st.error("Browser login failed.")
                    if out or err:
                        st.code(out + ("\n" if out and err else "") + err)


def render_sidebar_kite_session(*, key_prefix: str) -> None:
    """Always-visible sidebar entry so browser login is reachable even when a token exists."""
    with st.expander("Kite session (sign in / renew)", expanded=False):
        st.caption(
            "Set your Kite app **redirect URL** to `http://127.0.0.1:8765/` "
            "(or match **KITE_REDIRECT_PORT**)."
        )
        render_browser_login_button(
            key=f"{key_prefix}_exp_browser",
            primary=False,
            spinner_label="Browser login…",
        )
        if st.button("Forget session (clear saved file)", key=f"{key_prefix}_exp_forget"):
            kd.clear_saved_access_token()
            kd.set_ignore_env_access_token(True)
            st.cache_data.clear()
            st.rerun()


def render_auth_cleared_banner() -> None:
    """Show one-shot message after session was cleared due to Kite auth failure."""
    msg = st.session_state.pop("_kite_cleared_notice", None)
    if msg:
        st.warning(msg)


def handle_kite_fetch_error(exc: BaseException, *, user_label: str = "Could not load Kite data") -> None:
    """On bad/expired token, clear session and rerun so the sign-in UI appears."""
    if kd.is_kite_auth_error(exc):
        kd.invalidate_session_after_auth_error()
        st.cache_data.clear()
        st.session_state["_kite_cleared_notice"] = (
            "Kite rejected this session (**Incorrect api_key or access_token**: token expired, or it was "
            "issued for a different **API_KEY**). Saved **`.kite_access_token`** was removed and "
            "**ACCESS_TOKEN** in `.env` is ignored until you sign in again. "
            "Use **Kite session (sign in / renew)** in the sidebar → **Browser login — auto-capture token**, "
            "or fix `.env` and restart the app."
        )
        st.rerun()
    st.error(f"{user_label}: {exc}")
    st.stop()

def ensure_kite_ready() -> bool:
    """
    Return True if an access token is available.
    Otherwise show login UI and return False (caller should st.stop()).
    """
    # If manually logged out, show simple login button
    if st.session_state.get("kite_logged_out"):
        st.info("**Sign in to Kite** — you logged out.")
        if st.button("Log back in"):
            st.session_state["kite_logged_out"] = False
            st.rerun()
        return False

    if kd.load_access_token():
        return True

    st.info("**Sign in to Kite** — session not found yet.")
    st.markdown(
        "Zerodha only issues an **access token** after you complete login in the browser and "
        "exchange the short-lived **request_token** using your app's **API_SECRET**. "
        "This app saves the token to **`.kite_access_token`** (preferred over **ACCESS_TOKEN** in `.env`)."
    )

    try:
        url = kd.kite_login_url()
    except Exception as e:
        st.warning(f"Could not build login URL (check **API_KEY** in `.env`): {e}")
        return False

    st.link_button("Open Kite login (manual)", url, use_container_width=True)
    st.caption(
        "For automatic capture, your Kite app's **redirect URL** must be "
        "`http://127.0.0.1:<port>/` (default port **8765**, or set **KITE_REDIRECT_PORT** in `.env`)."
    )
    render_browser_login_button(key="kite_browser_main")

    st.divider()
    st.caption("Or paste **request_token** from the redirect URL if redirect is not set to localhost.")
    req = st.text_input("request_token", placeholder="paste token from redirect URL", type="password")
    if st.button("Connect & save session (manual token)"):
        if not req or not req.strip():
            st.warning("Paste the request_token first.")
        else:
            try:
                kd.exchange_request_token(req.strip())
                st.cache_data.clear()
                st.success("Session saved. Reloading…")
                st.rerun()
            except Exception as e:
                st.error(str(e))
    return False

def render_logout_controls(*, key: str = "kite_logout") -> None:
    """Sidebar: clear saved Kite session."""
    if not kd.load_access_token():
        return
    if st.session_state.get("kite_logged_out"):
        return
    if st.button("Log out (clear Kite session)", use_container_width=True, key=key):
        st.session_state["kite_logged_out"] = True  # just set flag
        st.cache_data.clear()
        st.rerun()