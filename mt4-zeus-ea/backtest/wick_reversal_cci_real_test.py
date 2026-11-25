#!/usr/bin/env python3
"""
wick_reversal_cci_real_test.py

Reruns wick_reversal_cci_test.py's strategy (Renko Wick Reversal arrows
gated by CCI, no RC, no Jerk) against the REAL offline Renko chart's own
OHLC (Renko_OHLC_HistoryDump.mq4's export via real_renko_loader.py) --
true wicks and true reversal-brick doubling, instead of the wickless
synthetic reconstruction that made wick_reversal_cci_test.py fire zero
signals.

Same rule: buy when wick_buy_arrow fires AND CCI < 0; sell when
wick_sell_arrow fires AND CCI > 0; exit mirrors entry (opposite arrow +
CCI permits it). Same 4-leg risk/reward as live. Same dev/lockbox split,
CCI_Period=14.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from cci_generator import compute_cci
from wick_reversal_generator import compute_wick_reversal
from real_renko_loader import load_real_renko
from wick_reversal_cci_test import run_wick_cci_backtest, summarize

RAW_DIR = Path(__file__).parent / "data" / "raw"

print("Loading the REAL offline Renko chart's OHLC history (true wicks)...")
renko = load_real_renko(RAW_DIR / "renko_ohlc_history.csv")
print(f"  {len(renko)} real bricks after dropping the seed-fill rows")

renko = compute_cci(renko)
usable = compute_wick_reversal(renko)
usable = usable.dropna(subset=["cci_value"]).reset_index(drop=True)

buy_signals = int((usable["wick_buy_arrow"] & (usable["cci_value"] < 0)).sum())
sell_signals = int((usable["wick_sell_arrow"] & (usable["cci_value"] > 0)).sum())
raw_buy_arrows = int(usable["wick_buy_arrow"].sum())
raw_sell_arrows = int(usable["wick_sell_arrow"].sum())
print(f"usable: {len(usable)} bricks")
print(f"  raw wick arrows (before CCI gate): buy={raw_buy_arrows} sell={raw_sell_arrows}")
print(f"  entry signals (after CCI gate):    buy={buy_signals} sell={sell_signals}\n")

n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"dev: {len(dev)} | lockbox: {len(lockbox)}\n")

print("=== Renko Wick Reversal + CCI ONLY, on REAL Renko OHLC -- no RC, no Jerk ===")
dev_t, dev_wr, dev_e = summarize(run_wick_cci_backtest(dev, 1000.0))
lb_t, lb_wr, lb_e = summarize(run_wick_cci_backtest(lockbox, 1000.0))
print(f"  dev    : trades={dev_t} wr={dev_wr:.1f}% ending=${dev_e:,.2f}")
print(f"  lockbox: trades={lb_t} wr={lb_wr:.1f}% ending=${lb_e:,.2f}")
