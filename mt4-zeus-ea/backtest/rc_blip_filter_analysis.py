#!/usr/bin/env python3
"""
rc_blip_filter_analysis.py

Answers: how often did Jerk and/or CCI prevent a bad trade entry during a
minor RC blip that flips, then flips right back to the direction price
was already going?

Important methodological note: this uses REAL RC/Jerk/CCI/brick data at
the current live settings (RC period=8, Jerk_LPD_Period=5, CCI_Period=14)
-- NOT the synthetic flip injection from rc_repaint_simulation_test.py.
That injection only ever altered RC's READING during a run of bricks that
were ALL REALLY moving the same direction, which means the real brick
itself never actually confirmed the flipped direction -- ZeusAI.mq4's
own brickOK requirement (the just-closed brick must print IN the entry
direction) already blocks 100% of entries in that exact scenario, making
Jerk/CCI irrelevant to measure there. To get a scenario where Jerk/CCI's
agreement actually matters, the REAL brick has to also have genuinely
moved the "wrong" way for that one bar (a real minor pullback brick, not
just an altered indicator reading) -- so this looks for REAL 3-bar RC
patterns (direction D, then -D for one bar, then back to D) and checks,
at that middle bar, whether the real brick also confirms -D (making it a
live entry candidate at all), and if so, whether Jerk and/or CCI would
have blocked it.
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
RC_PERIOD = 8
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


print(f"Building dataset (RC period={RC_PERIOD}, Jerk period=5, CCI period=14 -- all real, no injection)...")
raw = load_time_series(RAW_DIR / "USDJPY_M1.csv")
brick_size = BRICK_SIZE_PIPS * PIP_SIZE_USDJPY
renko = generate_renko_bricks(raw, brick_size, decimals=DECIMALS)

jerk5 = load_period_col(RAW_DIR / "jerk_history_multiperiod.csv", "jerk_p5")
left = renko.sort_values("timestamp", kind="stable").reset_index(drop=True)
right = jerk5.sort_values("timestamp", kind="stable").reset_index(drop=True)
renko = pd.merge_asof(left, right, on="timestamp", direction="backward")
renko = compute_cci(renko)

dump = load_multiperiod_dump(MULTI_PERIOD_FILE)
renko = align_rc_period(renko, dump, RC_PERIOD)

usable = renko.dropna(subset=["rc_value", "jerk_value", "cci_value"]).sort_values(
    "timestamp", kind="stable").reset_index(drop=True)
print(f"usable: {len(usable)} bricks\n")

rc_dir = usable["rc_value"].apply(zb.rc_dir).to_numpy()
jerk_dir = usable["jerk_value"].apply(zb.jerk_dir).to_numpy()
cci_val = usable["cci_value"].to_numpy()
brick_dir = (usable["close"] > usable["open"]).to_numpy() * 2 - 1  # +1 or -1
close = usable["close"].to_numpy()
ts = usable["timestamp"].to_numpy()

n = len(usable)
blip_total = 0
brick_also_confirms = 0
jerk_alone_prevented = 0
cci_prevented = 0
not_prevented = []

for k in range(1, n - 1):
    d_before = rc_dir[k - 1]
    d_mid = rc_dir[k]
    d_after = rc_dir[k + 1]
    if d_before == 0 or d_mid == 0:
        continue
    if d_mid != -d_before:
        continue
    if d_after != d_before:
        continue  # only count it as "flipped back" if it actually reverts

    blip_total += 1
    wrong_dir = d_mid  # the blip's (wrong) suggested direction

    if brick_dir[k] != wrong_dir:
        continue  # the real brick never confirmed the blip -- brickOK alone already blocks this, Jerk/CCI irrelevant here
    brick_also_confirms += 1

    if jerk_dir[k] != wrong_dir:
        jerk_alone_prevented += 1
        continue  # Jerk disagreement means entryDir never even forms -- CCI is never reached

    # Jerk agreed with the blip too -- down to CCI as the last line of defense
    if not cci_allows_direction(wrong_dir, cci_val[k]):
        cci_prevented += 1
    else:
        not_prevented.append((pd.Timestamp(ts[k]), wrong_dir, close[k]))

print("=" * 70)
print(f"Total real 3-bar RC blips (D, -D, back to D):                {blip_total}")
print(f"  -- of those, the real brick ALSO confirmed the blip dir:   {brick_also_confirms} "
      f"({brick_also_confirms/blip_total*100:.1f}% of blips)")
print(f"       (the rest never had brickOK, so couldn't have entered regardless of Jerk/CCI)")
print()
print(f"Of the {brick_also_confirms} blips that WERE live entry candidates:")
print(f"  Jerk alone disagreed and blocked it:      {jerk_alone_prevented} "
      f"({jerk_alone_prevented/brick_also_confirms*100:.1f}%)")
print(f"  Jerk agreed, but CCI blocked it:          {cci_prevented} "
      f"({cci_prevented/brick_also_confirms*100:.1f}%)")
print(f"  Jerk AND CCI both agreed -- NOT prevented: {len(not_prevented)} "
      f"({len(not_prevented)/brick_also_confirms*100:.1f}%)")

if not_prevented:
    print("\nUnprotected cases (RC blip + Jerk + CCI all agreed on the wrong direction):")
    for t, d, c in not_prevented[:20]:
        print(f"  {t}  direction={'BUY' if d == 1 else 'SELL'}  close={c:.3f}")
    if len(not_prevented) > 20:
        print(f"  ... and {len(not_prevented) - 20} more")
