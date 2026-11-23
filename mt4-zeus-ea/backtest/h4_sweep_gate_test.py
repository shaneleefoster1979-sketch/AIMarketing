#!/usr/bin/env python3
"""
h4_sweep_gate_test.py

Tests gating the current live entry rule (RC+Jerk dual-agreement) with a
4-hour-timeframe liquidity-sweep bias (see h4_sweep_generator.py): a buy
is only permitted while the bias is armed "buy only" (a bullish H4 candle
swept, then recovered, by the very next H4 candle), a sell only while
armed "sell only" -- a pure veto on top of RC+Jerk, same as the CCI gate
tests, never a direction source of its own. Same dev/lockbox split,
Jerk_LPD_Period=5.
"""
import sys
sys.path.insert(0, "/home/user/AIMarketing/mt4-zeus-ea/backtest")
from pathlib import Path

import pandas as pd

from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from rc_generator import load_rc_dump, align_to_renko
from h4_sweep_generator import build_h4_bars, compute_h4_sweep_bias, align_h4_bias_to_renko, h4_bias_allows_direction
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


def h4_gated_direction(row, slots):
    rc = zb.rc_dir(row["rc_value"])
    jerk = zb.jerk_dir(row["jerk_value"])
    entry_dir = 0
    if rc < 0 and jerk == -1:
        entry_dir = -1
    elif rc > 0 and jerk == 1:
        entry_dir = 1
    if entry_dir == 0:
        return 0
    return entry_dir if h4_bias_allows_direction(entry_dir, row["h4_bias"]) else 0


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

print("Building H4 bars from the same M1 series and computing the sweep bias...")
h4_bars = build_h4_bars(raw)
h4_bias = compute_h4_sweep_bias(h4_bars)
usable = align_h4_bias_to_renko(usable_base, h4_bias)
buy_bricks = int((usable["h4_bias"] == 1).sum())
sell_bricks = int((usable["h4_bias"] == -1).sum())
print(f"usable: {len(usable)} bricks -- buy-biased: {buy_bricks}, sell-biased: {sell_bricks}, "
      f"neutral/unarmed: {len(usable) - buy_bricks - sell_bricks}\n")

n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"dev: {len(dev)} | lockbox: {len(lockbox)}\n")

print("=== Current live rule (RC + Jerk dual-agreement) -- reference ===")
dev_t, dev_wr, dev_e = summarize(zb.run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0))
lb_t, lb_wr, lb_e = summarize(zb.run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0))
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")

print("\n=== RC + Jerk, gated by 4H sweep bias (sticky until opposite sweep fires) ===")
dev_t2, dev_wr2, dev_e2 = summarize(zb.run_zeus_backtest(dev, 1000.0, direction_fn=h4_gated_direction))
lb_t2, lb_wr2, lb_e2 = summarize(zb.run_zeus_backtest(lockbox, 1000.0, direction_fn=h4_gated_direction))
print(f"  dev    : trades={dev_t2} wr={dev_wr2:.1f}% ending=${dev_e2:,.2f}")
print(f"  lockbox: trades={lb_t2} wr={lb_wr2:.1f}% ending=${lb_e2:,.2f}")
