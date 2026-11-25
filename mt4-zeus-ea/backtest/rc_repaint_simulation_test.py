#!/usr/bin/env python3
"""
rc_repaint_simulation_test.py

Hypothetical: "assume at period 8 (the actual current live RC_Period),
RC flips every 3rd brick that moves in the same direction" -- simulates
that specific repaint artifact on top of REAL RC data and reruns the
current live EA rule (RC+Jerk dual-agreement, gated by CCI) to see the
impact.

Uses the real period=8 dump (re-run by the user with RC_Period8=8 set
directly in RC_HistoryDump_MultiPeriod.mq4's input dialog, replacing the
period=6 stand-in this script originally used).

The flip rule: track consecutive same-direction Renko bricks (direction
changes reset the run to 1). On every 3rd brick of a continuing run (the
3rd, 6th, 9th, ... brick in that same-direction streak), the REAL rc_value
for that brick is negated (sign flipped, same magnitude) in the synthetic
series -- simulating RC spuriously showing the opposite side for one brick
before (implicitly) reverting, which is what repainting back to "as if it
never happened" would look like to the live EA at the moment of decision.
All other bricks keep their real, un-flipped rc_value.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from cci_generator import compute_cci, cci_allows_direction
from rc_period_sweep import load_multiperiod_dump, align_rc_period
import zeus_backtest as zb

RAW_DIR = Path(__file__).parent / "data" / "raw"
MULTI_PERIOD_FILE = RAW_DIR / "rc_history_multiperiod.csv"
BASE_RC_PERIOD = 8  # the actual current live RC_Period setting
JERK_CLAMP_MAX = 25.0
FLIP_EVERY_N_BRICKS = 3


def load_period_col(path, col, tz="UTC"):
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_localize(tz)
    df = df.sort_values("timestamp", kind="stable").drop_duplicates(subset=["timestamp"], keep="last")
    sub = df[["timestamp", col]].dropna(subset=[col]).copy()
    sub["jerk_value"] = sub[col].clip(-JERK_CLAMP_MAX, JERK_CLAMP_MAX)
    return sub[["timestamp", "jerk_value"]]


def inject_repaint_flips(df: pd.DataFrame) -> pd.DataFrame:
    """Adds rc_value_repainted: the real rc_value, with every 3rd brick of
    a same-direction Renko streak sign-flipped. df must be in ascending
    chronological order (oldest first)."""
    closes = df["close"].to_numpy()
    opens = df["open"].to_numpy()
    rc = df["rc_value"].to_numpy()
    n = len(df)

    out = rc.copy()
    run_len = 0
    prev_dir = 0
    flipped_count = 0
    for i in range(n):
        brick_dir = 1 if closes[i] > opens[i] else -1
        run_len = run_len + 1 if brick_dir == prev_dir else 1
        prev_dir = brick_dir
        if run_len % FLIP_EVERY_N_BRICKS == 0:
            out[i] = -rc[i]
            flipped_count += 1

    result = df.copy()
    result["rc_value_repainted"] = out
    print(f"  Injected flips on {flipped_count}/{n} bricks ({flipped_count/n*100:.1f}%)")
    return result


def make_direction_fn(rc_col: str):
    def direction_fn(row, slots):
        rc = zb.rc_dir(row[rc_col])
        jerk = zb.jerk_dir(row["jerk_value"])
        entry_dir = 0
        if rc < 0 and jerk == -1:
            entry_dir = -1
        elif rc > 0 and jerk == 1:
            entry_dir = 1
        if entry_dir == 0:
            return 0
        return entry_dir if cci_allows_direction(entry_dir, row["cci_value"]) else 0
    return direction_fn


def summarize(result: dict) -> tuple[int, float, float]:
    tl = result["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    wr = wins / len(tl) * 100 if tl else float("nan")
    return len(tl), wr, result["ending_equity"]


print(f"Building dataset (RC period={BASE_RC_PERIOD}, the real live setting)...")
raw = load_time_series(RAW_DIR / "USDJPY_M1.csv")
brick_size = BRICK_SIZE_PIPS * PIP_SIZE_USDJPY
renko = generate_renko_bricks(raw, brick_size, decimals=DECIMALS)

jerk5 = load_period_col(RAW_DIR / "jerk_history_multiperiod.csv", "jerk_p5")
left = renko.sort_values("timestamp", kind="stable").reset_index(drop=True)
right = jerk5.sort_values("timestamp", kind="stable").reset_index(drop=True)
renko = pd.merge_asof(left, right, on="timestamp", direction="backward")
renko = compute_cci(renko)

dump = load_multiperiod_dump(MULTI_PERIOD_FILE)
renko = align_rc_period(renko, dump, BASE_RC_PERIOD)

usable = renko.dropna(subset=["rc_value", "jerk_value", "cci_value"]).reset_index(drop=True)
print(f"usable: {len(usable)} bricks\n")
print("Injecting the repaint-flip artifact (every 3rd same-direction brick)...")
usable = inject_repaint_flips(usable)

n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"dev: {len(dev)} | lockbox: {len(lockbox)}\n")

real_fn = make_direction_fn("rc_value")
repainted_fn = make_direction_fn("rc_value_repainted")

print(f"=== Real RC (period={BASE_RC_PERIOD}), no injected flips -- reference ===")
dev_t, dev_wr, dev_e = summarize(zb.run_zeus_backtest(dev, 1000.0, direction_fn=real_fn))
lb_t, lb_wr, lb_e = summarize(zb.run_zeus_backtest(lockbox, 1000.0, direction_fn=real_fn))
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")

print(f"\n=== Simulated repaint: every 3rd same-direction brick flipped ===")
dev_t2, dev_wr2, dev_e2 = summarize(zb.run_zeus_backtest(dev, 1000.0, direction_fn=repainted_fn))
lb_t2, lb_wr2, lb_e2 = summarize(zb.run_zeus_backtest(lockbox, 1000.0, direction_fn=repainted_fn))
print(f"  dev    : trades={dev_t2} wr={dev_wr2:.1f}% ending=${dev_e2:,.2f}")
print(f"  lockbox: trades={lb_t2} wr={lb_wr2:.1f}% ending=${lb_e2:,.2f}")
