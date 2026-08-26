#!/usr/bin/env python3
"""
train_quota_agent.py

Trains a small DQN on QuotaEnv's take-or-skip decision: same Zeus rules,
same sizing, same SL/TP -- the only thing learned is whether to act on a
signal Zeus's own gate already validated, shaped toward a trailing-30-day
10% target without ever rewarding a bad trade for "trying." Walk-forward
on dev (85%), one-touch lockbox at the end, exactly like every other
sweep in this project.
"""

from __future__ import annotations

import random
from collections import deque

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim

from quota_environment import QuotaEnv

OBS_DIM = 5
N_ACTIONS = 2
GAMMA = 0.95
LR = 1e-3
BATCH_SIZE = 64
REPLAY_CAPACITY = 20_000
TARGET_SYNC_EVERY = 500
EPS_START, EPS_END, EPS_DECAY_STEPS = 1.0, 0.05, 20_000


class QNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(OBS_DIM, 64), nn.ReLU(),
            nn.Linear(64, 64), nn.ReLU(),
            nn.Linear(64, N_ACTIONS),
        )

    def forward(self, x):
        return self.net(x)


def train_dqn(df: pd.DataFrame, n_episodes: int, seed: int = 0) -> QNet:
    torch.manual_seed(seed)
    random.seed(seed)
    np.random.seed(seed)

    policy = QNet()
    target = QNet()
    target.load_state_dict(policy.state_dict())
    opt = optim.Adam(policy.parameters(), lr=LR)
    replay = deque(maxlen=REPLAY_CAPACITY)

    step_count = 0
    for ep in range(n_episodes):
        env = QuotaEnv(df)
        obs = env.reset()
        done = env._done_immediately
        while not done:
            eps = max(EPS_END, EPS_START - step_count / EPS_DECAY_STEPS * (EPS_START - EPS_END))
            if random.random() < eps:
                action = random.randint(0, N_ACTIONS - 1)
            else:
                with torch.no_grad():
                    q = policy(torch.tensor(obs).unsqueeze(0))
                    action = int(q.argmax(dim=1).item())

            next_obs, reward, done, _ = env.step(action)
            replay.append((obs, action, reward, next_obs, done))
            obs = next_obs if next_obs is not None else obs
            step_count += 1

            if len(replay) >= BATCH_SIZE:
                batch = random.sample(replay, BATCH_SIZE)
                obs_b = torch.tensor(np.array([b[0] for b in batch], dtype=np.float32))
                act_b = torch.tensor([b[1] for b in batch]).long()
                rew_b = torch.tensor([b[2] for b in batch]).float()
                next_b = torch.tensor(np.array(
                    [b[3] if b[3] is not None else np.zeros(OBS_DIM, dtype=np.float32) for b in batch],
                    dtype=np.float32,
                ))
                done_b = torch.tensor([b[4] for b in batch]).float()

                q_vals = policy(obs_b).gather(1, act_b.unsqueeze(1)).squeeze(1)
                with torch.no_grad():
                    next_q = target(next_b).max(dim=1).values
                    target_vals = rew_b + GAMMA * next_q * (1 - done_b)
                loss = nn.functional.smooth_l1_loss(q_vals, target_vals)
                opt.zero_grad()
                loss.backward()
                opt.step()

                if step_count % TARGET_SYNC_EVERY == 0:
                    target.load_state_dict(policy.state_dict())

        if (ep + 1) % 5 == 0:
            print(f"  episode {ep+1}/{n_episodes}  ending_equity=${env.equity:,.2f}  trades={len(env.trade_log)}  eps={eps:.3f}")

    return policy


def evaluate(policy: QNet, df: pd.DataFrame) -> dict:
    env = QuotaEnv(df)
    obs = env.reset()
    done = False
    n_skipped = 0
    n_taken = 0
    while not done:
        with torch.no_grad():
            q = policy(torch.tensor(obs).unsqueeze(0))
            action = int(q.argmax(dim=1).item())
        if action == 1:
            n_taken += 1
        else:
            n_skipped += 1
        obs, reward, done, info = env.step(action)
    tl = info["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    return {
        "trades": len(tl), "win_rate": wins / len(tl) * 100 if tl else float("nan"),
        "ending_equity": info["equity"], "signals_taken": n_taken, "signals_skipped": n_skipped,
    }


if __name__ == "__main__":
    renko = pd.read_csv("data/processed/renko_usdjpy.csv")
    renko["timestamp"] = pd.to_datetime(renko["timestamp"], utc=True)
    usable = renko.dropna(subset=["rc_value"]).reset_index(drop=True)

    n = len(usable)
    split = int(n * 0.85)
    dev = usable.iloc[:split].reset_index(drop=True)
    lockbox = usable.iloc[split:].reset_index(drop=True)
    print(f"dev: {len(dev)} bricks | lockbox: {len(lockbox)} bricks (untouched)")

    print("\nTraining quota-shaped DQN on dev...")
    policy = train_dqn(dev, n_episodes=30, seed=0)

    print("\n=== DEV evaluation (greedy policy) ===")
    print(evaluate(policy, dev))

    print("\n=== LOCKBOX evaluation (one-touch) ===")
    print(evaluate(policy, lockbox))

    print("\n=== Baseline: always-take (== current Zeus exactly), for comparison ===")
    import zeus_backtest as zb
    r_dev = zb.run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0)
    r_lb = zb.run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0)
    print(f"dev:     trades={len(r_dev['trade_log'])}  ending=${r_dev['ending_equity']:,.2f}")
    print(f"lockbox: trades={len(r_lb['trade_log'])}  ending=${r_lb['ending_equity']:,.2f}")

    torch.save(policy.state_dict(), "data/processed/quota_dqn.pt")
