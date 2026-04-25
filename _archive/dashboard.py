import os
import time

import yfinance as yf
from dotenv import load_dotenv

import kite_data as kd

load_dotenv()

while True:
    kite = kd.kite_client()

    margins = kite.margins()
    holdings = kite.holdings()
    positions = kite.positions()

    nifty_price = kd.nifty_spot()
    if nifty_price is None:
        nifty = yf.Ticker("^NSEI")
        try:
            nifty_price = float(nifty.info.get("regularMarketPrice") or 0)
        except Exception:
            nifty_price = 0.0

    balance = margins["equity"]["net"]
    day_positions = positions["day"]

    os.system("cls" if os.name == "nt" else "clear")

    print("=" * 30)
    print("      YOUR ACCOUNT SUMMARY")
    print("=" * 30)
    print(f"📉 Nifty 50:  ₹{nifty_price:,.2f}")
    print("-" * 30)
    print(f"💰 Balance:   ₹{balance:,.2f}")
    print(f"📈 Holdings:  {len(holdings)} stocks")
    if len(holdings) > 0:
        for h in holdings:
            print(f"   {h['tradingsymbol']} → ₹{h['last_price']}")
    print(f"📊 Positions: {len(day_positions)} open today")
    print("=" * 30)
    print("🔄 Refreshing in 5 seconds...")

    time.sleep(5)
