#!/usr/bin/env python3
"""
cci_armed_reversal_test.py

Builds on cci_armed_gate_test.py (RC+Jerk entries gated by the armed CCI
state -- touch/cross -100 or +100, stay beyond 0 until re-crossed) and
adds one structural rule: the moment a position is fully stopped out, a
new position opens IMMEDIATELY in the opposite direction, unconditionally
(bypassing the RC+Jerk+CCI entry gate for that one reversal trade only).
After that, entries go back to the normal armed-CCI-gated rule.

This can't be expressed through run_zeus_backtest's direction_fn hook
(that only overrides the entry-direction check, not the loop's structure),
so this is a standalone copy of the loop with the reversal step added at
the very end of each bar -- same position as the normal step 5 entry, so
a reversal trade is never itself checked against SL/TP/exit until the
following bar, exactly like any other entry. If the normal gated entry
already fired on the same bar as a stop-out, the reversal is skipped
(never opens two directions on one bar).

Same dev/lockbox split, Jerk_LPD_Period=5, CCI_Period=14.
"""
import sys
sys.path.insert(0, "/home/user/AIMarketing/mt4-zeus-ea/backtest")
from pathlib import Path

import pandas as pd

from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from rc_generator import load_rc_dump, align_to_renko
from cci_generator import compute_cci, compute_cci_armed_state, cci_armed_allows_direction
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


def _open_position(slots, direction, close, ts, equity):
    for idx, (weight, tp_pips) in enumerate(zip(zb.ZEUS_WEIGHTS, zb.ZEUS_TP_PIPS)):
        lots = zb.get_lot_size(equity, weight, close)
        stop = close - direction * zb.ZEUS_STOP_LOSS_PIPS * zb.PIP_SIZE_USDJPY
        target = (close + direction * tp_pips * zb.PIP_SIZE_USDJPY) if tp_pips is not None else None
        slots[idx] = {
            "label": f"T{idx + 1}", "direction": direction, "entry_price": close,
            "entry_timestamp": ts, "lots": lots, "stop": stop, "target": target,
        }


def run_armed_reversal_backtest(df: pd.DataFrame, starting_balance: float, spread_pips: float = 1.0) -> dict:
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
        jerk = zb.jerk_dir(row["jerk_value"])

        was_open_before = any(leg is not None for leg in slots)
        prior_direction = next((leg["direction"] for leg in slots if leg is not None), None)

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

        stopped_out_full = was_open_before and all(leg is None for leg in slots)
        reversal_direction = -prior_direction if stopped_out_full else None

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

        # 4. RC-flip exit, dual-agreement with Jerk (same as live)
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
                if jerk == 0:
                    continue
                if leg["direction"] == 1 and jerk != -1:
                    continue
                if leg["direction"] == -1 and jerk != 1:
                    continue
                pnl, record = zb._close_leg(leg, close, ts, "rc_exit", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        if all(leg is None for leg in slots):
            breakeven_triggered = False
            t1_was_open = False

        # 5. Entry -- RC+Jerk dual-agreement, gated by armed CCI state, brick confirm.
        if all(leg is None for leg in slots):
            entry_dir = 0
            if rc < 0 and jerk == -1:
                entry_dir = -1
            elif rc > 0 and jerk == 1:
                entry_dir = 1
            if entry_dir != 0 and not cci_armed_allows_direction(entry_dir, row["buy_armed"], row["sell_armed"]):
                entry_dir = 0
            if entry_dir != 0 and brick_dir == entry_dir:
                _open_position(slots, entry_dir, close, ts, equity)
                t1_was_open = True
                breakeven_triggered = False

        # 6. Forced reversal on a full stop-out this bar -- unconditional, bypasses
        # the gate entirely. Skipped if step 5 already opened a (gated) position.
        if reversal_direction is not None and all(leg is None for leg in slots):
            _open_position(slots, reversal_direction, close, ts, equity)
            t1_was_open = True
            breakeven_triggered = False

    return {"trade_log": trade_log, "ending_equity": equity}


def cci_armed_direction(row, slots):
    rc = zb.rc_dir(row["rc_value"])
    jerk = zb.jerk_dir(row["jerk_value"])
    entry_dir = 0
    if rc < 0 and jerk == -1:
        entry_dir = -1
    elif rc > 0 and jerk == 1:
        entry_dir = 1
    if entry_dir == 0:
        return 0
    return entry_dir if cci_armed_allows_direction(entry_dir, row["buy_armed"], row["sell_armed"]) else 0


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

print("Computing CCI + armed buy/sell state directly from the Renko OHLC series...")
usable = compute_cci(usable_base)
usable = compute_cci_armed_state(usable)
print(f"usable: {len(usable)} bricks, CCI coverage: {usable['cci_value'].notna().sum()}\n")

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

print("\n=== Armed CCI gate (no reversal-on-stop) -- last test, for comparison ===")
dev_t2, dev_wr2, dev_e2 = summarize(zb.run_zeus_backtest(dev, 1000.0, direction_fn=cci_armed_direction))
lb_t2, lb_wr2, lb_e2 = summarize(zb.run_zeus_backtest(lockbox, 1000.0, direction_fn=cci_armed_direction))
print(f"  dev    : trades={dev_t2} wr={dev_wr2:.1f}% ending=${dev_e2:,.2f}")
print(f"  lockbox: trades={lb_t2} wr={lb_wr2:.1f}% ending=${lb_e2:,.2f}")

print("\n=== Armed CCI gate + reversal-on-stop ===")
dev_t3, dev_wr3, dev_e3 = summarize(run_armed_reversal_backtest(dev, 1000.0))
lb_t3, lb_wr3, lb_e3 = summarize(run_armed_reversal_backtest(lockbox, 1000.0))
print(f"  dev    : trades={dev_t3} wr={dev_wr3:.1f}% ending=${dev_e3:,.2f}")
print(f"  lockbox: trades={lb_t3} wr={lb_wr3:.1f}% ending=${lb_e3:,.2f}")
