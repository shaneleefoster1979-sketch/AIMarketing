#!/usr/bin/env python3
"""
quota_target_sweep.py

Trains a fresh DQN for each of several rolling-30-day quota targets
(25%, 50%, 75%, 100%) -- QUOTA_TARGET is baked into the reward's
skip-penalty term, so this genuinely changes what the agent learns to
do, not just an evaluation-time knob. Same architecture, same 5 base
features, same dev/lockbox split as every other run in this project.
"""
import sys
sys.path.insert(0, ".")
import pandas as pd
import torch

import quota_environment as qe
from train_quota_agent import train_dqn, evaluate
import zeus_backtest as zb

renko = pd.read_csv("data/processed/renko_usdjpy.csv")
renko["timestamp"] = pd.to_datetime(renko["timestamp"], utc=True)
usable = renko.dropna(subset=["rc_value"]).reset_index(drop=True)
n = len(usable)
split = int(n * 0.85)
dev = usable.iloc[:split].reset_index(drop=True)
lockbox = usable.iloc[split:].reset_index(drop=True)
print(f"dev: {len(dev)} bricks | lockbox: {len(lockbox)} bricks (untouched)\n")

targets = [0.25, 0.50, 0.75, 1.00]
results = []

for target in targets:
    qe.QUOTA_TARGET = target
    print(f"=== Training at QUOTA_TARGET={target:.0%} per {qe.QUOTA_WINDOW_DAYS} days ===")
    policy = train_dqn(dev, n_episodes=30, seed=0)
    dev_r = evaluate(policy, dev)
    lb_r = evaluate(policy, lockbox)
    print(f"  dev:     trades={dev_r['trades']} win_rate={dev_r['win_rate']:.1f}% ending=${dev_r['ending_equity']:,.2f}")
    print(f"  lockbox: trades={lb_r['trades']} win_rate={lb_r['win_rate']:.1f}% ending=${lb_r['ending_equity']:,.2f}")
    print()
    results.append({"target": target, "dev": dev_r, "lockbox": lb_r})

print("=" * 100)
print(f"{'Target':>8} | {'Dev trades':>10} | {'Dev WR':>7} | {'Dev ending':>15} | {'LB trades':>9} | {'LB WR':>7} | {'LB ending':>12}")
for r in results:
    print(f"{r['target']:>7.0%} | {r['dev']['trades']:>10} | {r['dev']['win_rate']:>6.1f}% | "
          f"${r['dev']['ending_equity']:>13,.2f} | {r['lockbox']['trades']:>9} | "
          f"{r['lockbox']['win_rate']:>6.1f}% | ${r['lockbox']['ending_equity']:>10,.2f}")

print()
print("=== Baseline: fixed Zeus settings (no AI, no quota concept at all) ===")
r_dev = zb.run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0)
r_lb = zb.run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0)
for name, r in [("dev", r_dev), ("lockbox", r_lb)]:
    tl = r["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    wr = wins / len(tl) * 100 if tl else float("nan")
    print(f"{name}: trades={len(tl)} win_rate={wr:.1f}% ending=${r['ending_equity']:,.2f}")
