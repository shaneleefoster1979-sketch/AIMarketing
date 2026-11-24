#!/usr/bin/env python3
"""
jerk_cci_no_rc_test.py

Tests removing RC from the strategy entirely: entry and exit are both
driven by Jerk + CCI agreement (brick-confirmed), per request --
Jerk > 0 AND CCI < 0 for a buy, Jerk < 0 AND CCI > 0 for a sell (the
same CCI sign convention as cci_gate_test.py: CCI < 0 is the buy side).
The old RC-flip exit is replaced by its natural equivalent with RC
removed: a position closes when Jerk and CCI both reverse to agree on
the OPPOSITE direction, brick-confirmed -- same "exit fires when the
opposite entry condition fires" symmetry used in every other
"RC removed" test this session (jerk_nal_no_rc_test.py, h4/orb-only).

Same dev/lockbox split, Jerk_LPD_Period=5, CCI_Period=14 (the settings
already decided on for both).
"""
import sys
sys.path.insert(0, "/home/user/AIMarketing/mt4-zeus-ea/backtest")
from pathlib import Path

import pandas as pd

from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from rc_generator import load_rc_dump, align_to_renko
from cci_generator import compute_cci
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


def run_jerk_cci_backtest(df: pd.DataFrame, starting_balance: float, spread_pips: float = 1.0) -> dict:
    """Same SL/TP/BE machinery as zeus_backtest.run_zeus_backtest. RC
    removed entirely -- entry and exit both driven by Jerk+CCI dual
    agreement, brick-confirmed."""
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
        jerk = zb.jerk_dir(row["jerk_value"])
        cci = row["cci_value"]

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

        # 4. Exit -- Jerk+CCI both reverse to agree on the opposite direction, brick-confirmed. No RC.
        if any(leg is not None for leg in slots) and not pd.isna(cci):
            for idx, leg in enumerate(slots):
                if leg is None:
                    continue
                if jerk == 0:
                    continue
                if leg["direction"] == 1 and (jerk != -1 or cci <= 0 or brick_dir != -1):
                    continue
                if leg["direction"] == -1 and (jerk != 1 or cci >= 0 or brick_dir != 1):
                    continue
                pnl, record = zb._close_leg(leg, close, ts, "jerk_cci_exit", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        if all(leg is None for leg in slots):
            breakeven_triggered = False
            t1_was_open = False

        # 5. Entry -- Jerk+CCI dual-agreement, brick-confirmed, all slots flat. No RC.
        if all(leg is None for leg in slots) and not pd.isna(cci):
            entry_dir = 0
            if jerk == 1 and cci < 0:
                entry_dir = 1
            elif jerk == -1 and cci > 0:
                entry_dir = -1

            if entry_dir != 0 and brick_dir == entry_dir:
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


print("Building dataset (RC + Jerk period=5, RC kept only for the reference backtest)...")
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

print("Computing CCI directly from the Renko OHLC series...")
usable = compute_cci(usable_base)
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

print("\n=== Jerk + CCI only, RC removed entirely (Jerk>0 & CCI<0 => buy, Jerk<0 & CCI>0 => sell) ===")
dev_t2, dev_wr2, dev_e2 = summarize(run_jerk_cci_backtest(dev, 1000.0))
lb_t2, lb_wr2, lb_e2 = summarize(run_jerk_cci_backtest(lockbox, 1000.0))
print(f"  dev    : trades={dev_t2} wr={dev_wr2:.1f}% ending=${dev_e2:,.2f}")
print(f"  lockbox: trades={lb_t2} wr={lb_wr2:.1f}% ending=${lb_e2:,.2f}")
