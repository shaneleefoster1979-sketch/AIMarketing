#!/usr/bin/env python3
"""
jerk_period_sweep.py

Backtests the RC+Jerk gate (no AI, matching current live logic exactly)
across several Jerk LPD_Period values, using a multi-column dump from
Jerk_HistoryDump_MultiPeriod.mq4 (timestamp;jerk_p10;jerk_p16;...).

Same dev/lockbox 85/15 split used throughout this project. Each period's
column is clamped to +-25 and aligned onto the Renko brick series via
merge_asof-backward, identical to jerk_generator.py's single-period path,
just repeated once per period column.
"""
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from rc_generator import load_rc_dump, align_to_renko
from zeus_backtest import run_zeus_backtest

RAW_DIR = Path(__file__).parent / "data" / "raw"
MULTI_PERIOD_FILE = RAW_DIR / "jerk_history_multiperiod.csv"
JERK_CLAMP_MAX = 25.0


def load_multiperiod_dump(path: Path, tz: str = "UTC") -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_localize(tz)
    df = df.sort_values("timestamp", kind="stable").drop_duplicates(subset=["timestamp"], keep="last")
    return df.reset_index(drop=True)


def align_period_column(renko_df: pd.DataFrame, dump_df: pd.DataFrame, period_col: str) -> pd.DataFrame:
    sub = dump_df[["timestamp", period_col]].dropna(subset=[period_col]).copy()
    sub["jerk_value"] = sub[period_col].clip(-JERK_CLAMP_MAX, JERK_CLAMP_MAX)
    sub = sub[["timestamp", "jerk_value"]]
    left = renko_df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    right = sub.sort_values("timestamp", kind="stable").reset_index(drop=True)
    return pd.merge_asof(left, right, on="timestamp", direction="backward")


def summarize(result: dict) -> tuple[int, float, float]:
    tl = result["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    wr = wins / len(tl) * 100 if tl else float("nan")
    return len(tl), wr, result["ending_equity"]


if __name__ == "__main__":
    if not MULTI_PERIOD_FILE.exists():
        print(f"Missing {MULTI_PERIOD_FILE} -- run Jerk_HistoryDump_MultiPeriod.mq4 and drop the CSV there first.")
        sys.exit(1)

    print("Building base Renko + RC dataset (shared across all periods)...")
    raw = load_time_series(RAW_DIR / "USDJPY_M1.csv")
    brick_size = BRICK_SIZE_PIPS * PIP_SIZE_USDJPY
    renko = generate_renko_bricks(raw, brick_size, decimals=DECIMALS)
    rc = load_rc_dump(RAW_DIR / "rc_history.csv")
    renko = align_to_renko(renko, rc)
    renko = renko.dropna(subset=["rc_value"]).reset_index(drop=True)
    print(f"  {len(renko)} bricks with RC")

    dump = load_multiperiod_dump(MULTI_PERIOD_FILE)
    period_cols = [c for c in dump.columns if re.match(r"jerk_p\d+$", c)]
    print(f"  periods found in dump: {[c.replace('jerk_p', '') for c in period_cols]}")

    results = []
    for col in period_cols:
        period = int(col.replace("jerk_p", ""))
        merged = align_period_column(renko, dump, col)
        usable = merged.dropna(subset=["rc_value", "jerk_value"]).reset_index(drop=True)
        n = len(usable)
        split = int(n * 0.85)
        dev = usable.iloc[:split].reset_index(drop=True)
        lockbox = usable.iloc[split:].reset_index(drop=True)

        dev_trades, dev_wr, dev_end = summarize(run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0))
        lb_trades, lb_wr, lb_end = summarize(run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0))

        results.append({
            "period": period, "usable_bricks": n,
            "dev_trades": dev_trades, "dev_wr": dev_wr, "dev_end": dev_end,
            "lb_trades": lb_trades, "lb_wr": lb_wr, "lb_end": lb_end,
        })
        print(f"period={period:>3}  usable={n:>6}  "
              f"dev: trades={dev_trades:>5} wr={dev_wr:>5.1f}% end=${dev_end:>14,.2f}  |  "
              f"lockbox: trades={lb_trades:>4} wr={lb_wr:>5.1f}% end=${lb_end:>12,.2f}")

    print()
    print("=" * 110)
    print(f"{'Period':>6} | {'Dev trades':>10} | {'Dev WR':>7} | {'Dev ending':>16} | {'LB trades':>9} | {'LB WR':>7} | {'LB ending':>14}")
    for r in sorted(results, key=lambda x: x["period"]):
        marker = " <- current live" if r["period"] == 32 else ""
        print(f"{r['period']:>6} | {r['dev_trades']:>10} | {r['dev_wr']:>6.1f}% | "
              f"${r['dev_end']:>14,.2f} | {r['lb_trades']:>9} | {r['lb_wr']:>6.1f}% | ${r['lb_end']:>12,.2f}{marker}")
