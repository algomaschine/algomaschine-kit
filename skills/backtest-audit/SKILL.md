---
name: backtest-audit
description: The "too good to be true" forensic audit of any backtest or walk-forward result — luck (bootstrap Sharpe CI, PSR, DSR, MinTRL, MinBTL, Harvey–Liu haircut, Lo autocorrelation), the search (White Reality Check / Hansen SPA over everything tried, PBO, plateau), the market (random-timing null, Sharpe difference vs buy-and-hold, HAC alpha, Treynor–Mazuy), look-ahead (plausibility, execution-delay profile, returns rebuilt from positions, point-in-time rebuilds, design provenance) and fragility (costs x2/x3, leverage, stability, top days, one year, tails, bet count). Use whenever a result looks attractive, before anyone believes or trades it, or when asked whether a backtest is overfit, leaky or real.
---

# Backtest audit (amq.audit.forensics)

Run it on every result that looks good. A backtest can be explained by **luck**, **the search**, **the market** or an **error**
before skill; the audit tests each, plus **fragility**. Rules are fixed in code, so they cannot be bent after seeing results.

## In a kit project
```bash
make report      # writes results.json, oof.pkl (every configuration's out-of-fold returns) and var_sr
make audit       # capped job -> outputs/audit.json; the dashboard's Audit tab shows it
```
`config.toml`:
```toml
[audit]
rebuild = ["2015-01-01"]            # point-in-time re-runs of the whole walk-forward; every earlier position must match
provenance = "where the idea came from, and whether it was already known to work on this data"
provenance_status = "warn"          # "pass" only if the idea was fixed before looking at this market's history
# start = "2010-01-01"              # optional audit window
```

## Anywhere else (any backtest, any engine)
```python
from amq.audit import forensics as F
a = F.audit(name, ret, r, pos, cost=1e-4, bench=r_market, n_trials=N, var_sr=V,
            universe=U, pbo_universe=G, rebuild=lambda dt: positions_with_data_before(dt),
            rebuild_dates=["2019-07-01"], provenance={"text": "...", "status": "warn"}, start="2014-01-01")
F.summarize(a)      # plain-English findings (HTML) for reports
```
Conventions that must hold, or the look-ahead tests are meaningless:
- `pos[t]` is the position held from the close of t to the close of t+1, so `ret[t+1] = pos[t]*r[t+1] - cost*|pos[t]-pos[t-1]|`.
  Multi-asset: `pos` and `r` as DataFrames with the same columns; `cost` per column.
- `universe` = the daily returns of EVERYTHING tried on this data (configurations, rules, earlier kernels). Leaving things
  out makes the Reality Check lenient; say so if you must.
- `n_trials` comes from the project's trial ledger (never reset); `var_sr` = variance of the trials' per-period Sharpes.
- `rebuild(dt)` must recompute the pipeline from raw data cut at `dt` (not slice a finished run). The last day before the
  cut is excluded automatically (a cut-off run must close still-open trades there).

## Reading the verdict
- **Not proven**: a core test fails (plausibility, Sharpe CI, DSR, Reality Check, random timing, rebuilt returns, any
  point-in-time rebuild). Luck, the market, the search or an error can explain the result.
- **Inconclusive**: no core failure, but another failure or three or more warnings.
- **Credible so far**: next step is paper trading, never capital.
Report failures honestly, with the numbers, in the language of the reader (the dashboard and `summarize` do this).

## What the audit has caught in AlgoMaschine projects
- A leverage cap that used a risk estimate from the LAST year for every earlier year (a dict keyed by rule name kept the
  final value): positions off by up to 3% on 61 of 1,381 days. Invisible in the results; the point-in-time rebuild found it.
- A synthesis with Sharpe 0.83 vs 0.65 for the index that did not survive the Reality Check against the ~4,000 rules tried
  (p = 0.81) or deflation (DSR 0.86), and was not significantly better than buy-and-hold.
- A pattern model whose 2014-2026 record rested on one year (87% of the profit), with 23 separate positions in 12 years.
- A calendar rule that collapses with a one-day delay: exact timing matters (a calendar effect, not look-ahead) and it was
  already published (design provenance).

## Sources
White (2000); Hansen (2005); Bailey & López de Prado (2012, 2014); Bailey, Borwein, López de Prado & Zhu (2014, 2017);
Harvey & Liu (2015); Harvey, Liu & Zhu (2016); Ledoit & Wolf (2008); Lo (2002); Politis & Romano (1994); Newey & West
(1987); Treynor & Mazuy (1966); Aronson (2006); Arnott, Harvey & Markowitz (2019); McLean & Pontiff (2016);
Moreira & Muir (2017). The dashboard's Method page explains every test with formulas.
