#!/usr/bin/env python3
"""
vwap_triple_test.py

Tests VWAP as a THIRD required agreement condition alongside RC+RMC
(same dual-agreement pattern Zeus already uses for RMC, extended to a
triple-agreement gate: RC, RMC, and VWAP must all agree in sign before
entry). Fixed Zeus settings throughout (60-pip stop, 60/120/180/none
targets, 3% risk) -- isolates the effect of the extra filter alone, no
AI/dynamic-settings involved. Standard dev/lockbox discipline.
"""
import sys
sys.path.insert(0, ".")
import pandas as pd

from vwap_generator import compute_vwap
from zeus_backtest import run_zeus_backtest, rc_dir, rmc_dir

renko = pd.read_csv("data/processed/renko_usdjpy.csv")
renko["timestamp"] = pd.to_datetime(renko["timestamp"], utc=True)
usable = renko.dropna(subset=["rc_value"]).reset_index(drop=True)
usable = compute_vwap(usable)

n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"dev: {len(dev)} bricks | lockbox: {len(lockbox)} bricks (untouched)")


def triple_direction_fn(row, slots):
    rc = rc_dir(row["rc_value"])
    rmc = rmc_dir(row["rmc_value"])
    vwap = row["vwap_dir"]
    if rc < 0 and rmc == -1 and vwap == -1:
        return -1
    if rc > 0 and rmc == 1 and vwap == 1:
        return 1
    return 0


def report(name, df):
    result = run_zeus_backtest(df, starting_balance=1000.0, spread_pips=1.0, direction_fn=triple_direction_fn)
    tl = result["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    wr = wins / len(tl) * 100 if tl else float("nan")
    print(f"{name}: trades={len(tl)}  win_rate={wr:.1f}%  ending=${result['ending_equity']:,.2f}")
    return len(tl), wr, result["ending_equity"]


print("\n=== RC+RMC+VWAP triple agreement ===")
report("dev", dev)
report("lockbox", lockbox)

print("\n=== Baseline: RC+RMC only (current live Zeus gate) ===")
r_dev = run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0)
r_lb = run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0)
for name, r in [("dev", r_dev), ("lockbox", r_lb)]:
    tl = r["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    wr = wins / len(tl) * 100 if tl else float("nan")
    print(f"{name}: trades={len(tl)}  win_rate={wr:.1f}%  ending=${r['ending_equity']:,.2f}")
