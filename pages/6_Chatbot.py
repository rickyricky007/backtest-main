import streamlit as st
import anthropic
import sqlite3
import os
import json
import glob
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

st.set_page_config(page_title="Trading Assistant", page_icon="🤖")
st.title("🤖 Trading Assistant")
st.caption("Ask me anything about your trading data!")

def read_project_files():
    """Auto reads all project Python files"""
    project_context = "\n\n📂 Project files:\n"
    
    # Read all .py files in root
    py_files = glob.glob("*.py") + glob.glob("pages/*.py")
    
    for file_path in py_files:
        try:
            with open(file_path, "r") as f:
                content = f.read()
                project_context += f"\n📄 {file_path}:\n```python\n{content[:1500]}\n```\n"
        except:
            pass
    
    return project_context

def get_trading_context():
    try:
        conn = sqlite3.connect("dashboard.sqlite")
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT symbol, interval, bars FROM price_series")
        series = cursor.fetchall()

        cursor.execute("""
            SELECT strategy_name, symbol, interval,
            total_return_pct, max_drawdown_pct,
            num_trades, ran_at
            FROM backtest_runs
            ORDER BY ran_at DESC LIMIT 10
        """)
        runs = cursor.fetchall()

        cursor.execute("SELECT name, config_json FROM strategies")
        strategies = cursor.fetchall()

        conn.close()

        context = """You are an expert trading assistant for Indian markets.
You have deep knowledge of NSE/BSE, Options, Futures,
Technical Analysis, OI, PCR, Greeks, and Expiry strategies.

Here is the user's complete trading data:\n\n"""

        if series:
            context += "📊 Available price data:\n"
            for s in series:
                context += f"- {s[0]} | {s[1]} interval | {s[2]} bars\n"

        if strategies:
            context += "\n🎯 Saved strategies:\n"
            for s in strategies:
                context += f"- {s[0]}: {s[1]}\n"

        if runs:
            context += "\n📈 Recent backtest results:\n"
            for r in runs:
                context += f"- {r[0]} on {r[1]} | Return: {r[3]}% | Max DD: {r[4]}% | Trades: {r[5]}\n"

        return context

    except Exception as e:
        return "You are an expert trading assistant for Indian markets."

def read_uploaded_file(uploaded_file):
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
            return f"\n📁 Uploaded CSV: {uploaded_file.name}\n{df.head(20).to_string()}\n"
        elif uploaded_file.name.endswith(".json"):
            content = json.load(uploaded_file)
            return f"\n📁 Uploaded JSON: {uploaded_file.name}\n{json.dumps(content, indent=2)[:2000]}\n"
        elif uploaded_file.name.endswith(".py"):
            content = uploaded_file.read().decode("utf-8")
            return f"\n📁 Uploaded Python: {uploaded_file.name}\n```python\n{content[:3000]}\n```\n"
        elif uploaded_file.name.endswith(".txt"):
            content = uploaded_file.read().decode("utf-8")
            return f"\n📁 Uploaded text: {uploaded_file.name}\n{content[:2000]}\n"
        else:
            content = uploaded_file.read().decode("utf-8")
            return f"\n📁 Uploaded file: {uploaded_file.name}\n{content[:2000]}\n"
    except Exception as e:
        return f"\n📁 File uploaded: {uploaded_file.name}\n"

# Sidebar
with st.sidebar:
    st.subheader("📁 Upload Trading Files")
    uploaded_files = st.file_uploader(
        "Upload your trading files",
        type=["csv", "py", "json", "txt"],
        accept_multiple_files=True,
        help="Upload CSV data, Python strategies, JSON configs"
    )

    if uploaded_files:
        st.success(f"✅ {len(uploaded_files)} file(s) uploaded!")
        for f in uploaded_files:
            st.caption(f"📄 {f.name}")

    st.divider()

    # Auto project reading toggle
    st.subheader("📂 Project Files")
    auto_read = st.toggle(
        "Auto read project files",
        value=False,
        help="Automatically include all project .py files in context"
    )

    if auto_read:
        py_files = glob.glob("*.py") + glob.glob("pages/*.py")
        st.success(f"✅ Reading {len(py_files)} project files!")
        for f in py_files:
            st.caption(f"📄 {f}")

    st.divider()
    st.caption("Supported files:")
    st.caption("📊 CSV - Price data")
    st.caption("🐍 PY - Strategy files")
    st.caption("⚙️ JSON - Config files")
    st.caption("📝 TXT - Notes")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("Ask about trades, strategies, OI, expiry, market concepts..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Build context
    context = get_trading_context()

    # Add project files if toggle is ON
    if auto_read:
        context += read_project_files()

    # Add uploaded files
    if uploaded_files:
        context += "\n\n📁 User uploaded files:\n"
        for f in uploaded_files:
            f.seek(0)
            context += read_uploaded_file(f)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1000,
                    system=context,
                    messages=[
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state.messages
                    ]
                )
                answer = response.content[0].text
                st.markdown(answer)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer
                })
            except Exception as e:
                st.error(f"Error: {e}")