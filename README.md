# International_Features

## FII/DII and retail delivery analysis — this branch

Branch: **`codex/fii-dii-retail-delivery-pipeline`**

This branch adds a local Python pipeline for ten-year historical acquisition and
ongoing collection of NSE, BSE and MSEI reports. It estimates delivery value from
each security's turnover and delivery quantity, captures available FII/DII gross
buys and sells, and calculates a conditional remaining-participant bucket for
the retail-participation research.

**The remaining bucket includes everyone outside reported FII/DII. It does not
isolate retail.** Delivery money is an estimate; historical institutional inputs,
MSEI delivery quantities and instrument-scope comparability have explicit gaps.
No complete ten-year institutional or delivery-money series is claimed.

- [Pipeline instructions, sources and methodology](pipelines/fii_dii_retail_delivery/README.md)
- [What every file does](FILES.md)
- [Validation results](pipelines/fii_dii_retail_delivery/VERIFICATION.json)
- [Small frozen CSV examples](pipelines/fii_dii_retail_delivery/examples/)

```sh
git switch codex/fii-dii-retail-delivery-pipeline
cd pipelines/fii_dii_retail_delivery
python marketpipe.py backfill --years 10
python marketpipe.py update --lookback 10 --refresh
python marketpipe.py status
```

Use `python3` or `py -3` if that is your Python 3 command. This pipeline requires
Python 3.10+ and no additional packages or AI calls. Windows launchers and an
optional local daily scheduler are included. Pushing this branch does not install
or run that scheduler. Downloads, local databases and logs remain ignored by Git;
the examples are frozen validation samples.

## Existing international-features research

Research on Nifty 50's relationship with exchange rates, Brent oil, government
bond yields, and global markets.

## Download and test on your computer

Install Git and Python 3.10 or newer, then clone the repository:

```sh
git clone https://github.com/Hannibalbbarca/International_Features.git
cd International_Features
```

If you already have a clone, run `git pull --ff-only` from its project directory.
The downloader uses Python's standard library and an IANA time-zone database.
On Windows, install the time-zone data with:

```powershell
py -3 -m pip install -r requirements.txt
```

For the commands below, use `py -3` instead of `python3` on Windows.

## Refresh public data

Run from this repository:

```sh
python3 scripts/fetch_data.py --start 2015-01-01 --only nifty50 usd_inr brent_spot us_yield_10y sp500 us_vix
```

Omitting `--end` requests data through yesterday in Indian time. Run the same
command again to refresh from the providers; every run preserves earlier files.
Use `--start YYYY-MM-DD` to request a smaller recent period.
The default start is **January 1, 2015**, even if `--start` is omitted. Each
provider's first available observation can be later than the requested date.

To try a small local download first:

```sh
python3 scripts/fetch_data.py --start 2025-01-01 --end 2025-01-31 --only brent_spot us_yield_10y
```

Daily refers to observation frequency. Refreshing is manual; there is currently
no GitHub Actions schedule or background job.

Add `--probe-brent-intraday` for a recent 30-minute NYMEX Brent futures pilot.
This does not provide a decade of intraday observations or an aligned overnight
return. The daily Indian 10-year yield source remains unresolved; the unrestricted
default run includes that source, records the gap, and returns a nonzero exit.

Raw responses are under `data/raw/`, normalized CSVs under `data/processed/`,
and provenance/quality manifests under `data/runs/`, each in its run directory.
Market data are ignored by Git; acquisition code and source definitions are not.

See [acquisition details](DATA_ACQUISITION.md),
[source configuration](config/data_sources.json), and [study design](RESEARCH_PLAN.md).

## Verify the downloader

```sh
python3 -m unittest discover -s tests -v
```

These tests verify data-integrity safeguards; they do not establish market
relationships or validate causal/predictive session alignment.
