#!/usr/bin/env python3
"""
One-off test (not committed to the pipeline): inverts Jerk's sign
convention for BOTH entry and exit -- buy above 0 / sell below 0,
instead of the current live buy below 0 / sell above 0 -- and reruns
the standard dev/lockbox split at LPD_Period=5 (the current live
setting) to compare against the normal-sign result.
"""
import sys
sys.path.insert(0, "/home/user/AIMarketing/mt4-zeus-ea/backtest")
from pathlib import Path

import pandas as pd

from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from rc_generator import load_rc_dump, align_to_renko
import zeus_backtest as zb

RAW_DIR = Path("/home/user/AIMarketing/mt4-zeus-ea/backtest/data/raw")
JERK_CLAMP_MAX = 25.0


def load_period_col(path, col, tz="UTC"):
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_localize(tz)
    df = df.sort_values("timestamp", kind="stable").drop_duplicates(subset=["timestamp"], keep="last")
    sub = df[["timestamp", col]].dropna(subset=[col]).copy()
    sub["jerk_value"] = sub[col].clip(-JERK_CLAMP_MAX, JERK_CLAMP_MAX)
    return sub[["timestamp", "jerk_value"]]


def inverted_jerk_dir(jerk_value):
    if pd.isna(jerk_value):
        return 0
    if jerk_value > 0:
        return 1   # INVERTED: Jerk above zero -> buy side
    if jerk_value < 0:
        return -1  # INVERTED: Jerk below zero -> sell side
    return 0


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

usable = renko.dropna(subset=["rc_value", "jerk_value"]).reset_index(drop=True)
n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"usable: {n} bricks | dev: {len(dev)} | lockbox: {len(lockbox)}\n")

print("=== NORMAL sign (current live: buy below 0, sell above 0) ===")
dev_t, dev_wr, dev_e = summarize(zb.run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0))
lb_t, lb_wr, lb_e = summarize(zb.run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0))
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")

print("\n=== INVERTED sign (buy above 0, sell below 0) ===")
zb.jerk_dir = inverted_jerk_dir  # monkey-patch: affects both entry AND exit, both call the module-level jerk_dir()
dev_t2, dev_wr2, dev_e2 = summarize(zb.run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0))
lb_t2, lb_wr2, lb_e2 = summarize(zb.run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0))
print(f"  dev    : trades={dev_t2} wr={dev_wr2:.1f}% ending=${dev_e2:,.2f}")
print(f"  lockbox: trades={lb_t2} wr={lb_wr2:.1f}% ending=${lb_e2:,.2f}")
