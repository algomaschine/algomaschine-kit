"""amq.review.harness: the pre-run review gate. Nothing is walked forward on real data until it passes.

Checks (each one caught a real bug in the AlgoMaschine projects):
  C1 causality     events and CV scores at T are identical when every price from T on is replaced
  C2 purging       no training label overlaps a test fold (purged k-fold with embargo)
  C3 timing        a position set at the close of t earns only r[t+1]
  S1 null          on sign-flipped returns (volatility kept, predictability destroyed) the whole walk-forward
                   earns ~nothing (OOS Sharpe < 0.3)
  S2 planted       a planted effect of realistic size (full-sample t ~ 5, the strategy's own best configuration)
                   is found out of sample (OOS Sharpe > 0.3). A planted t ~ 1.5 effect must NOT count: an honest
                   method cannot see it.
Writes <out>/review.json and, only if every check passes, <out>/review_passed.json.
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from amq.afml import core as A
from amq.engine import walkforward as WF


def _rebuild(mk, x):
    r = np.r_[np.nan, np.diff(x)]
    sig = np.sqrt((pd.Series(r) ** 2).ewm(halflife=20, min_periods=20).mean()).to_numpy()
    return {**mk, "x": x, "r": r, "sigma": sig, "close": np.exp(x)}


def run(strat, mk, st: WF.Settings, out: Path, t_check="2000-01-01", null_first=None, log=print, plant_t=5.0):
    out.mkdir(parents=True, exist_ok=True)
    rep = {"hard": {}, "info": {}}

    def check(name, ok, detail):
        rep["hard"][name] = {"ok": bool(ok), "detail": detail}
        log(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")

    x = mk["x"]
    n = len(x)
    T = int(np.searchsorted(mk["dates"], pd.Timestamp(t_check)))
    xp = x.copy()
    xp[T:] += np.random.default_rng(0).normal(0, 0.03, n - T).cumsum()
    mk2 = _rebuild(mk, xp)
    prep1, prep2 = strat.prepare(mk), strat.prepare(mk2)
    same_ev, same_sc = True, True
    for cfg in strat.grid()[:24]:
        e1, e2 = strat.candidates(mk, prep1, cfg, T), strat.candidates(mk2, prep2, cfg, T)
        if e1 is None or e2 is None:
            continue
        k1, k2 = np.asarray(e1["e"]) < T, np.asarray(e2["e"]) < T
        same_ev &= np.array_equal(np.asarray(e1["e"])[k1], np.asarray(e2["e"])[k2])
        same_sc &= np.isclose(WF.cv_score(strat, mk, e1, cfg, T, st)[0], WF.cv_score(strat, mk2, e2, cfg, T, st)[0], equal_nan=True)
    check("C1 causality: events and CV scores before T unchanged when the future is replaced", same_ev and same_sc,
          f"T = {t_check}, first 24 configurations")
    ev = strat.candidates(mk, prep1, strat.grid()[0], n)
    e, h = np.asarray(ev["e"], np.int64), np.asarray(ev["h"], np.int64)
    bad = 0
    for tr, te in A.purged_kfold(e, e + h, st.k_folds, st.embargo):
        lo, hi = e[te].min(), (e + h)[te].max()
        bad += int(((e[tr] <= hi) & (e[tr] + h[tr] >= lo)).sum())
    check("C2 purging: no training label overlaps a test fold", bad == 0, f"overlaps {bad}")
    pos = np.zeros(10)
    pos[3] = 1
    rr = np.arange(10) / 100
    ret, _ = A.pnl(pos[:-1], rr[1:], 0.0)
    check("C3 timing: a position set at the close of t earns only r[t+1]", ret[3] == rr[4] and ret.sum() == rr[4], "pnl alignment")
    stn = WF.Settings(**{**st.__dict__, "first_year": null_first or st.first_year})
    rng = np.random.default_rng(3)
    r = np.nan_to_num(mk["r"])
    null = _rebuild(mk, np.cumsum(r * rng.choice([-1.0, 1.0], n)) + x[0])
    res = WF.walk_forward(strat, null, stn, log=lambda m: None)
    s = res["returns"]
    sr = float(s.mean() / s.std() * np.sqrt(252)) if s.std() > 0 else 0.0
    rep["info"]["null_cv_sr_median"] = float(np.median([hh["cv_sr"] for hh in res["history"] if np.isfinite(hh["cv_sr"])] or [0]))
    check("S1 null: on sign-flipped returns the walk-forward earns ~nothing", sr < 0.3,
          f"OOS Sharpe {sr:.2f} (median chosen CV Sharpe {rep['info']['null_cv_sr_median']:.2f} = selection bias)")
    # plant an effect after the events of the first configuration, sized for full-sample t ~ plant_t
    cfg0 = strat.grid()[0]
    prep0 = strat.prepare(null)
    ev0 = strat.candidates(null, prep0, cfg0, n)
    e0, h0 = np.asarray(ev0["e"], np.int64), np.asarray(ev0["h"], np.int64)
    ok = e0 + h0 < n
    e0, h0 = e0[ok], h0[ok]
    sd_h = np.nanstd(r) * np.sqrt(np.mean(h0))
    mu = plant_t * sd_h / np.sqrt(max(len(e0), 1)) / np.mean(h0)
    rp = np.nan_to_num(null["r"]).copy()
    for a, b in zip(e0, h0):
        rp[a + 1:a + b + 1] += mu
    planted = _rebuild(mk, np.cumsum(rp) + x[0])
    res = WF.walk_forward(strat, planted, stn, log=lambda m: None)
    s = res["returns"]
    sr2 = float(s.mean() / s.std() * np.sqrt(252)) if s.std() > 0 else 0.0
    check(f"S2 planted: an effect of full-sample t ~ {plant_t:g} is found out of sample", sr2 > 0.3,
          f"OOS Sharpe {sr2:.2f}; {len(e0)} planted events, drift {mu * 1e4:.1f} bp/day")
    rep["passed"] = all(v["ok"] for v in rep["hard"].values())
    (out / "review.json").write_text(json.dumps(rep, indent=1, default=str))
    if rep["passed"]:
        (out / "review_passed.json").write_text(json.dumps({"passed": time.strftime("%Y-%m-%d %H:%M:%S")}))
    log(f"REVIEW {'PASSED' if rep['passed'] else 'FAILED'}")
    return rep
