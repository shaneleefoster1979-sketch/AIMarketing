#!/usr/bin/env python3
"""
cci_generator.py

Direct Python port of MetaQuotes' stock CCI.mq4 (the same formula MT4's
built-in iCCI() uses): typical price (High+Low+Close)/3, its simple moving
average, the mean absolute deviation of typical price from that average,
and the 0.015 scaling constant. Open-source/standard formula, so (like
nal_generator.py) this is computed directly from the Renko series, no MT4
dump needed.

Operates on ascending-chronological rows (oldest first), same convention
nal_generator.py/jerk_generator.py use.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CCI_PERIOD = 14


def compute_cci(df: pd.DataFrame, period: int = CCI_PERIOD) -> pd.DataFrame:
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(close)

    typical = (high + low + close) / 3.0
    cci = np.full(n, np.nan)

    for i in range(period - 1, n):
        window = typical[i - period + 1 : i + 1]
        mov = window.mean()
        mean_dev = np.abs(window - mov).mean()
        cci[i] = 0.0 if mean_dev == 0 else (typical[i] - mov) / (0.015 * mean_dev)

    out = df.copy()
    out["cci_value"] = cci
    return out


def cci_allows_direction(direction: int, cci_value) -> bool:
    """Matches ZeusAI.mq4's CCI_AllowsDirection(): a GATE, not a direction
    source. CCI < 0 permits a BUY, CCI > 0 permits a SELL -- the inverse of
    CCI's usual overbought/oversold reading, per the requested test."""
    if pd.isna(cci_value):
        return False
    if direction == 1:
        return cci_value < 0
    if direction == -1:
        return cci_value > 0
    return False
