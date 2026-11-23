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


def compute_cci_armed_state(df: pd.DataFrame) -> pd.DataFrame:
    """Stateful, stricter version of the plain CCI gate: a buy isn't just
    "CCI < 0 right now" -- CCI must have touched or crossed below -100 at
    some point, and buy stays armed only as long as CCI has stayed below 0
    ever since (a cross back to >= 0 disarms it, requiring a fresh -100
    touch to re-arm). Sell is the mirror: armed by touching/crossing above
    +100, disarmed the moment CCI crosses back to <= 0. Adds buy_armed/
    sell_armed boolean columns, walked chronologically (oldest first, same
    row order as the rest of this file) since this is inherently path-
    dependent across bars, unlike the plain per-bar CCI gate."""
    cci = df["cci_value"].to_numpy(dtype=float)
    n = len(cci)
    buy_armed = np.zeros(n, dtype=bool)
    sell_armed = np.zeros(n, dtype=bool)

    buy_state = False
    sell_state = False
    for i in range(n):
        c = cci[i]
        if not np.isnan(c):
            if c <= -100:
                buy_state = True
            if c >= 0:
                buy_state = False
            if c >= 100:
                sell_state = True
            if c <= 0:
                sell_state = False
        buy_armed[i] = buy_state
        sell_armed[i] = sell_state

    out = df.copy()
    out["buy_armed"] = buy_armed
    out["sell_armed"] = sell_armed
    return out


def cci_armed_allows_direction(direction: int, buy_armed: bool, sell_armed: bool) -> bool:
    if direction == 1:
        return bool(buy_armed)
    if direction == -1:
        return bool(sell_armed)
    return False
