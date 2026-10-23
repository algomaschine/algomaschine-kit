---
name: afml-validation
description: López de Prado (AFML / MLAM) validation toolkit and checklist for quantitative strategies — purged k-fold with embargo, CPCV, sample uniqueness, triple-barrier labels, meta-labelling, bet sizing, PSR/DSR, PBO, feature importance — and how to avoid the traps. Use when calibrating parameters, choosing among many rules, labelling events, or judging whether a backtest is overfit.
---

# AFML validation (amq.afml, amq.engine)

| Need | Use | Notes |
|---|---|---|
| Cross-validation on overlapping labels | `amq.afml.core.purged_kfold(e, t1, k, embargo)` | removes training labels overlapping the test span + an embargo after it |
| Many backtest paths, not one | `cpcv_paths(N, k)` + `amq.report.build.cpcv` | N=10, k=2 -> 45 splits, 9 paths; report the path Sharpe distribution |
| Overlapping labels in training | `avg_uniqueness(e, t1, n)` | sample weights; random forest max_samples = mean uniqueness |
| Labels | `tools.triple_barrier`, `tools.trend_scan` | barriers in sigma*sqrt(h); trend scanning looks forward: labels only, inside purged training |
| Event sampling | `tools.cusum_filter`, `tools.zigzag` | CUSUM (AFML 2.5) and Merrill's filtered waves; pivots usable only after confirmation |
| Stationarity with memory | `tools.frac_diff_ffd`, `tools.ffd_select` | smallest d passing ADF on TRAINING data; FFT convolution |
| Should we take the trade / how big | meta-labelling (engine `meta=true`) + `bet_size` | size = 2*Phi(z)-1, z=(p-1/2)/sqrt(p(1-p)); average active bets |
| Is the Sharpe luck? | `psr`, `dsr(x, n_trials, var_sr)` | n_trials from the project's trial ledger: never reset it |
| Did choosing the best overfit? | `pbo_cscv(M)` on the T x N out-of-fold matrix (`walkforward.oof_matrix`) | PBO > 0.5 = the in-sample best is usually below median OOS |
| Choosing among 1e3-1e6 rules | `amq.engine.selection.select(z, alpha)` | expected false picks < alpha under a robust empirical null (median, IQR); per-family budgets |

## Traps that produced fake edges in AlgoMaschine projects
- Selecting with BH/FDR when one true effect lights up hundreds of correlated relatives: FDR loosens and lets
  ~q of that inflated count through. Bound expected false picks instead.
- Smoothed-density local fdr misses sparse strong effects; central-matching nulls can degenerate with short
  history (mu0 far from the median). Use the robust null.
- The CV score of the best of N configurations is optimistic by construction (null data gave CV Sharpe 0.4 and
  OOS 0.0): always judge out of sample and deflate.
- A planted test effect must be detectable in principle (full-sample t ~ 5); t ~ 1.5 effects are invisible to any
  honest method, and "finding" them would be a false discovery.
- Per-cell estimates (e.g. 32 pattern means) are data-starved: pool or shrink before trusting them.
