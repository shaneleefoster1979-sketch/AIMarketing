#!/usr/bin/env python3
"""
wick_reversal_generator.py

Direct Python port of RenkoWickReversal.mq4's arrow logic, for backtest
use. Operates on ascending-chronological rows (oldest first), same
convention as every other generator in this project -- "previous brick"
is row k-1, not k+1 (the MQL4 file's shift convention is reversed, 0 =
newest).

  Buy arrow : brick k is a buy brick (Close > Open), the previous brick
              (k-1) was a sell brick (Close < Open), AND brick k's Low
              wicked below that previous sell brick's Close.
  Sell arrow: brick k is a sell brick, the previous brick was a buy
              brick, AND brick k's High wicked above that previous buy
              brick's Close.
"""
from __future__ import annotations

import pandas as pd


def compute_wick_reversal(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy()
    low = df["low"].to_numpy()
    high = df["high"].to_numpy()
    n = len(df)

    buy_arrow = [False] * n
    sell_arrow = [False] * n

    for k in range(1, n):
        is_buy_brick = close[k] > open_[k]
        is_sell_brick = close[k] < open_[k]
        prev_was_sell = close[k - 1] < open_[k - 1]
        prev_was_buy = close[k - 1] > open_[k - 1]

        if is_buy_brick and prev_was_sell and low[k] < close[k - 1]:
            buy_arrow[k] = True
        if is_sell_brick and prev_was_buy and high[k] > close[k - 1]:
            sell_arrow[k] = True

    out = df.copy()
    out["wick_buy_arrow"] = buy_arrow
    out["wick_sell_arrow"] = sell_arrow
    return out
