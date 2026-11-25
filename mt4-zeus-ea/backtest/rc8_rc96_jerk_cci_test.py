#!/usr/bin/env python3
"""
rc8_rc96_jerk_cci_test.py

Current live entry rule (RC(8) + Jerk(5) dual-agreement, brick-confirmed)
with TWO new entry gates stacked on top, per request:

  1. A second RC reading at period 96 must AGREE (same sign) with RC(8)'s
     direction before an entry is allowed.
  2. CCI (period 14) must also permit that direction (CCI<0 for buy,
     CCI>0 for sell), same as cci_gate_test.py.

Both are gates on the EXISTING RC(8)+Jerk entry direction, not new
direction sources -- same pattern as every other filter added this
session. The RC-flip EXIT is left untouched (still just RC(8)+Jerk,
brick-confirmed), since every prior filter (CCI included) was only ever
added as an entry gate in the live EA, never touching the exit.
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
JERK_CLAMP_MAX = 25.0
RC_PRIMARY_PERIOD = 8
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


def rc8_rc96_cci_direction(row, slots):
    rc8 = zb.rc_dir(row["rc_value"])
    rc96 = zb.rc_dir(row["rc96_value"])
    jerk = zb.jerk_dir(row["jerk_value"])

    entry_dir = 0
    if rc8 < 0 and jerk == -1:
        entry_dir = -1
    elif rc8 > 0 and jerk == 1:
        entry_dir = 1
    if entry_dir == 0:
        return 0

    if rc96 != entry_dir:
        return 0
    if not cci_allows_direction(entry_dir, row["cci_value"]):
        return 0
    return entry_dir


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

dump = load_multiperiod_dump(MULTI_PERIOD_FILE)
renko_base = renko.sort_values("timestamp", kind="stable").reset_index(drop=True)
renko_p8 = align_rc_period(renko_base, dump, RC_PRIMARY_PERIOD)      # adds rc_value (period 8)
renko_p96 = align_rc_period(renko_base, dump, RC_SECONDARY_PERIOD)   # adds rc_value (period 96)
# Both derive from the same renko_base with identical row order (merge_asof preserves
# the left frame's row order/count), so the period-96 reading can be attached directly.
renko = renko_p8.copy()
renko["rc96_value"] = renko_p96["rc_value"].to_numpy()

usable = renko.dropna(subset=["rc_value", "rc96_value", "jerk_value", "cci_value"]).sort_values(
    "timestamp", kind="stable").reset_index(drop=True)
print(f"usable: {len(usable)} bricks\n")

n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"dev: {len(dev)} | lockbox: {len(lockbox)}\n")

print(f"=== Current live rule (RC({RC_PRIMARY_PERIOD}) + Jerk dual-agreement) -- reference ===")
dev_t, dev_wr, dev_e = summarize(zb.run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0))
lb_t, lb_wr, lb_e = summarize(zb.run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0))
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")

print(f"\n=== + RC({RC_SECONDARY_PERIOD}) agreement + CCI gate ===")
dev_t2, dev_wr2, dev_e2 = summarize(zb.run_zeus_backtest(dev, 1000.0, direction_fn=rc8_rc96_cci_direction))
lb_t2, lb_wr2, lb_e2 = summarize(zb.run_zeus_backtest(lockbox, 1000.0, direction_fn=rc8_rc96_cci_direction))
print(f"  dev    : trades={dev_t2} wr={dev_wr2:.1f}% ending=${dev_e2:,.2f}")
print(f"  lockbox: trades={lb_t2} wr={lb_wr2:.1f}% ending=${lb_e2:,.2f}")
