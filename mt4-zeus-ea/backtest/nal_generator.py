#!/usr/bin/env python3
"""
nal_generator.py

Direct Python port of DistributionalRankMomentum.mq4's math (NordicAlphaLab's
"Distributional Rank Momentum | NAL", MPL 2.0) -- same percentile-linear-
interpolation, same 99-level rank scoring, same EMA confluence gate, same
sticky NAL state machine. Unlike RC/Jerk this indicator is open-source, so
this is computed directly from the Renko close series, no MT4 dump needed.

Operates on ascending-chronological rows (oldest first), unlike the MQL4
port's 0=newest series convention -- window directions are mirrored
accordingly, same translation jerk_generator.py/rmc_generator.py use.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAL_MOM_LEN = 60
NAL_LOOKBACK = 60
NAL_U_THRESHOLD = 90.0
NAL_L_THRESHOLD = 40.0
NAL_USE_EMA = True
NAL_EMA_LENGTH = 30


def _percentile_linear_interp(sorted_asc: np.ndarray, pct: float) -> float:
    n = len(sorted_asc)
    if n == 0:
        return np.nan
    if n == 1:
        return sorted_asc[0]
    rank = pct / 100.0 * (n - 1)
    lo = int(np.floor(rank))
    hi = int(np.ceil(rank))
    lo = max(0, lo)
    hi = min(n - 1, hi)
    frac = rank - lo
    return sorted_asc[lo] + frac * (sorted_asc[hi] - sorted_asc[lo])


def compute_nal(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].to_numpy(dtype=float)
    n = len(close)
    pct = (NAL_U_THRESHOLD + NAL_L_THRESHOLD) / 2.0

    momentum = np.full(n, np.nan)
    for pos in range(NAL_MOM_LEN - 1, n):
        window = np.sort(close[pos - NAL_MOM_LEN + 1 : pos + 1])
        momentum[pos] = close[pos] - _percentile_linear_interp(window, pct)

    score = np.full(n, np.nan)
    for pos in range(NAL_LOOKBACK - 1, n):
        win = momentum[pos - NAL_LOOKBACK + 1 : pos + 1]
        if np.isnan(win).any():
            continue
        sorted_win = np.sort(win)
        cur = momentum[pos]
        above = 0
        for p in range(1, 100):
            lvl = _percentile_linear_interp(sorted_win, float(p))
            if lvl < cur:
                above += 1
        score[pos] = above / 99.0 * 100.0

    ema = np.full(n, np.nan)
    alpha = 2.0 / (NAL_EMA_LENGTH + 1.0)
    running = np.nan
    for pos in range(n):
        if np.isnan(score[pos]):
            continue
        running = score[pos] if np.isnan(running) else alpha * score[pos] + (1.0 - alpha) * running
        ema[pos] = running

    nal = np.zeros(n, dtype=int)
    prev = 0
    for pos in range(n):
        if np.isnan(score[pos]):
            nal[pos] = 0
            prev = 0
            continue
        have_ema = NAL_USE_EMA and not np.isnan(ema[pos])
        ema_bull = (not NAL_USE_EMA) or (have_ema and score[pos] > ema[pos])
        ema_bear = (not NAL_USE_EMA) or (have_ema and score[pos] < ema[pos])
        bullish = score[pos] >= NAL_U_THRESHOLD and ema_bull
        bearish = score[pos] < NAL_L_THRESHOLD and ema_bear
        cur_nal = 1 if bullish else (-1 if bearish else prev)
        nal[pos] = cur_nal
        prev = cur_nal

    out = df.copy()
    out["nal_score"] = score
    out["nal_state"] = nal
    return out


def nal_dir(nal_state) -> int:
    """+1 = NAL bullish (greenish-blue, buy side), -1 = NAL bearish (dark
    blue, sell side), 0 = neutral/undefined (pre-warmup only in practice,
    since NAL is sticky once it first fires)."""
    if pd.isna(nal_state):
        return 0
    return int(nal_state)
