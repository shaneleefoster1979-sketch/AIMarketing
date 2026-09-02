#!/usr/bin/env python3
"""
zeus_backtest.py

Python replica of Zeus.mq4's live logic, run bar-by-bar over a Renko
brick series with rc_value and rmc_value already attached. One row = one
brick = one potential decision point, matching how Zeus itself only acts
on closed-brick data (CheckVirtualSL/CheckVirtualTP compare against
Close[1], entries/exits happen on brick close).

Mirrors the current Zeus.mq4 exactly, including the RMC_MinConfirmMagnitude
fix (RMC must clear a minimum magnitude before it counts as a confirmed
red/blue direction, not just any nonzero sign) -- both the entry dual-
agreement check and the RC-flip exit gate use it, same as the live EA.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PIP_SIZE_USDJPY = 0.01
CONTRACT_SIZE = 100_000

ZEUS_TOTAL_RISK_PERCENT = 3.0
ZEUS_STOP_LOSS_PIPS = 60.0
ZEUS_TP_PIPS = [60.0, 120.0, 180.0, None]  # T1..T4; T4 has no target (rides the trend)
ZEUS_WEIGHTS = [20, 25, 25, 30]            # risk-% split across T1..T4
ZEUS_MAX_LOTS_PER_TRADE = 50.0
RMC_MIN_CONFIRM_MAGNITUDE = 0.03           # matches Zeus.mq4's RMC_Dir() fix -- raised from 0.02 to 0.03 by the user live after a trade still entered on an invisible RMC signal line at 0.02
RMC_MIN_SIGN_RUN_BARS = 2                  # matches ZeusAI.mq4's RMC_MinSignRunBars fix -- MT4 can't draw a visible connecting line on the first bar of a fresh sign flip, so require the sign to hold this many bars before counting as confirmed


def compute_rmc_confirmed_dir(rmc_series: pd.Series) -> np.ndarray:
    """Precomputed, stateful gate -- exact match for ZeusAI.mq4's
    GetRMC_Value()+RMC_Dir(): RMC's sign must hold for RMC_MIN_SIGN_RUN_BARS
    consecutive bars (reset to 0 on any NaN/no-reading bar, same as EMPTY_
    VALUE resetting g_rmcSignRunLength live) AND clear RMC_MIN_CONFIRM_
    MAGNITUDE, before it counts as a confirmed +1/-1 direction. This can't
    be a stateless per-row function like rc_dir() since it depends on the
    run of prior bars, so it's computed once up front instead."""
    values = rmc_series.to_numpy()
    n = len(values)
    out = np.zeros(n, dtype=int)
    prev_sign = 0
    run_len = 0
    for i in range(n):
        v = values[i]
        if pd.isna(v):
            prev_sign, run_len = 0, 0
            continue
        sign = 1 if v > 0 else (-1 if v < 0 else 0)
        if sign != 0 and sign == prev_sign:
            run_len += 1
        else:
            run_len = 1 if sign != 0 else 0
        prev_sign = sign

        if run_len >= RMC_MIN_SIGN_RUN_BARS:
            if v >= RMC_MIN_CONFIRM_MAGNITUDE:
                out[i] = 1
            elif v <= -RMC_MIN_CONFIRM_MAGNITUDE:
                out[i] = -1
    return out


def rmc_dir(rmc_value) -> int:
    """Magnitude-only gate, no run-length state -- kept for the DQN's own
    raw-feature construction (which reads rmc_value directly, unaffected
    by the entry/exit gate's stricter rule) and anywhere a single value is
    checked in isolation. Entry/exit gating uses compute_rmc_confirmed_dir
    instead, which is the one that actually matches live ZeusAI.mq4."""
    if pd.isna(rmc_value):
        return 0
    if rmc_value >= RMC_MIN_CONFIRM_MAGNITUDE:
        return 1
    if rmc_value <= -RMC_MIN_CONFIRM_MAGNITUDE:
        return -1
    return 0


def rc_dir(rc_value) -> int:
    if pd.isna(rc_value):
        return 0
    return 1 if rc_value > 0 else (-1 if rc_value < 0 else 0)


def pip_value_per_lot(price: float) -> float:
    return PIP_SIZE_USDJPY * CONTRACT_SIZE / price


def get_lot_size(equity: float, weight_pct: int, price: float) -> float:
    risk_dollars = equity * (ZEUS_TOTAL_RISK_PERCENT / 100.0) * (weight_pct / 100.0)
    lots = risk_dollars / (ZEUS_STOP_LOSS_PIPS * pip_value_per_lot(price))
    lots = min(lots, ZEUS_MAX_LOTS_PER_TRADE)
    return max(round(lots, 2), 0.01)


def _close_leg(leg: dict, exit_price: float, exit_timestamp, outcome: str, spread_pips: float) -> tuple[float, dict]:
    pips = (exit_price - leg["entry_price"]) * leg["direction"] / PIP_SIZE_USDJPY - spread_pips
    pnl = pips * pip_value_per_lot(leg["entry_price"]) * leg["lots"]
    record = {
        "leg": leg["label"], "direction": "LONG" if leg["direction"] == 1 else "SHORT",
        "entry_timestamp": leg["entry_timestamp"], "exit_timestamp": exit_timestamp,
        "outcome": outcome, "lots": leg["lots"], "pnl": pnl,
    }
    return pnl, record


def run_zeus_backtest(df: pd.DataFrame, starting_balance: float, spread_pips: float = 1.0, direction_fn=None) -> dict:
    """direction_fn(row, slots) -> -1/0/1, optional: overrides the entry
    direction check only (step 5 below) for testing additional filters on
    top of the same RC+RMC exit/management logic. Leave None for the
    exact current live Zeus entry rule (RC+RMC dual-agreement)."""
    equity = starting_balance
    slots: list[dict | None] = [None, None, None, None]
    t1_was_open = False
    breakeven_triggered = False
    trade_log: list[dict] = []
    rmc_confirmed = compute_rmc_confirmed_dir(df["rmc_value"])

    for i in range(len(df)):
        if equity <= 0:
            break
        row = df.iloc[i]
        close, open_ = float(row["close"]), float(row["open"])
        ts = row["timestamp"]
        brick_dir = 1 if close > open_ else -1
        rc = rc_dir(row["rc_value"])
        rmc = int(rmc_confirmed[i])

        # 1. Virtual SL -- candle close only.
        for idx, leg in enumerate(slots):
            if leg is None:
                continue
            hit = (leg["direction"] == 1 and close <= leg["stop"]) or (leg["direction"] == -1 and close >= leg["stop"])
            if hit:
                pnl, record = _close_leg(leg, close, ts, "stop", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        # 2. Break-even once T1 is gone (either way).
        if t1_was_open and not breakeven_triggered:
            t1_exists = any(leg is not None and leg["label"] == "T1" for leg in slots)
            if not t1_exists:
                for leg in slots:
                    if leg is not None:
                        leg["stop"] = leg["entry_price"]
                breakeven_triggered = True
                t1_was_open = False

        # 3. Virtual TP -- candle close only.
        for idx, leg in enumerate(slots):
            if leg is None or leg["target"] is None:
                continue
            hit = (leg["direction"] == 1 and close >= leg["target"]) or (leg["direction"] == -1 and close <= leg["target"])
            if hit:
                pnl, record = _close_leg(leg, close, ts, "target", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        # 4. RC-flip exit, gated by reversal brick + RMC agreement (dual-agreement, same rule as entry).
        any_open = any(leg is not None for leg in slots)
        if any_open:
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
                if rmc == 0:
                    continue
                if leg["direction"] == 1 and rmc != -1:
                    continue
                if leg["direction"] == -1 and rmc != 1:
                    continue
                pnl, record = _close_leg(leg, close, ts, "rc_exit", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        if all(leg is None for leg in slots):
            breakeven_triggered = False
            t1_was_open = False

        # 5. Entry -- RC and RMC dual-agreement, brick must print in trade direction, all slots flat.
        if all(leg is None for leg in slots):
            if direction_fn is not None:
                entry_dir = direction_fn(row, slots)
            else:
                entry_dir = 0
                if rc < 0 and rmc == -1:
                    entry_dir = -1
                elif rc > 0 and rmc == 1:
                    entry_dir = 1

            if entry_dir != 0 and brick_dir == entry_dir:
                for idx, (weight, tp_pips) in enumerate(zip(ZEUS_WEIGHTS, ZEUS_TP_PIPS)):
                    label = f"T{idx + 1}"
                    lots = get_lot_size(equity, weight, close)
                    stop = close - entry_dir * ZEUS_STOP_LOSS_PIPS * PIP_SIZE_USDJPY
                    target = (close + entry_dir * tp_pips * PIP_SIZE_USDJPY) if tp_pips is not None else None
                    slots[idx] = {
                        "label": label, "direction": entry_dir, "entry_price": close,
                        "entry_timestamp": ts, "lots": lots, "stop": stop, "target": target,
                    }
                t1_was_open = True
                breakeven_triggered = False

    return {"trade_log": trade_log, "ending_equity": equity}
