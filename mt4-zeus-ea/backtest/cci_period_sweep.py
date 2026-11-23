#!/usr/bin/env python3
"""
cci_period_sweep.py

Same plain CCI gate as cci_gate_test.py (CCI < 0 permits a buy, CCI > 0
permits a sell -- a veto on the existing RC+Jerk dual-agreement entry,
never a direction source), swept across CCI_Period = 5, 7, 9, 12 to see
how period choice affects it. Same dev/lockbox split, Jerk_LPD_Period=5.
"""
import sys
sys.path.insert(0, "/home/user/AIMarketing/mt4-zeus-ea/backtest")
from pathlib import Path

import pandas as pd

from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from rc_generator import load_rc_dump, align_to_renko
from cci_generator import compute_cci, cci_allows_direction
import zeus_backtest as zb

RAW_DIR = Path("/home/user/AIMarketing/mt4-zeus-ea/backtest/data/raw")
JERK_CLAMP_MAX = 25.0
PERIODS_TO_SWEEP = [5, 7, 9, 12]


def load_period_col(path, col, tz="UTC"):
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_localize(tz)
    df = df.sort_values("timestamp", kind="stable").drop_duplicates(subset=["timestamp"], keep="last")
    sub = df[["timestamp", col]].dropna(subset=[col]).copy()
    sub["jerk_value"] = sub[col].clip(-JERK_CLAMP_MAX, JERK_CLAMP_MAX)
    return sub[["timestamp", "jerk_value"]]


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


def summarize(result):
    tl = result["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    wr = wins / len(tl) * 100 if tl else float("nan")
    return len(tl), wr, result["ending_equity"]


print("Building dataset (RC + Jerk period=5)...")
raw = load_time_series(RAW_DIR / "USDJPY_M1.csv")
brick_size = BRICK_SIZE_PIPS * PIP_SIZE_USDJPY
renko = generate_renko_bricks(raw, brick_size, decimals=DECIMALS)
rc = load_rc_dump(RAW_DIR / "rc_history.csv")
renko = align_to_renko(renko, rc)

jerk5 = load_period_col(RAW_DIR / "jerk_history_multiperiod.csv", "jerk_p5")
left = renko.sort_values("timestamp", kind="stable").reset_index(drop=True)
right = jerk5.sort_values("timestamp", kind="stable").reset_index(drop=True)
renko = pd.merge_asof(left, right, on="timestamp", direction="backward")

usable_base = renko.dropna(subset=["rc_value", "jerk_value"]).reset_index(drop=True)

n = len(usable_base)
split = int(n * 0.85)
print(f"usable: {n} bricks -- dev: {split} | lockbox: {n - split}\n")

print("=== Current live rule (RC + Jerk dual-agreement) -- reference ===")
dev_ref = usable_base.iloc[:split].reset_index(drop=True)
lb_ref = usable_base.iloc[split:].reset_index(drop=True)
dev_t, dev_wr, dev_e = summarize(zb.run_zeus_backtest(dev_ref, starting_balance=1000.0, spread_pips=1.0))
lb_t, lb_wr, lb_e = summarize(zb.run_zeus_backtest(lb_ref, starting_balance=1000.0, spread_pips=1.0))
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")

for period in PERIODS_TO_SWEEP:
    usable = compute_cci(usable_base, period=period)
    dev = usable.iloc[:split].reset_index(drop=True)
    lockbox = usable.iloc[split:].reset_index(drop=True)

    dev_t, dev_wr, dev_e = summarize(zb.run_zeus_backtest(dev, 1000.0, direction_fn=cci_gated_direction))
    lb_t, lb_wr, lb_e = summarize(zb.run_zeus_backtest(lockbox, 1000.0, direction_fn=cci_gated_direction))

    print(f"\n=== CCI_Period = {period} ===")
    print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
    print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")
