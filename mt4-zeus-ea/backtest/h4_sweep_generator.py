#!/usr/bin/env python3
"""
h4_sweep_generator.py

Builds a directional bias from a 2-candle liquidity-sweep pattern on the
4-hour timeframe, built directly from the same M1 series the Renko bricks
come from (not an MT4 dump -- pure price-action rule, no indicator needed):

  Buy-sweep : candle A (a closed H4 bar) closes bullish (Close > Open),
              the very next H4 candle B dips below A's Low, then closes
              back ABOVE A's Low. Arms a "buy trades only" bias.

  Sell-sweep: candle A closes bearish, candle B pokes above A's High,
              then closes back BELOW A's High. Arms a "sell trades only"
              bias.

The bias is sticky: once armed, it stays in effect indefinitely until the
OPPOSITE sweep pattern fires (per request), not until any fixed timeout.
Starts neutral (0, which blocks both directions, same as the armed-CCI
gate's unarmed state) until the first sweep ever occurs.

H4 bars are built via pandas resample("4h"), which bins to UTC-midnight-
aligned 4h windows (00/04/08/12/16/20) on the same broker-server timestamps
already used everywhere else in this pipeline (load_time_series labels
them "UTC" without converting -- a labeling convention, not a real
timezone conversion, consistent with how RC/Jerk dumps are already
treated). This is a best-effort standard H4 alignment; it is NOT guaranteed
to exactly match whatever session-start offset an MT4 broker's own H4
chart uses, since that offset isn't recorded in the M1 export.

The bias becomes usable only once the confirming candle B has actually
closed -- bias_known_at = B's open time + 4h -- and is merged onto the
Renko series via merge_asof(direction="backward"), so no brick ever sees
a bias before it was genuinely known. Same no-lookahead discipline as
every other filter in this project.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_h4_bars(m1_df: pd.DataFrame) -> pd.DataFrame:
    idx = m1_df.set_index("timestamp")
    h4 = idx.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    h4 = h4.dropna().reset_index()
    return h4


def compute_h4_sweep_bias(h4_df: pd.DataFrame) -> pd.DataFrame:
    o = h4_df["open"].to_numpy(dtype=float)
    h = h4_df["high"].to_numpy(dtype=float)
    l = h4_df["low"].to_numpy(dtype=float)
    c = h4_df["close"].to_numpy(dtype=float)
    n = len(c)

    bias = np.zeros(n, dtype=int)
    state = 0
    for j in range(1, n):
        a_bull = c[j - 1] > o[j - 1]
        a_bear = c[j - 1] < o[j - 1]
        buy_sweep = a_bull and (l[j] < l[j - 1]) and (c[j] > l[j - 1])
        sell_sweep = a_bear and (h[j] > h[j - 1]) and (c[j] < h[j - 1])
        if buy_sweep:
            state = 1
        elif sell_sweep:
            state = -1
        bias[j] = state

    out = h4_df.copy()
    out["h4_bias"] = bias
    out["bias_known_at"] = out["timestamp"] + pd.Timedelta(hours=4)
    return out


def align_h4_bias_to_renko(renko_df: pd.DataFrame, h4_bias_df: pd.DataFrame) -> pd.DataFrame:
    bias_series = h4_bias_df[["bias_known_at", "h4_bias"]].rename(columns={"bias_known_at": "timestamp"})
    bias_series = bias_series.sort_values("timestamp", kind="stable").reset_index(drop=True)
    left = renko_df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    merged = pd.merge_asof(left, bias_series, on="timestamp", direction="backward")
    merged["h4_bias"] = merged["h4_bias"].fillna(0).astype(int)
    return merged


def h4_bias_allows_direction(direction: int, h4_bias: int) -> bool:
    if direction == 1:
        return h4_bias == 1
    if direction == -1:
        return h4_bias == -1
    return False
