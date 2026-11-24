#!/usr/bin/env python3
"""
orb_break_retest_test.py

Break-and-retest strategy, per request:
  1. 15-minute opening range at 9:30-9:45 AM New York (16:30-16:45 broker
     time -- see orb_generator.py for the broker-offset derivation).
  2. A breakout brick closes beyond the range -- arms "waiting for retest".
  3. The next brick whose wick comes back to touch the broken level but
     still closes back beyond it fires a SINGLE entry that day (see
     compute_break_retest_signal() in orb_generator.py for the exact
     state machine).

Stop-loss: just below the retest brick's own Low for a buy (just above its
own High for a sell) -- the specific brick that triggered entry, not the
opening range's opposite boundary. Taken literally as exactly that Low/High,
no extra buffer added since none was specified.

Risk/reward: 1:3 fixed. Target = entry +/- 3x the SL distance.

Single trade, full position (not the 4-leg T1-T4 split) -- sized with the
same 3% TotalRiskPercent convention as every other backtest this session,
applied entirely to this one trade. Only one position open at a time; a new
day's signal is skipped if the previous day's trade hasn't closed yet.
"""
import sys
sys.path.insert(0, "/home/user/AIMarketing/mt4-zeus-ea/backtest")
from pathlib import Path

import pandas as pd

from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from orb_generator import compute_break_retest_signal
import zeus_backtest as zb

RAW_DIR = Path("/home/user/AIMarketing/mt4-zeus-ea/backtest/data/raw")


def run_break_retest_backtest(df: pd.DataFrame, starting_balance: float, spread_pips: float = 1.0) -> dict:
    equity = starting_balance
    position = None
    trade_log: list[dict] = []

    for i in range(len(df)):
        if equity <= 0:
            break
        row = df.iloc[i]
        close = float(row["close"])
        ts = row["timestamp"]
        entry_signal = int(row["retest_entry"])

        # 1. Check SL/TP on the open position.
        if position is not None:
            hit_sl = (position["direction"] == 1 and close <= position["stop"]) or \
                     (position["direction"] == -1 and close >= position["stop"])
            hit_tp = (position["direction"] == 1 and close >= position["target"]) or \
                     (position["direction"] == -1 and close <= position["target"])
            if hit_sl or hit_tp:
                outcome = "stop" if hit_sl else "target"
                pnl, record = zb._close_leg(position, close, ts, outcome, spread_pips)
                equity += pnl
                trade_log.append(record)
                position = None

        # 2. Entry -- only if flat, and only on the brick the signal actually fires.
        if position is None and entry_signal != 0:
            direction = entry_signal
            entry_price = close
            stop = float(row["low"]) if direction == 1 else float(row["high"])
            risk = abs(entry_price - stop)
            if risk > 0:
                target = entry_price + direction * 3.0 * risk
                risk_pips = risk / zb.PIP_SIZE_USDJPY
                risk_dollars = equity * (zb.ZEUS_TOTAL_RISK_PERCENT / 100.0)
                lots = risk_dollars / (risk_pips * zb.pip_value_per_lot(entry_price))
                lots = min(lots, zb.ZEUS_MAX_LOTS_PER_TRADE)
                lots = max(round(lots, 2), 0.01)
                position = {
                    "label": "ORB", "direction": direction, "entry_price": entry_price,
                    "entry_timestamp": ts, "lots": lots, "stop": stop, "target": target,
                }

    return {"trade_log": trade_log, "ending_equity": equity}


def summarize(result):
    tl = result["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    wr = wins / len(tl) * 100 if tl else float("nan")
    return len(tl), wr, result["ending_equity"]


print("Building dataset...")
raw = load_time_series(RAW_DIR / "USDJPY_M1.csv")
brick_size = BRICK_SIZE_PIPS * PIP_SIZE_USDJPY
renko = generate_renko_bricks(raw, brick_size, decimals=DECIMALS)

print("Computing the break-and-retest signal (15-min range, 16:30-16:45 broker time)...")
usable = compute_break_retest_signal(renko, raw, range_minutes=15)
signal_days = usable.loc[usable["retest_entry"] != 0, "timestamp"].dt.date.nunique()
print(f"usable: {len(usable)} bricks, entry fired on {signal_days} distinct days\n")

n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"dev: {len(dev)} | lockbox: {len(lockbox)}\n")

print("=== Break-and-retest ORB (15-min range, 1:3 R:R, single trade) ===")
dev_t, dev_wr, dev_e = summarize(run_break_retest_backtest(dev, 1000.0))
lb_t, lb_wr, lb_e = summarize(run_break_retest_backtest(lockbox, 1000.0))
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")
