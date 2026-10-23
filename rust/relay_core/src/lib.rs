//! relay_core: speed-critical kernels for the AlgoMaschine walk-forward engine.
//! Every kernel has a Python/numpy reference implementation; the benchmark (`make bench`) checks equality
//! and measures speed. All loops that touch O(T x S) data release the GIL and run on rayon.

use numpy::ndarray::{Array1, Array3, ArrayView1, ArrayView2, ArrayView3};
use numpy::{IntoPyArray, PyArray1, PyArray3, PyReadonlyArray1, PyReadonlyArray2, PyReadonlyArray3};
use pyo3::prelude::*;
use rayon::prelude::*;

const NC: usize = 7; // regime conditions per filter in the factory grammar

// ------------------------------------------------------------------ factory: intraday statistics
fn active_lists(f: &ArrayView2<bool>, conds: &ArrayView3<bool>) -> (Vec<usize>, Vec<u16>) {
    let (n_inst, t_len, nc) = conds.dim();
    let nf = f.ncols();
    let mut offs = Vec::with_capacity(n_inst * t_len + 1);
    let mut idx: Vec<u16> = Vec::new();
    offs.push(0);
    for k in 0..n_inst {
        for t in 0..t_len {
            for fi in 0..nf {
                if f[[t, fi]] {
                    for c in 0..nc {
                        if conds[[k, t, c]] {
                            idx.push((fi * nc + c) as u16);
                        }
                    }
                }
            }
            offs.push(idx.len());
        }
    }
    (offs, idx)
}

/// Yearly sufficient statistics of every (window-series, filter x condition) combo.
/// rt: window returns transposed (S x T, f32, NaN = no data); yi: year index per day (T);
/// f: filters (T x 20); conds: (n_inst x T x 7); ik: instrument of each series (S); ny: years;
/// flip: optional per-day sign (null runs). Returns (S1, S2, N) each shaped (S, ny, 20*7).
#[pyfunction]
#[pyo3(signature = (rt, yi, f, conds, ik, ny, flip=None, only_s1=false))]
fn intra_stats<'py>(
    py: Python<'py>, rt: PyReadonlyArray2<'py, f32>, yi: PyReadonlyArray1<'py, i64>,
    f: PyReadonlyArray2<'py, bool>, conds: PyReadonlyArray3<'py, bool>, ik: PyReadonlyArray1<'py, i64>,
    ny: usize, flip: Option<PyReadonlyArray1<'py, f64>>, only_s1: bool,
) -> PyResult<(Bound<'py, PyArray3<f64>>, Option<Bound<'py, PyArray3<f64>>>, Option<Bound<'py, PyArray3<f64>>>)> {
    let rt = rt.as_array();
    let yi = yi.as_array();
    let f = f.as_array();
    let conds = conds.as_array();
    let ik = ik.as_array();
    let flip_v = flip.as_ref().map(|x| x.as_array());
    let (s_len, t_len) = rt.dim();
    let nm = f.ncols() * NC;
    let per = ny * nm;
    let (s1, s2, nn) = py.allow_threads(|| {
        let (offs, idx) = active_lists(&f, &conds);
        let mut s1 = vec![0f64; s_len * per];
        let mut s2 = if only_s1 { Vec::new() } else { vec![0f64; s_len * per] };
        let mut nn = if only_s1 { Vec::new() } else { vec![0f64; s_len * per] };
        let kern = |s: usize, a: &mut [f64], mut b: Option<&mut [f64]>, mut c: Option<&mut [f64]>| {
            let k = ik[s] as usize;
            let row = rt.row(s);
            for t in 0..t_len {
                let v0 = row[t];
                if !v0.is_finite() {
                    continue;
                }
                let v = v0 as f64 * flip_v.as_ref().map_or(1.0, |fl| fl[t]);
                let base = yi[t] as usize * nm;
                let lo = offs[k * t_len + t];
                let hi = offs[k * t_len + t + 1];
                for &m in &idx[lo..hi] {
                    let j = base + m as usize;
                    a[j] += v;
                    if let Some(bb) = b.as_deref_mut() {
                        bb[j] += v * v;
                    }
                    if let Some(cc) = c.as_deref_mut() {
                        cc[j] += 1.0;
                    }
                }
            }
        };
        if only_s1 {
            s1.par_chunks_mut(per).enumerate().for_each(|(s, a)| kern(s, a, None, None));
        } else {
            s1.par_chunks_mut(per)
                .zip(s2.par_chunks_mut(per))
                .zip(nn.par_chunks_mut(per))
                .enumerate()
                .for_each(|(s, ((a, b), c))| kern(s, a, Some(b), Some(c)));
        }
        (s1, s2, nn)
    });
    let mk = |v: Vec<f64>| Array3::from_shape_vec((s_len, ny, nm), v).unwrap();
    let a = mk(s1).into_pyarray(py);
    if only_s1 {
        return Ok((a, None, None));
    }
    Ok((a, Some(mk(s2).into_pyarray(py)), Some(mk(nn).into_pyarray(py))))
}

// ------------------------------------------------------------------ factory: higher-timeframe statistics
/// Yearly stats of position series with turnover costs. pt: positions (J x T, i8); tk: target
/// instrument per series (J); rt: daily returns (I x T, NaN = none); conds (I x T x 7); cost (I,
/// round trip); yi (T); flip (T) optional. Returns S1, S2, N (active days), TO (turnover cost),
/// each shaped (J, ny, 7).
#[pyfunction]
#[pyo3(signature = (pt, tk, rt, conds, cost, yi, ny, flip=None))]
fn htf_stats<'py>(
    py: Python<'py>, pt: PyReadonlyArray2<'py, i8>, tk: PyReadonlyArray1<'py, i64>, rt: PyReadonlyArray2<'py, f64>,
    conds: PyReadonlyArray3<'py, bool>, cost: PyReadonlyArray1<'py, f64>, yi: PyReadonlyArray1<'py, i64>, ny: usize,
    flip: Option<PyReadonlyArray1<'py, f64>>,
) -> PyResult<Vec<Bound<'py, PyArray3<f64>>>> {
    let pt = pt.as_array();
    let tk = tk.as_array();
    let rt = rt.as_array();
    let conds = conds.as_array();
    let cost = cost.as_array();
    let yi = yi.as_array();
    let flip_v = flip.as_ref().map(|x| x.as_array());
    let (j_len, t_len) = pt.dim();
    let per = ny * NC;
    let out = py.allow_threads(|| {
        let mut bufs: Vec<Vec<f64>> = (0..4).map(|_| vec![0f64; j_len * per]).collect();
        let (b0, rest) = bufs.split_at_mut(1);
        let (b1, rest) = rest.split_at_mut(1);
        let (b2, b3) = rest.split_at_mut(1);
        b0[0].par_chunks_mut(per)
            .zip(b1[0].par_chunks_mut(per))
            .zip(b2[0].par_chunks_mut(per))
            .zip(b3[0].par_chunks_mut(per))
            .enumerate()
            .for_each(|(j, (((s1, s2), n), to))| {
                let k = tk[j] as usize;
                let half = cost[k] / 2.0;
                let prow = pt.row(j);
                let rrow = rt.row(k);
                for c in 0..NC {
                    let mut prev = 0.0f64;
                    for t in 0..t_len {
                        let pos = prow[t] as f64 * if conds[[k, t, c]] { 1.0 } else { 0.0 };
                        let y = yi[t] as usize * NC + c;
                        let mut r = rrow[t];
                        if let Some(fl) = flip_v.as_ref() {
                            r *= fl[t];
                        }
                        if r.is_finite() {
                            let pnl = pos * r;
                            s1[y] += pnl;
                            s2[y] += pnl * pnl;
                            n[y] += pos.abs();
                        }
                        to[y] += (pos - prev).abs() * half;
                        prev = pos;
                    }
                }
            });
        bufs
    });
    Ok(out.into_iter().map(|v| Array3::from_shape_vec((j_len, ny, NC), v).unwrap().into_pyarray(py)).collect())
}

// ------------------------------------------------------------------ waves: Merrill filter (zig-zag)
/// Filtered waves: a turning point is confirmed when the price retraces by at least h[t] (log units)
/// from the running extreme. Returns (pivot index, pivot type +1 high / -1 low, confirmation index).
/// The pivot is only known at its confirmation index: that is the index a trading rule may use.
#[pyfunction]
fn zigzag<'py>(py: Python<'py>, x: PyReadonlyArray1<'py, f64>, h: PyReadonlyArray1<'py, f64>)
    -> PyResult<(Bound<'py, PyArray1<i64>>, Bound<'py, PyArray1<i8>>, Bound<'py, PyArray1<i64>>)> {
    let x = x.as_array();
    let h = h.as_array();
    let (pi, pt, pc) = zigzag_core(&x, &h);
    Ok((Array1::from(pi).into_pyarray(py), Array1::from(pt).into_pyarray(py), Array1::from(pc).into_pyarray(py)))
}

fn zigzag_core(x: &ArrayView1<f64>, h: &ArrayView1<f64>) -> (Vec<i64>, Vec<i8>, Vec<i64>) {
    let n = x.len();
    let (mut pi, mut pt, mut pc) = (Vec::new(), Vec::new(), Vec::new());
    let mut dir: i8 = 0;
    let (mut hi, mut hi_i, mut lo, mut lo_i) = (f64::NEG_INFINITY, 0usize, f64::INFINITY, 0usize);
    for t in 0..n {
        let v = x[t];
        if !v.is_finite() || !h[t].is_finite() {
            continue;
        }
        match dir {
            0 => {
                if v > hi { hi = v; hi_i = t; }
                if v < lo { lo = v; lo_i = t; }
                if v - lo >= h[t] && lo_i < t {
                    pi.push(lo_i as i64); pt.push(-1); pc.push(t as i64);
                    dir = 1; hi = v; hi_i = t;
                } else if hi - v >= h[t] && hi_i < t {
                    pi.push(hi_i as i64); pt.push(1); pc.push(t as i64);
                    dir = -1; lo = v; lo_i = t;
                }
            }
            1 => {
                if v > hi { hi = v; hi_i = t; } else if hi - v >= h[t] {
                    pi.push(hi_i as i64); pt.push(1); pc.push(t as i64);
                    dir = -1; lo = v; lo_i = t;
                }
            }
            _ => {
                if v < lo { lo = v; lo_i = t; } else if v - lo >= h[t] {
                    pi.push(lo_i as i64); pt.push(-1); pc.push(t as i64);
                    dir = 1; hi = v; hi_i = t;
                }
            }
        }
    }
    (pi, pt, pc)
}

/// Many zig-zags at once (a parameter grid): returns the number of confirmed pivots per threshold
/// scale, used by the calibration sweep. hs: (G x T) threshold paths.
#[pyfunction]
fn zigzag_count_grid<'py>(py: Python<'py>, x: PyReadonlyArray1<'py, f64>, hs: PyReadonlyArray2<'py, f64>)
    -> PyResult<Bound<'py, PyArray1<i64>>> {
    let x = x.as_array();
    let hs = hs.as_array();
    let out: Vec<i64> = py.allow_threads(|| {
        (0..hs.nrows()).into_par_iter().map(|g| zigzag_core(&x, &hs.row(g)).0.len() as i64).collect()
    });
    Ok(Array1::from(out).into_pyarray(py))
}

// ------------------------------------------------------------------ AFML: CUSUM filter
/// Symmetric CUSUM filter (Lopez de Prado, AFML 2.5.2.1) on returns r with threshold h[t]:
/// S+ = max(0, S+ + r), S- = min(0, S- + r); an event (index, sign) when S+ > h or S- < -h, then reset.
#[pyfunction]
fn cusum_filter<'py>(py: Python<'py>, r: PyReadonlyArray1<'py, f64>, h: PyReadonlyArray1<'py, f64>)
    -> PyResult<(Bound<'py, PyArray1<i64>>, Bound<'py, PyArray1<i8>>)> {
    let r = r.as_array();
    let h = h.as_array();
    let (mut sp, mut sn) = (0.0f64, 0.0f64);
    let (mut ix, mut sg) = (Vec::new(), Vec::new());
    for t in 0..r.len() {
        let v = r[t];
        if !v.is_finite() || !h[t].is_finite() {
            continue;
        }
        sp = (sp + v).max(0.0);
        sn = (sn + v).min(0.0);
        if sp > h[t] {
            ix.push(t as i64); sg.push(1); sp = 0.0; sn = 0.0;
        } else if sn < -h[t] {
            ix.push(t as i64); sg.push(-1); sp = 0.0; sn = 0.0;
        }
    }
    Ok((Array1::from(ix).into_pyarray(py), Array1::from(sg).into_pyarray(py)))
}

// ------------------------------------------------------------------ AFML: fractional differentiation (FFD)
/// Fixed-width-window fractional differentiation (AFML 5.5): y_t = sum_k w_k x_{t-k}, k < L.
/// w: the FFD weights (w_0 = 1, ...). The first L-1 outputs are NaN.
#[pyfunction]
fn frac_diff_ffd<'py>(py: Python<'py>, x: PyReadonlyArray1<'py, f64>, w: PyReadonlyArray1<'py, f64>)
    -> PyResult<Bound<'py, PyArray1<f64>>> {
    let x = x.as_array();
    let w = w.as_array();
    let n = x.len();
    let l = w.len();
    let mut out = vec![f64::NAN; n];
    py.allow_threads(|| {
        out.par_iter_mut().enumerate().for_each(|(t, o)| {
            if t + 1 >= l {
                let mut s = 0.0;
                for k in 0..l {
                    s += w[k] * x[t - k];
                }
                *o = s;
            }
        });
    });
    Ok(Array1::from(out).into_pyarray(py))
}

// ------------------------------------------------------------------ trend scanning (labels, look forward)
/// Trend-scanning labels (Lopez de Prado, MLAM 5.4): for each t, OLS of x[t..t+L) on time for L in
/// [lmin, lmax] (step); keep the L with the largest |t-value of the slope|. Uses future data by
/// design: a label, only ever used inside purged training windows. Returns (t-value, L).
#[pyfunction]
fn trend_scan<'py>(py: Python<'py>, x: PyReadonlyArray1<'py, f64>, lmin: usize, lmax: usize, step: usize)
    -> PyResult<(Bound<'py, PyArray1<f64>>, Bound<'py, PyArray1<i64>>)> {
    let x = x.as_array();
    let n = x.len();
    let mut cs = vec![0f64; n + 1];
    let mut cs2 = vec![0f64; n + 1];
    let mut csi = vec![0f64; n + 1];
    for t in 0..n {
        cs[t + 1] = cs[t] + x[t];
        cs2[t + 1] = cs2[t] + x[t] * x[t];
        csi[t + 1] = csi[t] + (t as f64) * x[t];
    }
    let res: Vec<(f64, i64)> = py.allow_threads(|| {
        (0..n).into_par_iter().map(|t| {
            let (mut best, mut bl) = (f64::NAN, 0i64);
            let mut l = lmin;
            while l <= lmax && t + l <= n {
                let lf = l as f64;
                let sx = cs[t + l] - cs[t];
                let sxx = cs2[t + l] - cs2[t];
                let si_abs = csi[t + l] - csi[t];
                // regress on u = i - t, u = 0..L-1
                let sux = si_abs - (t as f64) * sx;
                let su = lf * (lf - 1.0) / 2.0;
                let suu = (lf - 1.0) * lf * (2.0 * lf - 1.0) / 6.0;
                let varu = suu - su * su / lf;
                let covux = sux - su * sx / lf;
                let b = covux / varu;
                let sse = (sxx - sx * sx / lf) - b * covux;
                if l > 2 && varu > 0.0 && sse > 0.0 {
                    let se = (sse / (lf - 2.0) / varu).sqrt();
                    let tv = b / se;
                    if best.is_nan() || tv.abs() > best.abs() {
                        best = tv;
                        bl = l as i64;
                    }
                }
                l += step;
            }
            (best, bl)
        }).collect()
    });
    let tv: Vec<f64> = res.iter().map(|r| r.0).collect();
    let ln: Vec<i64> = res.iter().map(|r| r.1).collect();
    Ok((Array1::from(tv).into_pyarray(py), Array1::from(ln).into_pyarray(py)))
}

// ------------------------------------------------------------------ AFML: triple barrier
/// Triple-barrier method (AFML 3.4). x: log close (T); ev: event indices; up/dn: barrier widths
/// (log units, > 0; +inf disables); t1: vertical barrier index per event; side: +1/-1 (0 = both).
/// Returns (touch index, label +1 upper / -1 lower / 0 vertical, return from event to touch, in side terms).
#[pyfunction]
fn triple_barrier<'py>(
    py: Python<'py>, x: PyReadonlyArray1<'py, f64>, ev: PyReadonlyArray1<'py, i64>, up: PyReadonlyArray1<'py, f64>,
    dn: PyReadonlyArray1<'py, f64>, t1: PyReadonlyArray1<'py, i64>, side: PyReadonlyArray1<'py, f64>,
) -> PyResult<(Bound<'py, PyArray1<i64>>, Bound<'py, PyArray1<i8>>, Bound<'py, PyArray1<f64>>)> {
    let x = x.as_array();
    let ev = ev.as_array();
    let up = up.as_array();
    let dn = dn.as_array();
    let t1 = t1.as_array();
    let side = side.as_array();
    let n = x.len() as i64;
    let res: Vec<(i64, i8, f64)> = py.allow_threads(|| {
        (0..ev.len()).into_par_iter().map(|e| {
            let t0 = ev[e];
            let end = t1[e].min(n - 1);
            let s = if side[e] == 0.0 { 1.0 } else { side[e] };
            let x0 = x[t0 as usize];
            let mut t = t0 + 1;
            while t <= end {
                let r = (x[t as usize] - x0) * s;
                if r.is_finite() {
                    if r >= up[e] {
                        return (t, 1i8, r);
                    }
                    if r <= -dn[e] {
                        return (t, -1i8, r);
                    }
                }
                t += 1;
            }
            let te = end.max(t0);
            (te, 0i8, (x[te as usize] - x0) * s)
        }).collect()
    });
    Ok((
        Array1::from(res.iter().map(|r| r.0).collect::<Vec<_>>()).into_pyarray(py),
        Array1::from(res.iter().map(|r| r.1).collect::<Vec<_>>()).into_pyarray(py),
        Array1::from(res.iter().map(|r| r.2).collect::<Vec<_>>()).into_pyarray(py),
    ))
}

// ------------------------------------------------------------------ BOCPD (Adams & MacKay 2007)
fn lgamma(x: f64) -> f64 {
    // Lanczos approximation (g = 7, n = 9), |error| < 1e-13 for x > 0.5
    const G: f64 = 7.0;
    const C: [f64; 9] = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313,
        -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
    if x < 0.5 {
        return (std::f64::consts::PI / (std::f64::consts::PI * x).sin()).ln() - lgamma(1.0 - x);
    }
    let x = x - 1.0;
    let mut a = C[0];
    let t = x + G + 0.5;
    for (i, c) in C.iter().enumerate().skip(1) {
        a += c / (x + i as f64);
    }
    0.5 * (2.0 * std::f64::consts::PI).ln() + (x + 0.5) * t.ln() - t + a.ln()
}

fn logaddexp(a: f64, b: f64) -> f64 {
    if a == f64::NEG_INFINITY { return b; }
    if b == f64::NEG_INFINITY { return a; }
    let m = a.max(b);
    m + ((a - m).exp() + (b - m).exp()).ln()
}

/// Normal-Gamma BOCPD. Returns (P(run length < w), MAP run length) per step (NaN inputs skipped).
#[pyfunction]
#[pyo3(signature = (z, hazard=1.0/250.0, rmax=500, mu0=0.0, kappa0=1.0, alpha0=2.0, beta0=1.0, w=20))]
fn bocpd<'py>(py: Python<'py>, z: PyReadonlyArray1<'py, f64>, hazard: f64, rmax: usize, mu0: f64, kappa0: f64,
    alpha0: f64, beta0: f64, w: usize) -> PyResult<(Bound<'py, PyArray1<f64>>, Bound<'py, PyArray1<f64>>)> {
    let z = z.as_array();
    let n = z.len();
    let (lh, l1h) = (hazard.ln(), (-hazard).ln_1p());
    let mut log_r: Vec<f64> = vec![0.0];
    let (mut mu, mut ka, mut al, mut be) = (vec![mu0], vec![kappa0], vec![alpha0], vec![beta0]);
    let mut out = vec![f64::NAN; n];
    let mut mapr = vec![f64::NAN; n];
    for t in 0..n {
        let x = z[t];
        if !x.is_finite() {
            continue;
        }
        let m = log_r.len();
        let mut grow = Vec::with_capacity(m + 1);
        grow.push(f64::NEG_INFINITY);
        let mut cp = f64::NEG_INFINITY;
        for i in 0..m {
            let df = 2.0 * al[i];
            let sc2 = be[i] * (ka[i] + 1.0) / (al[i] * ka[i]);
            let lp = lgamma((df + 1.0) / 2.0) - lgamma(df / 2.0) - 0.5 * (std::f64::consts::PI * df * sc2).ln()
                - (df + 1.0) / 2.0 * (1.0 + (x - mu[i]).powi(2) / (df * sc2)).ln();
            let a = log_r[i] + lp;
            grow.push(a + l1h);
            cp = logaddexp(cp, a + lh);
        }
        grow[0] = cp;
        let mut tot = f64::NEG_INFINITY;
        for v in &grow {
            tot = logaddexp(tot, *v);
        }
        for v in grow.iter_mut() {
            *v -= tot;
        }
        let mut nmu = Vec::with_capacity(m + 1);
        let mut nka = Vec::with_capacity(m + 1);
        let mut nal = Vec::with_capacity(m + 1);
        let mut nbe = Vec::with_capacity(m + 1);
        nmu.push(mu0); nka.push(kappa0); nal.push(alpha0); nbe.push(beta0);
        for i in 0..m {
            nmu.push((ka[i] * mu[i] + x) / (ka[i] + 1.0));
            nka.push(ka[i] + 1.0);
            nal.push(al[i] + 0.5);
            nbe.push(be[i] + ka[i] * (x - mu[i]).powi(2) / (2.0 * (ka[i] + 1.0)));
        }
        if grow.len() > rmax {
            grow.truncate(rmax); nmu.truncate(rmax); nka.truncate(rmax); nal.truncate(rmax); nbe.truncate(rmax);
        }
        log_r = grow; mu = nmu; ka = nka; al = nal; be = nbe;
        out[t] = log_r.iter().take(w).map(|v| v.exp()).sum();
        let mut bi = 0usize;
        for i in 1..log_r.len() {
            if log_r[i] > log_r[bi] { bi = i; }
        }
        mapr[t] = bi as f64;
    }
    Ok((Array1::from(out).into_pyarray(py), Array1::from(mapr).into_pyarray(py)))
}

#[pymodule]
fn relay_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(intra_stats, m)?)?;
    m.add_function(wrap_pyfunction!(htf_stats, m)?)?;
    m.add_function(wrap_pyfunction!(zigzag, m)?)?;
    m.add_function(wrap_pyfunction!(zigzag_count_grid, m)?)?;
    m.add_function(wrap_pyfunction!(cusum_filter, m)?)?;
    m.add_function(wrap_pyfunction!(frac_diff_ffd, m)?)?;
    m.add_function(wrap_pyfunction!(trend_scan, m)?)?;
    m.add_function(wrap_pyfunction!(triple_barrier, m)?)?;
    m.add_function(wrap_pyfunction!(bocpd, m)?)?;
    Ok(())
}
