#!/usr/bin/env python3
"""
rmc_generator.py

Faithful port of Renko_Momentum_Cycle.mq4's CalcRMC (brick-run analysis +
adaptive-period RSI + momentum-decay), computed offline over a full Renko
brick history instead of per-tick in MT4. Same formulas Zeus.mq4 itself
uses (RMC_GetBrickRun/RMC_EstimateCycleLength/RMC_GetMomentumDecay), so
this reproduces exactly what the live EA reads.

MT4's arrays index 0 = newest bar, increasing index = older. This module
works in normal ascending-chronological order instead, so every "look at
k=i, i+1, i+2... (older)" loop in the original becomes "look at k=pos,
pos-1, pos-2... (backward in time)" here -- same relative direction,
translated indexing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_RUN_LENGTH = 2
MAX_RUN_LOOKBACK = 10
RSI_MIN_PERIOD = 7
RSI_MAX_PERIOD = 21
CYCLE_MEMORY = 5


def attach_brick_volume(renko_df: pd.DataFrame, raw_df: pd.DataFrame) -> pd.DataFrame:
    """Sums raw M1 volume falling into each brick's (prev_brick_ts, this_brick_ts]
    window and attaches it as a 'volume' column."""
    raw = raw_df[["timestamp", "volume"]].sort_values("timestamp", kind="stable").reset_index(drop=True)
    raw_cum = raw.copy()
    raw_cum["cum_vol"] = raw_cum["volume"].cumsum()

    renko = renko_df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    merged = pd.merge_asof(renko[["timestamp"]], raw_cum[["timestamp", "cum_vol"]], on="timestamp", direction="backward")
    cum_at_boundary = merged["cum_vol"].fillna(0.0).to_numpy()

    prev_cum = np.concatenate([[0.0], cum_at_boundary[:-1]])
    renko = renko.reset_index(drop=True)
    renko["volume"] = np.maximum(cum_at_boundary - prev_cum, 0.0)
    return renko


def wilder_rsi(closes: pd.Series, period: int) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0)
    return rsi


def compute_rmc(df: pd.DataFrame) -> pd.DataFrame:
    out = df.reset_index(drop=True).copy()
    n = len(out)
    close = out["close"].to_numpy()
    open_ = out["open"].to_numpy()
    volume = out["volume"].to_numpy(dtype=float)
    brick_up = close > open_  # Renko bricks always move; no flat bars

    rsi_by_period = {
        p: wilder_rsi(out["close"], p).to_numpy() for p in range(RSI_MIN_PERIOD, RSI_MAX_PERIOD + 1)
    }

    rmc = np.full(n, np.nan)

    for pos in range(n):
        if pos < RSI_MAX_PERIOD * 3:
            continue  # insufficient warm-up history

        # --- GetBrickRun ---
        is_up = brick_up[pos]
        count = 0
        run_vol = 0.0
        k = pos
        while k >= 0 and count < MAX_RUN_LOOKBACK:
            if brick_up[k] != is_up:
                break
            count += 1
            run_vol += volume[k]
            k -= 1
        run = count if is_up else -count
        if abs(run) < MIN_RUN_LENGTH:
            continue

        # --- EstimateCycleLength ---
        run_count = 0
        total_len = 0
        k = pos
        last_dir = brick_up[pos]
        run_len = 0
        while k >= 0 and run_count < CYCLE_MEMORY * 2:
            k_up = brick_up[k]
            if k_up == last_dir:
                run_len += 1
            else:
                if run_len >= MIN_RUN_LENGTH:
                    total_len += run_len
                    run_count += 1
                last_dir = k_up
                run_len = 1
            k -= 1
        if run_count == 0:
            rsi_period = (RSI_MIN_PERIOD + RSI_MAX_PERIOD) // 2
        else:
            avg_run = total_len / run_count
            rsi_period = int(round(avg_run * 2))
            rsi_period = max(RSI_MIN_PERIOD, min(RSI_MAX_PERIOD, rsi_period))

        rsi = rsi_by_period[rsi_period][pos]
        if np.isnan(rsi):
            continue
        rsi_norm = (rsi - 50.0) / 50.0

        # --- GetMomentumDecay ---
        cur_dir = brick_up[pos]
        cur_vol = 0.0
        cur_len = 0
        k = pos
        while k >= 0:
            if brick_up[k] != cur_dir:
                break
            cur_len += 1
            cur_vol += volume[k]
            k -= 1
        k2 = pos - cur_len
        opp_dir = not cur_dir
        while k2 >= 0 and brick_up[k2] == opp_dir:
            k2 -= 1
        prev_vol = 0.0
        prev_len = 0
        k = k2
        while k >= 0:
            if brick_up[k] != cur_dir:
                break
            prev_len += 1
            prev_vol += volume[k]
            k -= 1
        if prev_len == 0 or prev_vol == 0:
            decay = 1.0
        else:
            len_ratio = cur_len / prev_len
            vol_ratio = (cur_vol / cur_len) / (prev_vol / prev_len)
            decay = min(len_ratio * 0.5 + vol_ratio * 0.5, 1.5)

        run_strength = min(abs(run), MAX_RUN_LOOKBACK)
        run_norm = run_strength / MAX_RUN_LOOKBACK
        if run < 0:
            run_norm = -run_norm

        avg_vol = 0.0
        v_cnt = 0
        k = pos
        while k > pos - rsi_period and k >= 0:
            avg_vol += volume[k]
            v_cnt += 1
            k -= 1
        if v_cnt > 0:
            avg_vol /= v_cnt
        if avg_vol > 0 and abs(run) > 0:
            vol_norm = min((run_vol / abs(run)) / avg_vol, 2.0)
        else:
            vol_norm = 1.0
        vol_norm = (vol_norm - 1.0) * 0.3 + 1.0

        val = (rsi_norm * 0.5 + run_norm * 0.35 + (vol_norm - 1.0) * 0.15) * min(decay, 1.0)
        rmc[pos] = max(-1.0, min(1.0, val))

    out["rmc_value"] = rmc
    return out
