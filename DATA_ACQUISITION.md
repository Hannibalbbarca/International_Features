# Public data acquisition

The acquisition script uses Python 3.10+ and its standard library, with the
`tzdata` package needed on Windows (see requirements.txt). It stores raw
responses, source metadata, retrieval times, SHA-256 hashes, processed observations,
and a per-run manifest. Files are retained under ignored `data/` directories;
each run has a new directory and does not replace earlier runs.

Run from the repository root, either in the cloud or on your own computer:

```sh
python3 scripts/fetch_data.py --start 2015-01-01
python3 scripts/fetch_data.py --start 2015-01-01 --only nifty50 usd_inr brent_spot us_yield_10y sp500 us_vix
python3 scripts/fetch_data.py --only brent_spot us_vix
python3 scripts/fetch_data.py --only brent_spot --probe-brent-intraday
python3 scripts/fetch_data.py --only brent_spot us_vix --allow-snapshot-fallback
python3 -m unittest discover -s tests -v
```

The default end is yesterday in Asia/Kolkata. The optional intraday probe requests
only recent 30-minute Brent futures bars, not a decade of history. Its latest
bar may be incomplete: it is an availability pilot, not an analysis-ready panel.
The default start is January 1, 2015. Use explicit `--start` and `--end` dates
for fixed-period local tests. On Windows use `py -3` instead of `python3`.

Local downloads use the computer's own Internet access, not the Codex cloud's
network allowlist. Data are written relative to the script's repository root;
no `/workspace` directory or cloud credentials are required. Providers can still
apply access restrictions or rate limits. See README.md for clone instructions.

Exit status is nonzero when any selected source fails or remains unresolved.
The manifest distinguishes downloaded/structurally validated observations from
failed providers. A partial download is not a complete study dataset.
The first command also attempts the unresolved daily Indian yield source and
therefore reports a nonzero exit until that source is configured. The second
command selects only the six currently configured daily feeds.

Re-running the script refreshes the requested period, rather than merging over
old raw data or overwriting earlier snapshots. Choose a more recent `--start`
for a smaller update. Downloads can lag the requested end; observed coverage and
missing counts are recorded explicitly. No scheduler has been installed.

## Source definitions

`config/data_sources.json` is the source inventory, including units, timing
limitations, provider identifiers, and exact Git revisions for DataHub snapshots.
Live feeds are used by default: FRED's EIA Brent spot series (DCOILBRENTEU) and
FRED's CBOE VIX closing-level series (VIXCLS). Direct CBOE CSV access remains
blocked in the current instance; VIXCLS is a documented alternative publisher.
Older DataHub snapshots are available only with `--allow-snapshot-fallback` and
are marked explicitly in the run manifest. DataHub's Brent package identifies
EIA as its source; its VIX package identifies CBOE. Publisher resource checksums
are enforced when supplied. Snapshot revisions are deliberately pinned; refreshing
them requires reviewing the new metadata and revision rather than silently
changing expected hashes.

DataHub is a third-party publisher, not a substitute for primary-source checking.
Declared licenses are retained with the downloaded package, but users must also
respect the originating provider's terms. Primary-source cross-checks are pending
where direct access is blocked.

FRED DEXINUS supplies USD/INR and DGS10 supplies the daily US 10-year
constant-maturity yield. Yahoo ^NSEI and ^GSPC supply daily price indices;
primary-index-provider cross-checks remain outstanding. Total-return indices are
not assumed. A daily Indian 10-year yield endpoint remains unresolved: monthly
averages or different bond maturities will not be silently substituted.
CCIL's inspected indicative-yield page requires sign-in for its download, and
FBIL's G-Sec valuation interface is not yet established as a suitable daily
10-year benchmark series. No account registration or licensing action was taken.

FRED's DEXINUS documentation specifies noon buying rates in New York City.
That observation occurs after the Indian close and cannot be assigned as
pre-close Indian information. Historical publication timestamps are still not
provided by the daily CSV.

## Timing and quality safeguards

- Brent spot rows have a date and USD/barrel value, not an Indian-session timestamp.
- FRED dates and Yahoo daily bar labels are not historical availability timestamps.
- No one-row shift, calendar forward-fill, or overnight return is generated here.
- Missing prices/yields remain missing. Duplicate dates, incorrect schemas,
  invalid numbers, and inconsistent OHLC values fail validation.
- The final Yahoo daily bar is excluded when it is dated on the provider's current
  exchange-local date, to avoid treating a live session as completed.
- Indian overnight Brent returns need quotes around 15:30 IST at the previous
  Indian close and 09:15 IST at the next Indian opening, plus a verified exchange
  calendar, bar convention, and futures contract/roll definition.
- Yahoo identifies the optional BZ=F intraday pilot as NYMEX Brent Crude Oil Last
  Day Financial Futures, not ICE futures. Do not mix it with spot observations or
  label it as an ICE contract. Only recent pilot coverage has been fetched.

## Network access

Initial direct FRED and CBOE checks received HTTP 403 from the environment's
CONNECT proxy. These were network access denials, not evidence of missing API
keys. Subsequent FRED and Yahoo downloads succeeded. Public DataHub publications
are also available on the permitted GitHub route. Provider access and rate limits
may change; consult the current run manifest rather than assuming readiness.

A domain-specific network draft has been saved for FRED, CBOE, Yahoo, NSE/Nifty
Indices, RBI, CCIL, FBIL, ICE, and EIA. Saving a draft does not itself establish
runtime access or publication. The draft tool requested review/save in environment
settings and publication for persistence. Retry policy failures after access
changes; respect provider rate limits rather than trying to evade them.

Historical intraday coverage, daily Indian government-yield coverage, and actual
observation/publication times remain to be verified. Do not begin a predictive
study or claim a completed five-series panel based on these preliminary files.
