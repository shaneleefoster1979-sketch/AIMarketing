#!/usr/bin/env python3
"""
rc_period_sweep.py

Backtests the CURRENT live EA rule exactly -- RC + Jerk dual-agreement,
gated by CCI (CCI<0 permits buy, CCI>0 permits sell), Jerk_LPD_Period=5,
CCI_Period=14 -- across several RC_Period values, using a multi-column
dump from RC_HistoryDump_MultiPeriod.mq4 (timestamp;blue_p96;maroon_p96;
blue_p86;maroon_p86;...).

Same sentinel handling and blue/maroon-to-signed-value combination as
rc_generator.py's single-period path (2147483647.0 = not-enough-warmup,
blue is the bull buffer, maroon is already negative-signed for bear),
just repeated once per period's column pair. Same dev/lockbox 85/15
split used throughout this project.
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from cci_generator import compute_cci, cci_allows_direction
import zeus_backtest as zb

RAW_DIR = Path(__file__).parent / "data" / "raw"
MULTI_PERIOD_FILE = RAW_DIR / "rc_history_multiperiod.csv"
RC_EMPTY_SENTINEL = 2147483647.0
JERK_CLAMP_MAX = 25.0
# NOTE: the current live RC_Period (8) is NOT among the periods swept here --
# the dump script's RC_Period8 input defaulted to 26, not 8 (a labeling
# mistake in that file, not in what it captured). This sweep only covers
# the 96-down-to-6-by-10s sequence actually requested and actually dumped.


def load_multiperiod_dump(path: Path, tz: str = "UTC") -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_localize(tz)
    df = df.sort_values("timestamp", kind="stable").drop_duplicates(subset=["timestamp"], keep="last")
    return df.reset_index(drop=True)


def load_period_col(path, col, tz="UTC"):
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_localize(tz)
    df = df.sort_values("timestamp", kind="stable").drop_duplicates(subset=["timestamp"], keep="last")
    sub = df[["timestamp", col]].dropna(subset=[col]).copy()
    sub["jerk_value"] = sub[col].clip(-JERK_CLAMP_MAX, JERK_CLAMP_MAX)
    return sub[["timestamp", "jerk_value"]]


def align_rc_period(renko_df: pd.DataFrame, dump_df: pd.DataFrame, period: int) -> pd.DataFrame:
    blue_col, maroon_col = f"blue_p{period}", f"maroon_p{period}"
    blue = dump_df[blue_col].where(dump_df[blue_col] != RC_EMPTY_SENTINEL, np.nan)
    maroon = dump_df[maroon_col].where(dump_df[maroon_col] != RC_EMPTY_SENTINEL, np.nan)
    rc_value = np.where(blue.fillna(0) != 0, blue, np.where(maroon.fillna(0) != 0, maroon, np.nan))

    sub = pd.DataFrame({"timestamp": dump_df["timestamp"], "rc_value": rc_value}).dropna(subset=["rc_value"])
    sub = sub.sort_values("timestamp", kind="stable").drop_duplicates(subset=["timestamp"], keep="last")

    left = renko_df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    right = sub.sort_values("timestamp", kind="stable").reset_index(drop=True)
    return pd.merge_asof(left, right, on="timestamp", direction="backward")


def cci_gated_direction(row, slots):
    rc = zb.rc_dir(row["rc_value"])
    jerk = zb.jerk_dir(row["jerk_value"])
    entry_dir = 0
    if rc < 0 and jerk == -1:
        entry_dir = -1
    elif rc > 0 and jerk == 1:
        entry_dir = 1
    if entry_dir == 0:
        return 0
    return entry_dir if cci_allows_direction(entry_dir, row["cci_value"]) else 0


def summarize(result: dict) -> tuple[int, float, float]:
    tl = result["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    wr = wins / len(tl) * 100 if tl else float("nan")
    return len(tl), wr, result["ending_equity"]


if __name__ == "__main__":
    if not MULTI_PERIOD_FILE.exists():
        print(f"Missing {MULTI_PERIOD_FILE} -- run RC_HistoryDump_MultiPeriod.mq4 and drop the CSV there first.")
        sys.exit(1)

    print("Building base Renko + Jerk(p5) + CCI(14) dataset (shared across all RC periods)...")
    raw = load_time_series(RAW_DIR / "USDJPY_M1.csv")
    brick_size = BRICK_SIZE_PIPS * PIP_SIZE_USDJPY
    renko = generate_renko_bricks(raw, brick_size, decimals=DECIMALS)

    jerk5 = load_period_col(RAW_DIR / "jerk_history_multiperiod.csv", "jerk_p5")
    left = renko.sort_values("timestamp", kind="stable").reset_index(drop=True)
    right = jerk5.sort_values("timestamp", kind="stable").reset_index(drop=True)
    renko = pd.merge_asof(left, right, on="timestamp", direction="backward")

    renko = compute_cci(renko)
    print(f"  {len(renko)} bricks, Jerk coverage: {renko['jerk_value'].notna().sum()}, "
          f"CCI coverage: {renko['cci_value'].notna().sum()}")

    dump = load_multiperiod_dump(MULTI_PERIOD_FILE)
    period_cols = [c for c in dump.columns if re.match(r"blue_p\d+$", c)]
    periods = sorted((int(c.replace("blue_p", "")) for c in period_cols), reverse=True)
    print(f"  RC periods found in dump: {periods}")

    results = []
    for period in periods:
        merged = align_rc_period(renko, dump, period)
        usable = merged.dropna(subset=["rc_value", "jerk_value", "cci_value"]).reset_index(drop=True)
        n = len(usable)
        split = int(n * 0.85)
        dev = usable.iloc[:split].reset_index(drop=True)
        lockbox = usable.iloc[split:].reset_index(drop=True)

        dev_trades, dev_wr, dev_end = summarize(
            zb.run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0, direction_fn=cci_gated_direction))
        lb_trades, lb_wr, lb_end = summarize(
            zb.run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0, direction_fn=cci_gated_direction))

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
    for r in sorted(results, key=lambda x: -x["period"]):
        print(f"{r['period']:>6} | {r['dev_trades']:>10} | {r['dev_wr']:>6.1f}% | "
              f"${r['dev_end']:>14,.2f} | {r['lb_trades']:>9} | {r['lb_wr']:>6.1f}% | ${r['lb_end']:>12,.2f}")
