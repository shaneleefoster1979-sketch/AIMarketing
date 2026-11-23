#!/usr/bin/env python3
"""
orb_only_test.py

Opening Range Breakout as its own standalone strategy on the Renko
series -- no RC, no Jerk, no CCI. See orb_generator.py for the exact
rule: 30-minute range anchored to 9:30 AM New York (16:30 broker-server
time, given this broker runs 7h ahead of EST), bias armed by the first
qualifying breakout brick each day, flips allowed within the same day,
resets to neutral every new day.

Entry : flat, bias != 0, brick confirms the bias direction.
Exit  : standard TP/SL (reused risk/reward, per request) PLUS an early
        exit if the bias flips to the opposite direction, brick-confirmed
        -- same reversal-exit discipline as every other "entries/exits
        driven solely by X" test this session (h4_sweep_only_test.py).

Same risk/reward as live: 4 legs (T1-T4), same weights, same 60/120/180
pip TPs, same 60 pip SL, same breakeven-after-T1 rule. Same dev/lockbox
split.
"""
import sys
sys.path.insert(0, "/home/user/AIMarketing/mt4-zeus-ea/backtest")
from pathlib import Path

import pandas as pd

from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from orb_generator import compute_orb_bias
import zeus_backtest as zb

RAW_DIR = Path("/home/user/AIMarketing/mt4-zeus-ea/backtest/data/raw")


def run_orb_only_backtest(df: pd.DataFrame, starting_balance: float, spread_pips: float = 1.0) -> dict:
    equity = starting_balance
    slots: list[dict | None] = [None, None, None, None]
    t1_was_open = False
    breakeven_triggered = False
    trade_log: list[dict] = []

    for i in range(len(df)):
        if equity <= 0:
            break
        row = df.iloc[i]
        close, open_ = float(row["close"]), float(row["open"])
        ts = row["timestamp"]
        brick_dir = 1 if close > open_ else -1
        bias = int(row["orb_bias"])

        # 1. Virtual SL
        for idx, leg in enumerate(slots):
            if leg is None:
                continue
            hit = (leg["direction"] == 1 and close <= leg["stop"]) or (leg["direction"] == -1 and close >= leg["stop"])
            if hit:
                pnl, record = zb._close_leg(leg, close, ts, "stop", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        # 2. Break-even once T1 is gone
        if t1_was_open and not breakeven_triggered:
            t1_exists = any(leg is not None and leg["label"] == "T1" for leg in slots)
            if not t1_exists:
                for leg in slots:
                    if leg is not None:
                        leg["stop"] = leg["entry_price"]
                breakeven_triggered = True
                t1_was_open = False

        # 3. Virtual TP
        for idx, leg in enumerate(slots):
            if leg is None or leg["target"] is None:
                continue
            hit = (leg["direction"] == 1 and close >= leg["target"]) or (leg["direction"] == -1 and close <= leg["target"])
            if hit:
                pnl, record = zb._close_leg(leg, close, ts, "target", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        # 4. Exit -- ORB bias flips to the opposite direction, brick-confirmed. No RC/Jerk/CCI.
        if any(leg is not None for leg in slots):
            for idx, leg in enumerate(slots):
                if leg is None:
                    continue
                if leg["direction"] == 1 and (bias != -1 or brick_dir != -1):
                    continue
                if leg["direction"] == -1 and (bias != 1 or brick_dir != 1):
                    continue
                pnl, record = zb._close_leg(leg, close, ts, "orb_exit", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        if all(leg is None for leg in slots):
            breakeven_triggered = False
            t1_was_open = False

        # 5. Entry -- ORB bias sets direction, brick must confirm, all slots flat. No RC/Jerk/CCI.
        if all(leg is None for leg in slots) and bias != 0 and brick_dir == bias:
            entry_dir = bias
            for idx, (weight, tp_pips) in enumerate(zip(zb.ZEUS_WEIGHTS, zb.ZEUS_TP_PIPS)):
                lots = zb.get_lot_size(equity, weight, close)
                stop = close - entry_dir * zb.ZEUS_STOP_LOSS_PIPS * zb.PIP_SIZE_USDJPY
                target = (close + entry_dir * tp_pips * zb.PIP_SIZE_USDJPY) if tp_pips is not None else None
                slots[idx] = {
                    "label": f"T{idx + 1}", "direction": entry_dir, "entry_price": close,
                    "entry_timestamp": ts, "lots": lots, "stop": stop, "target": target,
                }
            t1_was_open = True
            breakeven_triggered = False

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

print("Computing the ORB bias (16:30-17:00 broker time = 9:30-10:00 AM New York)...")
usable = compute_orb_bias(renko, raw)
armed_days = usable.loc[usable["orb_bias"] != 0, "timestamp"].dt.date.nunique()
print(f"usable: {len(usable)} bricks, breakout armed on at least part of {armed_days} distinct days\n")

n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"dev: {len(dev)} | lockbox: {len(lockbox)}\n")

print("=== ORB (Opening Range Breakout) ONLY -- no RC, no Jerk, no CCI ===")
dev_t, dev_wr, dev_e = summarize(run_orb_only_backtest(dev, 1000.0))
lb_t, lb_wr, lb_e = summarize(run_orb_only_backtest(lockbox, 1000.0))
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")
