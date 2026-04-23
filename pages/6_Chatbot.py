import streamlit as st
import anthropic
import sqlite3
import os
import json
import glob
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ── Safe client init ─────────────────────────────
client = None
if API_KEY:
    client = anthropic.Anthropic(api_key=API_KEY)

st.set_page_config(page_title="Trading Assistant", page_icon="🤖")
st.title("🤖 Trading Assistant")
st.caption("Ask me anything about your trading data!")

# ── Read project files (LIMITED SIZE) ────────────
def read_project_files():
    context = "\n\n📂 Project files:\n"
    py_files = glob.glob("*.py") + glob.glob("pages/*.py")

    for file_path in py_files:
        try:
            with open(file_path, "r") as f:
                content = f.read()[:1000]   # ⚠️ reduced size
                context += f"\n📄 {file_path}:\n```python\n{content}\n```\n"
        except:
            continue

    return context


# ── Trading DB Context (SAFE) ────────────────────
def get_trading_context():
    try:
        conn = sqlite3.connect("dashboard.sqlite")
        cursor = conn.cursor()

        # safer queries
        try:
            cursor.execute("SELECT DISTINCT symbol, interval, bars FROM price_series LIMIT 20")
            series = cursor.fetchall()
        except:
            series = []

        try:
            cursor.execute("""
                SELECT strategy_name, symbol, interval,
                total_return_pct, max_drawdown_pct,
                num_trades
                FROM backtest_runs
                ORDER BY ran_at DESC LIMIT 5
            """)
            runs = cursor.fetchall()
        except:
            runs = []

        try:
            cursor.execute("SELECT name FROM strategies LIMIT 10")
            strategies = cursor.fetchall()
        except:
            strategies = []

        conn.close()

        context = "You are an expert trading assistant for Indian markets.\n\n"

        if series:
            context += "📊 Data:\n"
            for s in series:
                context += f"- {s[0]} ({s[1]})\n"

        if strategies:
            context += "\n🎯 Strategies:\n"
            for s in strategies:
                context += f"- {s[0]}\n"

        if runs:
            context += "\n📈 Backtests:\n"
            for r in runs:
                context += f"- {r[0]} {r[3]}% return\n"

        return context

    except Exception:
        return "You are an expert trading assistant for Indian markets."


# ── Uploaded files reader (SAFE) ────────────────
def read_uploaded_file(uploaded_file):
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
            return f"\nCSV:\n{df.head(10)}\n"

        elif uploaded_file.name.endswith(".json"):
            content = json.load(uploaded_file)
            return f"\nJSON:\n{json.dumps(content)[:1000]}\n"

        elif uploaded_file.name.endswith(".py"):
            content = uploaded_file.read().decode("utf-8")[:1000]
            return f"\nPython:\n{content}\n"

        else:
            return f"\nFile uploaded: {uploaded_file.name}\n"

    except:
        return f"\nFile uploaded: {uploaded_file.name}\n"


# ── Sidebar ─────────────────────────────────────
with st.sidebar:
    st.subheader("Upload Files")

    uploaded_files = st.file_uploader(
        "Upload",
        type=["csv", "py", "json", "txt"],
        accept_multiple_files=True
    )

    auto_read = st.toggle("Read project files", value=False)


# ── Chat memory ─────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []


# ── Show chat ───────────────────────────────────
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])


# ── Chat input ──────────────────────────────────
if prompt := st.chat_input("Ask something..."):

    if not client:
        st.error("❌ Anthropic API key missing")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    # ── Build context ───────────────────────────
    context = get_trading_context()

    if auto_read:
        context += read_project_files()

    if uploaded_files:
        for f in uploaded_files:
            f.seek(0)
            context += read_uploaded_file(f)

    # ⚠️ LIMIT context size (VERY IMPORTANT)
    context = context[:12000]

    # ── Call Claude ────────────────────────────
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):

            try:
                response = client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=800,
                    system=context,
                    messages=st.session_state.messages[-10:]  # last 10 only
                )

                answer = response.content[0].text

            except Exception as e:
                answer = f"⚠️ Error: {e}"

            st.markdown(answer)

            st.session_state.messages.append({
                "role": "assistant",
                "content": answer
            })