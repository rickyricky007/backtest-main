"""
F&O Universe — Complete Symbol Registry
========================================
Single source of truth for ALL F&O tradeable symbols.
Every strategy, scanner and signal engine imports from here.

Usage:
    from fo_symbols import FO_INDICES, FO_STOCKS, ALL_FO_SYMBOLS, get_exchange
"""

from __future__ import annotations

# ── F&O Indices (NSE + BSE) ───────────────────────────────────────────────────
# These are index derivatives — traded on NFO exchange

FO_INDICES: dict[str, str] = {
    # Display name     : Kite instrument key
    "NIFTY 50":        "NSE:NIFTY 50",
    "BANK NIFTY":      "NSE:NIFTY BANK",
    "FINNIFTY":        "NSE:NIFTY FIN SERVICE",
    "MIDCAP NIFTY":    "NSE:NIFTY MID SELECT",
    "SENSEX":          "BSE:SENSEX",
    "BANKEX":          "BSE:BANKEX",
}

# yfinance tickers for historical data (indices only)
YF_INDEX_MAP: dict[str, str] = {
    "NIFTY 50":     "^NSEI",
    "BANK NIFTY":   "^NSEBANK",
    "FINNIFTY":     "NIFTY_FIN_SERVICE.NS",
    "MIDCAP NIFTY": "^NSEMDCP50",
    "SENSEX":       "^BSESN",
    "BANKEX":       "^BSESN",   # fallback
}

# ── F&O Stocks — Complete NSE F&O list (~180 stocks) ─────────────────────────
# All stocks that have futures & options on NSE

FO_STOCKS: list[str] = [
    # ── Large Cap / Index heavyweights ────────────────────────────────────────
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
    "SUNPHARMA", "ULTRACEMCO", "WIPRO", "NESTLEIND", "BAJFINANCE",
    "HCLTECH", "TECHM", "POWERGRID", "NTPC", "ONGC",
    "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "COALINDIA", "ADANIENT",
    "BAJAJFINSV", "DIVISLAB", "DRREDDY", "CIPLA", "EICHERMOT",
    "HEROMOTOCO", "APOLLOHOSP", "BPCL", "GRASIM", "HINDALCO",
    "INDUSINDBK", "M&M", "SBILIFE", "HDFCLIFE", "BRITANNIA",
    "UPL", "SHREECEM", "TATACONSUM", "PIDILITIND", "DMART",

    # ── Banking & Finance ─────────────────────────────────────────────────────
    "BANKBARODA", "PNB", "CANBK", "INDIANB", "FEDERALBNK",
    "IDFCFIRSTB", "RBLBANK", "BANDHANBNK", "AUBANK", "CUB",
    "CHOLAFIN", "BAJAJ-AUTO", "MANAPPURAM", "MUTHOOTFIN", "M&MFIN",
    "LICHSGFIN", "CANFINHOME", "RECLTD", "PFC", "L&TFH",
    "HDFCAMC", "ICICIPRULI", "ICICIGI", "SBICARD", "ANGELONE",
    "MCX", "SHRIRAMFIN", "ABCAPITAL",

    # ── IT & Technology ───────────────────────────────────────────────────────
    "LTIM", "LTTS", "MPHASIS", "COFORGE", "PERSISTENT",
    "KPITTECH", "BSOFT", "OFSS", "INDIAMART",

    # ── Auto & Auto Ancillary ─────────────────────────────────────────────────
    "TVSMOTOR", "ESCORTS", "BALKRISIND", "APOLLOTYRE",
    "EXIDEIND", "BHARATFORG", "ASHOKLEY", "MOTHERSON",
    "TIINDIA", "MRF",

    # ── Pharma & Healthcare ───────────────────────────────────────────────────
    "AUROPHARMA", "LUPIN", "ALKEM", "IPCALAB", "LALPATHLAB",
    "METROPOLIS", "BIOCON", "GLENMARK", "GRANULES", "NAVINFLUOR",
    "SYNGENE", "ABBOTINDIA", "MAXHEALTH", "ZYDUSLIFE", "TORNTPHARM",

    # ── FMCG & Consumer ──────────────────────────────────────────────────────
    "DABUR", "MARICO", "COLPAL", "GODREJCP", "BATAINDIA",
    "JUBLFOOD", "UBL", "MFSL", "PAGEIND",

    # ── Cement & Building Materials ───────────────────────────────────────────
    "AMBUJACEM", "ACC", "DALBHARAT", "JKCEMENT", "RAMCOCEM",
    "ASTRAL", "POLYCAB", "KEI", "HAVELLS", "CROMPTON",
    "APLAPOLLO", "KAJARIACER",

    # ── Metals & Mining ───────────────────────────────────────────────────────
    "SAIL", "NATIONALUM", "HINDCOPPER", "NMDC", "VEDL",
    "JINDALSTEL", "JSL",

    # ── Energy & Power ────────────────────────────────────────────────────────
    "GAIL", "IOC", "HINDPETRO", "PETRONET", "GSPL",
    "GUJGASLTD", "IGL", "ATGL", "JSWENERGY", "TATAPOWER",
    "TORNTPOWER",

    # ── Infrastructure & Real Estate ──────────────────────────────────────────
    "DLF", "GODREJPROP", "OBEROIRLTY", "IBREALEST",
    "GMRINFRA", "IRB", "CONCOR", "INDUSTOWER",

    # ── Chemicals ────────────────────────────────────────────────────────────
    "DEEPAKNTR", "ATUL", "PIIND", "SRF", "TATACHEM",
    "CHAMBLFERT", "COROMANDEL", "GNFC", "RAIN",

    # ── Media, Hotels & Others ───────────────────────────────────────────────
    "ZEEL", "SUNTV", "SAREGAMA", "PVRINOX", "INDHOTEL",
    "TATACOMM", "IRCTC", "INDIGO", "HAL", "BEL",
    "BHEL", "SIEMENS", "ABB", "HONAUT", "CUMMINSIND",
    "BOSCHLTD", "BERGEPAINT", "DIXON", "ROUTE", "STAR",
    "DELTACORP", "IDEA", "IDFC", "IEX", "RAJESHEXPO",
    "SOLARINDS", "VOLTAS",
]

# ── Combined universe ─────────────────────────────────────────────────────────

ALL_FO_SYMBOLS: list[str] = list(FO_INDICES.keys()) + FO_STOCKS

# ── Top 50 high-liquidity F&O stocks (for faster scans) ──────────────────────
# Use this when you want speed over coverage

TOP_50_LIQUID: list[str] = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK",
    "WIPRO", "HCLTECH", "BAJFINANCE", "BAJAJFINSV", "MARUTI",
    "TITAN", "SUNPHARMA", "ULTRACEMCO", "NESTLEIND", "ITC",
    "ONGC", "BPCL", "COALINDIA", "HINDUNILVR", "ASIANPAINT",
    "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "ADANIENT", "HINDALCO",
    "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP", "EICHERMOT",
    "HEROMOTOCO", "M&M", "TECHM", "POWERGRID", "NTPC",
    "INDUSINDBK", "GRASIM", "SBILIFE", "HDFCLIFE", "BRITANNIA",
    "TATACONSUM", "PIDILITIND", "VEDL", "BANKBARODA", "PNB",
]

# ── Exchange mapping ──────────────────────────────────────────────────────────

def get_exchange(symbol: str) -> str:
    """Returns exchange for a symbol — BSE for SENSEX/BANKEX, NSE for everything else."""
    if symbol in ("SENSEX", "BANKEX"):
        return "BSE"
    if symbol in FO_INDICES:
        return "NSE"
    return "NSE"


def get_kite_key(symbol: str) -> str:
    """Returns the full Kite instrument key for a symbol."""
    if symbol in FO_INDICES:
        return FO_INDICES[symbol]
    return f"NSE:{symbol}"


def get_yf_ticker(symbol: str) -> str:
    """Returns yfinance ticker for a symbol."""
    if symbol in YF_INDEX_MAP:
        return YF_INDEX_MAP[symbol]
    return f"{symbol}.NS"


def is_index(symbol: str) -> bool:
    return symbol in FO_INDICES
