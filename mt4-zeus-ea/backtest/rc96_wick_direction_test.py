#!/usr/bin/env python3
"""
rc96_wick_direction_test.py

Standalone strategy, per request: nothing but RC(96) and the Renko
brick's own direction -- no Jerk, no CCI, no RC(8). Uses the REAL
offline Renko chart's OHLC (true wicks, ~27 years, via
real_renko_loader.py) rather than the synthetic wickless reconstruction,
since "wick direction" was specifically asked for.

Entry : flat, RC(96) direction != 0, and the just-closed real brick's
        own Close-vs-Open direction confirms it.
Exit  : RC(96) flips to the opposite direction, confirmed by the brick
        -- same "opposite signal fires" symmetry as every other
        standalone (RC-removed/filter-free) test this session.

Same 4-leg risk/reward as live. Same dev/lockbox split.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from real_renko_loader import load_real_renko
from rc_period_sweep import load_multiperiod_dump, align_rc_period
import zeus_backtest as zb

RAW_DIR = Path(__file__).parent / "data" / "raw"
MULTI_PERIOD_FILE = RAW_DIR / "rc_history_multiperiod.csv"
RC_PERIOD = 96


def run_rc96_wick_backtest(df: pd.DataFrame, starting_balance: float, spread_pips: float = 1.0) -> dict:
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
        rc96 = zb.rc_dir(row["rc_value"])

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

        # 4. Exit -- RC(96) flips to the opposite direction, brick-confirmed. No Jerk/CCI/RC8.
        if any(leg is not None for leg in slots):
            for idx, leg in enumerate(slots):
                if leg is None:
                    continue
                rev_dir = -leg["direction"]
                if rc96 != rev_dir or brick_dir != rev_dir:
                    continue
                pnl, record = zb._close_leg(leg, close, ts, "rc96_wick_exit", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        if all(leg is None for leg in slots):
            breakeven_triggered = False
            t1_was_open = False

        # 5. Entry -- RC(96) sets direction, brick must confirm, all slots flat. No Jerk/CCI/RC8.
        if all(leg is None for leg in slots) and rc96 != 0 and brick_dir == rc96:
            entry_dir = rc96
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


def summarize(result: dict) -> tuple[int, float, float]:
    tl = result["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    wr = wins / len(tl) * 100 if tl else float("nan")
    return len(tl), wr, result["ending_equity"]


print("Loading the REAL offline Renko chart's OHLC history (true wicks)...")
renko = load_real_renko(RAW_DIR / "renko_ohlc_history.csv")
print(f"  {len(renko)} real bricks after dropping the seed-fill rows")

print(f"Aligning RC(period={RC_PERIOD}) onto it...")
dump = load_multiperiod_dump(MULTI_PERIOD_FILE)
renko = align_rc_period(renko, dump, RC_PERIOD)

usable = renko.dropna(subset=["rc_value"]).sort_values("timestamp", kind="stable").reset_index(drop=True)
print(f"usable: {len(usable)} bricks\n")

n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"dev: {len(dev)} | lockbox: {len(lockbox)}\n")

print(f"=== RC({RC_PERIOD}) + real brick direction ONLY -- no Jerk, no CCI, no RC(8) ===")
dev_t, dev_wr, dev_e = summarize(run_rc96_wick_backtest(dev, 1000.0))
lb_t, lb_wr, lb_e = summarize(run_rc96_wick_backtest(lockbox, 1000.0))
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")
