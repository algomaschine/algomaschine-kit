"""amq.audit.forensics: the "too good to be true" audit of a backtest.

Run it on ANY result that looks attractive, before anyone believes it. Each test records what it checks, why it
matters (in plain words), the pass rule and the source. The inputs are daily series on one calendar:
    ret    net daily returns of the system, as the backtest reports them
    r      daily returns of the traded asset(s), close t-1 -> close t (Series, or DataFrame with one column per asset)
    pos    positions (same shape as r): pos[t] is held from the close of t to the close of t+1, so
           ret[t+1] = sum over assets of pos[t] * r[t+1] - cost * |pos[t] - pos[t-1]|
Optional:
    universe      T x N returns of EVERYTHING tried (for the Reality Check); the system is added to it
    pbo_universe  T x N returns of the configuration grid of the system (for PBO and the plateau test)
    n_trials, var_sr   the trial ledger count and the variance of the trials' per-period Sharpe (for DSR)
    rebuild(date) -> positions computed with data up to `date` only (the point-in-time test)
    provenance    {"text": ..., "status": "pass"|"warn"|"fail"}: where the hypotheses came from

Sources: López de Prado, Advances in Financial Machine Learning (2018) ch. 7, 11-14; Bailey & López de Prado,
"The Sharpe Ratio Efficient Frontier" (2012: PSR, MinTRL) and "The Deflated Sharpe Ratio" (2014); Bailey, Borwein,
López de Prado & Zhu, "Pseudo-Mathematics and Financial Charlatanism" (2014: MinBTL) and "The Probability of Backtest
Overfitting" (2017); Harvey & Liu, "Backtesting" (2015); Harvey, Liu & Zhu, "...and the Cross-Section of Expected
Returns" (2016); White, "A Reality Check for Data Snooping" (2000); Hansen, "A Test for Superior Predictive Ability"
(2005); Ledoit & Wolf, "Robust performance hypothesis testing with the Sharpe ratio" (2008); Lo, "The Statistics of
Sharpe Ratios" (2002); Politis & Romano (1994); Newey & West (1987); Treynor & Mazuy (1966); Arnott, Harvey &
Markowitz, "A Backtesting Protocol in the Era of Machine Learning" (2019); McLean & Pontiff (2016).
"""
import re

import numpy as np
import pandas as pd
from scipy import stats

from amq.afml import core as A

PASS, WARN, FAIL, INFO = "pass", "warn", "fail", "info"
CORE = ("L0", "S1", "S3", "D1", "T1", "L2")        # a FAIL here, or in any point-in-time rebuild, decides the verdict
GROUPS = ["Luck: is the evidence strong enough?", "The search: could it be the best of many tries?",
          "The market: skill, or just being invested?", "Errors: could it have used the future?",
          "Fragility: does it hang on a few things?"]


def _sr(x, periods=252):
    x = pd.Series(x).dropna()
    return float(x.mean() / x.std() * np.sqrt(periods)) if len(x) > 20 and x.std() > 0 else np.nan


def _frame(x):
    return x.to_frame("asset") if isinstance(x, pd.Series) else x


def _costs(cost, cols):
    return pd.Series(cost, index=cols, dtype=float) if np.isscalar(cost) else pd.Series(cost, dtype=float).reindex(cols)


def _align(R, P):
    return R.set_axis(P.columns, axis=1) if R.shape[1] == P.shape[1] else R[P.columns]


def from_positions(pos, r, cost, delay=0, cap=None):
    """Daily returns implied by the positions. `delay` postpones every trade by that many days; `cap` limits each
    position to +/- cap (no leverage beyond it)."""
    P = _frame(pos).fillna(0.0)
    R = _align(_frame(r), P)
    if delay:
        P = P.shift(delay).fillna(0.0)
    if cap is not None:
        P = P.clip(-cap, cap)
    turn = P.diff().abs().fillna(P.abs())
    return (P.shift(1) * R.fillna(0.0) - turn.shift(1) * _costs(cost, P.columns)).sum(axis=1).fillna(0.0)


def _boot_idx(n, B, block, rng):
    """Politis-Romano stationary bootstrap indices (B x n), mean block length `block`."""
    new = rng.random((B, n)) < 1 / block
    new[:, 0] = True
    starts = rng.integers(n, size=(B, n))
    t = np.broadcast_to(np.arange(n), (B, n))
    p = np.maximum.accumulate(np.where(new, t, 0), axis=1)
    return (np.take_along_axis(starts, p, axis=1) + (t - p)) % n


def reality_check(X, sys_col, B=1000, block=20, seed=0):
    """White's Reality Check with Hansen's consistent recentring (SPA_c), studentised, stationary bootstrap.
    Returns (p for the system's own t, p for the best of the universe, the system's t, the best t).
    p_system = chance that the BEST of all strategies tried, when none has any skill, reaches the system's t."""
    X = np.nan_to_num(np.asarray(X, float))
    n, k = X.shape
    mu, sd = X.mean(0), X.std(0, ddof=1)
    sd = np.where(sd > 0, sd, np.inf)
    t = np.sqrt(n) * mu / sd
    thr = -sd * np.sqrt(2 * np.log(np.log(n)) / n)
    mu_c = np.where(mu >= thr, mu, 0.0)              # clearly bad strategies must not inflate the null (Hansen 2005)
    rng = np.random.default_rng(seed)
    mx = []
    for b0 in range(0, B, 100):
        idx = _boot_idx(n, min(100, B - b0), block, rng)
        cnt = np.zeros((len(idx), n))
        np.add.at(cnt, (np.repeat(np.arange(len(idx)), n), idx.ravel()), 1.0)
        mx.append(np.max(np.sqrt(n) * (cnt @ X / n - mu_c) / sd, axis=1))
    mx = np.concatenate(mx)
    p = lambda s: float((np.sum(mx >= s) + 1) / (len(mx) + 1))  # noqa: E731
    return p(t[sys_col]), p(max(t.max(), 0.0)), float(t[sys_col]), float(t.max())


def random_timing(pos, r, cost, B=1000, min_shift=21, seed=0):
    """Sharpe ratios of the same positions moved to random dates (circular shifts of the whole position path):
    same exposure, sizes, holding times and turnover; only the timing is random."""
    P = _frame(pos).fillna(0.0)
    R = _align(_frame(r), P).fillna(0.0).to_numpy(float)
    c = _costs(cost, P.columns).to_numpy()
    P = P.to_numpy(float)
    n = len(P)
    rng = np.random.default_rng(seed)
    out = np.empty(B)
    for b in range(B):
        Ps = np.roll(P, int(rng.integers(min_shift, n - min_shift)), axis=0)
        turn = np.abs(np.diff(np.vstack([np.zeros((1, P.shape[1])), Ps]), axis=0))
        x = (Ps[:-1] * R[1:] - turn[:-1] * c).sum(1)
        out[b] = x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0.0
    return out


def sharpe_difference(ret, bench, B=2000, block=20, seed=0):
    """Sharpe(system) - Sharpe(benchmark) with a paired stationary-bootstrap 95% interval and a one-sided p-value
    (in the spirit of Ledoit & Wolf 2008)."""
    x, y = ret.to_numpy(float), bench.to_numpy(float)
    idx = _boot_idx(len(x), B, block, np.random.default_rng(seed))
    sr = lambda m: m.mean(1) / m.std(1, ddof=1) * np.sqrt(252)  # noqa: E731
    d = sr(x[idx]) - sr(y[idx])
    d0 = _sr(ret) - _sr(bench)
    return d0, tuple(np.percentile(d, [2.5, 97.5])), float((np.sum(d - d0 >= d0) + 1) / (B + 1))


def _hac_ols(y, X):
    """OLS coefficients and Newey-West t-statistics."""
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    n = len(y)
    L = int(4 * (n / 100) ** (2 / 9))
    Xe = X * e[:, None]
    S = Xe.T @ Xe / n
    for l in range(1, L + 1):
        G = Xe[l:].T @ Xe[:-l] / n
        S += (1 - l / (L + 1)) * (G + G.T)
    Q = np.linalg.inv(X.T @ X / n)
    V = Q @ S @ Q / n
    return b, b / np.sqrt(np.diag(V))


def audit(name, ret, r, pos=None, cost=1e-4, bench=None, n_trials=1, var_sr=None, universe=None, pbo_universe=None,
          rebuild=None, rebuild_dates=(), provenance=None, start=None, B=1000, sr_implausible=3.0):
    """Returns {name, period, verdict, verdict_text, summary, tests}. Each test: id, group, title, value, rule,
    status (pass/warn/fail/info), why (plain words), ref (literature)."""
    idx = ret.index if start is None else ret.index[ret.index >= pd.Timestamp(start)]
    ret = ret.reindex(idx).fillna(0.0)
    R = _frame(r).reindex(idx)
    P = None if pos is None else _frame(pos).reindex(idx).fillna(0.0)
    if P is not None:
        R = _align(R, P)
    bench = (R.mean(axis=1) if bench is None else bench.reindex(idx)).fillna(0.0)
    T = []

    def add(tid, group, title, value, rule, status, why, ref, **data):
        T.append({"id": tid, "group": group, "title": title, "value": re.sub(r"(?<![\w.])-(?=\d)", "\u2212", value), "rule": rule,
                  "status": status, "why": why, "ref": ref, "data": data})

    n = len(ret)
    years = n / 252
    sr = _sr(ret)
    # ------------------------------------------------------------------ 1. statistical evidence
    ci = A.stationary_bootstrap_sr(ret)
    add("S1", GROUPS[0], "Sharpe ratio and its 95% confidence interval", f"{sr:.2f} [{ci[0]:.2f}, {ci[1]:.2f}]",
        "pass if the interval excludes zero", PASS if ci[0] > 0 else (WARN if sr > 0 else FAIL),
        "The Sharpe ratio is return per unit of risk. From a finite history it is only an estimate; the interval is the "
        "range of true values consistent with the data (stationary bootstrap, which keeps calm and stormy spells together).",
        "Politis & Romano (1994); Lo (2002)", sr=sr, lo=ci[0], hi=ci[1])
    psr = A.psr(ret)
    add("S2", GROUPS[0], "Probabilistic Sharpe ratio (PSR)", f"{psr:.2f}", "pass ≥ 0.95, warn ≥ 0.80",
        PASS if psr >= 0.95 else (WARN if psr >= 0.8 else FAIL),
        "The probability that the true Sharpe is above zero, allowing for the length of the record and for skew and fat tails.",
        "Bailey & López de Prado (2012)")
    if var_sr is None and pbo_universe is not None:
        var_sr = float(np.var(pbo_universe.apply(lambda c: c.mean() / c.std() if c.std() > 0 else np.nan).dropna()))
    if var_sr:
        dsr = A.dsr(ret, max(n_trials, 2), var_sr)
        add("S3", GROUPS[0], "Deflated Sharpe ratio (DSR)", f"{dsr:.2f} after {n_trials} trials", "pass ≥ 0.95, warn ≥ 0.50",
            PASS if dsr >= 0.95 else (WARN if dsr >= 0.5 else FAIL),
            "The PSR measured against the best Sharpe that the same number of strategies with NO skill would produce by luck. "
            "The more that was tried, the higher the bar.", "Bailey & López de Prado (2014)", dsr=dsr, n_trials=n_trials)
    srd = ret.mean() / ret.std() if ret.std() > 0 else 0.0
    if srd > 0:
        g3, g4 = stats.skew(ret), stats.kurtosis(ret, fisher=False)
        mintrl = 1 + (1 - g3 * srd + (g4 - 1) / 4 * srd ** 2) * (stats.norm.ppf(0.95) / srd) ** 2
        add("S4", GROUPS[0], "Minimum track record length (MinTRL)", f"needs {mintrl / 252:.1f} years, has {years:.1f}",
            "pass if the record is at least MinTRL", PASS if n >= mintrl else FAIL,
            "How many years of this return stream are needed before its Sharpe is significant at 95%.",
            "Bailey & López de Prado (2012)", years_needed=mintrl / 252, years=years)
        if n_trials > 1:
            minbtl = 2 * np.log(n_trials) / sr ** 2
            add("S5", GROUPS[0], "Minimum backtest length for the number of trials (MinBTL)",
                f"needs {minbtl:.1f} years for {n_trials} trials, has {years:.1f}", "warn if the history is shorter",
                PASS if years >= minbtl else WARN,
                "Try N strategies on pure noise and the best one shows a Sharpe of about √(2·ln N / years). The history "
                "must be long enough that the observed Sharpe could not be that artefact (trials that resemble each other "
                "count for less, so this is a strict version).", "Bailey, Borwein, López de Prado & Zhu (2014)")
    tstat = sr * np.sqrt(years)
    p_adj = min(1.0, 2 * stats.norm.sf(abs(tstat)) * max(n_trials, 1))
    hsr = stats.norm.isf(p_adj / 2) / np.sqrt(years) if p_adj < 1 else 0.0
    add("S6", GROUPS[0], "t-statistic and the Sharpe after a multiple-testing haircut",
        f"t = {tstat:.2f}; haircut Sharpe {hsr:.2f} (from {sr:.2f})", "pass if t > 3 and the adjusted p < 0.05; warn if t > 2",
        PASS if (tstat > 3 and p_adj < 0.05) else (WARN if tstat > 2 else FAIL),
        "Adjusts the Sharpe for every trial run (Bonferroni), as a sceptical referee would. Harvey, Liu & Zhu argue that "
        "a new effect should clear t > 3, not the usual 2.", "Harvey & Liu (2015); Harvey, Liu & Zhu (2016)", t=tstat, haircut=hsr)
    def lo_factor(x, q=252):
        ac = [x.autocorr(k) for k in range(1, 11)]
        return float(np.sqrt(q / max(q + 2 * sum((q - k) * rho for k, rho in enumerate(ac, 1) if np.isfinite(rho)), 1e-9)))
    adj_raw = lo_factor(ret)
    adj = lo_factor(ret.clip(ret.quantile(0.01), ret.quantile(0.99)))    # outliers must not drive the estimate
    add("S7", GROUPS[0], "Sharpe adjusted for autocorrelation", f"{sr * adj:.2f} (×{adj:.2f}; ×{adj_raw:.2f} before trimming the 1% extremes)",
        "warn if the adjustment removes more than 20%", PASS if adj >= 0.8 else WARN,
        "Returns that trend from day to day (smoothed prices, overlapping positions) make the annualised Sharpe look better "
        "than it is. Estimated with the most extreme 1% of days trimmed so that a few big days do not decide it.", "Lo (2002)")
    # ------------------------------------------------------------------ 2. data snooping
    if universe is not None and universe.shape[1] >= 1:
        U = universe.reindex(idx).fillna(0.0)
        U = U.loc[:, U.std() > 0]
        X = np.column_stack([U.to_numpy(float), ret.to_numpy(float)])
        p_sys, p_best, t_sys, t_best = reality_check(X, X.shape[1] - 1, B=B)
        add("D1", GROUPS[1], "Reality Check against everything that was tried",
            f"p = {p_sys:.3f} (system t {t_sys:.2f}; best of {X.shape[1]:,} strategies t {t_best:.2f}, p {p_best:.3f})",
            "pass p < 0.05, warn < 0.20", PASS if p_sys < 0.05 else (WARN if p_sys < 0.2 else FAIL),
            "Asks: if none of the strategies ever tried had any skill, how often would the luckiest of them look at least as "
            "good as this system? A small p means the system stands out from the search that produced it.",
            "White (2000); Hansen (2005)", p=p_sys, t=t_sys, t_best=t_best, p_best=p_best, k=X.shape[1])
    if pbo_universe is not None and pbo_universe.shape[1] > 1:
        G = pbo_universe.reindex(idx).fillna(0.0)
        pbo = A.pbo_cscv(G, 16)["pbo"]
        add("D2", GROUPS[1], "Probability of backtest overfitting (PBO)", f"{pbo:.2f} over {G.shape[1]} configurations",
            "pass < 0.20, warn < 0.50", PASS if pbo < 0.2 else (WARN if pbo < 0.5 else FAIL),
            "Splits the history into halves in every possible way: how often does the configuration that was best in one "
            "half land below the median in the other?", "Bailey, Borwein, López de Prado & Zhu (2017)")
        share = float((G.apply(_sr) > 0).mean())
        add("D3", GROUPS[1], "Plateau: share of configurations with a positive Sharpe", f"{share:.0%} of {G.shape[1]}",
            "warn below 30%", PASS if share >= 0.3 else WARN,
            "A real effect shows up across neighbouring settings (a plateau), not in one lucky corner of the grid.",
            "López de Prado (2018) ch. 11")
    # ------------------------------------------------------------------ 3. skill vs market
    if P is not None:
        rt = random_timing(P, R, cost, B=B)
        p_t = float((np.sum(rt >= sr) + 1) / (len(rt) + 1))
        add("T1", GROUPS[2], "Random-timing test (same trades at random dates)",
            f"p = {p_t:.3f}; random timing gives a median Sharpe of {np.median(rt):.2f} (95th percentile {np.percentile(rt, 95):.2f})",
            "pass p < 0.05, warn < 0.20", PASS if p_t < 0.05 else (WARN if p_t < 0.2 else FAIL),
            "Keeps every position, its size, length and the time spent in the market, but slides the whole sequence to random "
            "start dates. If random timing does as well, the result comes from being in a rising market, not from knowing when.",
            "Aronson (2006); Arnott, Harvey & Markowitz (2019)", p=p_t, median=float(np.median(rt)), p95=float(np.percentile(rt, 95)))
    d0, dci, dp = sharpe_difference(ret, bench)
    add("T2", GROUPS[2], "Better than simply holding the market?", f"Sharpe difference {d0:+.2f} [{dci[0]:+.2f}, {dci[1]:+.2f}], p = {dp:.3f}",
        "pass if the interval excludes zero; warn if the difference is positive", PASS if dci[0] > 0 else (WARN if d0 > 0 else FAIL),
        "Compares risk-adjusted return with buy-and-hold over the same days, resampling both together so shared market "
        "moves cancel out.", "Ledoit & Wolf (2008)", diff=d0, lo=dci[0], hi=dci[1], p=dp, bench_sr=_sr(bench))
    y = ret.to_numpy(float)
    m = bench.to_numpy(float)
    b, tb = _hac_ols(y, np.column_stack([np.ones(n), m]))
    add("T3", GROUPS[2], "Alpha after market beta", f"beta {b[1]:.2f}; alpha {b[0] * 252:+.2%} a year, t {tb[0]:.2f}",
        "pass t > 2, warn t > 1", PASS if tb[0] > 2 else (WARN if tb[0] > 1 else FAIL),
        "Removes the part of the return explained by the market's own moves (beta) and tests what is left (Newey-West t).",
        "Sharpe (1964); Newey & West (1987)", beta=b[1], alpha=b[0] * 252, t=tb[0])
    bq, tq = _hac_ols(y, np.column_stack([np.ones(n), m, m ** 2]))
    add("T4", GROUPS[2], "Market-timing convexity (Treynor–Mazuy)", f"gamma {bq[2]:.2f} (t {tq[2]:.2f})", "information", INFO,
        "A positive gamma means the system gains more in big market moves than in small ones: timing skill, or an "
        "option-like exposure.", "Treynor & Mazuy (1966)")
    # ------------------------------------------------------------------ 4. look-ahead and timing
    add("L0", GROUPS[3], "Plausibility of the Sharpe ratio", f"{sr:.2f}",
        f"fail above {sr_implausible:.0f}, warn above {sr_implausible - 1:.0f}",
        FAIL if sr > sr_implausible else (WARN if sr > sr_implausible - 1 else PASS),
        "Daily strategies on liquid markets with backtested Sharpe ratios far above 2 almost always contain an error, "
        "usually information from the future. A practitioners' rule of thumb, not a theorem.", "Practitioner consensus")
    if P is not None:
        dl = {d: _sr(from_positions(P, R, cost, delay=d)) for d in (0, 1, 2, 5)}
        keep = dl[1] / dl[0] if dl[0] and dl[0] > 0 else np.nan
        add("L1", GROUPS[3], "Execution-delay profile", " · ".join(f"+{d} d: {v:.2f}" for d, v in dl.items()),
            "warn if one day of delay removes more than half the Sharpe", PASS if (np.isfinite(keep) and keep >= 0.5) else WARN,
            "Trades are postponed by 1, 2 and 5 days. Real information usually fades gradually. An edge that vanishes with a "
            "one-day delay needs exact timing (a calendar effect), or it is a sign of look-ahead.",
            "López de Prado (2018) ch. 11; Arnott, Harvey & Markowitz (2019)", **{f"d{k}": v for k, v in dl.items()})
        rec = from_positions(P, R, cost)
        cor = float(np.corrcoef(rec, ret)[0, 1])
        gap = float((ret - rec).mean() * 252)
        add("L2", GROUPS[3], "Returns rebuilt from positions and next-day prices",
            f"correlation {cor:.4f}; reported minus rebuilt {gap:+.2%} a year",
            "pass if correlation ≥ 0.99 and the gap is under 0.25% a year",
            PASS if (cor >= 0.99 and abs(gap) < 0.0025) else (WARN if cor >= 0.95 else FAIL),
            "Recomputes each day's profit as yesterday's position times today's price change, minus costs on every change "
            "in position. A gap means the reported returns used information, or skipped costs, that the positions do not explain.",
            "López de Prado (2018) ch. 7", corr=cor, gap=gap)
    if rebuild is not None and P is not None:
        for dt in rebuild_dates:
            p2 = _frame(rebuild(dt)).fillna(0.0)
            p2 = p2.set_axis(P.columns, axis=1) if p2.shape[1] == P.shape[1] else p2[P.columns]
            common = p2.index.intersection(P.index)
            common = common[common < pd.Timestamp(dt)][:-1]   # the cut-off run must close a still-open trade on its last day
            diff = np.abs(p2.loc[common].to_numpy() - P.loc[common].to_numpy())
            worst = float(diff.max()) if len(common) else np.nan
            rel = worst / max(float(P.loc[common].abs().to_numpy().max()), 1e-12) if len(common) else np.nan
            n_diff = int((diff.max(axis=1) > 1e-9).sum()) if len(common) else 0
            add(f"L3-{str(dt)[:10]}", GROUPS[3], f"Point-in-time rebuild with data up to {str(dt)[:10]}",
                f"{len(common):,} days compared (all but the last before the cut); {n_diff} differ; largest difference {worst:.1e} "
                f"({rel:.1%} of the largest position)",
                "pass if identical (below 1e-9)", INFO if not len(common) else (PASS if worst < 1e-9 else FAIL),
                "Re-runs the whole pipeline as if today were that date, then compares every earlier position with the full run. "
                "Any difference means the past used the future.", "Arnott, Harvey & Markowitz (2019)",
                n=len(common), n_diff=n_diff, worst=worst, rel=rel)
    if provenance:
        add("L4", GROUPS[3], "Where the idea came from", provenance["text"], "warn if the hypothesis was already known to work on this data",
            provenance.get("status", WARN),
            "Testing an idea because it is already known to have worked on this market is look-ahead in the design, even when "
            "the code is clean. Published anomalies also tend to weaken after publication.",
            "Harvey, Liu & Zhu (2016); McLean & Pontiff (2016)")
    # ------------------------------------------------------------------ 5. robustness
    if P is not None:
        c2, c3 = _sr(from_positions(P, R, 2 * _costs(cost, P.columns))), _sr(from_positions(P, R, 3 * _costs(cost, P.columns)))
        add("R1", GROUPS[4], "Costs doubled and tripled", f"Sharpe {c2:.2f} at ×2, {c3:.2f} at ×3",
            "pass if doubling costs keeps half the Sharpe", PASS if sr > 0 and c2 >= 0.5 * sr else WARN,
            "Real fills are worse than the model assumes; an edge must survive that.", "Arnott, Harvey & Markowitz (2019)")
        gross = P.abs().sum(axis=1)
        c1 = _sr(from_positions(P, R, cost, cap=1.0))
        on = gross[gross > 0]
        add("R2", GROUPS[4], "Leverage used, and the result without leverage",
            f"when invested: median {on.median():.2f}×, 95th percentile {on.quantile(0.95):.2f}×; Sharpe with a 1× cap {c1:.2f}",
            "warn if the Sharpe halves without leverage", PASS if c1 >= 0.5 * sr else WARN,
            "Volatility targeting borrows more in quiet markets. Leverage scales profits and losses alike, and it can also "
            "change the shape of the results.", "Moreira & Muir (2017)", median=float(on.median()) if len(on) else 0.0,
            p95=float(on.quantile(0.95)) if len(on) else 0.0, sr_1x=c1)
        entries = int(((gross > 0) & (gross.shift(1).fillna(0) == 0)).sum())
        add("R6", GROUPS[4], "Number of independent bets", f"{entries} separate positions; invested {float((gross > 0).mean()):.0%} of days",
            "warn below 50", PASS if entries >= 50 else WARN,
            "Statistics built on a few dozen trades are fragile: two or three trades can make or break the result.",
            "López de Prado (2018) ch. 4", entries=entries, invested=float((gross > 0).mean()))
    h = n // 2
    s1, s2 = _sr(ret.iloc[:h]), _sr(ret.iloc[h:])
    yr = ret.groupby(ret.index.year).sum()
    yr = yr[ret.groupby(ret.index.year).size() > 60]
    share = float((yr > 0).mean())
    roll = ret.rolling(756).apply(lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan, raw=True)
    add("R3", GROUPS[4], "Stability over time",
        f"first half {s1:.2f}, second half {s2:.2f}; {share:.0%} of years positive; rolling 3-year Sharpe {roll.min():.2f} to {roll.max():.2f}",
        "pass if both halves > 0 and at least 60% of years are positive",
        PASS if (s1 > 0 and s2 > 0 and share >= 0.6) else (WARN if (s1 > 0 or s2 > 0) else FAIL),
        "A real edge should work in both halves of the sample and in most years, not in one lucky stretch.",
        "López de Prado (2018) ch. 11", first=s1, second=s2, share_years=share)
    top = ret.sort_values(ascending=False)
    share_top = float(top.iloc[:max(1, n // 100)].sum() / ret.sum()) if ret.sum() > 0 else np.nan
    ex10 = _sr(ret.drop(top.index[:10]))
    top_txt = f"best 1% of days = {share_top:.0%} of total profit" if np.isfinite(share_top) else "no net profit to attribute"
    add("R4", GROUPS[4], "Dependence on a few days", f"{top_txt}; Sharpe without the best 10 days {ex10:.2f}",
        "warn if removing the best 10 days halves the Sharpe", PASS if ex10 >= 0.5 * sr else WARN,
        "If a handful of days make the whole result, missing one of them changes the story.", "Taleb (2007)", ex10=ex10, top_share=share_top)
    active = ret[ret != 0]
    sk, ku = stats.skew(active), stats.kurtosis(active, fisher=False)
    wk = ret.rolling(5).sum().min()
    add("R5", GROUPS[4], "Shape of the losses", f"on days with a position: skew {sk:.2f}, kurtosis {ku:.1f}; worst day {ret.min():.2%}, worst week {wk:.2%}",
        "warn if skew < −1 (rare large losses)", PASS if sk >= -1 else WARN,
        "Strategies that earn small, steady gains and occasionally lose big look excellent until the loss arrives. Measured "
        "on days with a position, so that flat days do not distort the shape.", "Lo (2002)")
    by_year = ret.groupby(ret.index.year).sum()
    best_share = float(by_year.max() / by_year.sum()) if by_year.sum() > 0 else np.nan
    ex_best = _sr(ret[ret.index.year != by_year.idxmax()])
    yr_txt = f"best year {by_year.idxmax()} = {best_share:.0%} of total profit" if np.isfinite(best_share) else f"no net profit (best year {by_year.idxmax()})"
    add("R7", GROUPS[4], "Dependence on one year", f"{yr_txt}; Sharpe without it {ex_best:.2f}",
        "warn if the best year is more than half the profit", PASS if (np.isfinite(best_share) and best_share <= 0.5) else WARN,
        "A result that rests on one exceptional year is a story about that year, not a repeatable edge.",
        "López de Prado (2018) ch. 11", year=int(by_year.idxmax()), share=best_share, ex_best=ex_best)
    # ------------------------------------------------------------------ verdict
    core_fail = any(t["status"] == FAIL and (t["id"] in CORE or t["id"].startswith("L3")) for t in T)
    n_fail = sum(t["status"] == FAIL for t in T)
    n_warn = sum(t["status"] == WARN for t in T)
    if core_fail:
        verdict, text = "not proven", "Not proven: luck, the market, the search or a data error can explain the result."
    elif n_fail or n_warn >= 3:
        verdict, text = "inconclusive", "Inconclusive: promising in places, but not proven."
    else:
        verdict, text = "credible", "Credible so far: paper-trade it before committing capital."
    return {"name": name, "period": f"{idx[0].date()} – {idx[-1].date()}", "verdict": verdict, "verdict_text": text,
            "sharpe": sr, "summary": {"pass": sum(t["status"] == PASS for t in T), "warn": n_warn, "fail": n_fail,
                                      "info": sum(t["status"] == INFO for t in T)},
            "tests": sorted(T, key=lambda t: (GROUPS.index(t["group"]), t["id"]))}


def summarize(a, market="the market"):
    """The audit's conclusions in plain words (HTML), built from the test results."""
    T = {t["id"]: t for t in a["tests"]}
    d = lambda i: T.get(i, {}).get("data", {})  # noqa: E731
    why = a["verdict_text"].split(":", 1)[1].strip()
    F = [f"<b>Verdict: {a['verdict']}.</b> {why[:1].upper() + why[1:]} Sharpe ratio {a['sharpe']:.2f} over {a['period']}."]
    if "D1" in T:
        F.append(f"<b>{'The search can explain it' if d('D1')['p'] >= 0.05 else 'It stands out from the search'}.</b> Among the "
                 f"{d('D1')['k']:,} strategies tried, the luckiest would match its t-statistic of {d('D1')['t']:.2f} in "
                 f"{d('D1')['p']:.0%} of worlds with no skill (Reality Check).")
    if "S3" in T:
        F.append(f"<b>Deflated Sharpe ratio {d('S3')['dsr']:.2f}</b> after {d('S3')['n_trials']} trials (0.95 needed); the "
                 f"multiple-testing haircut leaves a Sharpe ratio of {d('S6').get('haircut', float('nan')):.2f}.")
    t2 = d("T2")
    head = "Significantly worse than" if t2["hi"] < -0.005 else ("Not significantly better than" if t2["lo"] <= 0.005 else "Significantly better than")
    F.append(f"<b>{head} holding {market}:</b> Sharpe ratio difference {t2['diff']:+.2f}, 95% interval {t2['lo']:+.2f} to {t2['hi']:+.2f}.")
    if "T1" in T:
        F.append(f"<b>Random timing</b> gives a median Sharpe ratio of {d('T1')['median']:.2f}; the system beats "
                 f"{1 - d('T1')['p']:.0%} of the random placements.")
    if "R7" in T and np.isfinite(d("R7").get("share", np.nan)):
        F.append(f"<b>Dependence on one year:</b> {d('R7')['year']} provided {d('R7')['share']:.0%} of the profit; without it the "
                 f"Sharpe ratio is {d('R7')['ex_best']:.2f}.")
    l3 = [t for t in a["tests"] if t["id"].startswith("L3")]
    if l3:
        F.append("<b>Point-in-time rebuilds:</b> " + "; ".join(f"cut at {t['id'][3:]}: {t['data']['n']:,} earlier days, "
                                                             f"{t['data']['n_diff']} different" for t in l3) + ".")
    if "S4" in T:
        F.append(f"<b>What would change the verdict:</b> new data. At this Sharpe ratio the record needs about "
                 f"{d('S4')['years_needed']:.0f} years to be significant on its own (MinTRL); paper-trade it unchanged.")
    return [re.sub(r"(?<![\w.])-(?=\d)", "\u2212", f) for f in F]
