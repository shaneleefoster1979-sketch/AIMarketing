#!/usr/bin/env python3
"""
rc_flip_filter_pnl_simulation.py

Full version of the RC-blip filter question, per request: treats a run of
3 real same-direction Renko bricks where RC's reading flips on the 3rd
(the same artifact as rc_repaint_simulation_test.py) as a hypothetical
entry trigger in the WRONG (flipped) direction, checks what Jerk and CCI
are reading at that exact same moment, then walks the brick series FORWARD
(brick 4, 5, 6, ...) to see whether price actually continues in the real
original direction (the wrong-direction trade would LOSE) or reverses to
match the flip (it would WIN) -- using the EA's own brick-count thresholds
(3 favorable bricks = win, 2 adverse bricks = loss, matching
StopLossPoints=600/TP1=600 at BrickSizePoints=200, i.e. T1's real 1:1
setup: SLBricksFromPoints(600)=2, 600/200=3). Counts, of the hypothetical
entries that WOULD have lost money, how many were actually prevented
because Jerk and/or CCI disagreed with the flip.

Methodology note -- this DELIBERATELY ignores ZeusAI.mq4's brickOK gate
(the real just-closed brick must itself print in the entry direction).
Since the injected flip only ever happens on a brick that's REALLY still
going the original direction, brickOK would otherwise block 100% of these
by construction (shown in rc_blip_filter_analysis.py's real-data search,
which is why that version only found 10 genuine candidates in the whole
history). This version instead tests Jerk+CCI's OWN discriminating power
in isolation, as requested, treating the flip as the entry trigger
directly.
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
FLIP_EVERY_N_BRICKS = 4
TP_FAVORABLE_BRICKS = 3   # TP1 = 600 points / 200 points per brick
SL_ADVERSE_BRICKS = 2     # SLBricksFromPoints(600) with BrickSizePoints=200
MAX_FORWARD_BRICKS = 500  # give up and call it unresolved beyond this


def load_period_col(path, col, tz="UTC"):
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_localize(tz)
    df = df.sort_values("timestamp", kind="stable").drop_duplicates(subset=["timestamp"], keep="last")
    sub = df[["timestamp", col]].dropna(subset=[col]).copy()
    sub["jerk_value"] = sub[col].clip(-JERK_CLAMP_MAX, JERK_CLAMP_MAX)
    return sub[["timestamp", "jerk_value"]]


print(f"Building dataset (RC period={RC_PERIOD}, Jerk period=5, CCI period=14)...")
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
n = len(usable)
print(f"usable: {n} bricks\n")

jerk_dir_arr = usable["jerk_value"].apply(zb.jerk_dir).to_numpy()
cci_val_arr = usable["cci_value"].to_numpy()
brick_dir_arr = ((usable["close"] > usable["open"]).to_numpy() * 2 - 1)  # +1/-1
ts_arr = usable["timestamp"].to_numpy()
close_arr = usable["close"].to_numpy()

run_len = 0
prev_dir = 0
flip_events = []  # (index, wrong_dir, real_dir)

for i in range(n):
    d = brick_dir_arr[i]
    run_len = run_len + 1 if d == prev_dir else 1
    prev_dir = d
    if run_len % FLIP_EVERY_N_BRICKS == 0:
        flip_events.append((i, -d, d))

print(f"Flip-trigger events (every {FLIP_EVERY_N_BRICKS}th same-direction brick): {len(flip_events)}\n")


def simulate_outcome(start_idx: int, wrong_dir: int) -> str:
    """Walk forward from start_idx+1. favorable = bricks matching wrong_dir
    (the hypothetical trade's direction), adverse = bricks matching the
    real original direction. Returns 'win', 'loss', or 'unresolved'."""
    favorable = 0
    adverse = 0
    end = min(n, start_idx + 1 + MAX_FORWARD_BRICKS)
    for j in range(start_idx + 1, end):
        if brick_dir_arr[j] == wrong_dir:
            favorable += 1
            if favorable >= TP_FAVORABLE_BRICKS:
                return "win"
        else:
            adverse += 1
            if adverse >= SL_ADVERSE_BRICKS:
                return "loss"
    return "unresolved"


results = {
    "blocked_by_jerk": {"win": 0, "loss": 0, "unresolved": 0},
    "blocked_by_cci": {"win": 0, "loss": 0, "unresolved": 0},
    "not_blocked": {"win": 0, "loss": 0, "unresolved": 0},
}

for idx, wrong_dir, real_dir in flip_events:
    outcome = simulate_outcome(idx, wrong_dir)

    jerk_agrees = (jerk_dir_arr[idx] == wrong_dir)
    if not jerk_agrees:
        results["blocked_by_jerk"][outcome] += 1
        continue

    cci_agrees = cci_allows_direction(wrong_dir, cci_val_arr[idx])
    if not cci_agrees:
        results["blocked_by_cci"][outcome] += 1
        continue

    results["not_blocked"][outcome] += 1

print("=" * 78)
total_losses_if_unfiltered = sum(r["loss"] for r in results.values())
losses_prevented = results["blocked_by_jerk"]["loss"] + results["blocked_by_cci"]["loss"]
wins_missed = results["blocked_by_jerk"]["win"] + results["blocked_by_cci"]["win"]

for category, r in results.items():
    total = sum(r.values())
    print(f"{category:16s}: total={total:5d}  win={r['win']:5d}  loss={r['loss']:5d}  unresolved={r['unresolved']:5d}")

print()
print(f"Of all {len(flip_events)} flip events, {total_losses_if_unfiltered} would have been LOSING trades "
      f"if entered on the flip alone (RC agreeing with itself, no Jerk/CCI check).")
print(f"  -> Jerk and/or CCI PREVENTED {losses_prevented} of those losing entries "
      f"({losses_prevented/total_losses_if_unfiltered*100:.1f}% of all would-be losses).")
print(f"  -> Jerk and/or CCI also BLOCKED {wins_missed} entries that would actually have WON "
      f"(missed opportunities, the cost of the filter).")
print(f"  -> {results['not_blocked']['loss']} losing entries got through BOTH filters unprevented.")
