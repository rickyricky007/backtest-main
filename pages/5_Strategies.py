"""Indicators reference, strategy definitions, groups, matrix backtests, SQLite runs."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

import backtest_runner as bt
import indicators_catalog as icat
import local_store as store
import strategy_matrix as smx

from dotenv import load_dotenv
import os
from alert_engine import send_telegram_message

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def _parse_dataset_label(label: str) -> tuple[str, str]:
    sym, rest = label.split(" | ", 1)
    iv = rest.split(" (", 1)[0].strip()
    return sym.strip().upper(), iv


st.set_page_config(page_title="Strategies", layout="wide")

st.title("Strategies & backtests")
st.caption(
    f"Indicator catalog + JSON strategies + groups + matrix tests on **{store.db_path().name}** (local SQLite)."
)

with st.sidebar:
    st.subheader("SQLite")
    st.caption(str(store.db_path()))
    st.markdown(
        "Supported **`config_json`**:\n"
        '- **`type`**: `sma_cross` | `rsi_threshold` | `bollinger_revert`\n'
        "- **`params`**: per type (see *Indicators reference*).\n"
        "- **Groups**: batch many strategies or compare **Group A vs Group B** per symbol."
    )

store.init_db()

(
    tab_ref,
    tab_build,
    tab_run,
    tab_groups,
    tab_matrix,
    tab_history,
) = st.tabs(
    [
        "Indicators reference",
        "Build strategies",
        "Run backtest",
        "Strategy groups",
        "Batch & compare groups",
        "Past runs",
    ]
)

with tab_ref:
    st.subheader("Building blocks (combine with price / volume)")
    st.markdown(
        "Use these indicators in your own rules. Preset **`type`** values are implemented in "
        "`backtest_runner.py`; extend there for more logic."
    )
    for category, rows in icat.indicators_by_category().items():
        st.markdown(f"#### {category}")
        for ind in rows:
            with st.expander(f"{ind['name']} (`{ind['id']}`)", expanded=False):
                st.markdown(f"**Inputs:** {ind.get('inputs', '—')}")
                st.markdown(ind.get("description", ""))
                if ind.get("params"):
                    st.markdown("**Parameters**")
                    st.json(ind["params"])
                st.markdown(f"**Combine with:** {ind.get('combinations', '—')}")
                if ind.get("strategy_types"):
                    st.caption("Runnable types: " + ", ".join(ind["strategy_types"]))

    st.divider()
    st.subheader("Runnable strategy presets (`type` + `params`)")
    for spec in icat.STRATEGY_TYPE_HELP:
        with st.expander(spec["title"] + f" — `{spec['type']}`", expanded=False):
            st.markdown(spec.get("rules", ""))
            st.code(json.dumps(spec["config_example"], indent=2), language="json")

with tab_build:
    st.subheader("Create strategy")
    ex = icat.STRATEGY_TYPE_HELP[0]["config_example"]
    default_cfg = json.dumps(ex, indent=2)
    with st.form("new_strategy", clear_on_submit=True):
        n1, n2 = st.columns(2)
        with n1:
            name = st.text_input("Name", placeholder="e.g. nifty_ma_cross")
        with n2:
            description = st.text_area("Description", placeholder="Plain-language rules", height=100)
        cfg_text = st.text_area("config_json", value=default_cfg, height=220)
        submitted = st.form_submit_button("Save strategy", type="primary")
        if submitted:
            name = (name or "").strip()
            if not name:
                st.error("Name is required.")
            else:
                try:
                    cfg = json.loads(cfg_text or "{}")
                    if not isinstance(cfg, dict):
                        st.error("config_json must be a JSON object `{}`.")
                    elif "type" not in cfg:
                        st.error('config_json must include a "type" field (see Indicators reference).')
                    else:
                        store.create_strategy(name, description or "", cfg)
                        st.success(f"Saved strategy **{name}**.")
                        st.rerun()
                except json.JSONDecodeError as e:
                    st.error(f"Invalid JSON: {e}")
                except Exception as e:
                    st.error(str(e))

    st.divider()
    st.subheader("Saved strategies")
    df = store.list_strategies()
    if df.empty:
        st.info("No strategies yet. Add one above.")
    else:
        st.dataframe(
            df.drop(columns=["config_json"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Edit or delete")
        labels = [f"{r['id']}: {r['name']}" for _, r in df.iterrows()]
        choice = st.selectbox("Strategy", options=labels, key="strat_pick")
        sid = int(choice.split(":", 1)[0].strip())
        row = store.get_strategy(sid)
        if row:
            with st.form("edit_strategy"):
                en = st.text_input("Name", value=row["name"])
                ed = st.text_area("Description", value=row.get("description") or "", height=80)
                ej = st.text_area(
                    "config_json",
                    value=json.dumps(row.get("config") or {}, indent=2, ensure_ascii=False),
                    height=240,
                )
                upd = st.form_submit_button("Update strategy", type="primary")
                if upd:
                    try:
                        cfg = json.loads(ej or "{}")
                        if not isinstance(cfg, dict):
                            st.error("config_json must be a JSON object `{}`.")
                        elif "type" not in cfg:
                            st.error('config_json must include "type".')
                        else:
                            store.update_strategy(sid, en, ed, cfg)
                            st.success("Updated.")
                            st.rerun()
                    except json.JSONDecodeError as e:
                        st.error(f"Invalid JSON: {e}")
                    except Exception as e:
                        st.error(str(e))

            if st.button("Delete this strategy", key="strat_delete_btn"):
                store.delete_strategy(sid)
                st.success("Deleted.")
                st.rerun()

        with st.expander("Raw config_json (all strategies)"):
            for _, r in df.iterrows():
                st.markdown(f"**{r['name']}** (id={r['id']})")
                st.code(r["config_json"] or "{}", language="json")

with tab_run:
    st.subheader("Backtest on SQLite OHLCV")
    meta = store.list_historical_series()
    strat_df = store.list_strategies()
    if meta.empty:
        st.warning("No historical series in the database. Use **Historical data** page to download first.")
    elif strat_df.empty:
        st.warning("No strategies defined. Create one under **Build strategies**.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            slabels = [f"{r['id']}: {r['name']}" for _, r in strat_df.iterrows()]
            schoice = st.selectbox("Strategy", slabels, key="bt_strat")
            strat_id = int(schoice.split(":", 1)[0].strip())
        with c2:
            mlabels = [f"{r['symbol']} | {r['interval']} ({int(r['bars'])} bars)" for _, r in meta.iterrows()]
            mchoice = st.selectbox("Dataset", mlabels, key="bt_data")
            sym, iv = _parse_dataset_label(mchoice)

        max_bars = st.number_input("Max bars to load (full history can be large)", 500, 500_000, 15_000, 500)

        if st.button("Run backtest", type="primary", key="bt_go"):
            strat = store.get_strategy(strat_id)
            if not strat:
                st.error("Strategy not found.")
            else:
                try:
                    ohlc = store.load_historical_bars(sym, iv, limit=int(max_bars))
                    if ohlc.empty:
                        st.error("No rows for that dataset.")
                    else:
                        res = bt.run_backtest(ohlc, strat["config"])
                        st.session_state["_last_bt"] = res
                        st.session_state["_last_bt_meta"] = {
                            "strategy_id": strat_id,
                            "symbol": sym,
                            "interval": iv,
                        }
                except Exception as e:
                    st.error(str(e))

        res = st.session_state.get("_last_bt")
        meta_bt = st.session_state.get("_last_bt_meta")
        if res and meta_bt:
            st.success("Backtest finished (not saved yet).")
            s = res.get("summary") or {}
            send_telegram_message(TOKEN, CHAT_ID,
                 f"📊 <b>Backtest Complete!</b>\n"
                f"📌 Symbol: <b>{meta_bt['symbol']}</b>\n"
                f"💰 Final Equity: ₹{s.get('final_equity', 0):,.0f}\n"
                f"📈 Return: {s.get('total_return_pct', 0):.2f}%\n"
                f"📉 Max DD: {s.get('max_drawdown_pct', 0):.2f}%\n"
                f"🔁 Trades: {s.get('num_trades', 0)}"                      
            )
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Final equity", f"{s.get('final_equity', 0):,.0f}")
            m2.metric("Total return %", f"{s.get('total_return_pct', 0):.2f}")
            m3.metric("Max DD %", f"{s.get('max_drawdown_pct', 0):.2f}")
            m4.metric("Trades", s.get("num_trades", 0))
            m5.metric("Sharpe-like (daily step)", f"{s.get('sharpe_like_daily', 0):.2f}")

            eq = pd.DataFrame(res.get("equity_curve_sample") or [])
            if not eq.empty:
                st.line_chart(eq.set_index("bar_ts")["equity"])

            with st.expander("Trades"):
                st.dataframe(pd.DataFrame(res.get("trades") or []), use_container_width=True, hide_index=True)

            if st.button("Save this run to SQLite", key="bt_save"):
                try:
                    summary, blob = bt.results_to_storable_blob(res)
                    rid = store.save_backtest_run(
                        meta_bt["strategy_id"],
                        meta_bt["symbol"],
                        meta_bt["interval"],
                        summary=summary,
                        results_json=blob,
                    )
                    st.success(f"Saved as backtest run **id={rid}**.")
                except Exception as e:
                    st.error(str(e))

with tab_groups:
    st.subheader("Strategy groups")
    st.caption(
        "Put strategies into named groups (e.g. **momentum** vs **mean reversion**). "
        "Use **Batch & compare groups** to run everyone in a group, or **Group A vs Group B** per symbol."
    )
    gdf = store.list_strategy_groups()
    with st.form("new_group"):
        gn = st.text_input("New group name", placeholder="e.g. momentum_pack")
        add_g = st.form_submit_button("Create group")
        if add_g:
            gn = (gn or "").strip()
            if not gn:
                st.error("Name is required.")
            else:
                try:
                    store.create_strategy_group(gn)
                    st.success(f"Created **{gn}**.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    if gdf.empty:
        st.info("No groups yet.")
    else:
        st.dataframe(gdf, use_container_width=True, hide_index=True)

    st.divider()
    sdf = store.list_strategies()
    if not gdf.empty and not sdf.empty:
        gid = int(
            st.selectbox(
                "Manage members for group",
                options=[int(r["id"]) for _, r in gdf.iterrows()],
                format_func=lambda i: dict(zip(gdf["id"], gdf["name"]))[i],
                key="grp_manage_id",
            )
        )
        members = store.list_group_members(gid)
        st.markdown("**Members**")
        if members.empty:
            st.caption("No strategies in this group.")
        else:
            st.dataframe(members, use_container_width=True, hide_index=True)

        strat_opts = {f"{r['id']}: {r['name']}": int(r["id"]) for _, r in sdf.iterrows()}
        pick_add = st.multiselect("Add strategies to group", list(strat_opts.keys()), key="grp_add_ms")
        if st.button("Add selected to group", key="grp_add_btn"):
            for lbl in pick_add:
                store.add_strategy_to_group(gid, strat_opts[lbl])
            st.success("Updated.")
            st.rerun()

        if not members.empty:
            rm_lbl = st.selectbox(
                "Remove from group",
                [f"{r['strategy_id']}: {r['strategy_name']}" for _, r in members.iterrows()],
                key="grp_rm_sel",
            )
            if st.button("Remove selected member", key="grp_rm_btn"):
                rsid = int(rm_lbl.split(":", 1)[0].strip())
                store.remove_strategy_from_group(gid, rsid)
                st.rerun()

        del_pick = st.selectbox(
            "Delete entire group",
            options=[int(r["id"]) for _, r in gdf.iterrows()],
            format_func=lambda i: dict(zip(gdf["id"], gdf["name"]))[i],
            key="grp_del_sel",
        )
        if st.button("Delete group (and memberships)", key="grp_del_btn"):
            store.delete_strategy_group(del_pick)
            st.success("Group deleted.")
            st.rerun()

with tab_matrix:
    st.subheader("Batch & group comparison")
    st.markdown(
        "**Batch** runs **many strategies on the same set of symbols** so you can rank them. "
        "**Group vs group** runs **all strategies in group A** and **all in group B** on the same "
        "datasets and summarizes which group fits each symbol better (mean / median return, best name)."
    )

    meta = store.list_historical_series()
    strat_df = store.list_strategies()
    gdf = store.list_strategy_groups()

    if meta.empty or strat_df.empty:
        st.warning("Need at least one historical series and one strategy (see other tabs).")
    else:
        mlabels = [f"{r['symbol']} | {r['interval']} ({int(r['bars'])} bars)" for _, r in meta.iterrows()]
        max_bars = st.number_input(
            "Max bars per series (applies to all runs below)",
            500,
            500_000,
            10_000,
            500,
            key="mx_max_bars",
        )

        st.markdown("### A) Batch — multiple strategies × multiple datasets")
        batch_strat_lbls = st.multiselect(
            "Strategies to run together",
            [f"{r['id']}: {r['name']}" for _, r in strat_df.iterrows()],
            key="mx_batch_strats",
        )
        batch_ds = st.multiselect(
            "Datasets",
            mlabels,
            default=mlabels[: min(3, len(mlabels))],
            key="mx_batch_ds",
        )
        if st.button("Run batch matrix", type="primary", key="mx_batch_go"):
            if not batch_strat_lbls or not batch_ds:
                st.error("Pick at least one strategy and one dataset.")
            else:
                ids = [int(x.split(":", 1)[0].strip()) for x in batch_strat_lbls]
                ds_keys = [_parse_dataset_label(x) for x in batch_ds]
                prog = st.progress(0, text="Running…")
                total = max(1, len(ids) * len(ds_keys))
                state = {"k": 0}

                def step() -> None:
                    state["k"] += 1
                    prog.progress(min(state["k"] / total, 1.0), text=f"{state['k']}/{total}")

                try:
                    bdf = smx.run_strategy_matrix(
                        ids,
                        ds_keys,
                        int(max_bars),
                        group_key="batch",
                        group_name="batch",
                        on_step=step,
                    )
                    st.session_state["_mx_batch"] = bdf
                finally:
                    prog.empty()

        bdf = st.session_state.get("_mx_batch")
        if bdf is not None and not bdf.empty:
            st.dataframe(bdf, use_container_width=True, hide_index=True)
            err_n = int(bdf["error"].notna().sum()) if "error" in bdf.columns else 0
            if err_n:
                st.caption(f"{err_n} rows have errors — expand filters or fix configs.")
            ok = bdf[bdf["error"].isna()].copy() if "error" in bdf.columns else bdf
            if not ok.empty and ok["total_return_pct"].notna().any():
                st.markdown("**Mean return % by strategy (across selected symbols)**")
                ch = ok.groupby("strategy_name", as_index=False)["total_return_pct"].mean()
                st.bar_chart(ch.set_index("strategy_name"))
            csv_b = bdf.to_csv(index=False).encode("utf-8")
            st.download_button("Download batch results CSV", csv_b, "batch_matrix.csv", "text/csv")

        st.divider()
        st.markdown("### B) Group A vs Group B — which pack fits which symbol?")
        if gdf.empty or len(gdf) < 2:
            st.info("Create **two** strategy groups under **Strategy groups** first.")
        else:
            gopts = {int(r["id"]): str(r["name"]) for _, r in gdf.iterrows()}
            ga = st.selectbox("Group A", options=list(gopts.keys()), format_func=lambda i: gopts[i], key="mx_ga")
            gb = st.selectbox(
                "Group B",
                options=[x for x in gopts.keys() if x != ga] or list(gopts.keys()),
                format_func=lambda i: gopts[i],
                key="mx_gb",
            )
            cmp_ds = st.multiselect(
                "Datasets for comparison",
                mlabels,
                default=mlabels[: min(5, len(mlabels))],
                key="mx_cmp_ds",
            )
            if st.button("Run group vs group", type="primary", key="mx_cmp_go"):
                if not cmp_ds:
                    st.error("Select at least one dataset.")
                else:
                    ds_keys = [_parse_dataset_label(x) for x in cmp_ds]
                    prog2 = st.progress(0, text="Comparing…")
                    tot = (
                        len(store.get_group_strategy_ids(ga) or []) * len(ds_keys)
                        + len(store.get_group_strategy_ids(gb) or []) * len(ds_keys)
                    )
                    tot = max(1, tot)
                    st2 = {"k": 0}

                    def step2() -> None:
                        st2["k"] += 1
                        prog2.progress(min(st2["k"] / tot, 1.0), text=f"{st2['k']}/{tot}")

                    try:
                        det, summ = smx.compare_strategy_groups(
                            ga,
                            gb,
                            ds_keys,
                            int(max_bars),
                            on_step=step2,
                        )
                        st.session_state["_mx_cmp_detail"] = det
                        st.session_state["_mx_cmp_summary"] = summ
                    except Exception as e:
                        st.error(str(e))
                    finally:
                        prog2.empty()

        det = st.session_state.get("_mx_cmp_detail")
        summ = st.session_state.get("_mx_cmp_summary")
        if det is not None and isinstance(det, pd.DataFrame) and not det.empty:
            st.markdown("**Detail (every strategy × symbol)**")
            st.dataframe(det, use_container_width=True, hide_index=True)
            st.download_button(
                "Download detail CSV",
                det.to_csv(index=False).encode("utf-8"),
                "group_compare_detail.csv",
                "text/csv",
                key="dl_det",
            )
        if summ is not None and isinstance(summ, pd.DataFrame) and not summ.empty:
            st.markdown("**Summary — who wins per symbol?**")
            st.dataframe(summ, use_container_width=True, hide_index=True)
            st.download_button(
                "Download summary CSV",
                summ.to_csv(index=False).encode("utf-8"),
                "group_compare_summary.csv",
                "text/csv",
                key="dl_sum",
            )
            wmean = summ["winner_by_mean"].value_counts(dropna=False)
            st.caption("Win counts (by mean return): " + ", ".join(f"{k}={v}" for k, v in wmean.items()))

with tab_history:
    st.subheader("Saved backtest runs")
    runs = store.list_backtest_runs(limit=200)
    if runs.empty:
        st.info("No runs saved yet.")
    else:
        st.dataframe(runs, use_container_width=True, hide_index=True)
        pick = st.selectbox("Inspect run id", [int(x) for x in runs["id"].tolist()])
        br = store.get_backtest_run(pick)
        if br:
            st.json(br.get("summary") or {})
            res = br.get("results") or {}
            tdf = pd.DataFrame(res.get("trades") or [])
            if not tdf.empty:
                st.markdown("**Trades**")
                st.dataframe(tdf, use_container_width=True, hide_index=True)
            edf = pd.DataFrame(res.get("equity_curve_sample") or [])
            if not edf.empty:
                st.markdown("**Equity (sampled)**")
                st.line_chart(edf.set_index("bar_ts")["equity"])
