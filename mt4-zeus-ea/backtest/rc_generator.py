#!/usr/bin/env python3
"""
rc_generator.py

Loads an RC_HistoryDump.mq4 export (semicolon-delimited
`timestamp;blue;maroon`, one row per RC update -- sparse, not one row per
bar) and aligns it onto a Renko brick series: each brick inherits the most
recent RC reading known at or before that brick's own timestamp (as-of /
forward-fill join), since RC updates far less often than bricks form.

RC_EMPTY_SENTINEL (2147483647.0, MQL4's INT_MAX cast to double) marks rows
from before the indicator had enough warm-up history -- treated as no
reading. Blue is the bull (positive) buffer, maroon is already
negative-signed for bear readings in this export, so the combined signed
value is whichever side is actually populated.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

RC_EMPTY_SENTINEL = 2147483647.0


def load_rc_dump(path: Path, tz: str = "UTC") -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_localize(tz)

    blue = df["blue"].where(df["blue"] != RC_EMPTY_SENTINEL, np.nan)
    maroon = df["maroon"].where(df["maroon"] != RC_EMPTY_SENTINEL, np.nan)

    rc_value = np.where(blue.fillna(0) != 0, blue, np.where(maroon.fillna(0) != 0, maroon, np.nan))
    df["rc_value"] = rc_value
    df = df.dropna(subset=["rc_value"])
    df = df.sort_values("timestamp", kind="stable").drop_duplicates(subset=["timestamp"], keep="last")
    return df[["timestamp", "rc_value"]].reset_index(drop=True)


def align_to_renko(renko_df: pd.DataFrame, rc_df: pd.DataFrame) -> pd.DataFrame:
    left = renko_df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    right = rc_df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    merged = pd.merge_asof(left, right, on="timestamp", direction="backward")
    return merged
