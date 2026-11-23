#!/usr/bin/env python3
"""
orb_generator.py

Classic Opening Range Breakout, adapted to trigger off Renko bricks
instead of a time-based chart.

Per your broker clock check (broker showed 00:02 while your own clock
showed 5:02 PM EST), this broker's server clock runs 7 hours ahead of
US Eastern -- GMT+2 relative to real UTC (EST is UTC-5, so broker =
EST+7 = UTC+2, a common EET-based MT4 server default). So 9:30 AM New
York time is 16:30 on the broker-server timestamps this whole pipeline
already uses -- NEW_YORK_OPEN_HOUR_BROKER/_MINUTE below is that
converted value, not a literal "9:30" on these timestamps.

  1. Each calendar day, the opening range is the high/low of price
     during [16:30, 17:00) broker time (30 minutes = 9:30-10:00 AM New
     York), built from the M1 series (not the Renko bricks -- the range
     itself is a real time-window concept, Renko bars don't have a
     fixed time span).
  2. The range becomes "known" the moment that window closes (10:00).
  3. From 10:00 onward that SAME day, the first Renko brick that closes
     beyond the range (above range_high and itself a bull brick, or
     below range_low and itself a bear brick) arms a directional bias
     for the rest of that day. Unlike the 4H sweep bias (sticky across
     days until the opposite pattern fires), ORB's bias resets to
     neutral at the start of every new day -- yesterday's breakout has
     no bearing once a new range starts forming. Within a day, a later
     breakout in the OPPOSITE direction is allowed to flip the bias
     again (not locked to the first direction only), same flip
     discipline as the 4H sweep bias.
  4. A day with no M1 coverage of the opening-range window (gap/holiday)
     never gets a range, so that whole day stays neutral (no trading).
"""
from __future__ import annotations

import pandas as pd

BROKER_OFFSET_HOURS_FROM_EST = 7  # broker showed 00:02 vs your 5:02 PM EST
NEW_YORK_OPEN_HOUR_BROKER = (9 + BROKER_OFFSET_HOURS_FROM_EST) % 24  # 9:30 AM NY -> 16:30 broker time
NEW_YORK_OPEN_MINUTE_BROKER = 30


def compute_daily_opening_range(m1_df: pd.DataFrame, range_start_hour: int = NEW_YORK_OPEN_HOUR_BROKER,
                                 range_start_minute: int = NEW_YORK_OPEN_MINUTE_BROKER,
                                 range_minutes: int = 30) -> pd.DataFrame:
    ts = m1_df["timestamp"]
    start_total_min = range_start_hour * 60 + range_start_minute
    total_min = ts.dt.hour * 60 + ts.dt.minute
    in_window = (total_min >= start_total_min) & (total_min < start_total_min + range_minutes)

    windowed = m1_df.loc[in_window].copy()
    windowed["date"] = windowed["timestamp"].dt.date
    daily = windowed.groupby("date").agg(range_high=("high", "max"), range_low=("low", "min")).reset_index()

    tz = m1_df["timestamp"].dt.tz
    daily["range_known_at"] = (
        pd.to_datetime(daily["date"]).dt.tz_localize(tz)
        + pd.Timedelta(hours=range_start_hour, minutes=range_start_minute + range_minutes)
    )
    return daily


def compute_orb_bias(renko_df: pd.DataFrame, m1_df: pd.DataFrame, range_start_hour: int = NEW_YORK_OPEN_HOUR_BROKER,
                      range_start_minute: int = NEW_YORK_OPEN_MINUTE_BROKER, range_minutes: int = 30) -> pd.DataFrame:
    daily = compute_daily_opening_range(m1_df, range_start_hour, range_start_minute, range_minutes)
    ranges_by_date = {
        row.date: (row.range_high, row.range_low, row.range_known_at)
        for row in daily.itertuples()
    }

    renko_sorted = renko_df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    bias_out = [0] * len(renko_sorted)

    current_date = None
    bias = 0
    range_high = range_low = range_known_at = None

    for i, row in enumerate(renko_sorted.itertuples()):
        ts = row.timestamp
        d = ts.date()
        if d != current_date:
            current_date = d
            bias = 0  # new day -- yesterday's breakout bias doesn't carry over
            entry = ranges_by_date.get(d)
            if entry is not None:
                range_high, range_low, range_known_at = entry
            else:
                range_high = range_low = range_known_at = None

        if range_known_at is not None and ts >= range_known_at:
            is_bull_brick = row.close > row.open
            is_bear_brick = row.close < row.open
            if row.close > range_high and is_bull_brick:
                bias = 1
            elif row.close < range_low and is_bear_brick:
                bias = -1

        bias_out[i] = bias

    renko_sorted["orb_bias"] = bias_out
    return renko_sorted
