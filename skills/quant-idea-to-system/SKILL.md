---
name: quant-idea-to-system
description: Turn a trading idea (how the alpha signal is generated, which extra data sources) into a tested, walk-forward quantitative trading system with the AlgoMaschine kit. Use when the user describes a new strategy idea, asks to "build / test / backtest a system", or opens a project made with `make new` from ~/algomaschine-kit.
---

# From idea to a walk-forward system (AlgoMaschine kit)

The kit lives at `~/algomaschine-kit` (library `amq`, `.mk` targets, templates, skills). The user gives the idea;
you do everything else, in this order, and you never skip a gate.

## 0. Start
- New idea -> `make -C ~/algomaschine-kit new NAME=<snake_name> [DIR=...]`, then work inside the project.
- Back up before changing an existing project: `make backup`. Commit at every milestone.
- Heavy work always runs as a capped systemd --user job (the make targets do it); never in the foreground.

## 1. Understand the idea -> IDEA.md
Fill IDEA.md with the user: mechanism (who is forced to trade / what is slow), signal computation, extra data
sources (symbol/URL, frequency, history, the clock time each value is KNOWN at), traded instrument, horizon, costs,
and what would falsify it. Ask only what you cannot infer.

## 2. Pre-register -> SPEC.md, then `make spec-lock`
Write SPEC.md (template sections) BEFORE any result on real data: data and clocks, the full configuration grid,
calibration protocol, money management, costs, overfitting controls, and the decision rule. Remove every TODO.
Keep the grid as small as the idea allows: every configuration is a trial (deflated Sharpe, PBO).
Changes later = `make spec-bump REASON="..."` (logged). Never silently edit a frozen spec.

## 3. Data -> `make data qa`
EODHD via `amq.data.eodhd` (see skill eodhd-data). Intraday series must pass the clock QA gate; drop failing years.
Extra sources: loaders in sources.py returning daily series; align with `known_before` so nothing is used before
it was known (e.g. VIX closes 15 min after the S&P: use the previous day).

## 4. Implement -> strategy.py
Subclass `amq.engine.walkforward.Strategy`:
- `grid()`: the pre-registered configurations.
- `prepare(mk)`: CAUSAL per-day features (value at t uses data up to the close of t).
- `candidates(mk, prep, cfg, train_end)`: events {e: entry index (>= decision close + 1), h: holding days,
  optional side, feat}; data-dependent transforms (FFD d*, thresholds) use only data before train_end.
- `fit_side` / `side`: anything learned (tables, models) is fitted on TRAINING events only.
Use `amq.afml` (triple barrier, trend scanning, CUSUM filter, FFD, Merrill filter, uniqueness, bet sizing).

## 5. Review gate -> `make review` (must pass before anything else)
Causality (future replaced -> identical past), purging, P&L timing, sign-flip null (OOS Sharpe ~ 0), planted
effect of full-sample t ~ 5 found. If a check fails: diagnose on SYNTHETIC data only, fix the machinery (or the
test design if it is provably wrong, e.g. a planted effect too small to be detectable), document it in SPEC.md,
re-run. Never tune on real results.

## 6. Walk-forward, report and audit -> `make walkforward report audit serve`
The engine auto-calibrates each year with purged k-fold CV, meta-labels, sizes bets, vol-targets (10%, 2x cap),
charges costs. The report adds PBO (CSCV), CPCV paths, deflated Sharpe with the project's trial ledger.
`make audit` runs the too-good-to-be-true audit (skill: backtest-audit): Reality Check against every configuration,
random timing, buy-and-hold difference, point-in-time rebuilds, fragility. Fill `[audit]` in config.toml first.
`make serve` prints the dashboard URL (token-protected; treat it as private): Results, Audit and Method pages.

## 7. Verdict (be ruthless)
Lead with the audit's verdict (not proven / inconclusive / credible so far) and its findings, in the reader's language.
Before claiming an edge, check: CI of the Sharpe, DSR, PBO, stability across halves, costs x2, and WHERE the
edge sits. The traps that faked edges before: a shared signal/entry price (enter at c+1), quotes in illiquid
hours or at a quote-source switch (EM opens, NDFs), FX without carry, dividends in overnight returns, index
autocorrelation from stale constituents (pre-1983 S&P), too many configurations for the data. Put the caveats in
config.toml [report] notes so they travel with the dashboard. Update PROGRESS/SPEC with the result.
