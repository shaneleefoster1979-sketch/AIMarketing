#!/usr/bin/env python3
"""
rc96_wick_jerk_test.py

Same as rc96_wick_cci_test.py, but with Jerk(5) instead of CCI as the
entry gate, per request: Jerk > 0 permits buy, Jerk < 0 permits sell
(momentum convention, matching the live EA's Jerk_Dir()). Still no RC(8),
no CCI. Exit unchanged (RC(96) flips, brick confirms) -- Jerk is an
entry-only gate here, same pattern as every other filter this session.

Same 4-leg risk/reward, same dev/lockbox split, Jerk_LPD_Period=5, max
drawdown tracked the same way.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from real_renko_loader import load_real_renko
from rc_period_sweep import load_multiperiod_dump, align_rc_period
from rc96_wick_direction_test import max_drawdown
import zeus_backtest as zb

RAW_DIR = Path(__file__).parent / "data" / "raw"
MULTI_PERIOD_FILE = RAW_DIR / "rc_history_multiperiod.csv"
RC_PERIOD = 96
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


def run_rc96_wick_jerk_backtest(df: pd.DataFrame, starting_balance: float, spread_pips: float = 1.0) -> dict:
    equity = starting_balance
    slots: list[dict | None] = [None, None, None, None]
    t1_was_open = False
    breakeven_triggered = False
    trade_log: list[dict] = []
    equity_curve: list[tuple] = [(None, equity)]

    for i in range(len(df)):
        if equity <= 0:
            break
        row = df.iloc[i]
        close, open_ = float(row["close"]), float(row["open"])
        ts = row["timestamp"]
        brick_dir = 1 if close > open_ else -1
        rc96 = zb.rc_dir(row["rc_value"])
        jerk = zb.jerk_dir(row["jerk_value"])

        # 1. Virtual SL
        for idx, leg in enumerate(slots):
            if leg is None:
                continue
            hit = (leg["direction"] == 1 and close <= leg["stop"]) or (leg["direction"] == -1 and close >= leg["stop"])
            if hit:
                pnl, record = zb._close_leg(leg, close, ts, "stop", spread_pips)
                equity += pnl
                trade_log.append(record)
                equity_curve.append((ts, equity))
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
                equity_curve.append((ts, equity))
                slots[idx] = None

        # 4. Exit -- RC(96) flips to the opposite direction, brick-confirmed. No Jerk gate on exit.
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
                equity_curve.append((ts, equity))
                slots[idx] = None

        if all(leg is None for leg in slots):
            breakeven_triggered = False
            t1_was_open = False

        # 5. Entry -- RC(96) sets direction, brick confirms, Jerk permits. No CCI/RC8.
        if all(leg is None for leg in slots) and rc96 != 0 and brick_dir == rc96:
            if jerk == rc96:
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

    return {"trade_log": trade_log, "ending_equity": equity, "equity_curve": equity_curve}


def summarize(result: dict) -> tuple[int, float, float]:
    tl = result["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    wr = wins / len(tl) * 100 if tl else float("nan")
    return len(tl), wr, result["ending_equity"]


print("Loading the REAL offline Renko chart's OHLC history (true wicks)...")
renko = load_real_renko(RAW_DIR / "renko_ohlc_history.csv")
print(f"  {len(renko)} real bricks after dropping the seed-fill rows")

print(f"Aligning RC(period={RC_PERIOD}) and Jerk(5) onto it...")
dump = load_multiperiod_dump(MULTI_PERIOD_FILE)
renko = align_rc_period(renko, dump, RC_PERIOD)

jerk5 = load_period_col(RAW_DIR / "jerk_history_multiperiod.csv", "jerk_p5")
left = renko.sort_values("timestamp", kind="stable").reset_index(drop=True)
right = jerk5.sort_values("timestamp", kind="stable").reset_index(drop=True)
renko = pd.merge_asof(left, right, on="timestamp", direction="backward")

usable = renko.dropna(subset=["rc_value", "jerk_value"]).sort_values("timestamp", kind="stable").reset_index(drop=True)
print(f"usable: {len(usable)} bricks\n")

n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"dev: {len(dev)} | lockbox: {len(lockbox)}\n")

print(f"=== RC({RC_PERIOD}) + real brick direction + Jerk gate -- no CCI, no RC(8) ===")
dev_result = run_rc96_wick_jerk_backtest(dev, 1000.0)
lb_result = run_rc96_wick_jerk_backtest(lockbox, 1000.0)
dev_t, dev_wr, dev_e = summarize(dev_result)
lb_t, lb_wr, lb_e = summarize(lb_result)
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")

dev_dd_pct, dev_dd_dollars, dev_peak_ts, dev_trough_ts = max_drawdown(dev_result["equity_curve"])
lb_dd_pct, lb_dd_dollars, lb_peak_ts, lb_trough_ts = max_drawdown(lb_result["equity_curve"])
print(f"\nLargest drawdown (peak-to-trough decline in running equity):")
print(f"  dev    : -{dev_dd_pct:.1f}% (-${dev_dd_dollars:,.2f}), peak at {dev_peak_ts}, trough at {dev_trough_ts}")
print(f"  lockbox: -{lb_dd_pct:.1f}% (-${lb_dd_dollars:,.2f}), peak at {lb_peak_ts}, trough at {lb_trough_ts}")
