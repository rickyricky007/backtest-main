"""Streamlit helpers: Kite session status and management (terminal-auth flow)."""

from __future__ import annotations

import streamlit as st

import kite_data as kd


def render_sidebar_kite_session(*, key_prefix: str = "kite") -> None:
    """Show Kite session status in the sidebar — green if active, red if not."""
    token = kd.load_access_token()
    if token:
        st.success("🟢 Kite connected", icon=None)
    else:
        st.error("🔴 No Kite session")
        st.caption(
            "Run this in your terminal to connect:\n\n"
            "```\npython generate_token.py\n```"
        )


def render_auth_cleared_banner() -> None:
    """Show one-shot warning after session was cleared due to Kite auth failure."""
    msg = st.session_state.pop("_kite_cleared_notice", None)
    if msg:
        st.warning(msg)


def handle_kite_fetch_error(exc: BaseException, *, user_label: str = "Could not load Kite data") -> None:
    """On bad/expired token, clear session and rerun so the sign-in notice appears."""
    if kd.is_kite_auth_error(exc):
        kd.invalidate_session_after_auth_error()
        st.cache_data.clear()
        st.session_state["_kite_cleared_notice"] = (
            "⚠️ Kite session expired or invalid (token rejected). "
            "Run `python generate_token.py` in your terminal to get a fresh token, then refresh this page."
        )
        st.rerun()
    st.error(f"{user_label}: {exc}")
    st.stop()


def ensure_kite_ready() -> bool:
    """
    Return True if a valid access token is available.
    Otherwise show a clear terminal instruction and return False.
    """
    if kd.load_access_token():
        return True

    st.warning(
        "### 🔴 No Kite session found\n\n"
        "Run the following command in your terminal to authenticate:\n\n"
        "```bash\npython generate_token.py\n```\n\n"
        "Then refresh this page. Tokens expire daily — re-run each morning before market open."
    )
    return False


def render_logout_controls(*, key: str = "kite_logout") -> None:
    """Sidebar button to clear the saved Kite session."""
    if not kd.load_access_token():
        return
    if st.button("🚪 Log out (clear Kite session)", use_container_width=True, key=key):
        kd.clear_saved_access_token()
        kd.set_ignore_env_access_token(True)
        st.cache_data.clear()
        st.rerun()
