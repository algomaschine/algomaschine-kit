# __NAME__: pre-registered specification
Written BEFORE any result on real data. Frozen with `make spec-lock`; any change needs `make spec-bump REASON=...`
(logged; the trial ledger keeps counting).

## Hypothesis
TODO: the mechanism, and the prediction it makes.

## Data and clocks
TODO: sources (EODHD symbols, extra data), history, the clock time each input is known at, QA gate results.
Timing rule: a signal known at the close of c trades at the close of c+1 (never at the price that completed it).

## Grammar / configuration grid
TODO: every configuration the calibration may choose (the grid in strategy.py). Each counts as a trial.

## Calibration and walk-forward
Every 1 January from `first_year`: purged k-fold CV (embargo) on events whose labels end before the refit date
chooses the configuration; optional meta-labelling (triple barrier, random forest with uniqueness weights) sizes
bets (AFML ch. 10); the year is traded with the average of active bets.

## Money management and costs
10% volatility target, 2x leverage cap, costs on every position change (config.toml). TODO: instrument specifics.

## Overfitting controls
Pre-run review (causality, purging, timing, sign-flip null, planted t~5 effect) gates the run; deflated Sharpe
with the project's trial ledger; PBO by CSCV across the grid; CPCV paths for the most-chosen configuration.

## Decision rule
TODO: what result counts as an edge (e.g. OOS Sharpe CI lower bound > 0, DSR > 0.95, PBO < 0.5, stable halves).
