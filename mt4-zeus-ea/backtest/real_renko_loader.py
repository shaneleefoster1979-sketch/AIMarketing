#!/usr/bin/env python3
"""
real_renko_loader.py

Loads Renko_OHLC_HistoryDump.mq4's export: the offline Renko chart's OWN
real Open/High/Low/Close (true wicks, true reversal-brick doubling) --
not the wickless synthetic reconstruction renko_generator.py builds from
M1 closes.

The dump's first ~1,176 rows are a seed/initialization artifact, not real
price action: every one of them is timestamped exactly "1999.03.05" (at
various times that day), with prices ranging implausibly from 357 down to
122 -- real USDJPY has never traded anywhere near 357. This is almost
certainly however the offline chart was originally built rapidly
replaying down to its real starting point, all stamped with that one
day's timestamps since the seeding process has no real per-brick times
for that phase. Real, genuinely spaced-out timestamps (and real wicks)
begin at 1999.03.08 (e.g. a 122.801/122.601 open/close brick with a
123.180 high -- a real wick above both). Everything from 1999.03.05 and
earlier is dropped.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

SEED_FILL_CUTOFF = pd.Timestamp("1999-03-08")


def load_real_renko(path: Path, tz: str = "UTC") -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_localize(tz)

    cutoff = SEED_FILL_CUTOFF.tz_localize(tz)
    before = len(df)
    df = df[df["timestamp"] >= cutoff]
    dropped = before - len(df)
    if dropped:
        print(f"Dropped {dropped} seed-fill rows before {SEED_FILL_CUTOFF.date()} (chart initialization artifact)")

    # NOT deduplicated by timestamp -- unlike the M1 raw-tick loader (where a
    # repeated minute is a real DST-duplicate artifact), multiple distinct
    # Renko bricks can legitimately share the same minute timestamp during a
    # fast move, and dropping them here would silently discard real bricks.
    df = df.sort_values("timestamp", kind="stable")
    return df[["timestamp", "open", "high", "low", "close"]].reset_index(drop=True)
