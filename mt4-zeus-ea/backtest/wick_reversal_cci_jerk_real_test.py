#!/usr/bin/env python3
"""
wick_reversal_cci_jerk_real_test.py

Adds Jerk (period 5) back in as a third required condition alongside the
Renko Wick Reversal arrows and CCI, on the REAL offline Renko OHLC (true
wicks) -- still no RC.

Buy  : wick_buy_arrow fires AND CCI < 0 AND Jerk > 0 (buy side).
Sell : wick_sell_arrow fires AND CCI > 0 AND Jerk < 0 (sell side).
Exit mirrors entry (opposite arrow + CCI + Jerk all agree on the
opposite direction).

Same 4-leg risk/reward as live. Same dev/lockbox split. CCI_Period=14,
Jerk_LPD_Period=5.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from cci_generator import compute_cci, cci_allows_direction
from wick_reversal_generator import compute_wick_reversal
from real_renko_loader import load_real_renko
import zeus_backtest as zb

RAW_DIR = Path(__file__).parent / "data" / "raw"
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


def run_wick_cci_jerk_backtest(df: pd.DataFrame, starting_balance: float, spread_pips: float = 1.0) -> dict:
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
        cci = row["cci_value"]
        jerk = zb.jerk_dir(row["jerk_value"])
        buy_arrow = bool(row["wick_buy_arrow"])
        sell_arrow = bool(row["wick_sell_arrow"])

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

        # 4. Exit -- opposite wick arrow + CCI + Jerk all agree on the opposite direction. No RC.
        if any(leg is not None for leg in slots) and not pd.isna(cci):
            for idx, leg in enumerate(slots):
                if leg is None:
                    continue
                if leg["direction"] == 1 and (not sell_arrow or cci >= 0 or jerk != -1):
                    continue
                if leg["direction"] == -1 and (not buy_arrow or cci <= 0 or jerk != 1):
                    continue
                pnl, record = zb._close_leg(leg, close, ts, "wick_cci_jerk_exit", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        if all(leg is None for leg in slots):
            breakeven_triggered = False
            t1_was_open = False

        # 5. Entry -- wick arrow + CCI + Jerk triple-agreement, all slots flat. No RC.
        if all(leg is None for leg in slots) and not pd.isna(cci):
            entry_dir = 0
            if buy_arrow and cci < 0 and jerk == 1:
                entry_dir = 1
            elif sell_arrow and cci > 0 and jerk == -1:
                entry_dir = -1

            if entry_dir != 0:
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


if __name__ == "__main__":
    print("Loading the REAL offline Renko chart's OHLC history (true wicks)...")
    renko = load_real_renko(RAW_DIR / "renko_ohlc_history.csv")
    print(f"  {len(renko)} real bricks after dropping the seed-fill rows")

    jerk5 = load_period_col(RAW_DIR / "jerk_history_multiperiod.csv", "jerk_p5")
    left = renko.sort_values("timestamp", kind="stable").reset_index(drop=True)
    right = jerk5.sort_values("timestamp", kind="stable").reset_index(drop=True)
    renko = pd.merge_asof(left, right, on="timestamp", direction="backward")

    renko = compute_cci(renko)
    usable = compute_wick_reversal(renko)
    usable = usable.dropna(subset=["cci_value", "jerk_value"]).reset_index(drop=True)

    buy_signals = int((usable["wick_buy_arrow"] & (usable["cci_value"] < 0) &
                        (usable["jerk_value"] > 0)).sum())
    sell_signals = int((usable["wick_sell_arrow"] & (usable["cci_value"] > 0) &
                         (usable["jerk_value"] < 0)).sum())
    print(f"usable: {len(usable)} bricks")
    print(f"  entry signals (wick arrow + CCI + Jerk all agree): buy={buy_signals} sell={sell_signals}\n")

    n = len(usable)
    split = int(n * 0.85)
    dev = usable.iloc[:split].reset_index(drop=True)
    lockbox = usable.iloc[split:].reset_index(drop=True)
    print(f"dev: {len(dev)} | lockbox: {len(lockbox)}\n")

    print("=== Renko Wick Reversal + CCI + Jerk(5), on REAL Renko OHLC -- no RC ===")
    dev_t, dev_wr, dev_e = summarize(run_wick_cci_jerk_backtest(dev, 1000.0))
    lb_t, lb_wr, lb_e = summarize(run_wick_cci_jerk_backtest(lockbox, 1000.0))
    print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
    print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")
