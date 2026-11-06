# What the files do

The repository now contains two data-acquisition modules. The international-features
module studies Nifty and macro/global-market variables. The FII/DII delivery module
collects exchange reports for the institutional-versus-rest participation question.
They currently produce separate datasets; no joined analysis is performed.

## Start here

| File | Purpose |
| --- | --- |
| `README.md` | Branch overview and starting commands for both modules. |
| `FILES.md` | This guide to source files, launchers and generated outputs. |

## FII/DII and retail delivery module

All paths in this table are below `pipelines/fii_dii_retail_delivery/`.

| File | Purpose |
| --- | --- |
| `marketpipe.py` | Main program. Downloads and validates exchange reports, caches originals, calculates security-level delivery-value estimates, stores daily aggregates in SQLite and exports CSV/HTML reports. Provides historical backfill, daily update, offline recomputation and institutional-history import commands. |
| `test_marketpipe.py` | Nineteen offline tests covering weighting, dates, schemas, quantity controls, missing-versus-zero data, cache behavior and institutional revisions. |
| `README.md` | Full setup, source URLs, historical-format handling, calculations, units and unresolved data limitations. |
| `VERIFICATION.json` | Recorded checks on actual 2016, July 2024 and November 2026 source dates, including the sample calculation. A validation record, not a claim that the entire archive is complete. |
| `Start-Backfill.cmd` | Windows double-click launcher for a hidden, resumable ten-year download through the latest completed evening. |
| `Update-Now.cmd` | Windows launcher to collect published actuals and refresh the latest ten calendar days for revisions. |
| `Show-Status.cmd` | Shows database progress and opens the local HTML report. |
| `Invoke-MarketPipeline.ps1` | Shared Windows runner used by the launchers. Resolves Python, sets dates, starts the process and records logs. |
| `Stop-Backfill.ps1` | Stops the recorded backfill after checking the process identity. Cached downloads remain available for a restart. |
| `Install-DailyTask.ps1` | Optional Windows Task Scheduler installer for a daily update, default 20:30 IST. Requires the computer on and the user signed in. It is not activated by cloning or pushing the repository. |
| `institutional_import_template.csv` | Required column names for importing verified historical gross FII buys/sells and DII buys/sells, in INR crore. Net-only data are insufficient. |
| `.gitignore` | Keeps the growing local archive, database, logs, Python bytecode and ZIP packages out of Git. |
| `examples/README.md` | Explains the frozen samples and where live reports will appear. |
| `examples/exchange_daily.csv` | Small exchange/date sample with turnover, delivery-value estimates, quantity coverage and issues. |
| `examples/daily_model.csv` | Small combined sample with delivery bounds and conditional rest buys, sells, net and participation. |
| `examples/institutions.csv` | Available gross institutional sample inputs and provenance. |

The current calculation is `sum(turnover_i * delivery_quantity_i / traded_quantity_i)`.
Conditional rest buys/sells subtract the corresponding FII and DII gross values.
The default instrument scope is all reported CM instruments. Rest is broader than
retail, and institutional comparability is unverified. Missing inputs stay missing
or bounded; they are not turned into observed zeroes.

### Files generated when the delivery pipeline runs

These paths are relative to the module's local `data/` directory, or the custom
directory supplied with `--data-dir`. They are not committed to Git.

| File or folder | Purpose |
| --- | --- |
| `market.sqlite` | Local daily totals, institutional inputs and revisions, source index, download attempts and run progress. |
| `raw/` | Original downloaded reports, compressed and named with content hashes so revisions can be retained. |
| `reports/exchange_daily.csv` | Exchange/date turnover and delivery quantities, estimated money, reported BSE money where available and quality flags. |
| `reports/daily_model.csv` | Combined delivery bounds and conditional FII/DII/rest calculations; money columns marked `_crore` are INR crore. |
| `reports/institutions.csv` | Stored gross FII/DII values and their sources. |
| `reports/source_attempts.csv` | Exchange download URLs, validation failures and HTTP errors for identifying gaps. |
| `reports/status.html` | Local progress page and latest 250 available dates, linking to the live CSVs. |
| `reports/status.json` | Machine-readable coverage counts and last-run progress. |
| `logs/` | Output/error logs from the Windows launchers. |
| `backfill-process.json` | Recorded local backfill PID used by the stop helper. |
| `writer.lock` | OS-managed lock preventing two pipeline writers from changing the same database concurrently. |

Forward updates collect newly published observations. They do not forecast prices
or automatically publish data to GitHub. Historical institutional inputs require
a verified gross-value import; the latest endpoint does not backfill those inputs.

## Existing international-features module

These paths are relative to the repository root.

| File | Purpose |
| --- | --- |
| `RESEARCH_PLAN.md` | Study design for relationships between Nifty, exchange rates, oil, yields and global markets; proposed variables, timing checks and methods. It is a plan, not calculated empirical results. |
| `DATA_ACQUISITION.md` | Sources, commands, units, publication/session-timing limitations, missing providers and validation rules for that study's downloader. |
| `config/data_sources.json` | Machine-readable source inventory: provider series/symbols, units, timing notes, pinned fallback versions and unresolved Indian-yield source. |
| `scripts/fetch_data.py` | Separate downloader for Nifty 50, USD/INR, Brent spot, US 10-year yield, S&P 500 and VIX. Also offers a recent Brent-futures intraday pilot. Writes raw data, normalized CSVs and run manifests. It does not calculate FII/DII/rest delivery values. |
| `tests/test_fetch_data.py` | Integrity tests for the international-features downloader. |
| `requirements.txt` | Windows `tzdata` dependency for that downloader's IANA time zones. The delivery pipeline uses a fixed IST offset and does not need this dependency. |
| `.gitignore` | Excludes the existing downloader's raw, processed and run-data folders and Python bytecode. |

The existing downloader creates root-level `data/raw/`, `data/processed/` and
`data/runs/`. These are independent of the delivery module's `data/` directory.

## Check both modules

From the repository root:

```sh
python -m unittest discover -s tests -v
python -m unittest discover -s pipelines/fii_dii_retail_delivery -v
```
