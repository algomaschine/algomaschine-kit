"""amq.afml.tools: labels, filters and features with optional Rust acceleration (relay_core).

Filtered waves (A. A. Merrill, 'Filtered Waves: Basic Theory', 1977) and the tools around them.

Merrill's filter keeps only the swings that exceed a minimum size: a turning point is confirmed when
the price retraces by at least the filter from the running extreme. The last five turning points form
one of 16 'M' (peak-trough-peak shaped: points 2 and 4 are peaks) or 16 'W' patterns (points 2 and
4 are troughs), identified by the height ranks of the five points (Merrill, 'M & W Wave Patterns').

Every function has a pure-Python/numpy reference; the Rust kernels in relay_core are used when present
(af/bench_rust.py checks they are identical). Turning points are only usable from their confirmation
index on: that is the no-look-ahead rule for everything built on waves.
"""
from itertools import permutations

import numpy as np

try:
    import relay_core as rc
except ImportError:                                   # pragma: no cover
    rc = None


# ------------------------------------------------------------------ zig-zag filter
def zigzag_py(x, h):
    n = len(x)
    pi, pt, pc = [], [], []
    d = 0
    hi, hi_i, lo, lo_i = -np.inf, 0, np.inf, 0
    for t in range(n):
        v = x[t]
        if not (np.isfinite(v) and np.isfinite(h[t])):
            continue
        if d == 0:
            if v > hi:
                hi, hi_i = v, t
            if v < lo:
                lo, lo_i = v, t
            if v - lo >= h[t] and lo_i < t:
                pi.append(lo_i); pt.append(-1); pc.append(t); d = 1; hi, hi_i = v, t
            elif hi - v >= h[t] and hi_i < t:
                pi.append(hi_i); pt.append(1); pc.append(t); d = -1; lo, lo_i = v, t
        elif d == 1:
            if v > hi:
                hi, hi_i = v, t
            elif hi - v >= h[t]:
                pi.append(hi_i); pt.append(1); pc.append(t); d = -1; lo, lo_i = v, t
        else:
            if v < lo:
                lo, lo_i = v, t
            elif v - lo >= h[t]:
                pi.append(lo_i); pt.append(-1); pc.append(t); d = 1; hi, hi_i = v, t
    return np.array(pi, np.int64), np.array(pt, np.int8), np.array(pc, np.int64)


def zigzag(x, h):
    """Pivots of log-price x with threshold path h (log units): (index, +1 high/-1 low, confirmed at)."""
    x = np.ascontiguousarray(x, float)
    h = np.ascontiguousarray(np.broadcast_to(h, x.shape), float)
    return rc.zigzag(x, h) if rc is not None else zigzag_py(x, h)


def pct_to_log(p):
    """Merrill's filter p (e.g. 0.05 = 5%) in log units, symmetric for rises and falls."""
    return np.log1p(p)


# ------------------------------------------------------------------ Merrill M & W patterns
def _families():
    """The 16 M and 16 W rank patterns. A pattern is the tuple of height ranks (1 = lowest) of the
    five alternating turning points; M: points 2, 4 are peaks; W: points 2, 4 are troughs.
    Numbering: lexicographic by rank tuple (Merrill's book numbers them by his own table; the set of
    32 patterns is the same)."""
    M, W = [], []
    for p in permutations(range(1, 6)):
        if p[1] > p[0] and p[1] > p[2] and p[3] > p[2] and p[3] > p[4]:
            M.append(p)
        if p[1] < p[0] and p[1] < p[2] and p[3] < p[2] and p[3] < p[4]:
            W.append(p)
    return sorted(M), sorted(W)


M_PATTERNS, W_PATTERNS = _families()
assert len(M_PATTERNS) == 16 and len(W_PATTERNS) == 16
PATTERN_ID = {**{p: f"M{i + 1}" for i, p in enumerate(M_PATTERNS)}, **{p: f"W{i + 1}" for i, p in enumerate(W_PATTERNS)}}
PATTERNS = [f"M{i}" for i in range(1, 17)] + [f"W{i}" for i in range(1, 17)]


def classify(vals):
    """Pattern id of five alternating turning-point values (ties broken by order)."""
    r = np.argsort(np.argsort(np.asarray(vals), kind="stable"), kind="stable") + 1
    return PATTERN_ID.get(tuple(int(v) for v in r))


def pattern_series(x, pi, pt, pc, n):
    """For each confirmation of a turning point, the pattern of the last five turning points.
    Returns arrays aligned to the pivots: pattern id (None for the first four) and its confirmation day."""
    out = [None] * len(pi)
    for k in range(4, len(pi)):
        out[k] = classify(x[pi[k - 4:k + 1]])
    return out


# ------------------------------------------------------------------ AFML tools
def cusum_py(r, h):
    sp = sn = 0.0
    ix, sg = [], []
    for t in range(len(r)):
        v = r[t]
        if not (np.isfinite(v) and np.isfinite(h[t])):
            continue
        sp, sn = max(0.0, sp + v), min(0.0, sn + v)
        if sp > h[t]:
            ix.append(t); sg.append(1); sp = sn = 0.0
        elif sn < -h[t]:
            ix.append(t); sg.append(-1); sp = sn = 0.0
    return np.array(ix, np.int64), np.array(sg, np.int8)


def cusum_filter(r, h):
    r = np.ascontiguousarray(r, float)
    h = np.ascontiguousarray(np.broadcast_to(h, r.shape), float)
    return rc.cusum_filter(r, h) if rc is not None else cusum_py(r, h)


def ffd_weights(d, thresh=1e-5, max_len=10_000):
    """Weights of the fixed-width-window fractional difference (AFML snippet 5.3)."""
    w = [1.0]
    k = 1
    while k < max_len:
        wk = -w[-1] * (d - k + 1) / k
        if abs(wk) < thresh:
            break
        w.append(wk)
        k += 1
    return np.array(w)


def frac_diff_ffd_py(x, w):
    out = np.full(len(x), np.nan)
    out[len(w) - 1:] = np.convolve(x, w, mode="valid")
    return out


def frac_diff_ffd(x, d, thresh=1e-5):
    """FFD via scipy FFT convolution: faster than both the direct loop and the Rust kernel (benchmarked)."""
    from scipy.signal import fftconvolve
    w = ffd_weights(d, thresh)
    x = np.ascontiguousarray(x, float)
    out = np.full(len(x), np.nan)
    if np.isfinite(x).all():
        out[len(w) - 1:] = fftconvolve(x, w, mode="valid")
        return out
    return frac_diff_ffd_py(x, w)


def trend_scan_py(x, lmin, lmax, step=1):
    n = len(x)
    cs = np.r_[0, np.cumsum(x)]
    cs2 = np.r_[0, np.cumsum(x * x)]
    csi = np.r_[0, np.cumsum(np.arange(n) * x)]
    best = np.full(n, np.nan)
    bl = np.zeros(n, np.int64)
    t = np.arange(n)
    for L in range(lmin, lmax + 1, step):
        ok = t + L <= n
        tt = t[ok]
        sx = cs[tt + L] - cs[tt]
        sxx = cs2[tt + L] - cs2[tt]
        sux = csi[tt + L] - csi[tt] - tt * sx
        su, suu = L * (L - 1) / 2, (L - 1) * L * (2 * L - 1) / 6
        varu = suu - su * su / L
        cov = sux - su * sx / L
        b = cov / varu
        sse = (sxx - sx * sx / L) - b * cov
        with np.errstate(all="ignore"):
            tv = np.where((L > 2) & (sse > 0), b / np.sqrt(sse / (L - 2) / varu), np.nan)
        cur = best[ok]
        upd = np.isfinite(tv) & (np.isnan(cur) | (np.abs(tv) > np.abs(np.nan_to_num(cur))))
        cur[upd] = tv[upd]
        best[ok] = cur
        b2 = bl[ok]
        b2[upd] = L
        bl[ok] = b2
    return best, bl


def trend_scan(x, lmin, lmax, step=1):
    x = np.ascontiguousarray(x, float)
    return rc.trend_scan(x, lmin, lmax, step) if rc is not None else trend_scan_py(x, lmin, lmax, step)


def triple_barrier_py(x, ev, up, dn, t1, side):
    n = len(x)
    ti, lab, ret = [], [], []
    for e in range(len(ev)):
        t0, end = ev[e], min(t1[e], n - 1)
        s = 1.0 if side[e] == 0 else side[e]
        hit = None
        for t in range(t0 + 1, end + 1):
            r = (x[t] - x[t0]) * s
            if np.isfinite(r):
                if r >= up[e]:
                    hit = (t, 1, r); break
                if r <= -dn[e]:
                    hit = (t, -1, r); break
        if hit is None:
            te = max(end, t0)
            hit = (te, 0, (x[te] - x[t0]) * s)
        ti.append(hit[0]); lab.append(hit[1]); ret.append(hit[2])
    return np.array(ti, np.int64), np.array(lab, np.int8), np.array(ret)


def triple_barrier(x, ev, up, dn, t1, side):
    a = [np.ascontiguousarray(v, dt) for v, dt in ((x, float), (ev, np.int64), (up, float), (dn, float),
                                                   (t1, np.int64), (side, float))]
    return rc.triple_barrier(*a) if rc is not None else triple_barrier_py(*a)


def ffd_select(x, train_end, grid=None, thresh=1e-4, alpha=0.05):
    """Smallest d whose FFD series passes ADF at `alpha` on data before train_end (AFML 5.6)."""
    from statsmodels.tsa.stattools import adfuller
    grid = grid or [round(d, 1) for d in np.arange(0.1, 1.01, 0.1)]
    for d in grid:
        f = frac_diff_ffd(x, d, thresh)
        v = f[:train_end]
        v = v[np.isfinite(v)]
        if len(v) > 500 and adfuller(v, maxlag=1, regression="c", autolag=None)[1] < alpha:
            return d, f
    return 1.0, frac_diff_ffd(x, 1.0, thresh)
