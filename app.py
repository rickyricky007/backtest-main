"""Trading dashboard — navigation shell (run with: streamlit run app.py)."""

from __future__ import annotations

import subprocess
import streamlit as st

# ── Auto-update CLAUDE.md silently every startup ──────────────────────────────
try:
    subprocess.Popen(
        ["python", "update_docs.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
except Exception:
    pass

# ── Page config — must be first st call ──────────────────────────────────────
st.set_page_config(
    page_title="Algo Trading",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Navigation — defines sidebar sections ────────────────────────────────────
pg = st.navigation(
    {
        "🏠 Home": [
            st.Page("home.py", title="Overview", icon="🏠", default=True),
        ],
        "💼 Account": [
            st.Page("pages/1_Account/1_Holdings.py",  title="Holdings",  icon="📦"),
            st.Page("pages/1_Account/2_Positions.py", title="Positions", icon="📊"),
            st.Page("pages/1_Account/3_Funds.py",     title="Funds",     icon="💰"),
        ],
        "📈 Market": [
            st.Page("pages/2_Market/1_Historical_Data.py", title="Historical Data", icon="📅"),
            st.Page("pages/2_Market/2_Options_Chain.py",   title="Options Chain",   icon="🔗"),
            st.Page("pages/2_Market/3_Charts.py",          title="Charts",          icon="📉"),
        ],
        "🎯 Signals": [
            st.Page("pages/3_Signals/1_Signal_Scanner.py", title="Signal Scanner", icon="🎯"),
            st.Page("pages/3_Signals/2_Strategy_Hub.py",   title="Strategy Hub",   icon="⚙️"),
            st.Page("pages/3_Signals/3_FO_Dashboard.py",   title="F&O Dashboard",  icon="📋"),
        ],
        "⚡ Trading": [
            st.Page("pages/4_Trading/1_ST_Paper_Trading.py", title="ST Paper Trading", icon="📄"),
            st.Page("pages/4_Trading/2_FO_Paper_Trading.py", title="FO Paper Trading", icon="📄"),
            st.Page("pages/4_Trading/3_Backtest.py",          title="Backtest",         icon="🔬"),
        ],
        "📊 Analytics": [
            st.Page("pages/5_Analytics/1_Strategy_PnL.py",  title="Strategy P&L",  icon="💹"),
            st.Page("pages/5_Analytics/2_Trade_Journal.py", title="Trade Journal",  icon="📓"),
        ],
        "🛠 System": [
            st.Page("pages/6_System/1_Chatbot.py",      title="Chatbot",       icon="🤖"),
            st.Page("pages/6_System/2_System_Status.py", title="System Status", icon="🖥️"),
        ],
    }
)

# ── Run the selected page ─────────────────────────────────────────────────────
pg.run()
