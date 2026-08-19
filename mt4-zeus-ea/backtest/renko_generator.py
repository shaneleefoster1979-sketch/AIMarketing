#!/usr/bin/env python3
"""
renko_generator.py

Builds 20-pip Renko bricks from a clean M1 `timestamp, close` series using
the sequential close-price method: whenever the latest close has moved at
least one brick_size away from the last brick's close, emit that many new,
uniformly-sized bricks (a bar that jumps more than one brick_size emits
multiple bricks, all stamped with that bar's timestamp). Every brick is
wickless by construction: high = max(open, close), low = min(open, close).

USDJPY pip = 0.01 (2nd decimal). 20 pips = 0.20 price units.
"""

from __future__ import annotations

import pandas as pd

RENKO_COLUMNS = ["timestamp", "open", "high", "low", "close"]

PIP_SIZE_USDJPY = 0.01
BRICK_SIZE_PIPS = 20.0
DECIMALS = 3


def generate_renko_bricks(df: pd.DataFrame, brick_size: float, decimals: int = DECIMALS) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=RENKO_COLUMNS)

    bricks = []
    last_close = round(float(df.iloc[0]["close"]), decimals)

    for row in df.itertuples(index=False):
        price = float(row.close)
        diff = price - last_close
        num_bricks = int(abs(diff) // brick_size)
        if num_bricks == 0:
            continue

        direction = 1 if diff > 0 else -1
        for _ in range(num_bricks):
            brick_open = last_close
            brick_close = round(last_close + direction * brick_size, decimals)
            bricks.append({
                "timestamp": row.timestamp,
                "open": brick_open,
                "high": max(brick_open, brick_close),
                "low": min(brick_open, brick_close),
                "close": brick_close,
            })
            last_close = brick_close

    return pd.DataFrame(bricks, columns=RENKO_COLUMNS)
