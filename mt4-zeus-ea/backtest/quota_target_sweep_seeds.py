#!/usr/bin/env python3
"""
quota_target_sweep_seeds.py

Same quota-target sweep (25/50/75/100%) as quota_target_sweep.py, but
5 seeds per target instead of 1 -- reports mean/std on lockbox win rate
and ending equity so a real target effect can be told apart from
ordinary training-run variance.
"""
import sys
sys.path.insert(0, ".")
import statistics as stats
import pandas as pd

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
seeds = [0, 1, 2, 3, 4]
summary = []

for target in targets:
    qe.QUOTA_TARGET = target
    print(f"=== QUOTA_TARGET={target:.0%}, {len(seeds)} seeds ===")
    lb_wrs, lb_endings, dev_wrs, dev_endings = [], [], [], []
    for seed in seeds:
        policy = train_dqn(dev, n_episodes=30, seed=seed)
        dev_r = evaluate(policy, dev)
        lb_r = evaluate(policy, lockbox)
        dev_wrs.append(dev_r["win_rate"]); dev_endings.append(dev_r["ending_equity"])
        lb_wrs.append(lb_r["win_rate"]); lb_endings.append(lb_r["ending_equity"])
        print(f"  seed={seed}: dev WR={dev_r['win_rate']:.1f}% ${dev_r['ending_equity']:,.0f}  |  "
              f"lockbox WR={lb_r['win_rate']:.1f}% ${lb_r['ending_equity']:,.0f}")
    summary.append({
        "target": target,
        "dev_wr_mean": stats.mean(dev_wrs), "dev_wr_std": stats.stdev(dev_wrs),
        "dev_end_mean": stats.mean(dev_endings), "dev_end_std": stats.stdev(dev_endings),
        "lb_wr_mean": stats.mean(lb_wrs), "lb_wr_std": stats.stdev(lb_wrs),
        "lb_end_mean": stats.mean(lb_endings), "lb_end_std": stats.stdev(lb_endings),
    })
    print()

print("=" * 110)
print(f"{'Target':>7} | {'Dev WR mean±std':>18} | {'Dev ending mean±std':>26} | {'LB WR mean±std':>18} | {'LB ending mean±std':>24}")
for s in summary:
    print(f"{s['target']:>6.0%} | {s['dev_wr_mean']:>7.1f}% ± {s['dev_wr_std']:>5.1f} | "
          f"${s['dev_end_mean']:>11,.0f} ± ${s['dev_end_std']:>9,.0f} | "
          f"{s['lb_wr_mean']:>7.1f}% ± {s['lb_wr_std']:>5.1f} | "
          f"${s['lb_end_mean']:>10,.0f} ± ${s['lb_end_std']:>9,.0f}")

print()
print("=== Baseline: fixed Zeus settings (no AI, no quota concept at all) ===")
r_dev = zb.run_zeus_backtest(dev, starting_balance=1000.0, spread_pips=1.0)
r_lb = zb.run_zeus_backtest(lockbox, starting_balance=1000.0, spread_pips=1.0)
for name, r in [("dev", r_dev), ("lockbox", r_lb)]:
    tl = r["trade_log"]
    wins = sum(1 for t in tl if t["pnl"] > 0)
    wr = wins / len(tl) * 100 if tl else float("nan")
    print(f"{name}: trades={len(tl)} win_rate={wr:.1f}% ending=${r['ending_equity']:,.2f}")
