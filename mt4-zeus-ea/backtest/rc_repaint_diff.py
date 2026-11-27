#!/usr/bin/env python3
"""
rc_repaint_diff.py

Companion to RC_RepaintSnapshot.mq4. Takes two or more snapshot CSVs
(each captured at a different real-world moment, via repeated runs of
that script) and reports, for EACH period dumped (A=8, B=96 by default),
exactly which bars' RC reading changed between snapshots -- i.e. actual,
measured repainting, not an assumption.

With only two snapshots, a changed bar tells you THAT it repainted
between those two moments, not the shape of the change. With three or
more snapshots (taken at different times), this also detects the
specific "crossed over, then crossed back" pattern described live:
direction X in snapshot 1, a DIFFERENT direction in some middle
snapshot, then back to X in a later snapshot -- printed out explicitly
when found.

Usage: list the snapshot files in SNAPSHOT_FILES below, in the order
they were taken (oldest first), and run.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

RAW_DIR = Path(__file__).parent / "data" / "raw"

# Add each new snapshot file here, OLDEST FIRST, as you take them.
SNAPSHOT_FILES: list[str] = [
    # "rc_repaint_snapshot_2026.11.27_120000.csv",
    # "rc_repaint_snapshot_2026.11.28_083000.csv",
]

RC_EMPTY_SENTINEL = 2147483647.0


def load_snapshot(path: Path) -> tuple[str, int, int, pd.DataFrame]:
    with open(path, "r") as f:
        taken_at_line = f.readline().strip()
        header_line = f.readline().strip()

    taken_at = taken_at_line.split(";", 1)[1] if ";" in taken_at_line else taken_at_line
    cols = header_line.split(";")
    # cols: bar_timestamp, blue_p<A>, maroon_p<A>, blue_p<B>, maroon_p<B>
    period_a = int(re.search(r"blue_p(\d+)", cols[1]).group(1))
    period_b = int(re.search(r"blue_p(\d+)", cols[3]).group(1))

    df = pd.read_csv(path, sep=";", skiprows=2, header=None, names=cols)
    df["bar_timestamp"] = pd.to_datetime(df["bar_timestamp"], format="%Y.%m.%d %H:%M", errors="coerce")
    df = df.dropna(subset=["bar_timestamp"]).drop_duplicates(subset=["bar_timestamp"], keep="last")

    for col in cols[1:]:
        df[col] = df[col].where(df[col] != RC_EMPTY_SENTINEL, np.nan)

    return taken_at, period_a, period_b, df.set_index("bar_timestamp")


def combined_direction(blue, maroon) -> int:
    blue_on = pd.notna(blue) and blue != 0.0
    maroon_on = pd.notna(maroon) and maroon != 0.0
    if blue_on and not maroon_on:
        return 1
    if maroon_on and not blue_on:
        return -1
    if blue_on and maroon_on:
        return 1 if abs(blue) >= abs(maroon) else -1
    return 0


def main():
    if len(SNAPSHOT_FILES) < 2:
        print("Add at least 2 snapshot filenames to SNAPSHOT_FILES (oldest first) and re-run.")
        return

    snapshots = []
    for fname in SNAPSHOT_FILES:
        path = RAW_DIR / fname
        if not path.exists():
            print(f"Missing {path} -- copy the uploaded snapshot there first.")
            return
        snapshots.append(load_snapshot(path))

    period_a = snapshots[0][1]
    period_b = snapshots[0][2]
    print(f"Loaded {len(snapshots)} snapshots, periods {period_a} and {period_b}:")
    for taken_at, _, _, df in snapshots:
        print(f"  taken_at={taken_at}  bars={len(df)}")
    print()

    # Build a direction series per snapshot per period, aligned on bar_timestamp.
    for period, blue_col_fmt, maroon_col_fmt in [
        (period_a, f"blue_p{period_a}", f"maroon_p{period_a}"),
        (period_b, f"blue_p{period_b}", f"maroon_p{period_b}"),
    ]:
        print(f"=== Period {period} ===")
        dir_series = []
        for taken_at, _, _, df in snapshots:
            s = df.apply(lambda row: combined_direction(row[blue_col_fmt], row[maroon_col_fmt]), axis=1)
            dir_series.append(s)

        common_index = dir_series[0].index
        for s in dir_series[1:]:
            common_index = common_index.intersection(s.index)
        common_index = common_index.sort_values()

        aligned = pd.DataFrame({i: s.reindex(common_index) for i, s in enumerate(dir_series)})

        changed_count = 0
        crossback_count = 0
        for ts, row in aligned.iterrows():
            vals = row.to_numpy()
            if len(set(vals)) > 1:
                changed_count += 1
                if changed_count <= 20:
                    print(f"  CHANGED  {ts}  readings over time: {list(vals)}")
            # Crossed-over-then-crossed-back: first and last reading match,
            # but something in between differs.
            if len(vals) >= 3 and vals[0] == vals[-1] and any(v != vals[0] for v in vals[1:-1]):
                crossback_count += 1
                if crossback_count <= 20:
                    print(f"  CROSS-BACK  {ts}  readings over time: {list(vals)}")

        print(f"  {changed_count}/{len(common_index)} bars changed between at least two snapshots")
        print(f"  {crossback_count} bars show a crossed-over-then-crossed-back pattern")
        print()


if __name__ == "__main__":
    main()
