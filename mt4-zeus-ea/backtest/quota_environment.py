#!/usr/bin/env python3
"""
quota_environment.py

Take-or-skip environment: Zeus's own rules (RC+RMC dual-agreement gate,
4-leg 20/25/25/30 sizing, 60-pip stop, 60/120/180/none targets, 3% total
risk, 50-lot cap, break-even-on-T1-close) are completely unchanged and
untouchable by the agent. The ONLY decision the agent makes is, at each
bar where Zeus's own rule would open a trade while flat: take it, or skip
it. All position sizing, stops, and targets for a taken trade are exactly
what Zeus would use -- the agent cannot make a taken trade bigger or
riskier than Zeus already allows.

Reward = actual realized P&L (as a fraction of pre-trade equity, so the
network sees a stable scale) from any legs that close this bar, PLUS a
skip-penalty that only fires when the trailing-30-day equity return is
below the quota target AND the agent chose to skip a valid signal. There
is no bonus for taking a trade -- only a cost for passing one up while
behind pace -- so the agent can't "fake" progress by taking bad trades;
every trade it does take still lives or dies on Zeus's own SL/TP.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from zeus_backtest import (
    ZEUS_WEIGHTS, ZEUS_TP_PIPS, ZEUS_STOP_LOSS_PIPS, PIP_SIZE_USDJPY,
    rc_dir, rmc_dir, get_lot_size, _close_leg,
)

QUOTA_WINDOW_DAYS = 30
QUOTA_TARGET = 0.10
SKIP_PENALTY_ALPHA = 1.0  # scales the behind-pace skip penalty; tuned empirically

MOMENTUM_RUN_CAP = 10  # same cap RMC itself uses for run length

# Approximate major FX session hours, UTC, ignoring DST (a reasonable
# approximation for a feature -- the boundaries shift by ~1hr twice a year,
# not worth the added complexity of a real DST calendar here).
SESSION_HOURS_UTC = {
    "sydney":    (22, 7),   # wraps midnight
    "tokyo":     (0, 9),
    "london":    (8, 17),
    "new_york":  (13, 22),
}


def _hour_in_session(hour: np.ndarray, start: int, end: int) -> np.ndarray:
    if start < end:
        return (hour >= start) & (hour < end)
    return (hour >= start) | (hour < end)  # wraps midnight (Sydney)


def compute_context_features(df: pd.DataFrame) -> np.ndarray:
    """Momentum (signed run length), volatility (brick formation speed),
    time-of-day (cyclic), and session-overlap features -- all computed
    once up front, purely from data Zeus's own rules don't already use."""
    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy()
    ts = pd.to_datetime(df["timestamp"])
    n = len(df)

    brick_up = close > open_
    # Signed run length ending at each position (same run-length logic RMC
    # uses internally, exposed here as its own raw feature).
    run_id = (brick_up != np.roll(brick_up, 1))
    run_id[0] = True
    run_id = np.cumsum(run_id)
    run_len = pd.Series(run_id).groupby(run_id).cumcount().to_numpy() + 1
    run_len = np.minimum(run_len, MOMENTUM_RUN_CAP)
    momentum = np.where(brick_up, run_len, -run_len) / MOMENTUM_RUN_CAP

    # Brick formation speed: minutes since the previous brick closed.
    # Fast bricks (short duration) = high volatility; slow = low volatility.
    minutes = ts.diff().dt.total_seconds().to_numpy() / 60.0
    minutes[0] = np.nanmedian(minutes[1:]) if n > 1 else 1.0
    minutes = np.nan_to_num(minutes, nan=1.0)
    volatility = -np.log1p(np.clip(minutes, 0, None))  # higher = faster = more volatile
    volatility = (volatility - volatility.mean()) / (volatility.std() + 1e-9)

    hour = ts.dt.hour.to_numpy()
    hour_sin = np.sin(2 * np.pi * hour / 24.0)
    hour_cos = np.cos(2 * np.pi * hour / 24.0)

    session_flags = {}
    for name, (start, end) in SESSION_HOURS_UTC.items():
        session_flags[name] = _hour_in_session(hour, start, end).astype(np.float32)
    n_active = sum(session_flags.values())

    return np.column_stack([
        momentum, volatility, hour_sin, hour_cos,
        session_flags["sydney"], session_flags["tokyo"],
        session_flags["london"], session_flags["new_york"],
        n_active,
    ]).astype(np.float32)


N_CONTEXT_FEATURES = 9


class QuotaEnv:
    def __init__(self, df: pd.DataFrame, starting_balance: float = 1000.0, spread_pips: float = 1.0):
        self.df = df.reset_index(drop=True)
        self.starting_balance = starting_balance
        self.spread_pips = spread_pips
        self.context = compute_context_features(self.df)

    def reset(self):
        self.i = 0
        self.equity = self.starting_balance
        self.slots: list[dict | None] = [None, None, None, None]
        self.t1_was_open = False
        self.breakeven_triggered = False
        self.trade_log: list[dict] = []
        # (timestamp, equity) history for the trailing-30-day lookup
        self.equity_history: list[tuple] = [(self.df.iloc[0]["timestamp"], self.equity)]
        obs, done, _ = self._advance_to_next_decision()
        self._done_immediately = done
        return obs

    def _trailing_30d_return(self, now_ts) -> float:
        cutoff = now_ts - pd.Timedelta(days=QUOTA_WINDOW_DAYS)
        past_equity = self.starting_balance
        for ts, eq in reversed(self.equity_history):
            if ts <= cutoff:
                past_equity = eq
                break
        else:
            past_equity = self.equity_history[0][1]
        if past_equity <= 0:
            return 0.0
        return self.equity / past_equity - 1.0

    def _obs(self, row) -> np.ndarray:
        trailing_ret = self._trailing_30d_return(row["timestamp"])
        base = np.array([
            row["rc_value"],
            row["rmc_value"] if not pd.isna(row["rmc_value"]) else 0.0,
            trailing_ret - QUOTA_TARGET,          # ahead(+)/behind(-) pace
            np.log(max(self.equity, 1.0) / self.starting_balance),
            1.0 if any(s is not None for s in self.slots) else 0.0,
        ], dtype=np.float32)
        return np.concatenate([base, self.context[self.i]])

    def _manage_open_legs(self, row) -> float:
        """Runs Zeus's exact VSL/break-even/VTP/RC-flip-exit logic for one
        bar. Returns this bar's realized P&L (0.0 if nothing closed)."""
        close, open_ = float(row["close"]), float(row["open"])
        ts = row["timestamp"]
        brick_dir = 1 if close > open_ else -1
        rc = rc_dir(row["rc_value"])
        rmc = rmc_dir(row["rmc_value"])
        pnl_this_bar = 0.0

        for idx, leg in enumerate(self.slots):
            if leg is None:
                continue
            hit = (leg["direction"] == 1 and close <= leg["stop"]) or (leg["direction"] == -1 and close >= leg["stop"])
            if hit:
                pnl, record = _close_leg(leg, close, ts, "stop", self.spread_pips)
                self.equity += pnl
                pnl_this_bar += pnl
                self.trade_log.append(record)
                self.slots[idx] = None

        if self.t1_was_open and not self.breakeven_triggered:
            if not any(s is not None and s["label"] == "T1" for s in self.slots):
                for leg in self.slots:
                    if leg is not None:
                        leg["stop"] = leg["entry_price"]
                self.breakeven_triggered = True
                self.t1_was_open = False

        for idx, leg in enumerate(self.slots):
            if leg is None or leg["target"] is None:
                continue
            hit = (leg["direction"] == 1 and close >= leg["target"]) or (leg["direction"] == -1 and close <= leg["target"])
            if hit:
                pnl, record = _close_leg(leg, close, ts, "target", self.spread_pips)
                self.equity += pnl
                pnl_this_bar += pnl
                self.trade_log.append(record)
                self.slots[idx] = None

        if any(s is not None for s in self.slots):
            for idx, leg in enumerate(self.slots):
                if leg is None:
                    continue
                flip = (leg["direction"] == 1 and rc < 0) or (leg["direction"] == -1 and rc > 0)
                if not flip:
                    continue
                if leg["direction"] == 1 and brick_dir != -1:
                    continue
                if leg["direction"] == -1 and brick_dir != 1:
                    continue
                if rmc == 0:
                    continue
                if leg["direction"] == 1 and rmc != -1:
                    continue
                if leg["direction"] == -1 and rmc != 1:
                    continue
                pnl, record = _close_leg(leg, close, ts, "rc_exit", self.spread_pips)
                self.equity += pnl
                pnl_this_bar += pnl
                self.trade_log.append(record)
                self.slots[idx] = None

        if all(s is None for s in self.slots):
            self.breakeven_triggered = False
            self.t1_was_open = False

        return pnl_this_bar

    def _open_trade(self, row, entry_dir: int) -> None:
        close, ts = float(row["close"]), row["timestamp"]
        for idx, (weight, tp_pips) in enumerate(zip(ZEUS_WEIGHTS, ZEUS_TP_PIPS)):
            lots = get_lot_size(self.equity, weight, close)
            stop = close - entry_dir * ZEUS_STOP_LOSS_PIPS * PIP_SIZE_USDJPY
            target = (close + entry_dir * tp_pips * PIP_SIZE_USDJPY) if tp_pips is not None else None
            self.slots[idx] = {
                "label": f"T{idx + 1}", "direction": entry_dir, "entry_price": close,
                "entry_timestamp": ts, "lots": lots, "stop": stop, "target": target,
            }
        self.t1_was_open = True
        self.breakeven_triggered = False

    def _advance_to_next_decision(self):
        """Runs management-only bars until either the data runs out or a
        flat bar with a valid Zeus signal is reached (a real decision
        point). Returns (obs, done, pnl_accum_while_fast_forwarding)."""
        pnl_accum = 0.0
        while self.i < len(self.df):
            row = self.df.iloc[self.i]
            pnl_accum += self._manage_open_legs(row)
            self.equity_history.append((row["timestamp"], self.equity))

            flat = all(s is None for s in self.slots)
            if flat:
                close, open_ = float(row["close"]), float(row["open"])
                brick_dir = 1 if close > open_ else -1
                rc = rc_dir(row["rc_value"])
                rmc = rmc_dir(row["rmc_value"])
                entry_dir = 0
                if rc < 0 and rmc == -1:
                    entry_dir = -1
                elif rc > 0 and rmc == 1:
                    entry_dir = 1
                if entry_dir != 0 and brick_dir == entry_dir:
                    self._pending_entry_dir = entry_dir
                    return self._obs(row), False, pnl_accum
            self.i += 1
        return None, True, pnl_accum

    def step(self, action: int):
        """action: 0 = skip the pending signal, 1 = take it (Zeus sizing/SL/TP)."""
        row = self.df.iloc[self.i]
        trailing_ret = self._trailing_30d_return(row["timestamp"])
        behind_pace = max(0.0, QUOTA_TARGET - trailing_ret)

        pnl_pct_before = 0.0
        if action == 1:
            equity_before = self.equity
            self._open_trade(row, self._pending_entry_dir)
            self.i += 1
            obs, done, pnl_accum = self._advance_to_next_decision()
            pnl_pct_before = pnl_accum / equity_before if equity_before > 0 else 0.0
            reward = pnl_pct_before
        else:
            self.i += 1
            obs, done, pnl_accum = self._advance_to_next_decision()
            equity_ref = self.equity if self.equity > 0 else 1.0
            reward = (pnl_accum / equity_ref) - SKIP_PENALTY_ALPHA * behind_pace

        return obs, reward, done, {"equity": self.equity, "trade_log": self.trade_log}
