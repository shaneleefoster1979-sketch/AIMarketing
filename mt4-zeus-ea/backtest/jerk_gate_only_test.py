#!/usr/bin/env python3
"""
jerk_gate_only_test.py

Tests Jerk as a pure ON/OFF trading filter instead of a direction-setter:
RC alone decides buy vs sell (plus the usual brick-direction confirm);
Jerk's raw sign only decides whether new entries are allowed AT ALL.
Exits are RC-flip only, with no Jerk involvement -- the request was
specifically about gating entries, not exits.

Two variants, both at Jerk_LPD_Period=5 (current live setting), same
dev/lockbox split as every other comparison in this project:
  A) trade only when Jerk > 0 (both buy and sell allowed), 0 trades when Jerk <= 0
  B) trade only when Jerk < 0 (both buy and sell allowed), 0 trades when Jerk >= 0
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


def run_gate_only_backtest(df: pd.DataFrame, starting_balance: float, gate_sign: int, spread_pips: float = 1.0) -> dict:
    """gate_sign=+1: trade only when jerk_value > 0. gate_sign=-1: trade only
    when jerk_value < 0. Direction comes from RC alone when the gate is open.
    Exit is RC-flip only (brick-confirmed), no Jerk involvement at all --
    identical management/SL/TP machinery to zeus_backtest.run_zeus_backtest,
    just with Jerk removed from both the direction-setting and the exit gate."""
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
        rc = zb.rc_dir(row["rc_value"])
        jerk_raw = row["jerk_value"]
        gate_open = (not pd.isna(jerk_raw)) and (
            (gate_sign > 0 and jerk_raw > 0) or (gate_sign < 0 and jerk_raw < 0)
        )

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

        # 4. RC-flip exit -- RC + brick confirmation only, no Jerk gate.
        if any(leg is not None for leg in slots):
            for idx, leg in enumerate(slots):
                if leg is None:
                    continue
                flip = (leg["direction"] == 1 and rc < 0) or (leg["direction"] == -1 and rc > 0)
                if not flip:
                    continue
                if leg["direction"] == 1 and brick_dir != -1:
                    continue
                if leg["direction"] == -1 and brick_dir != 1:
                    continue
                pnl, record = zb._close_leg(leg, close, ts, "rc_exit", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        if all(leg is None for leg in slots):
            breakeven_triggered = False
            t1_was_open = False

        # 5. Entry -- RC alone sets direction, brick must confirm, gated on/off by Jerk's raw sign.
        if all(leg is None for leg in slots) and gate_open:
            entry_dir = rc  # RC alone: rc_dir() already -1/0/1
            if entry_dir != 0 and brick_dir == entry_dir:
                for idx, (weight, tp_pips) in enumerate(zip(zb.ZEUS_WEIGHTS, zb.ZEUS_TP_PIPS)):
                    label = f"T{idx + 1}"
                    lots = zb.get_lot_size(equity, weight, close)
                    stop = close - entry_dir * zb.ZEUS_STOP_LOSS_PIPS * zb.PIP_SIZE_USDJPY
                    target = (close + entry_dir * tp_pips * zb.PIP_SIZE_USDJPY) if tp_pips is not None else None
                    slots[idx] = {
                        "label": label, "direction": entry_dir, "entry_price": close,
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

print("=== TEST A: trade only when Jerk > 0 (both directions), 0 trades when Jerk <= 0 ===")
dev_t, dev_wr, dev_e = summarize(run_gate_only_backtest(dev, 1000.0, gate_sign=1))
lb_t, lb_wr, lb_e = summarize(run_gate_only_backtest(lockbox, 1000.0, gate_sign=1))
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")

print("\n=== TEST B: trade only when Jerk < 0 (both directions), 0 trades when Jerk >= 0 ===")
dev_t2, dev_wr2, dev_e2 = summarize(run_gate_only_backtest(dev, 1000.0, gate_sign=-1))
lb_t2, lb_wr2, lb_e2 = summarize(run_gate_only_backtest(lockbox, 1000.0, gate_sign=-1))
print(f"  dev    : trades={dev_t2} wr={dev_wr2:.1f}% ending=${dev_e2:,.2f}")
print(f"  lockbox: trades={lb_t2} wr={lb_wr2:.1f}% ending=${lb_e2:,.2f}")

print("\n=== For reference: current live rule (RC+Jerk dual-agreement, momentum sign) ===")
dev_t3, dev_wr3, dev_e3 = summarize(zb.run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0))
lb_t3, lb_wr3, lb_e3 = summarize(zb.run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0))
print(f"  dev    : trades={dev_t3} wr={dev_wr3:.1f}% ending=${dev_e3:,.2f}")
print(f"  lockbox: trades={lb_t3} wr={lb_wr3:.1f}% ending=${lb_e3:,.2f}")
