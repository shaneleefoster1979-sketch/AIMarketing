#!/usr/bin/env python3
"""
rc7_full_agreement_exit_test.py

Per request: RC_Period=7 (not the 8 used in recent tests), and the
discretionary reversal EXIT now requires ALL FOUR conditions to agree
(RC(7) flip + brick confirms + Jerk agrees + CCI permits + RC(96) agrees),
instead of just RC(7)+brick+Jerk as the live EA currently codes it. If
that full agreement never arrives, the position only closes via SL (or
TP, unchanged -- brick-count based, independent of RC entirely).

Entry is unchanged from the current live design: RC(7)+Jerk dual
agreement, brick-confirmed, gated by CCI permitting it and RC(96)
agreeing with it (same as rc8_rc96_jerk_cci_test.py, just with the
primary period at 7 instead of 8).

This needs a custom loop (not zeus_backtest.run_zeus_backtest's
direction_fn hook, which only overrides entries) since the exit rule
itself is what's changing here. Same 4-leg risk/reward, same dev/
lockbox split, same reused risk-managed structure as every other test.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from cci_generator import compute_cci, cci_allows_direction
from rc_generator import load_rc_dump, align_to_renko
from rc_period_sweep import load_multiperiod_dump, align_rc_period
import zeus_backtest as zb

RAW_DIR = Path(__file__).parent / "data" / "raw"
MULTI_PERIOD_FILE = RAW_DIR / "rc_history_multiperiod.csv"
JERK_CLAMP_MAX = 25.0
RC_PRIMARY_PERIOD = 7
RC_SECONDARY_PERIOD = 96


def load_period_col(path, col, tz="UTC"):
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_localize(tz)
    df = df.sort_values("timestamp", kind="stable").drop_duplicates(subset=["timestamp"], keep="last")
    sub = df[["timestamp", col]].dropna(subset=[col]).copy()
    sub["jerk_value"] = sub[col].clip(-JERK_CLAMP_MAX, JERK_CLAMP_MAX)
    return sub[["timestamp", "jerk_value"]]


def run_full_agreement_backtest(df: pd.DataFrame, starting_balance: float, spread_pips: float = 1.0) -> dict:
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
        rc7 = zb.rc_dir(row["rc_value"])
        rc96 = zb.rc_dir(row["rc96_value"])
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

        # 3. Virtual TP -- unchanged, brick-count based, independent of RC
        for idx, leg in enumerate(slots):
            if leg is None or leg["target"] is None:
                continue
            hit = (leg["direction"] == 1 and close >= leg["target"]) or (leg["direction"] == -1 and close <= leg["target"])
            if hit:
                pnl, record = zb._close_leg(leg, close, ts, "target", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        # 4. Discretionary exit -- per request, ALL FOUR must agree on the reversal:
        # RC(7) flip + brick confirms + Jerk agrees + CCI permits + RC(96) agrees.
        # Otherwise the leg only closes via SL/TP above.
        if any(leg is not None for leg in slots) and not pd.isna(cci):
            for idx, leg in enumerate(slots):
                if leg is None:
                    continue
                rev_dir = -leg["direction"]  # the reversal direction needed to close this leg
                if rc7 != rev_dir:
                    continue
                if brick_dir != rev_dir:
                    continue
                if jerk != rev_dir:
                    continue
                if not cci_allows_direction(rev_dir, cci):
                    continue
                if rc96 != rev_dir:
                    continue
                pnl, record = zb._close_leg(leg, close, ts, "full_agreement_exit", spread_pips)
                equity += pnl
                trade_log.append(record)
                slots[idx] = None

        if all(leg is None for leg in slots):
            breakeven_triggered = False
            t1_was_open = False

        # 5. Entry -- unchanged from the current live design: RC(7)+Jerk dual-agreement,
        # brick-confirmed, gated by CCI and RC(96) agreement.
        if all(leg is None for leg in slots) and not pd.isna(cci):
            entry_dir = 0
            if rc7 < 0 and jerk == -1:
                entry_dir = -1
            elif rc7 > 0 and jerk == 1:
                entry_dir = 1

            if entry_dir != 0 and brick_dir == entry_dir and rc96 == entry_dir and cci_allows_direction(entry_dir, cci):
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


print(f"Building dataset (RC primary period={RC_PRIMARY_PERIOD}, RC secondary period={RC_SECONDARY_PERIOD}, "
      f"Jerk period=5, CCI period=14)...")
raw = load_time_series(RAW_DIR / "USDJPY_M1.csv")
brick_size = BRICK_SIZE_PIPS * PIP_SIZE_USDJPY
renko = generate_renko_bricks(raw, brick_size, decimals=DECIMALS)

jerk5 = load_period_col(RAW_DIR / "jerk_history_multiperiod.csv", "jerk_p5")
left = renko.sort_values("timestamp", kind="stable").reset_index(drop=True)
right = jerk5.sort_values("timestamp", kind="stable").reset_index(drop=True)
renko = pd.merge_asof(left, right, on="timestamp", direction="backward")
renko = compute_cci(renko)

renko_base = renko.sort_values("timestamp", kind="stable").reset_index(drop=True)

# Period 7 isn't in the multi-period sweep dump (96 down to 8/6 in steps of 10) --
# use the original single-period rc_history.csv instead, captured at period 7
# (the old default, before the live chart was changed to 8).
rc7 = load_rc_dump(RAW_DIR / "rc_history.csv")
renko_p7 = align_to_renko(renko_base, rc7)

dump = load_multiperiod_dump(MULTI_PERIOD_FILE)
renko_p96 = align_rc_period(renko_base, dump, RC_SECONDARY_PERIOD)

renko = renko_p7.copy()
renko["rc96_value"] = renko_p96["rc_value"].to_numpy()

usable = renko.dropna(subset=["rc_value", "rc96_value", "jerk_value", "cci_value"]).sort_values(
    "timestamp", kind="stable").reset_index(drop=True)
print(f"usable: {len(usable)} bricks\n")

n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"dev: {len(dev)} | lockbox: {len(lockbox)}\n")

print("=== Current live rule (RC(7)+RC(96)+Jerk+CCI entry, RC(7)+brick+Jerk exit) -- reference ===")

def current_exit_direction(row, slots):
    rc7 = zb.rc_dir(row["rc_value"])
    rc96 = zb.rc_dir(row["rc96_value"])
    jerk = zb.jerk_dir(row["jerk_value"])
    entry_dir = 0
    if rc7 < 0 and jerk == -1:
        entry_dir = -1
    elif rc7 > 0 and jerk == 1:
        entry_dir = 1
    if entry_dir == 0:
        return 0
    if rc96 != entry_dir:
        return 0
    if not cci_allows_direction(entry_dir, row["cci_value"]):
        return 0
    return entry_dir

dev_t, dev_wr, dev_e = summarize(zb.run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0, direction_fn=current_exit_direction))
lb_t, lb_wr, lb_e = summarize(zb.run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0, direction_fn=current_exit_direction))
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")

print("\n=== ALL filters must agree to exit (RC7+brick+Jerk+CCI+RC96), else SL/TP only ===")
dev_t2, dev_wr2, dev_e2 = summarize(run_full_agreement_backtest(dev, 1000.0))
lb_t2, lb_wr2, lb_e2 = summarize(run_full_agreement_backtest(lockbox, 1000.0))
print(f"  dev    : trades={dev_t2} wr={dev_wr2:.1f}% ending=${dev_e2:,.2f}")
print(f"  lockbox: trades={lb_t2} wr={lb_wr2:.1f}% ending=${lb_e2:,.2f}")
