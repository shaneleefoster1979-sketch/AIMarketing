# MT4 Data Ingestion

Builds a standardized training baseline from raw MetaTrader 4 historical
exports. MT4 has no native Python API, so this pipeline works off CSV files
exported from the platform's History Center.

## Usage

```
pip install -r requirements.txt

# Export EURUSD and GBPUSD D1 + H4 history from MT4's History Center into data/raw/,
# then run:
python data_ingestion.py
```

By default this scans `data/raw/` for CSV files, and writes the cleaned,
gap-filled, combined baseline to `data/processed/clean_history.csv`.

Options:

```
python data_ingestion.py \
  --input-dir data/raw \
  --output data/processed/clean_history.csv \
  --symbols EURUSD GBPUSD \
  --timeframes D1 H4 \
  --tz UTC \
  -v
```

## Expected input

Any MT4 export naming convention is accepted as long as the symbol and
timeframe are identifiable in the filename, e.g.:

- `EURUSD_D1.csv`, `EURUSD-H4.csv` (human-readable)
- `EURUSD1440.csv`, `EURUSD240.csv` (raw History Center period-in-minutes)

Each file may have MT4's default no-header `Date,Time,Open,High,Low,Close,Volume`
layout (comma or semicolon delimited), or a header row with a combined
datetime column.

## What the script does

1. **Scan** `data/raw/` for files matching the requested symbols/timeframes.
2. **Clean** each file onto the canonical schema:
   `timestamp, open, high, low, close, volume`.
3. **Validate** timestamps (parses MT4's `YYYY.MM.DD` dates, localizes to a
   consistent timezone, drops unparseable/duplicate/OHLC-inconsistent rows).
4. **Fix gaps**: reindexes each series onto the timeframe's expected
   business-day bar grid (so weekend market closures are never mistaken for
   missing data) and forward-fills any bar that's still missing
   (`open=high=low=close=prior close`, `volume=0`), flagging filled bars via
   an `is_filled` column so training code can exclude or down-weight them.
5. **Export** the combined result (all symbols/timeframes, tagged with
   `symbol` and `timeframe` columns) to `data/processed/clean_history.csv`.

Missing expected files or rows dropped for data-quality reasons are logged
as warnings — run with `-v` for full detail.
