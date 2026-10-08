# Indian equity markets and macroeconomic shocks

Status: acquisition has started; see DATA_ACQUISITION.md and per-run manifests
under data/runs/. No empirical relationships have been calculated. Nifty 50 is
the confirmed center of the study, using publicly available data first. Session
alignment and the daily Indian 10-year yield source remain unresolved.

## Objective

Measure how Indian equities relate to USD/INR, Brent oil, US government bond
yields, and Indian government bond yields. Distinguish contemporaneous
association, predictive relationships, and responses around unusually large
moves. Examine whether domestic equity shocks predict subsequent moves in
these variables as well.

Daily correlations and statistical shocks alone do not establish causality.
Credible causal claims require additional identification, such as independently
measured policy surprises or documented external events.

## Proposed baseline

- Primary equity outcome: Nifty 50 daily returns. Prefer a total-return index
  if reliable history is available; label a price-index substitute explicitly.
- Extensions: Bank Nifty, Sensex, and sector indices, subject to data availability.
- Target history: January 2015 through the latest verified complete observation,
  with an initial comparison over complete calendar years 2015–2025 where
  coverage permits. Do not assume every series has this coverage.
- Frequency: daily for the first study. Intraday and policy-announcement analysis
  are separate extensions requiring timestamped data.
- Horizons: the contemporaneous association and cumulative returns over the
  next 1, 5, and 20 Indian trading sessions.
- Start with public data where usable. Record unresolved access or licensing
  requirements instead of silently substituting a different economic series.

## Variables and measurement

| Variable | Measurement | Hypothesis to test |
| --- | --- | --- |
| Nifty 50 | Daily log return, reported in percent | Main Indian equity outcome |
| USD/INR | Daily log return of INR per USD | A positive return means INR depreciation; larger positive moves may coincide with weaker Indian equities |
| Brent crude | Daily log return in USD | Positive relationship is the researcher's observation; test whether its sign depends on the shock type and market regime |
| US 10-year government yield | Daily change in basis points | Yield increases may coincide with weaker Indian equities |
| Indian 10-year government yield | Daily change in basis points | Yield increases may coincide with weaker Indian equities |

Do not regress returns on raw price levels as the baseline. Report yield levels
as context, but use changes in basis points for the baseline return analysis.
For yields quoted in percent, a change from 4.00 to 4.10 is +10 basis points.

Keep the Indian yield's benchmark and maturity consistent. Document benchmark
bond switches. Do not substitute bond price returns for changes in yields.
For Brent futures, record the contract and roll rule; spot prices and continuous
futures are different measures and should not be mixed without documentation.

## Data acquisition and quality

Candidate sources, not yet verified:

- NSE/NSE Indices or a licensed provider for Indian equity indices.
- RBI or a documented licensed provider for USD/INR and Indian government yields.
- US Treasury/FRED for US yields; FRED may also provide USD/INR and Brent series.
- EIA/FRED or a documented market-data provider for Brent prices.

Possible FRED identifiers to investigate include DEXINUS, DGS10, and
DCOILBRENTEU. Verify definitions, timestamps, revisions, and actual coverage
before use. These identifiers do not solve Indian equity or Indian-yield access.

Preserve raw downloads with source, retrieval date, units, time zone, observation
time, publication/availability time where known, revision policy, and licensing
notes. Store the acquisition scripts and a data dictionary so the study can be
reproduced. Do not put credentials into files or logs.

Validate uniqueness, monotonic dates, units, missingness, obvious outliers,
benchmark changes, trading calendars, and start/end coverage. Review extreme
observations against the source rather than deleting them automatically.
Report the usable sample and exclusions for every analysis.

## Trading-session alignment

Use the Indian exchange calendar and Asia/Kolkata for equity session boundaries.
The Indian cash-equity close is normally 15:30 local time; validate exceptions
and the source's actual observation convention.

Build two explicitly different datasets:

1. A descriptive dataset for contemporaneous associations. Explain overlapping
   and non-overlapping observation windows; a matching calendar date does not
   imply information was available before the Indian close.
2. A predictive dataset containing only observations publicly available before
   the relevant Indian outcome window. A US closing yield on an Indian calendar
   date generally belongs to a later information window. Handle US holidays and
   daylight-saving changes using timestamps, not an unconditional one-row shift.

If a source has no usable availability timestamp, state the limitation and use
a conservative lagged specification. Never describe it as verified real-time
information. Do not fill missing prices/yields forward and interpret the resulting
zero change as an observed market move. Document how foreign-market movements
over Indian holidays are accumulated or assigned to the next Indian session.

## Analysis sequence

### 1. Describe the observations

Plot returns/yield changes and their distributions. Report Pearson and Spearman
correlations, rolling relationships, scatter plots, sample counts, and tail
behavior. Compare unconditional Indian returns with returns on positive and
negative factor days. Treat these as descriptive, not causal, results.

### 2. Separate the factors

Estimate baseline regressions for each factor individually and jointly, using
session-aligned factor changes and a small predeclared set of lags. Report the
effect of a 1% currency/oil move and a 10-basis-point yield move, confidence
intervals, and explanatory power. Check collinearity between the two yields.

Compare parsimonious specifications with ones containing lagged Indian returns,
global equity returns, and a volatility measure where data permits. Align every
control to the same information cutoff. Global controls can change the question
being estimated; present both specifications and explain that difference.
Use heteroskedasticity/autocorrelation-robust uncertainty estimates as appropriate.

### 3. Define and study statistical shocks

Define a shock as an unusually large change relative to information available
before that observation. A starting rule is an absolute innovation greater than
two trailing standard deviations, with positive and negative shocks separate.

Use a simple predeclared rolling forecast or lagged model to obtain innovations.
For a 60-session reference window, estimate its mean/variance using prior
observations only, and compare sensitivity to longer windows and alternative
thresholds. Do not standardize against the full future sample. Call these
statistical shocks, not externally identified economic shocks.

For each factor, report:

- Number and dates of positive/negative shocks and the usable sample per horizon.
- Indian equity response over the next 1, 5, and 20 sessions, with uncertainty.
- Typical response, negative-return frequency, and response dispersion.
- Whether outcomes differ for simultaneous versus isolated factor shocks.
- Clustering/overlap of events and sensitivity to excluding overlapping windows.

Use event-study summaries and local projections to estimate the response paths.
Keep pre-event controls fixed when estimating future outcomes; do not condition
on future variables that could themselves respond to the shock. Use uncertainty
methods that account for overlapping return horizons and dependent observations.

Repeat in the reverse direction: define large Indian equity innovations, then
measure subsequent FX, oil, and yield responses using valid information windows.
Label these predictive/event associations rather than causal spillovers.

### 4. Investigate economic shock types and regimes

Compare INR appreciation/depreciation, oil rises/falls, and yield rises/falls.
Test a small predeclared number of high/low-volatility or policy-period regimes,
with the sample size and uncertainty reported for each.

Oil demand and supply shocks can have different equity implications. Distinguish
them only when supported by additional data or documented events; the sign of
the oil return alone cannot identify their cause. Likewise, a yield increase
does not by itself distinguish growth news, inflation news, and monetary policy.
Any structural VAR needs explicit identification assumptions and sensitivity
checks; an arbitrary variable ordering is not proof of causality.

### 5. Check robustness and predictive usefulness

Use chronological training/validation/test periods with adequate data coverage.
Keep the last holdout period untouched during lag, threshold, and feature choice.
Account for the overlap between outcome horizons at split boundaries.

Compare predictions with simple historical-mean and lagged-return baselines.
Report forecast errors, incremental explanatory value, and the stability of
effect sizes across periods. Address multiple comparisons; label exploratory
sector/regime analyses accordingly. Do not infer tradability from significance;
any later strategy study needs realistic execution, costs, and out-of-sample tests.

## Planned deliverables

1. Reproducible acquisition and validation pipeline, with explicit data gaps.
2. Data dictionary and session-alignment report.
3. Descriptive relationship charts and joint-factor estimates.
4. Shock response charts with confidence intervals and event counts.
5. Robustness and chronological holdout results.
6. Plain-language report separating supported observations, unstable findings,
   unresolved questions, and limitations on causal interpretation.

No dashboard or trading system is assumed at this stage. The first empirical
milestone is a validated daily dataset covering all five baseline series.
