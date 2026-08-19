# Raw data

- `USDJPY_M1.csv` — confirmed USDJPY M1 export, 2023-04-26 to 2026-07-20, 1,200,000 rows. Verified contiguous, no gaps between the 3 uploaded parts.
- `rc_history.csv` — **UNVERIFIED SYMBOL**. This file's date range (1993-04-19 to 2026-08-07, 180,312 rows) matches the GBPJPY RC dump from earlier in this project, not USDJPY's actual trading history (2023-04-26 to 2026-07-20). Do not use for a USDJPY backtest until confirmed to be the RC export from a USDJPY chart. If it turns out to be GBPJPY's, replace this file with the correct USDJPY export before running rc_generator.py.
