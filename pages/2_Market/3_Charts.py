"""
Advanced F&O Charts — Multi-Timeframe with Indicators
======================================================
Interactive price charts for any F&O symbol with technical overlays.

Features:
    - Any F&O index or stock (searchable)
    - Timeframes: 1m, 5m, 15m, 1h, 1d
    - Indicator overlays: EMA 9/21/50/200, Bollinger Bands, VWAP, Supertrend
    - Sub-panels: MACD, RSI, Volume, ADX, Stochastic
    - Candle / Line / OHLC chart types
    - Signal markers — BUY/SELL dots from confluence engine
    - Expiry & market session info in sidebar
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import streamlit as st

from fo_symbols import FO_INDICES, FO_STOCKS, ALL_FO_SYMBOLS, get_yf_ticker
from market_intelligence import market_session_status, expiry_alert
from logger import get_logger

log = get_logger("charts")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="F&O Charts", page_icon="📈", layout="wide")

try:
    from auth_streamlit import render_sidebar_kite_session
    render_sidebar_kite_session()
except Exception:
    pass

st.title("📈 Advanced F&O Charts")
st.caption("Multi-timeframe charts with technical indicators for any F&O symbol")

# ── Sidebar — controls ────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ Chart Settings")

    INDEX_NAMES = list(FO_INDICES.keys())
    ALL_CHOICES = INDEX_NAMES + FO_STOCKS

    symbol = st.selectbox(
        "Symbol (type to search)",
        ALL_CHOICES,
        index=0,
        help="Any F&O index or stock"
    )

    timeframe = st.selectbox(
        "Timeframe",
        ["1m", "5m", "15m", "30m", "1h", "1d"],
        index=2,
        help="Candle interval"
    )

    # Map timeframe → yfinance period
    TF_PERIOD = {
        "1m":  ("7d",  "1m"),
        "5m":  ("60d", "5m"),
        "15m": ("60d", "15m"),
        "30m": ("60d", "30m"),
        "1h":  ("730d","1h"),
        "1d":  ("5y",  "1d"),
    }
    period, yf_interval = TF_PERIOD[timeframe]

    chart_type = st.radio("Chart Type", ["Candlestick", "OHLC", "Line"], index=0)

    st.divider()
    st.subheader("📊 Indicators")

    col_a, col_b = st.columns(2)
    with col_a:
        show_ema9   = st.checkbox("EMA 9",   value=True)
        show_ema21  = st.checkbox("EMA 21",  value=True)
        show_ema50  = st.checkbox("EMA 50",  value=False)
        show_ema200 = st.checkbox("EMA 200", value=False)
    with col_b:
        show_bb     = st.checkbox("Bollinger Bands", value=True)
        show_vwap   = st.checkbox("VWAP",   value=True)
        show_st     = st.checkbox("Supertrend", value=False)

    st.divider()
    st.subheader("📉 Sub-Panels")

    show_volume = st.checkbox("Volume",     value=True)
    show_macd   = st.checkbox("MACD",       value=True)
    show_rsi    = st.checkbox("RSI",        value=True)
    show_adx    = st.checkbox("ADX",        value=False)
    show_stoch  = st.checkbox("Stochastic", value=False)

    show_signals = st.checkbox("Show BUY/SELL signals", value=True,
                                help="Marks confluence engine signals on chart")

    st.divider()
    refresh = st.button("🔄 Refresh Chart", type="primary", width="stretch")

    # Market session info
    st.divider()
    st.subheader("🌍 Market Status")
    try:
        sess = market_session_status()
        exp  = expiry_alert()
        phase_color = "🟢" if sess["nse_open"] else "🔴"
        st.caption(f"{phase_color} NSE: **{sess['nse_phase']}**")
        st.caption(f"Weekly expiry in **{exp['dte_weekly']}** days")
        if exp["alerts"]:
            for a in exp["alerts"]:
                st.warning(a)
    except Exception:
        pass


# ── Data fetcher ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_data(symbol: str, period: str, interval: str) -> pd.DataFrame:
    try:
        import yfinance as yf
        ticker = get_yf_ticker(symbol)
        df = yf.Ticker(ticker).history(period=period, interval=interval)
        if df.empty:
            return pd.DataFrame()
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        df.index = pd.to_datetime(df.index)
        # Remove timezone for cleaner display
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        log.info(f"Fetched {len(df)} candles for {symbol} ({interval})")
        return df
    except Exception:
        log.error(f"Data fetch error for {symbol}", exc_info=True)
        return pd.DataFrame()


# ── Indicator calculators ─────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _bollinger(closes: pd.Series, period: int = 20, std: float = 2.0):
    mid = closes.rolling(period).mean()
    s   = closes.rolling(period).std()
    return mid + std * s, mid, mid - std * s


def _macd(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line   = _ema(closes, fast) - _ema(closes, slow)
    signal_line = _ema(macd_line, signal)
    hist        = macd_line - signal_line
    return macd_line, signal_line, hist


def _rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _vwap(df: pd.DataFrame) -> pd.Series:
    tp  = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_vol  = df["Volume"].cumsum()
    cum_tpvol = (tp * df["Volume"]).cumsum()
    return cum_tpvol / cum_vol.replace(0, np.nan)


def _supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0):
    hl2  = (df["High"] + df["Low"]) / 2
    atr  = (df["High"] - df["Low"]).rolling(period).mean()
    up   = hl2 + mult * atr
    dn   = hl2 - mult * atr
    st   = pd.Series(np.nan, index=df.index)
    direction = pd.Series(1, index=df.index)

    for i in range(1, len(df)):
        # Upper band
        up.iloc[i] = min(up.iloc[i], up.iloc[i-1]) if df["Close"].iloc[i-1] > up.iloc[i-1] else up.iloc[i]
        dn.iloc[i] = max(dn.iloc[i], dn.iloc[i-1]) if df["Close"].iloc[i-1] < dn.iloc[i-1] else dn.iloc[i]
        if df["Close"].iloc[i] > up.iloc[i-1]:
            direction.iloc[i] = 1
        elif df["Close"].iloc[i] < dn.iloc[i-1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i-1]

        st.iloc[i] = dn.iloc[i] if direction.iloc[i] == 1 else up.iloc[i]

    return st, direction


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    try:
        high, low, close = df["High"], df["Low"], df["Close"]
        tr   = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        dm_p = (high - high.shift()).clip(lower=0).where((high - high.shift()) > (low.shift() - low), 0)
        dm_n = (low.shift() - low).clip(lower=0).where((low.shift() - low) > (high - high.shift()), 0)
        atr  = tr.rolling(period).mean()
        di_p = 100 * dm_p.rolling(period).mean() / atr.replace(0, np.nan)
        di_n = 100 * dm_n.rolling(period).mean() / atr.replace(0, np.nan)
        dx   = (100 * (di_p - di_n).abs() / (di_p + di_n).replace(0, np.nan))
        return dx.rolling(period).mean()
    except Exception:
        return pd.Series(np.nan, index=df.index)


def _stochastic(df: pd.DataFrame, k: int = 14, d: int = 3):
    low_k  = df["Low"].rolling(k).min()
    high_k = df["High"].rolling(k).max()
    stoch_k = 100 * (df["Close"] - low_k) / (high_k - low_k).replace(0, np.nan)
    stoch_d = stoch_k.rolling(d).mean()
    return stoch_k, stoch_d


def _signal_markers(df: pd.DataFrame, closes: pd.Series):
    """Generate BUY/SELL marker points from quick scoring."""
    try:
        from indicators import score_symbol
        results = []
        window = 50

        for i in range(window, len(df)):
            c = closes.iloc[i-window:i].tolist()
            h = df["High"].iloc[i-window:i].tolist()
            l = df["Low"].iloc[i-window:i].tolist()
            v = df["Volume"].iloc[i-window:i].tolist()
            s = score_symbol(c, h, l, v)
            if s["action"] in ("BUY", "SELL"):
                results.append({
                    "dt":     df.index[i],
                    "price":  df["Close"].iloc[i],
                    "action": s["action"],
                    "score":  s["score"],
                })
        return pd.DataFrame(results)
    except Exception:
        log.warning("Signal marker error", exc_info=False)
        return pd.DataFrame()


# ── Main chart rendering ──────────────────────────────────────────────────────

with st.spinner(f"Loading {symbol} ({timeframe})..."):
    df = _fetch_data(symbol, period, yf_interval)

if df.empty:
    st.error(
        f"No data for **{symbol}** ({timeframe}). "
        "Check your internet connection or try a different timeframe."
    )
    st.stop()

closes  = df["Close"]
highs   = df["High"]
lows    = df["Low"]
volumes = df["Volume"]
dates   = df.index

# ── Metrics ───────────────────────────────────────────────────────────────────
last_close = closes.iloc[-1]
prev_close = closes.iloc[-2] if len(closes) > 1 else last_close
pct_chg    = (last_close - prev_close) / prev_close * 100
day_high   = highs.iloc[-1]
day_low    = lows.iloc[-1]

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Last Price",   f"₹{last_close:,.2f}", f"{pct_chg:+.2f}%",
          delta_color="normal" if pct_chg >= 0 else "inverse")
m2.metric("Day High",     f"₹{day_high:,.2f}")
m3.metric("Day Low",      f"₹{day_low:,.2f}")
m4.metric("Volume",       f"{volumes.iloc[-1]:,.0f}")
m5.metric("Candles",      f"{len(df):,}")

st.divider()

# ── Build chart with plotly ───────────────────────────────────────────────────
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    # Count sub-panels needed
    sub_panels = []
    if show_volume: sub_panels.append("Volume")
    if show_macd:   sub_panels.append("MACD")
    if show_rsi:    sub_panels.append("RSI")
    if show_adx:    sub_panels.append("ADX")
    if show_stoch:  sub_panels.append("Stochastic")

    n_panels = 1 + len(sub_panels)
    row_heights = [0.55] + [0.45 / max(len(sub_panels), 1)] * len(sub_panels)

    specs  = [[{"type": "xy"}]] * n_panels
    titles = [f"{symbol} ({timeframe})"] + sub_panels

    fig = make_subplots(
        rows=n_panels, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=row_heights,
        subplot_titles=titles,
    )

    # ── Price chart ───────────────────────────────────────────────────────────
    if chart_type == "Candlestick":
        fig.add_trace(go.Candlestick(
            x=dates, open=df["Open"], high=highs, low=lows, close=closes,
            name="Price",
            increasing_line_color="#22c55e", decreasing_line_color="#ef4444",
            increasing_fillcolor="#22c55e", decreasing_fillcolor="#ef4444",
        ), row=1, col=1)
    elif chart_type == "OHLC":
        fig.add_trace(go.Ohlc(
            x=dates, open=df["Open"], high=highs, low=lows, close=closes,
            name="Price",
            increasing_line_color="#22c55e", decreasing_line_color="#ef4444",
        ), row=1, col=1)
    else:
        fig.add_trace(go.Scatter(
            x=dates, y=closes, name="Close",
            line=dict(color="#3b82f6", width=2),
        ), row=1, col=1)

    # ── EMA overlays ──────────────────────────────────────────────────────────
    ema_configs = [
        (show_ema9,   9,   "#fbbf24", "EMA 9"),
        (show_ema21,  21,  "#f97316", "EMA 21"),
        (show_ema50,  50,  "#8b5cf6", "EMA 50"),
        (show_ema200, 200, "#ec4899", "EMA 200"),
    ]
    for show, period_e, color, name in ema_configs:
        if show and len(closes) > period_e:
            ema = _ema(closes, period_e)
            fig.add_trace(go.Scatter(
                x=dates, y=ema, name=name,
                line=dict(color=color, width=1.5),
            ), row=1, col=1)

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    if show_bb and len(closes) > 20:
        bb_up, bb_mid, bb_dn = _bollinger(closes)
        fig.add_trace(go.Scatter(x=dates, y=bb_up, name="BB Upper",
            line=dict(color="rgba(100,180,255,0.6)", width=1, dash="dot"),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=bb_dn, name="BB Lower",
            line=dict(color="rgba(100,180,255,0.6)", width=1, dash="dot"),
            fill="tonexty", fillcolor="rgba(100,180,255,0.05)",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=bb_mid, name="BB Mid",
            line=dict(color="rgba(100,180,255,0.4)", width=1),
        ), row=1, col=1)

    # ── VWAP ─────────────────────────────────────────────────────────────────
    if show_vwap:
        vwap = _vwap(df)
        fig.add_trace(go.Scatter(
            x=dates, y=vwap, name="VWAP",
            line=dict(color="#a78bfa", width=2, dash="dash"),
        ), row=1, col=1)

    # ── Supertrend ────────────────────────────────────────────────────────────
    if show_st and len(df) > 20:
        st_line, st_dir = _supertrend(df)
        bull_mask = st_dir == 1
        bear_mask = st_dir == -1
        fig.add_trace(go.Scatter(
            x=dates[bull_mask], y=st_line[bull_mask], name="Supertrend ▲",
            mode="markers", marker=dict(color="#22c55e", size=3, symbol="circle"),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=dates[bear_mask], y=st_line[bear_mask], name="Supertrend ▼",
            mode="markers", marker=dict(color="#ef4444", size=3, symbol="circle"),
        ), row=1, col=1)

    # ── BUY/SELL signals ──────────────────────────────────────────────────────
    if show_signals and len(df) > 60:
        with st.spinner("Computing signals..."):
            sigs = _signal_markers(df, closes)
        if not sigs.empty:
            buy_sigs  = sigs[sigs["action"] == "BUY"]
            sell_sigs = sigs[sigs["action"] == "SELL"]
            if not buy_sigs.empty:
                fig.add_trace(go.Scatter(
                    x=buy_sigs["dt"], y=buy_sigs["price"] * 0.998,
                    name="BUY Signal",
                    mode="markers",
                    marker=dict(symbol="triangle-up", color="#22c55e", size=12, line=dict(color="white", width=1)),
                    text=buy_sigs["score"].apply(lambda s: f"Score: {s:+d}"),
                    hoverinfo="text+x+y",
                ), row=1, col=1)
            if not sell_sigs.empty:
                fig.add_trace(go.Scatter(
                    x=sell_sigs["dt"], y=sell_sigs["price"] * 1.002,
                    name="SELL Signal",
                    mode="markers",
                    marker=dict(symbol="triangle-down", color="#ef4444", size=12, line=dict(color="white", width=1)),
                    text=sell_sigs["score"].apply(lambda s: f"Score: {s:+d}"),
                    hoverinfo="text+x+y",
                ), row=1, col=1)

    # ── Sub-panels ────────────────────────────────────────────────────────────
    panel_row = 2

    if show_volume:
        colors = ["#22c55e" if closes.iloc[i] >= df["Open"].iloc[i] else "#ef4444"
                  for i in range(len(df))]
        fig.add_trace(go.Bar(
            x=dates, y=volumes, name="Volume",
            marker_color=colors, opacity=0.7,
        ), row=panel_row, col=1)
        panel_row += 1

    if show_macd and len(closes) > 26:
        macd_l, macd_s, macd_h = _macd(closes)
        hist_colors = ["#22c55e" if v >= 0 else "#ef4444" for v in macd_h]
        fig.add_trace(go.Bar(x=dates, y=macd_h, name="MACD Hist",
            marker_color=hist_colors, opacity=0.6,
        ), row=panel_row, col=1)
        fig.add_trace(go.Scatter(x=dates, y=macd_l, name="MACD",
            line=dict(color="#3b82f6", width=1.5),
        ), row=panel_row, col=1)
        fig.add_trace(go.Scatter(x=dates, y=macd_s, name="Signal",
            line=dict(color="#f97316", width=1.5),
        ), row=panel_row, col=1)
        panel_row += 1

    if show_rsi and len(closes) > 14:
        rsi = _rsi(closes)
        fig.add_trace(go.Scatter(x=dates, y=rsi, name="RSI",
            line=dict(color="#a78bfa", width=1.5),
        ), row=panel_row, col=1)
        # Overbought/oversold lines
        fig.add_hline(y=70, line=dict(color="rgba(239,68,68,0.4)", dash="dash"), row=panel_row, col=1)
        fig.add_hline(y=30, line=dict(color="rgba(34,197,94,0.4)", dash="dash"), row=panel_row, col=1)
        fig.add_hline(y=50, line=dict(color="rgba(255,255,255,0.2)", dash="dot"), row=panel_row, col=1)
        panel_row += 1

    if show_adx and len(df) > 14:
        adx = _adx(df)
        fig.add_trace(go.Scatter(x=dates, y=adx, name="ADX",
            line=dict(color="#fbbf24", width=1.5),
        ), row=panel_row, col=1)
        fig.add_hline(y=25, line=dict(color="rgba(255,255,255,0.3)", dash="dash"), row=panel_row, col=1)
        panel_row += 1

    if show_stoch and len(df) > 14:
        stoch_k, stoch_d = _stochastic(df)
        fig.add_trace(go.Scatter(x=dates, y=stoch_k, name="%K",
            line=dict(color="#22d3ee", width=1.5),
        ), row=panel_row, col=1)
        fig.add_trace(go.Scatter(x=dates, y=stoch_d, name="%D",
            line=dict(color="#f97316", width=1.5),
        ), row=panel_row, col=1)
        fig.add_hline(y=80, line=dict(color="rgba(239,68,68,0.4)", dash="dash"), row=panel_row, col=1)
        fig.add_hline(y=20, line=dict(color="rgba(34,197,94,0.4)", dash="dash"), row=panel_row, col=1)
        panel_row += 1

    # ── Layout ─────────────────────────────────────────────────────────────
    chart_height = 550 + len(sub_panels) * 180

    fig.update_layout(
        height=chart_height,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.01,
            xanchor="left",   x=0,
            font=dict(size=11),
        ),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )

    # Remove weekend gaps for daily charts
    if timeframe == "1d":
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

    fig.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")

    st.plotly_chart(fig, width="stretch")

    # ── Signal summary ────────────────────────────────────────────────────────
    if show_signals and len(df) > 60:
        if not sigs.empty:
            recent_sigs = sigs.tail(10).sort_values("dt", ascending=False)
            with st.expander(f"📋 Recent Signals ({len(sigs)} total)", expanded=False):
                display_sigs = recent_sigs.copy()
                display_sigs["dt"]     = display_sigs["dt"].dt.strftime("%d %b %H:%M")
                display_sigs["price"]  = display_sigs["price"].apply(lambda x: f"₹{x:,.2f}")
                display_sigs["action"] = display_sigs["action"].apply(
                    lambda a: f"🟢 {a}" if a == "BUY" else f"🔴 {a}"
                )
                st.dataframe(display_sigs.rename(columns={
                    "dt": "Time", "price": "Price", "action": "Signal", "score": "Score"
                }), hide_index=True, width="stretch")

except ImportError:
    st.error("Plotly not installed. Run: `pip install plotly`")
    st.stop()
except Exception:
    log.error("Chart render error", exc_info=True)
    st.error("Chart render error — check logs.")

# ── Raw OHLCV data ────────────────────────────────────────────────────────────
st.divider()
with st.expander("📄 Raw OHLCV Data", expanded=False):
    display_df = df.copy()
    display_df.index = display_df.index.strftime("%d %b %Y %H:%M")
    display_df = display_df.tail(200)
    st.dataframe(display_df.round(2), width="stretch")

    csv = df.to_csv()
    st.download_button(
        "⬇️ Download OHLCV CSV", csv,
        file_name=f"{symbol}_{timeframe}_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )

st.caption(
    f"Data via yfinance | {symbol} | {timeframe} | "
    f"Last update: {datetime.now().strftime('%H:%M:%S')} | "
    "Refresh to update"
)
