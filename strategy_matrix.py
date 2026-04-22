"""Batch backtests: many strategies × many datasets; group vs group comparison."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

import backtest_runner as bt
import local_store as store

OnStep = Callable[[], None]


def run_strategy_matrix(
    strategy_ids: list[int],
    datasets: list[tuple[str, str]],
    max_bars: int,
    *,
    group_key: str = "",
    group_name: str = "",
    on_step: OnStep | None = None,
) -> pd.DataFrame:
    """
    Run every strategy in `strategy_ids` on every (symbol, interval) in `datasets`.
    `group_key` / `group_name` tag rows for later comparison (e.g. A vs B).
    """
    rows: list[dict[str, Any]] = []
    for sym, iv in datasets:
        sym = sym.strip().upper()
        iv = iv.strip()
        ohlc = store.load_historical_bars(sym, iv, limit=int(max_bars))
        for sid in strategy_ids:
            if on_step:
                on_step()
            base: dict[str, Any] = {
                "group_key": group_key,
                "group_name": group_name,
                "strategy_id": int(sid),
                "strategy_name": "",
                "symbol": sym,
                "interval": iv,
                "total_return_pct": None,
                "max_drawdown_pct": None,
                "num_trades": None,
                "final_equity": None,
                "error": None,
            }
            strat = store.get_strategy(int(sid))
            if not strat:
                base["error"] = "strategy not found"
                rows.append(base)
                continue
            base["strategy_name"] = str(strat.get("name") or "")
            if ohlc is None or ohlc.empty:
                base["error"] = "no bars"
                rows.append(base)
                continue
            try:
                res = bt.run_backtest(ohlc, strat["config"])
                s = res.get("summary") or {}
                base["total_return_pct"] = s.get("total_return_pct")
                base["max_drawdown_pct"] = s.get("max_drawdown_pct")
                base["num_trades"] = s.get("num_trades")
                base["final_equity"] = s.get("final_equity")
            except Exception as e:
                base["error"] = str(e)
            rows.append(base)
    return pd.DataFrame(rows)


def summarize_group_vs_group(detail: pd.DataFrame) -> pd.DataFrame:
    """
    For each (symbol, interval), compare mean return of group A vs B and pick best strategy per side.
    Expects `detail` from two `run_strategy_matrix` calls concatenated with group_key A and B.
    """
    if detail.empty or "group_key" not in detail.columns:
        return pd.DataFrame()
    d = detail.copy()
    d["ok"] = d["error"].isna() & d["total_return_pct"].notna()
    out_rows: list[dict[str, Any]] = []
    for (sym, iv), g in d.groupby(["symbol", "interval"], sort=False):
        ga = g[(g["group_key"] == "A") & g["ok"]]
        gb = g[(g["group_key"] == "B") & g["ok"]]
        ma = float(ga["total_return_pct"].mean()) if len(ga) else float("nan")
        mb = float(gb["total_return_pct"].mean()) if len(gb) else float("nan")
        med_a = float(ga["total_return_pct"].median()) if len(ga) else float("nan")
        med_b = float(gb["total_return_pct"].median()) if len(gb) else float("nan")

        def _best(sub: pd.DataFrame) -> tuple[str | None, float | None]:
            if sub.empty or not sub["total_return_pct"].notna().any():
                return None, None
            sub2 = sub.dropna(subset=["total_return_pct"])
            if sub2.empty:
                return None, None
            k = int(sub2["total_return_pct"].values.argmax())
            row = sub2.iloc[k]
            return str(row["strategy_name"]), float(row["total_return_pct"])

        best_a_name, best_a_ret = _best(ga)
        best_b_name, best_b_ret = _best(gb)

        if pd.isna(ma) and pd.isna(mb):
            winner_mean = "n/a"
        elif pd.isna(ma):
            winner_mean = "B"
        elif pd.isna(mb):
            winner_mean = "A"
        elif ma > mb:
            winner_mean = "A"
        elif mb > ma:
            winner_mean = "B"
        else:
            winner_mean = "tie"

        if pd.isna(med_a) and pd.isna(med_b):
            winner_med = "n/a"
        elif pd.isna(med_a):
            winner_med = "B"
        elif pd.isna(med_b):
            winner_med = "A"
        elif med_a > med_b:
            winner_med = "A"
        elif med_b > med_a:
            winner_med = "B"
        else:
            winner_med = "tie"

        out_rows.append(
            {
                "symbol": sym,
                "interval": iv,
                "n_A": int(len(ga)),
                "n_B": int(len(gb)),
                "mean_return_pct_A": round(ma, 4) if pd.notna(ma) else None,
                "mean_return_pct_B": round(mb, 4) if pd.notna(mb) else None,
                "median_return_pct_A": round(med_a, 4) if pd.notna(med_a) else None,
                "median_return_pct_B": round(med_b, 4) if pd.notna(med_b) else None,
                "winner_by_mean": winner_mean,
                "winner_by_median": winner_med,
                "best_strategy_A": best_a_name,
                "best_return_pct_A": round(best_a_ret, 4) if best_a_ret is not None and pd.notna(best_a_ret) else None,
                "best_strategy_B": best_b_name,
                "best_return_pct_B": round(best_b_ret, 4) if best_b_ret is not None and pd.notna(best_b_ret) else None,
            }
        )
    return pd.DataFrame(out_rows)


def compare_strategy_groups(
    group_a_id: int,
    group_b_id: int,
    datasets: list[tuple[str, str]],
    max_bars: int,
    *,
    on_step: OnStep | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Backtest all strategies in group A and all in group B on each dataset; return (detail, summary).
    """
    a = store.get_strategy_group(int(group_a_id))
    b = store.get_strategy_group(int(group_b_id))
    if not a or not b:
        raise ValueError("Unknown strategy group id.")
    ids_a = a["strategy_ids"]
    ids_b = b["strategy_ids"]
    if not ids_a or not ids_b:
        raise ValueError("Each group needs at least one strategy.")
    if not datasets:
        raise ValueError("Select at least one dataset.")

    def step() -> None:
        if on_step:
            on_step()

    df_a = run_strategy_matrix(
        ids_a,
        datasets,
        max_bars,
        group_key="A",
        group_name=str(a["name"]),
        on_step=step,
    )
    df_b = run_strategy_matrix(
        ids_b,
        datasets,
        max_bars,
        group_key="B",
        group_name=str(b["name"]),
        on_step=step,
    )
    detail = pd.concat([df_a, df_b], ignore_index=True)
    summary = summarize_group_vs_group(detail)
    return detail, summary
