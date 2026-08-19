#!/usr/bin/env python3
"""
data_ingestion.py

Loads a raw MT4 History Center export (M1, no header, comma-delimited
`date,time,open,high,low,close,volume` with date as YYYY.MM.DD and time as
HH:MM) into a clean, standardized `timestamp, open, high, low, close,
volume` DataFrame, sorted chronologically and deduplicated.

MT4 exports occasionally contain a duplicate timestamp around a DST
transition (the broker's server clock repeating an hour) -- these are
dropped (keep the first occurrence) rather than treated as an error.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

RAW_COLUMNS = ["date", "time", "open", "high", "low", "close", "volume"]


def load_raw_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, header=None, names=RAW_COLUMNS)
    return df


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["timestamp"] = pd.to_datetime(
        out["date"] + " " + out["time"], format="%Y.%m.%d %H:%M", errors="coerce"
    )
    out = out.drop(columns=["date", "time"])
    return out[["timestamp", "open", "high", "low", "close", "volume"]]


def clean_dataframe(df: pd.DataFrame, tz: str = "UTC") -> pd.DataFrame:
    out = df.dropna(subset=["timestamp"]).copy()
    out["timestamp"] = out["timestamp"].dt.tz_localize(tz)
    out = out.sort_values("timestamp", kind="stable")
    before = len(out)
    out = out.drop_duplicates(subset=["timestamp"], keep="first")
    dropped = before - len(out)
    if dropped:
        print(f"Dropped {dropped} duplicate-timestamp rows (DST repeats)")
    return out.reset_index(drop=True)


def load_time_series(input_file: Path, tz: str = "UTC") -> pd.DataFrame:
    raw = load_raw_file(input_file)
    standardized = standardize_columns(raw)
    cleaned = clean_dataframe(standardized, tz)
    return cleaned
