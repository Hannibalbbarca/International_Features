# FII/DII and retail delivery-analysis pipeline

This module supports research on institutional versus remaining-participant
activity in Indian cash markets. The remaining bucket is often the starting point
for the retail question, but includes corporate, proprietary and other non-FII/DII
participants. It cannot be interpreted as measured retail buying or selling.

From the repository root, enter `pipelines/fii_dii_retail_delivery` before using
the commands below. See [the repository file guide](../../FILES.md) for the purpose
of each script and output.

Python 3.10 or newer. No third-party packages, broker login, OpenAI API, subscription or model calls are used. Normal runs cost no AI credits. The first archive download uses ordinary network bandwidth and local disk space; subsequent runs reuse validated local files.

## Windows quick start

- **Start-Backfill.cmd** launches a hidden background process covering the last ten years through the latest completed evening. It can be stopped and resumed. Progress and errors are logged under `data/logs/`.
- **Show-Status.cmd** displays live database counts and opens the local report. The page refreshes every minute. Status works while a backfill holds the writer lock.
- **Update-Now.cmd** collects newly published daily reports and refreshes ten recent calendar dates to capture revisions.
- **Install-DailyTask.ps1** optionally registers a local Windows Task Scheduler job at **20:30 IST**. The user must be signed in and the computer on. StartWhenAvailable catches a missed trigger after the machine becomes available. This is a local Python task, not a Codex/AI automation. Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-DailyTask.ps1` to install it. Pass `-At '21:30'` to choose another time. This installer is provided but is not automatically activated by the Python program.
- **Stop-Backfill.ps1** stops only the recorded backfill PID after checking its command line. Downloaded data remains intact. Restarting the backfill reuses good files.

Do not move the folder after installing its scheduled task; reinstall the task after a move. A backfill and an update cannot write concurrently. The OS releases the writer lock if the process is interrupted.

## Command-line examples

Run commands from this folder. Global options appear **before** the subcommand.

```powershell
python marketpipe.py backfill --years 10
python marketpipe.py backfill --start 2016-11-05 --end 2026-11-05
python marketpipe.py update --lookback 10 --refresh
python marketpipe.py status
python marketpipe.py --offline report
python marketpipe.py --offline backfill --start 2026-11-05 --end 2026-11-05
python marketpipe.py backfill --start 2024-07-05 --end 2024-07-08 --retry-missing
```

The default includes calendar weekends so special weekend/Muhurat sessions can be discovered. `--weekdays-only` is faster but explicitly omits such sessions. If NSE's price report is unavailable, the default does not probe other exchanges for that date and records that limitation rather than calling it a holiday. Use `--probe-all` to probe BSE/MSEI independently on every requested date.

A file that is unavailable or temporarily blocked is not a zero. HTTP 404s are retried after a cooldown: 30 minutes for recent dates and 30 days for old dates. Transient failures have a shorter cooldown. `--retry-missing` overrides these cooldowns. 403 responses are recorded, not bypassed. Request pacing defaults to at least 0.75 seconds per host; 429/5xx and timeouts are retried with backoff. A failed refresh retains the previous good, correctly dated snapshot.

`forward` means collecting new **published actuals**, not predicting future values. The current day's file may not exist before publication. The institutional endpoint's returned trade date is used; yesterday's figures are never relabelled as today.

## Outputs

Everything lives below `data/` unless `--data-dir` is supplied.

| File | Contents |
|---|---|
| `market.sqlite` | Daily exchange totals, institutional values, cache index, attempts, run progress and institutional revision history |
| `raw/` | Original downloaded bytes, gzip-compressed, with content hashes in filenames; old versions retained |
| `reports/status.html` | Local progress and latest 250 data dates, with links to CSV files |
| `reports/status.json` | Machine-readable progress and coverage |
| `reports/exchange_daily.csv` | Exchange/date turnover, quantities, estimated delivery money, official reported money where available, coverage and exceptions |
| `reports/daily_model.csv` | Three-exchange delivery bounds, conditional remaining buys/sells/net, and data-status fields |
| `reports/institutions.csv` | Available gross FII/DII purchases and sales in INR crore |
| `reports/source_attempts.csv` | Dates, URLs, HTTP failures and validation failures |

CSV blanks mean unavailable. Raw source currency values are rupees; model CSV monetary columns explicitly end in `_crore`. Quantity fields are shares/units, not rupees. Raw files plus cache URLs, SHA-256 hashes and timestamps support audit and recomputation. Aggregate-only storage keeps SQLite compact; original security-level files remain available for later analysis.

## Sources and historical formats

- **NSE prices/turnover:** [official daily reports](https://www.nseindia.com/all-reports). Before 8 July 2024, legacy `cmDDMONYYYYbhav.csv.zip`; from that date, final CM UDiFF ZIP. Internal dates and unique security/series keys are validated.
- **NSE delivery:** daily `MTO_DDMMYYYY.DAT`. Its header's deliverable quantity and record count must equal the parsed security rows. Quantities are gross across client level for the file's covered universe. [Official format](https://nsearchives.nseindia.com/content/press/EOD_CM.pdf).
- **BSE:** daily [gross-delivery archive example](https://www.bseindia.com/BSEDATA/gross/2016/SCBSEALL0711.zip), plus legacy equity bhavcopy or final CM UDiFF prices. The delivery file contains its own dated quantity, turnover and published delivery value. Legacy price files lack an internal date, so they are used only with a matching dated delivery report. Price/delivery mismatches invalidate the affected close valuation rather than silently changing quantities.
- **MSEI:** [daily equity statistics](https://www.msei.in/downloads/equity-reports/daily-reports). The script deliberately uses the rupee `Market-Statistics-Report` CSV, not the UDiFF turnover field that was 1,000 times smaller in the inspected November 2026 snapshot. Historical slash and hyphen date formats are checked against the requested date. If security statistics are unavailable, the independently dated `Market-Activity-Report` can supply turnover bounds. Only an explicitly dated activity report with both zero turnover and zero quantity establishes zero trading. Positive aggregate-only activity does not establish exact share quantities. No MSEI delivery values are invented.
- **Institutions:** [NSE combined FII/DII report](https://www.nseindia.com/reports/fii-dii) via its public latest-data endpoint. It captures new snapshots going forward. This endpoint is **not represented as a ten-year historical API**.

Historical files were directly verified for NSE prices/delivery, BSE delivery/prices and MSEI turnover on 7 November 2016. The 5 and 8 July 2024 format transition and the preserved 5 November 2026 snapshot were also processed. All archive dates remain subject to actual source availability; source_attempts.csv exposes gaps. This is not a promise of a complete ten-year three-exchange delivery-money or institutional series.

## Historical FII/DII import

For older gross institutional history, supply a verified CSV with these exact columns, in **INR crore**:

```csv
date,fii_buy,fii_sell,dii_buy,dii_sell
2016-11-07,...,...,...,...
```

```powershell
python marketpipe.py import-institutions .\verified_history.csv --source "actual source URL or provenance"
```

All four gross values are required; net-only data cannot reconstruct them. Imports are transactional, and previous institutional values are retained when revised. No paid data is purchased. Missing historical institutional inputs remain blank and corresponding remaining-participant outputs stay unavailable. NSDL final flows, primary-market flows and F&O participant data are not silently substituted for the combined provisional cash series.

## Calculations and limitations

For each security `i`:

```text
VWAP_i = turnover_i / traded_quantity_i
estimated_delivery_i = delivery_quantity_i * VWAP_i
```

Sum **security-level monetary estimates**. Never multiply aggregate turnover by an aggregate share-count delivery ratio; different share prices make that shortcut incorrect.

The default scope is **all reported CM instruments**, including funds/ETFs and bonds present in the source reports. It is deliberately explicit and differs from the narrower cash-equity basket in the earlier conversation workbook. Do not splice those two scopes into one time series. Exact institutional instrument/settlement comparability remains unverified for either scope.

When NSE BE/BZ delivery quantities are absent, the traded quantity is used as a **derived full-delivery obligation** under trade-for-trade designation. These rows and quantities are counted separately. Observed ST/SZ quantities are retained even if below full delivery, and a review flag is attached. These are deliverable obligations, not proof of completed demat settlement. [NSE series definitions](https://www.nseindia.com/static/market-data/legend-of-series).

For missing delivery quantity with known turnover, the VWAP-model contribution is bounded by `[0, turnover]`. If an entire exchange's turnover is unavailable, the combined upper endpoint is **unavailable**, not zero. Quantity coverage includes explicitly derived TFT rows and is not a confidence score. Common-close estimates are provided only when all required closing prices are available.

```text
Rest buys  = estimated total delivery value - FII buys - DII buys
Rest sells = estimated total delivery value - FII sells - DII sells
Rest net   = -(FII net + DII net)
```

These are **conditional model outputs**, not observed retail transactions. `Rest` includes corporate, proprietary and other participants. A constant zero-sum balance is imposed algebraically and does not validate the delivery estimate. VWAP/close valuations are not observed delivery cash consideration. Clearing-corporation settlement-money reports are not substituted for gross client-delivery money, and clearing totals are not casually added to exchange totals under interoperability.

## Verification

```powershell
python -m unittest -v
```

Tests cover security price-weighting, wrong dates, HTML responses, MTO control totals, legitimate zero versus missing delivery, missing-exchange bounds, explicit TFT derivation, net-value invariance, offline cache use, failed refresh preservation and institutional revisions. The preserved 5 November 2026 source snapshot can be imported with:

```powershell
python marketpipe.py --offline seed "path-to-market_delivery_2026-11-05"
```

Source URLs or formats may change. New schemas cause visible validation errors rather than silently producing a clean zero. Re-run failed dates after adapting the parser. This program places no trades and sends no messages.
