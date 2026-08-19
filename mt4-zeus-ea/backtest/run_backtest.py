#!/usr/bin/env python3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from data_ingestion import load_time_series
from renko_generator import generate_renko_bricks, BRICK_SIZE_PIPS, PIP_SIZE_USDJPY, DECIMALS
from rc_generator import load_rc_dump, align_to_renko
from rmc_generator import attach_brick_volume, compute_rmc
from zeus_backtest import run_zeus_backtest

RAW_DIR = Path(__file__).parent / "data" / "raw"
OUT_DIR = Path(__file__).parent / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print("Loading raw USDJPY M1...")
raw = load_time_series(RAW_DIR / "USDJPY_M1.csv")
print(f"  {len(raw)} clean M1 bars, {raw['timestamp'].min()} to {raw['timestamp'].max()}")

print("Building 20-pip Renko bricks...")
brick_size = BRICK_SIZE_PIPS * PIP_SIZE_USDJPY
renko = generate_renko_bricks(raw, brick_size, decimals=DECIMALS)
print(f"  {len(renko)} bricks")

print("Loading and aligning RC dump...")
rc = load_rc_dump(RAW_DIR / "rc_history.csv")
renko = align_to_renko(renko, rc)
print(f"  {renko['rc_value'].notna().sum()}/{len(renko)} bricks have an RC reading")

print("Attaching brick volume and computing RMC...")
renko = attach_brick_volume(renko, raw)
renko = compute_rmc(renko)
print(f"  {renko['rmc_value'].notna().sum()}/{len(renko)} bricks have an RMC reading")

renko.to_csv(OUT_DIR / "renko_usdjpy.csv", index=False)
print(f"Wrote {OUT_DIR / 'renko_usdjpy.csv'}")

usable = renko.dropna(subset=["rc_value"]).reset_index(drop=True)
print(f"\nRunning Zeus backtest ({len(usable)} usable bricks, {usable['timestamp'].min()} to {usable['timestamp'].max()})...")
result = run_zeus_backtest(usable, starting_balance=1000.0, spread_pips=1.0)
tl = result["trade_log"]
wins = sum(1 for t in tl if t["pnl"] > 0)
print(f"\ntrades={len(tl)}  win_rate={wins/len(tl)*100:.1f}%  ending_equity=${result['ending_equity']:,.2f}")

recs = []
equity = 1000.0
for t in tl:
    equity += t["pnl"]
    recs.append({"timestamp": t["exit_timestamp"], "pnl": t["pnl"], "equity": equity})
mdf = pd.DataFrame(recs)
mdf["timestamp"] = pd.to_datetime(mdf["timestamp"], utc=True)
mdf["month"] = mdf["timestamp"].dt.to_period("M")
monthly_pnl = mdf.groupby("month")["pnl"].sum()
monthly_start_equity = mdf.groupby("month")["equity"].first() - mdf.groupby("month")["pnl"].first()
monthly_pct = (monthly_pnl / monthly_start_equity) * 100

print(f"\nn_months={len(monthly_pct)}  simple_avg_monthly_pct={monthly_pct.mean():.2f}  median_monthly_pct={monthly_pct.median():.2f}")
print("\nMonthly %:")
print(monthly_pct)

mdf.to_csv(OUT_DIR / "trade_log.csv", index=False)
