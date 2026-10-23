"""amq.afml.core: López de Prado, AFML (2018) and MLAM (2020), for event data with label intervals.
Extracted from the AlgoMaschine S&P lab (reviewed and tested there).

An event i has an entry index e_i (position taken at the close of e_i) and a label end index t1_i
(last day whose return belongs to the label). Everything below is expressed on the integer day index.
"""
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats


# ------------------------------------------------------------------ uniqueness (AFML 4.2-4.4)
def concurrency(e, t1, n):
    """Number of labels active on each day (a label covers the returns of days e+1 .. t1)."""
    c = np.zeros(n + 1)
    np.add.at(c, e + 1, 1)
    np.add.at(c, np.minimum(t1 + 1, n), -1)
    return np.cumsum(c)[:n]


def avg_uniqueness(e, t1, n):
    """Average uniqueness of each label: mean over its days of 1 / concurrency (AFML snippet 4.2)."""
    c = concurrency(e, t1, n)
    inv = np.where(c > 0, 1.0 / np.maximum(c, 1), 0.0)
    cs = np.r_[0, np.cumsum(inv)]
    lo, hi = e + 1, np.minimum(t1, n - 1) + 1
    ln = np.maximum(hi - lo, 1)
    return (cs[hi] - cs[lo]) / ln


# ------------------------------------------------------------------ purged k-fold with embargo (AFML 7.4)
def purged_kfold(e, t1, k=5, embargo=0.01):
    """Yield (train_idx, test_idx) over events sorted by entry. Test folds are contiguous in time;
    training events whose label interval [e, t1] overlaps the test span are purged, and so are the
    events that start within the embargo after the test span."""
    order = np.argsort(e, kind="stable")
    folds = np.array_split(order, k)
    span = int(max(e.max() - e.min(), 1) * embargo)
    for f in folds:
        if not len(f):
            continue
        lo, hi = e[f].min(), t1[f].max()
        test = np.zeros(len(e), bool)
        test[f] = True
        overlap = (e <= hi) & (t1 >= lo)
        emb = (e > hi) & (e <= hi + span)
        train = ~test & ~overlap & ~emb
        yield np.where(train)[0], f


# ------------------------------------------------------------------ CPCV (AFML 12.4)
def cpcv_splits(n_obs, n_groups=10, k_test=2):
    """Combinatorial purged CV on a time index 0..n_obs-1: every choice of k_test groups is a test set.
    Returns the list of (test group ids) and the group boundaries; paths are assembled by cpcv_paths."""
    bounds = np.array_split(np.arange(n_obs), n_groups)
    return list(combinations(range(n_groups), k_test)), bounds


def cpcv_paths(n_groups=10, k_test=2):
    """Assign each (split, test group) to a backtest path: every group appears in exactly
    phi = C(N-1, k-1) splits, which gives phi complete paths (AFML 12.4.2)."""
    splits = list(combinations(range(n_groups), k_test))
    phi = len([s for s in splits if 0 in s])
    counter = {g: 0 for g in range(n_groups)}
    assign = []
    for s in splits:
        a = []
        for g in s:
            a.append((g, counter[g]))
            counter[g] += 1
        assign.append(a)
    return splits, assign, phi


# ------------------------------------------------------------------ bet sizing (AFML 10.3)
def bet_size(p, step=0.1):
    """Size from the meta-model probability of success: 2*Phi(z) - 1 with z = (p - 1/2)/sqrt(p(1-p));
    no bet when p <= 1/2; discretised to `step`."""
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    z = (p - 0.5) / np.sqrt(p * (1 - p))
    s = np.where(p > 0.5, 2 * stats.norm.cdf(z) - 1, 0.0)
    return np.round(s / step) * step


def average_active(e, t1, size, n):
    """Daily position = mean of the sizes of the bets active on that day (AFML 10.4). A bet entered
    at the close of e is held for the returns of days e+1 .. t1; returned pos[t] is the position held
    from the close of t to the close of t+1."""
    num = np.zeros(n + 1)
    den = np.zeros(n + 1)
    np.add.at(num, e, size)
    np.add.at(num, np.minimum(t1, n), -size)
    np.add.at(den, e, 1.0)
    np.add.at(den, np.minimum(t1, n), -1.0)
    num, den = np.cumsum(num)[:n], np.cumsum(den)[:n]
    return np.where(den > 0.5, num / np.maximum(den, 1), 0.0)


# ------------------------------------------------------------------ money management and P&L
def vol_target_position(pos, sigma, target=0.10, cap=2.0):
    """Position scaled to an annual volatility target with the asset's EWMA sigma known at t."""
    k = np.minimum(cap, target / np.sqrt(252) / np.maximum(sigma, 1e-8))
    return pos * np.nan_to_num(k)


def pnl(pos, r_next, cost_per_unit=1e-4):
    """Net daily return: pos[t] (held close t -> close t+1) times r[t+1], minus cost on |pos[t] - pos[t-1]|."""
    turn = np.abs(np.diff(np.r_[0.0, pos]))
    return pos * np.nan_to_num(r_next) - cost_per_unit * turn, turn


def strategy_vol_target(u, exposure=None, target=0.10, cap=2.0, halflife=20):
    """Scale a unit-return stream to the target with its own EWMA vol up to t-1; exposure (notional per
    unit) caps the leverage at `cap`."""
    s = pd.Series(u)
    vol = np.sqrt((s ** 2).ewm(halflife=halflife, min_periods=20).mean().shift(1)).to_numpy()
    k = target / np.sqrt(252) / np.where(vol > 0, vol, np.nan)
    if exposure is not None:
        k = np.minimum(k, cap / np.maximum(np.asarray(exposure, float), 1e-12))
    return np.nan_to_num(k) * np.nan_to_num(u)


# ------------------------------------------------------------------ statistics
def perf(ret, bench=None, periods=252):
    x = pd.Series(ret).dropna()
    if len(x) < 30:
        return {}
    eq = np.exp(np.cumsum(np.log1p(x)))
    yrs = len(x) / periods
    dd = eq / np.maximum.accumulate(eq) - 1
    sr = x.mean() / x.std() * np.sqrt(periods) if x.std() > 0 else np.nan
    dn = x[x < 0].std()
    out = {"cagr": float(eq.iloc[-1] ** (1 / yrs) - 1), "vol": float(x.std() * np.sqrt(periods)), "sharpe": float(sr),
           "sortino": float(x.mean() / dn * np.sqrt(periods)) if dn > 0 else np.nan, "maxdd": float(dd.min()),
           "calmar": float((eq.iloc[-1] ** (1 / yrs) - 1) / -dd.min()) if dd.min() < 0 else np.nan,
           "hit": float((x[x != 0] > 0).mean()) if (x != 0).any() else np.nan, "exposure_days": float((x != 0).mean()),
           "psr0": psr(x), "years": yrs}
    if bench is not None:
        b = pd.Series(bench).reindex(x.index).fillna(0)
        cov = np.cov(x, b)
        beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 0 else np.nan
        out.update({"beta": float(beta), "corr": float(np.corrcoef(x, b)[0, 1]),
                    "alpha_ann": float((x.mean() - beta * b.mean()) * periods)})
    return out


def psr(x, sr_star=0.0):
    x = pd.Series(x).dropna()
    n = len(x)
    if n < 10 or x.std() == 0:
        return np.nan
    sr = x.mean() / x.std(ddof=1)
    g3, g4 = stats.skew(x), stats.kurtosis(x, fisher=False)
    return float(stats.norm.cdf((sr - sr_star) * np.sqrt(n - 1) / np.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2, 1e-12))))


def dsr(x, n_trials, var_sr):
    """Deflated Sharpe ratio: PSR against the expected maximum SR of n_trials unskilled trials."""
    g = 0.5772156649015329
    z = stats.norm.ppf
    e_max = np.sqrt(var_sr) * ((1 - g) * z(1 - 1 / n_trials) + g * z(1 - 1 / (n_trials * np.e))) if n_trials > 1 else 0.0
    return psr(x, e_max)


# ------------------------------------------------------------------ more statistics (from the factory)
def nw_tstat(r, lags=None):
    """Newey-West HAC t-statistic of the mean."""
    x = pd.Series(r).dropna().to_numpy(float)
    n = len(x)
    if n < 10:
        return np.nan
    lags = lags if lags is not None else int(np.floor(4 * (n / 100) ** (2 / 9)))
    e = x - x.mean()
    s = e @ e / n
    for L in range(1, lags + 1):
        s += 2 * (1 - L / (lags + 1)) * (e[L:] @ e[:-L]) / n
    return float(x.mean() / np.sqrt(s / n)) if s > 0 else np.nan


def stationary_bootstrap_sr(r, periods=252, n_boot=2000, block=20, seed=0):
    """Politis-Romano stationary bootstrap 95% CI of the annualised Sharpe."""
    x = pd.Series(r).dropna().to_numpy(float)
    n = len(x)
    if n < 50:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    new = rng.random((n_boot, n)) < 1 / block
    new[:, 0] = True
    starts = rng.integers(n, size=(n_boot, n))
    t = np.broadcast_to(np.arange(n), (n_boot, n))
    pos = np.maximum.accumulate(np.where(new, t, 0), axis=1)
    idx = (np.take_along_axis(starts, pos, axis=1) + (t - pos)) % n
    s = x[idx]
    sr = s.mean(1) / s.std(1, ddof=1) * np.sqrt(periods)
    return tuple(np.percentile(sr, [2.5, 97.5]))


def pbo_cscv(M, S=16):
    """Probability of backtest overfitting by combinatorially symmetric CV (Bailey et al. 2017).
    M: T x N DataFrame of per-period returns of N configurations."""
    X = M.fillna(0).to_numpy(float)
    T = X.shape[0] - X.shape[0] % S
    X = X[:T]
    blocks = np.array_split(np.arange(T), S)
    s1 = np.array([X[b].sum(0) for b in blocks])
    s2 = np.array([(X[b] ** 2).sum(0) for b in blocks])
    nb = np.array([len(b) for b in blocks])[:, None]
    logits = []
    for comb in combinations(range(S), S // 2):
        m = np.zeros(S, bool)
        m[list(comb)] = True

        def sr(mask):
            n, a, b = nb[mask].sum(), s1[mask].sum(0), s2[mask].sum(0)
            mu = a / n
            return mu / np.sqrt(np.maximum(b / n - mu ** 2, 1e-18))
        is_, oos = sr(m), sr(~m)
        rank = stats.rankdata(oos)[int(np.argmax(is_))] / (len(oos) + 1)
        logits.append(np.log(rank / (1 - rank)))
    logits = np.array(logits)
    return {"pbo": float((logits <= 0).mean()), "n_splits": len(logits), "logits": logits.tolist()}


def holm(p):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)
    adj = np.empty(m)
    run = 0.0
    for k, i in enumerate(o):
        run = max(run, min(1.0, p[i] * (m - k)))
        adj[i] = run
    return adj


def bh(p):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)[::-1]
    adj = np.empty(m)
    run = 1.0
    for k, i in enumerate(o):
        run = min(run, p[i] * m / (m - k))
        adj[i] = run
    return adj
