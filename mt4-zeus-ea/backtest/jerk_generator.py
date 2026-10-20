#!/usr/bin/env python3
"""
jerk_generator.py

Loads a Jerk_HistoryDump.mq4 export (semicolon-delimited `timestamp;jerk`,
one row per bar on the chart it was dumped from) and aligns it onto a
Renko brick series: each brick inherits the most recent Jerk reading known
at or before that brick's own timestamp (as-of / forward-fill join), same
technique rc_generator.py uses for RC.

The dump can carry duplicate same-minute timestamps (several Renko bricks
forming inside one calendar minute, since the export truncates to minute
resolution) -- kept last (the temporally later brick), same as RC's own
dedup rule.

Raw values are clamped to +-JERK_CLAMP_MAX, matching GetJerk_Value() in
ZeusAI.mq4 exactly -- the live EA never sees an unclamped reading, so
training must not either.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

JERK_CLAMP_MAX = 25.0


def load_jerk_dump(path: Path, tz: str = "UTC") -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_localize(tz)

    df = df.sort_values("timestamp", kind="stable").drop_duplicates(subset=["timestamp"], keep="last")
    df["jerk_value"] = df["jerk"].clip(-JERK_CLAMP_MAX, JERK_CLAMP_MAX)
    return df[["timestamp", "jerk_value"]].reset_index(drop=True)


def align_to_renko(renko_df: pd.DataFrame, jerk_df: pd.DataFrame) -> pd.DataFrame:
    left = renko_df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    right = jerk_df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    merged = pd.merge_asof(left, right, on="timestamp", direction="backward")
    return merged
