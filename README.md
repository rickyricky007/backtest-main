# 📊 Backtest Main — Algorithmic Trading Dashboard

A Streamlit-based trading dashboard integrating Zerodha Kite API, 
Yahoo Finance, paper trading, and strategy backtesting.

## 🔧 Current Work
- **Active Strategy:** SMA Crossover (Strategy #2)
- **Files to create:** sma_strategy.py, pages/10_SMA_Strategy.py
- **Last updated:** April 2026

---

## 🚀 Features
- Live indices dashboard (Nifty 50, Bank Nifty, Sensex)
- Holdings and positions overview
- Historical data fetching and storage
- Strategy backtesting (SMA, RSI, Bollinger Bands)
- RSI Bounce scanner with Telegram alerts
- F&O and Stock paper trading
- AI Chatbot integration

## 🛠️ Tech Stack
- Python / Streamlit
- Zerodha Kite Connect API
- Yahoo Finance (yfinance)
- SQLite
- Telegram Bot API

## 📈 Strategy Roadmap
| # | Strategy | Status |
|---|---|---|
| 1 | RSI Bounce (20→30) | ✅ Done |
| 2 | SMA Crossover | 🔜 Next |
| 3 | Bollinger Bands | 🔜 Planned |
| 4 | MACD Crossover | 🔜 Planned |
| 5 | VWAP Bounce | 🔜 Planned |
| 6 | Volume Spike | 🔜 Planned |
| 7 | EMA Trend | 🔜 Planned |
| 8 | RSI Overbought | 🔜 Planned |
| 9 | Support Level | 🔜 Planned |
| 10 | Candlestick Pattern | 🔜 Planned |

## 🎯 Confluence Engine (Coming Soon)
- 10 strategies running simultaneously
- Minimum 5 conditions met → paper trade executes
- Telegram notification on every signal

## ⚙️ Setup
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Create `.env` file with your credentials:


API_KEY=your_kite_api_key
API_SECRET=your_kite_api_secret
TELEGRAM_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id


4. Run: `streamlit run app.py`

## 📁 Project Structure


backtest-main/
├── app.py                 ← Main dashboard
├── kite_data.py           ← Kite API helpers
├── rsi_strategy.py        ← RSI strategy logic
├── backtest_runner.py     ← Backtesting engine
├── local_store.py         ← SQLite persistence
├── alert_engine.py        ← Telegram alerts
├── auth_streamlit.py      ← Authentication
└── pages/                 ← Streamlit pages
    ├── 1_Holdings.py
    ├── 2_Positions.py
    ├── 3_Funds.py
    ├── 4_Historical_data.py
    ├── 5_Strategies.py
    ├── 6_Chatbot.py
    ├── 7_ST_Paper_Trading.py
    ├── 8_FO_Paper_Trading.py
    └── 9_RSI_Strategy.py


## 👨‍💻 Author
Ricky — Self-taught developer transitioning into software development.
Mechanical engineering background with a passion for algorithmic trading.
