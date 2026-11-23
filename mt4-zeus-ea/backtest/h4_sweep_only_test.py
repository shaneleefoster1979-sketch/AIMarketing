#!/usr/bin/env python3
"""
h4_sweep_only_test.py

Curiosity test: RC, Jerk, and CCI all removed entirely. Entries AND exits
are driven solely by the 4H liquidity-sweep bias from h4_sweep_generator.py
-- same structure as jerk_nal_no_rc_test.py's "RC removed" test:

  Entry : flat, bias != 0, and the just-closed brick prints in the bias's
          direction.
  Exit  : bias flips to the opposite direction AND the just-closed brick
          confirms that opposite direction (brick-confirmed reversal,
          same discipline as the live RC-flip exit).

Same risk/reward as live: 4 legs (T1-T4), same weights, same 60/120/180
pip TPs, same 60 pip SL, same breakeven-after-T1 rule -- only the entry/
exit DIRECTION SOURCE changes. Same dev/lockbox split.
"""
import sys
sys.path.insert(0, "/home/user/AIMarketing/mt4-zeus-ea/backtest")
from pathlib import Path

import pandas as pd

from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from h4_sweep_generator import build_h4_bars, compute_h4_sweep_bias, align_h4_bias_to_renko
import zeus_backtest as zb

RAW_DIR = Path("/home/user/AIMarketing/mt4-zeus-ea/backtest/data/raw")


def run_h4_sweep_only_backtest(df: pd.DataFrame, starting_balance: float, spread_pips: float = 1.0) -> dict:
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
        bias = int(row["h4_bias"])

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

        # 4. Exit -- bias flips to the opposite direction, brick-confirmed. No RC/Jerk/CCI.
        if any(leg is not None for leg in slots):
            for idx, leg in enumerate(slots):
                if leg is None:
                    continue
                if leg["direction"] == 1 and (bias != -1 or brick_dir != -1):
                    continue
                if leg["direction"] == -1 and (bias != 1 or brick_dir != 1):
                    continue
                pnl, record = zb._close_leg(leg, close, ts, "h4_sweep_exit", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        if all(leg is None for leg in slots):
            breakeven_triggered = False
            t1_was_open = False

        # 5. Entry -- bias sets direction, brick must confirm, all slots flat. No RC/Jerk/CCI.
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

print("Building H4 bars and computing the sweep bias...")
h4_bars = build_h4_bars(raw)
h4_bias = compute_h4_sweep_bias(h4_bars)
usable = align_h4_bias_to_renko(renko, h4_bias)

n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"usable: {n} bricks -- dev: {len(dev)} | lockbox: {len(lockbox)}\n")

print("=== 4H sweep bias ONLY -- no RC, no Jerk, no CCI ===")
dev_t2, dev_wr2, dev_e2 = summarize(run_h4_sweep_only_backtest(dev, 1000.0))
lb_t2, lb_wr2, lb_e2 = summarize(run_h4_sweep_only_backtest(lockbox, 1000.0))
print(f"  dev    : trades={dev_t2} wr={dev_wr2:.1f}% ending=${dev_e2:,.2f}")
print(f"  lockbox: trades={lb_t2} wr={lb_wr2:.1f}% ending=${lb_e2:,.2f}")
