#!/usr/bin/env python3
"""
quota_environment.py

Dynamic-settings environment: Zeus's entry gate (RC+RMC dual-agreement,
brick direction match), 4-leg structure, weight split (20/25/25/30), and
3% total risk cap are unchanged and untouchable. What the agent now
controls, at each bar where Zeus's own gate would open a trade while
flat, is WHICH stop-loss distance and take-profit profile to use for that
trade -- position size is always recomputed so the total dollar risk
still equals exactly 3% of equity, split by the fixed weights, no matter
which stop distance is chosen. The agent cannot make a trade riskier than
Zeus's 3% cap allows; it can only change how that fixed risk is shaped
(tight/wide stops and targets) or skip the trade entirely.

Reward = actual realized P&L (as a fraction of pre-trade equity) from any
legs that close this bar, PLUS a skip-penalty that only fires when the
trailing-30-day equity return is below the quota target AND the agent
chose to skip a valid signal. No bonus for taking a trade of any
configuration -- only a cost for passing one up while behind pace.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from zeus_backtest import (
    ZEUS_WEIGHTS, ZEUS_TOTAL_RISK_PERCENT, ZEUS_MAX_LOTS_PER_TRADE,
    PIP_SIZE_USDJPY, pip_value_per_lot, rc_dir, rmc_dir,
    compute_rmc_confirmed_dir, _close_leg,
)

QUOTA_WINDOW_DAYS = 30
QUOTA_TARGET = 0.10
SKIP_PENALTY_ALPHA = 1.0

# The settings the agent may choose per trade. Position size is always
# recomputed to keep total risk at exactly 3% regardless of which of
# these is picked -- see get_lot_size_dynamic.
SL_CHOICES_PIPS = [40.0, 60.0, 80.0]
TP_PROFILES_PIPS = {
    "tight":    [40.0, 80.0, 120.0, None],
    "standard": [60.0, 120.0, 180.0, None],
    "wide":     [80.0, 160.0, 240.0, None],
}
TP_PROFILE_NAMES = list(TP_PROFILES_PIPS.keys())

N_CONTEXT_FEATURES = 0
N_SETTINGS_ACTIONS = len(SL_CHOICES_PIPS) * len(TP_PROFILE_NAMES)
N_ACTIONS = 1 + N_SETTINGS_ACTIONS  # action 0 = skip


def decode_action(action: int) -> tuple[float, list] | None:
    """Returns (sl_pips, tp_pips_list) for a take action, or None for skip."""
    if action == 0:
        return None
    idx = action - 1
    sl_idx, tp_idx = divmod(idx, len(TP_PROFILE_NAMES))
    return SL_CHOICES_PIPS[sl_idx], TP_PROFILES_PIPS[TP_PROFILE_NAMES[tp_idx]]


def get_lot_size_dynamic(equity: float, weight_pct: int, price: float, sl_pips: float) -> float:
    """Same 3%-of-equity risk formula as Zeus's own get_lot_size, but for
    an arbitrary chosen stop distance instead of the fixed 60 pips -- the
    dollar risk per leg stays pinned to equity * 3% * weight% no matter
    which stop the agent picks."""
    risk_dollars = equity * (ZEUS_TOTAL_RISK_PERCENT / 100.0) * (weight_pct / 100.0)
    lots = risk_dollars / (sl_pips * pip_value_per_lot(price))
    lots = min(lots, ZEUS_MAX_LOTS_PER_TRADE)
    return max(round(lots, 2), 0.01)


class QuotaEnv:
    def __init__(self, df: pd.DataFrame, starting_balance: float = 1000.0, spread_pips: float = 1.0):
        self.df = df.reset_index(drop=True)
        self.starting_balance = starting_balance
        self.spread_pips = spread_pips
        # Gated entry/exit direction (magnitude + 2-consecutive-bar sign-run,
        # matching live ZeusAI.mq4 exactly). The DQN's own _obs() feature
        # stays on the raw rmc_value, unaffected -- unchanged from training.
        self.rmc_confirmed = compute_rmc_confirmed_dir(self.df["rmc_value"])

    def reset(self):
        self.i = 0
        self.equity = self.starting_balance
        self.slots: list[dict | None] = [None, None, None, None]
        self.t1_was_open = False
        self.breakeven_triggered = False
        self.trade_log: list[dict] = []
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
        return np.array([
            row["rc_value"],
            row["rmc_value"] if not pd.isna(row["rmc_value"]) else 0.0,
            trailing_ret - QUOTA_TARGET,          # ahead(+)/behind(-) pace
            np.log(max(self.equity, 1.0) / self.starting_balance),
            1.0 if any(s is not None for s in self.slots) else 0.0,
        ], dtype=np.float32)

    def _manage_open_legs(self, row) -> float:
        close, open_ = float(row["close"]), float(row["open"])
        ts = row["timestamp"]
        brick_dir = 1 if close > open_ else -1
        rc = rc_dir(row["rc_value"])
        # Magnitude-only for the RC-flip exit -- NOT the strict entry gate.
        # See zeus_backtest.py's run_zeus_backtest step 4 for why: the
        # stricter sign-run gate delays this exit and backtested as a real
        # regression (more trades riding to their stop instead of getting
        # out early on a genuine reversal).
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

    def _open_trade(self, row, entry_dir: int, sl_pips: float, tp_pips_list: list) -> None:
        close, ts = float(row["close"]), row["timestamp"]
        for idx, (weight, tp_pips) in enumerate(zip(ZEUS_WEIGHTS, tp_pips_list)):
            lots = get_lot_size_dynamic(self.equity, weight, close, sl_pips)
            stop = close - entry_dir * sl_pips * PIP_SIZE_USDJPY
            target = (close + entry_dir * tp_pips * PIP_SIZE_USDJPY) if tp_pips is not None else None
            self.slots[idx] = {
                "label": f"T{idx + 1}", "direction": entry_dir, "entry_price": close,
                "entry_timestamp": ts, "lots": lots, "stop": stop, "target": target,
            }
        self.t1_was_open = True
        self.breakeven_triggered = False

    def _advance_to_next_decision(self):
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
                rmc = int(self.rmc_confirmed[self.i])
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
        """action 0 = skip. actions 1..N_SETTINGS_ACTIONS = take, using the
        (sl_pips, tp_profile) combination decode_action(action) selects --
        sized so total risk is still exactly 3%, whichever combination."""
        row = self.df.iloc[self.i]
        trailing_ret = self._trailing_30d_return(row["timestamp"])
        behind_pace = max(0.0, QUOTA_TARGET - trailing_ret)

        settings = decode_action(action)
        if settings is not None:
            sl_pips, tp_pips_list = settings
            equity_before = self.equity
            self._open_trade(row, self._pending_entry_dir, sl_pips, tp_pips_list)
            self.i += 1
            obs, done, pnl_accum = self._advance_to_next_decision()
            reward = pnl_accum / equity_before if equity_before > 0 else 0.0
        else:
            self.i += 1
            obs, done, pnl_accum = self._advance_to_next_decision()
            equity_ref = self.equity if self.equity > 0 else 1.0
            reward = (pnl_accum / equity_ref) - SKIP_PENALTY_ALPHA * behind_pace

        return obs, reward, done, {"equity": self.equity, "trade_log": self.trade_log}
