#!/usr/bin/env python3
"""
vwap_generator.py

Standard daily-reset VWAP computed directly on the Renko brick series
(typical price = (high+low+close)/3, weighted by each brick's attached
volume, cumulative sum reset at each new UTC day) -- no separate raw-data
pass needed since volume is already attached to renko_usdjpy.csv.

vwap_dir: +1 when the brick closed above VWAP (bullish), -1 below.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_vwap(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    ts = pd.to_datetime(out["timestamp"])
    day = ts.dt.date

    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    vol = out["volume"].fillna(0.0)
    pv = typical * vol

    cum_pv  = pv.groupby(day).cumsum()
    cum_vol = vol.groupby(day).cumsum()

    vwap = np.where(cum_vol > 0, cum_pv / cum_vol, out["close"])
    out["vwap"] = vwap
    out["vwap_dir"] = np.where(out["close"] > out["vwap"], 1, np.where(out["close"] < out["vwap"], -1, 0))
    return out
