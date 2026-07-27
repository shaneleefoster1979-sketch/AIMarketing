#!/usr/bin/env python3
"""
data_ingestion.py

Builds a standardized training baseline from raw MT4 historical exports.

MT4 has no native Python API, so historical bars are exported from the
platform's History Center as CSV and dropped into a folder (e.g. data/raw/).
This script scans that folder for Daily (D1) and 4-Hour (H4) OHLCV files for
EURUSD and GBPUSD, normalizes each file to a common
`timestamp, open, high, low, close, volume` schema, validates and repairs
the timestamp index, and writes a single combined baseline to
data/processed/clean_history.csv.

Usage:
    python data_ingestion.py
    python data_ingestion.py --input-dir data/raw --output data/processed/clean_history.csv
    python data_ingestion.py --symbols EURUSD GBPUSD --timeframes D1 H4
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("data_ingestion")

# MT4 History Center exports use numeric period codes in filenames
# (e.g. EURUSD1440.csv) as well as human-readable ones (EURUSD_D1.csv).
TIMEFRAME_ALIASES = {
    "D1": {"D1", "1440"},
    "H4": {"H4", "240"},
}

# Expected bar spacing per timeframe, used to detect and repair gaps.
TIMEFRAME_FREQ = {
    "D1": "1D",
    "H4": "4h",
}

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def find_symbol_timeframe(filename: str, symbols: list[str], timeframes: list[str]) -> tuple[str, str] | None:
    """Infer (symbol, timeframe) from an MT4 export filename.

    Handles both `EURUSD_D1.csv` / `EURUSD-H4.csv` style names and the raw
    MT4 History Center convention `EURUSD1440.csv` (period in minutes).
    """
    name = filename.upper()

    symbol = next((s for s in symbols if s.upper() in name), None)
    if symbol is None:
        return None

    for tf in timeframes:
        aliases = TIMEFRAME_ALIASES.get(tf.upper(), {tf.upper()})
        for alias in aliases:
            if re.search(rf"(?<!\d){alias}(?!\d)", name):
                return symbol.upper(), tf.upper()

    return None


def load_raw_file(path: Path) -> pd.DataFrame:
    """Load an MT4 CSV export into a raw DataFrame, tolerant of the export's
    quirks: optional header row, comma or semicolon delimiter, and either a
    combined datetime column or separate Date/Time columns.
    """
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        first_line = f.readline()

    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    has_header = bool(re.search(r"[A-Za-z]", first_line))

    raw = pd.read_csv(
        path,
        delimiter=delimiter,
        header=0 if has_header else None,
        dtype=str,
        skip_blank_lines=True,
    )
    raw.columns = [str(c).strip().lower() for c in raw.columns]
    return raw


def standardize_columns(raw: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Map an arbitrarily-shaped raw MT4 frame onto the canonical schema."""
    df = raw.copy()

    # Positional MT4 History Center export with no header:
    # date, time, open, high, low, close, volume
    if all(str(c).isdigit() for c in df.columns):
        n = df.shape[1]
        if n == 7:
            df.columns = ["date", "time", "open", "high", "low", "close", "volume"]
        elif n == 6:
            df.columns = ["date", "open", "high", "low", "close", "volume"]
        else:
            raise ValueError(f"{path.name}: unrecognized column layout ({n} columns)")

    rename_map = {
        "datetime": "timestamp",
        "date/time": "timestamp",
        "time": "_time",
        "date": "_date",
        "vol": "volume",
        "tickvol": "volume",
        "tick_volume": "volume",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    if "timestamp" not in df.columns:
        if "_date" in df.columns and "_time" in df.columns:
            df["timestamp"] = df["_date"].astype(str).str.strip() + " " + df["_time"].astype(str).str.strip()
        elif "_date" in df.columns:
            df["timestamp"] = df["_date"].astype(str).str.strip()
        else:
            raise ValueError(f"{path.name}: could not locate a date/time column")

    if "volume" not in df.columns:
        df["volume"] = 0

    missing = [c for c in ["timestamp", "open", "high", "low", "close", "volume"] if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing required column(s) {missing}")

    df = df[REQUIRED_COLUMNS].copy()
    return df


def clean_dataframe(df: pd.DataFrame, path: Path, tz: str | None) -> pd.DataFrame:
    """Coerce types, localize timestamps, drop invalid/duplicate rows, sort."""
    df = df.copy()

    # MT4 exports dates as YYYY.MM.DD; let pandas infer the rest.
    df["timestamp"] = df["timestamp"].astype(str).str.replace(".", "-", regex=False)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=False)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    dropped_bad = before - len(df)
    if dropped_bad:
        logger.warning("%s: dropped %d row(s) with unparseable timestamp/price data", path.name, dropped_bad)

    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(
            tz or "UTC", ambiguous="NaT", nonexistent="NaT"
        )
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert(tz or "UTC")

    before = len(df)
    df = df.dropna(subset=["timestamp"])
    dropped_tz = before - len(df)
    if dropped_tz:
        logger.warning(
            "%s: dropped %d row(s) with ambiguous/nonexistent local timestamps (DST fold)",
            path.name, dropped_tz,
        )

    df["volume"] = df["volume"].fillna(0)

    before = len(df)
    df = df.drop_duplicates(subset=["timestamp"], keep="last")
    dropped_dupes = before - len(df)
    if dropped_dupes:
        logger.warning("%s: dropped %d duplicate timestamp row(s)", path.name, dropped_dupes)

    before = len(df)
    sane = (df["high"] >= df["low"]) & (df["high"] >= df["open"]) & (df["high"] >= df["close"]) \
        & (df["low"] <= df["open"]) & (df["low"] <= df["close"])
    df = df[sane]
    dropped_insane = before - len(df)
    if dropped_insane:
        logger.warning("%s: dropped %d row(s) failing OHLC sanity checks (high/low bounds)", path.name, dropped_insane)

    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def fill_gaps(df: pd.DataFrame, timeframe: str, path: Path) -> pd.DataFrame:
    """Reindex onto the expected bar grid for the timeframe and repair gaps.

    Forex is closed on weekends, so a business-day/H4-on-business-day grid
    (not a naive calendar range) is used as the "expected" index — that way
    normal weekend closures are never mistaken for missing data. Any bar
    that's still missing inside that grid gets flat-filled (O=H=L=C=prior
    close, volume=0) and flagged via `is_filled` so downstream training code
    can drop or weight synthetic bars differently from real ones.
    """
    if df.empty:
        return df

    freq = TIMEFRAME_FREQ[timeframe]
    start, end = df["timestamp"].min(), df["timestamp"].max()

    if timeframe == "D1":
        expected = pd.date_range(start.normalize(), end.normalize(), freq="B", tz=df["timestamp"].dt.tz)
    else:  # H4 — 6 bars/day, business days only
        business_days = pd.date_range(start.normalize(), end.normalize(), freq="B", tz=df["timestamp"].dt.tz)
        expected = pd.DatetimeIndex(
            np.concatenate([
                pd.date_range(d, d + pd.Timedelta(hours=20), freq=freq).values
                for d in business_days
            ])
        ).tz_localize(None).tz_localize(df["timestamp"].dt.tz)
        expected = expected[(expected >= start) & (expected <= end)]

    df = df.set_index("timestamp")
    full = df.reindex(expected)
    n_missing = full["close"].isna().sum()

    if n_missing:
        logger.warning("%s: filling %d missing %s bar(s) via forward-fill", path.name, n_missing, timeframe)

    full["is_filled"] = full["close"].isna()
    prev_close = full["close"].ffill()
    for col in ["open", "high", "low", "close"]:
        full[col] = full[col].where(~full["is_filled"], prev_close)
    full["volume"] = full["volume"].where(~full["is_filled"], 0)

    full = full.dropna(subset=["close"])  # drop any leading gap with no prior bar to fill from
    full = full.reset_index().rename(columns={"index": "timestamp"})
    return full


def ingest(input_dir: Path, symbols: list[str], timeframes: list[str], tz: str | None) -> pd.DataFrame:
    files = sorted(p for p in input_dir.glob("*.csv") if p.is_file())
    if not files:
        raise FileNotFoundError(f"No CSV files found in {input_dir}")

    found: dict[tuple[str, str], Path] = {}
    for path in files:
        match = find_symbol_timeframe(path.name, symbols, timeframes)
        if match is None:
            logger.info("Skipping %s: filename doesn't match any expected symbol/timeframe", path.name)
            continue
        if match in found:
            logger.warning("Multiple files match %s %s (%s, %s) — using %s", *match, found[match].name, path.name, path.name)
        found[match] = path

    frames = []
    for symbol in symbols:
        for timeframe in timeframes:
            key = (symbol.upper(), timeframe.upper())
            path = found.get(key)
            if path is None:
                logger.warning("Missing expected file for %s %s — skipping", *key)
                continue

            logger.info("Loading %s %s from %s", *key, path.name)
            raw = load_raw_file(path)
            standardized = standardize_columns(raw, path)
            cleaned = clean_dataframe(standardized, path, tz)
            filled = fill_gaps(cleaned, timeframe.upper(), path)

            filled.insert(0, "symbol", symbol.upper())
            filled.insert(1, "timeframe", timeframe.upper())
            frames.append(filled)

            logger.info("%s %s: %d clean bars (%d filled)", *key, len(filled), int(filled["is_filled"].sum()))

    if not frames:
        raise RuntimeError("No matching symbol/timeframe files were successfully ingested")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(["symbol", "timeframe", "timestamp"]).reset_index(drop=True)
    return combined


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw"), help="Folder containing raw MT4 CSV exports")
    parser.add_argument("--output", type=Path, default=Path("data/processed/clean_history.csv"), help="Path to write the standardized baseline")
    parser.add_argument("--symbols", nargs="+", default=["EURUSD", "GBPUSD"], help="Symbols to ingest")
    parser.add_argument("--timeframes", nargs="+", default=["D1", "H4"], help="Timeframes to ingest")
    parser.add_argument("--tz", default="UTC", help="Timezone to localize naive MT4 timestamps to (default: UTC, i.e. treated as already UTC)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    combined = ingest(args.input_dir, args.symbols, args.timeframes, args.tz)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(args.output, index=False)

    logger.info("Wrote %d rows to %s", len(combined), args.output)
    summary = combined.groupby(["symbol", "timeframe"]).agg(
        bars=("timestamp", "count"),
        filled=("is_filled", "sum"),
        start=("timestamp", "min"),
        end=("timestamp", "max"),
    )
    logger.info("Summary:\n%s", summary.to_string())


if __name__ == "__main__":
    main()
