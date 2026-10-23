"""amq.engine.selection: choosing among very many candidate rules without fooling yourself.

The rule used by the AlgoMaschine factory kernels: estimate the null distribution of the candidates'
z-scores robustly (median, IQR/1.349: most candidates are null) and select a candidate only if the
EXPECTED NUMBER OF NULL CANDIDATES at least as extreme is below alpha. Unlike BH/FDR this does not
loosen when one real effect lights up hundreds of correlated relatives (found and fixed in review).
"""
import numpy as np
from scipy import stats


def empirical_null(z):
    q1, med, q3 = np.quantile(z, [0.25, 0.5, 0.75])
    return {"p0": 1.0, "mu0": float(med), "sigma0": float((q3 - q1) / 1.349)}


def expected_false(z, info):
    """p0 * N * P0(|Z - mu0| >= |z - mu0|) for each z (two-sided)."""
    mu0, s0, p0 = info["mu0"], info["sigma0"], info["p0"]
    return p0 * len(z) * 2 * stats.norm.sf(np.abs(z - mu0) / s0)


def fdr_q(z, info):
    """Tail-area Fdr q-values under the empirical null (reported, not used for selection)."""
    mu0, s0, p0 = info["mu0"], info["sigma0"], info["p0"]
    n = len(z)
    q = np.ones(n)
    for side in (1, -1):
        idx = np.where(side * (z - mu0) > 0)[0]
        if not len(idx):
            continue
        o = idx[np.argsort(-side * z[idx])]
        v = np.minimum(1.0, p0 * n * stats.norm.sf(side * (z[o] - mu0) / s0) / np.arange(1, len(o) + 1))
        q[o] = np.minimum.accumulate(v[::-1])[::-1]
    return q


def select(z, alpha=0.3, eligible=None):
    """Indices of candidates whose expected false picks < alpha (families: call once per family)."""
    z = np.asarray(z, float)
    ok = np.isfinite(z) if eligible is None else (np.isfinite(z) & eligible)
    out = np.zeros(len(z), bool)
    if ok.sum() < 20:
        return out
    info = empirical_null(z[ok])
    efp = np.full(len(z), np.inf)
    efp[ok] = expected_false(z[ok], info)
    return efp < alpha
