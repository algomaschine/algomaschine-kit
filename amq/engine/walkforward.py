"""amq.engine.walkforward: the generic auto-calibrated walk-forward engine (AFML protocol).

You describe an idea as a `Strategy`; the engine does the rest, the same way every time:
  every 1 January Y: configurations are scored by PURGED K-FOLD CV (embargo) on the events whose labels
  end before Y -> the best is chosen (every configuration is logged as a trial) -> optional META-LABELLING
  (triple barrier, random forest with uniqueness weights, bet sizing) -> the year is traded with the
  AVERAGE OF ACTIVE BETS, a VOLATILITY TARGET, a leverage cap and costs on every position change.

Timing convention: day index t; x[t] = log price at the close of t; r[t] = x[t] - x[t-1]. An event decided
with data up to the close of c must use entry e >= c + 1 (enter at the close of e): the price that completes a
signal is never the entry price. pos[t] is held from the close of t to the close of t+1.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import log_loss

from amq.afml import core as A, tools as W


class Strategy:
    """Subclass this for an idea. Minimal: grid() and candidates(). Optional: prepare, fit_side, side, features."""
    name = "strategy"

    def grid(self) -> list[dict]:
        """Every configuration the calibration may choose (each one is a trial for the deflated Sharpe)."""
        raise NotImplementedError

    def prepare(self, mk: dict) -> dict:
        """Causal per-day features (value at t uses data up to the close of t). Computed once."""
        return {}

    def candidates(self, mk: dict, prep: dict, cfg: dict, train_end: int) -> dict:
        """Signal events for this configuration: {'e': entry indices (int), 'h': holding days (int),
        optional 'side' (+1/-1, if the side is known from the rule), 'feat': 2-D per-event features}.
        train_end lets data-dependent transforms (e.g. FFD d*) use only data before it."""
        raise NotImplementedError

    def fit_side(self, mk: dict, ev: dict, train_idx: np.ndarray, cfg: dict):
        """Learn what the rule needs from TRAINING events only (e.g. a pattern -> side table)."""
        return None

    def side(self, mk: dict, ev: dict, model, idx: np.ndarray, cfg: dict) -> np.ndarray:
        """Side of events idx given the fitted model; default: the rule's own 'side'."""
        return np.asarray(ev["side"], float)[idx]


@dataclass
class Settings:
    first_year: int = 1990
    k_folds: int = 5
    embargo: float = 0.01
    cost: float = 1e-4                  # per unit of |delta position| (a round trip costs 2x)
    vol_target: float = 0.10
    leverage_cap: float = 2.0
    meta: bool = True
    barrier_m: tuple = (1.0, 2.0)       # triple-barrier widths in sigma * sqrt(h), chosen by purged-CV log-loss
    min_meta_events: int = 60
    rf: dict = field(default_factory=lambda: dict(n_estimators=500, max_depth=6, min_samples_leaf=5, max_features="sqrt",
                                                  class_weight="balanced_subsample", n_jobs=2))


def market(close: pd.Series, volume: pd.Series | None = None) -> dict:
    """The engine's market dict from a daily close series (traded instrument)."""
    x = np.log(close.to_numpy(float))
    r = np.r_[np.nan, np.diff(x)]
    sigma = np.sqrt((pd.Series(r) ** 2).ewm(halflife=20, min_periods=20).mean()).to_numpy()
    return {"dates": close.index, "x": x, "r": r, "sigma": sigma, "close": close.to_numpy(float),
            "volume": None if volume is None else volume.reindex(close.index).to_numpy(float)}


def _rule_pnl(e, h, side, r, n, lo, hi, cost):
    m = side != 0
    pos = A.average_active(e[m], e[m] + h[m], side[m], n)
    ret, _ = A.pnl(pos[:-1], r[1:], cost)
    return np.r_[ret, 0.0][lo:hi + 1]


def cv_score(strat, mk, ev, cfg, train_end, st: Settings):
    """Purged k-fold CV Sharpe of the rule (sides learned on the training folds only) + out-of-fold sides."""
    n = len(mk["x"])
    e, h = np.asarray(ev["e"], np.int64), np.asarray(ev["h"], np.int64)
    t1 = e + h
    use = np.where(t1 < train_end)[0]
    if len(use) < 50:
        return -np.inf, None, use
    rets, oof = [], np.zeros(len(use))
    for tr, te in A.purged_kfold(e[use], t1[use], st.k_folds, st.embargo):
        model = strat.fit_side(mk, ev, use[tr], cfg)
        s = strat.side(mk, ev, model, use[te], cfg)
        oof[te] = s
        rets.append(_rule_pnl(e[use][te], h[use][te], s, mk["r"], n, int(e[use][te].min()), int(min(t1[use][te].max(), n - 1)), st.cost))
    x = np.concatenate(rets)
    return (float(x.mean() / x.std() * np.sqrt(252)) if x.std() > 0 else -np.inf), oof, use


def _meta_fit(mk, ev, idx, sides, h, st, seed, train_end):
    feat = np.asarray(ev["feat"], float)[idx] if "feat" in ev else np.zeros((len(idx), 0))
    Xm = np.nan_to_num(np.column_stack([feat, sides]), nan=0.0, posinf=0.0, neginf=0.0)
    e = np.asarray(ev["e"], np.int64)[idx]
    best, best_ll, fitted = None, np.inf, None
    for m in st.barrier_m:
        up = m * np.maximum(mk["sigma"][e], 1e-6) * np.sqrt(h[idx])
        ti, _, ret = W.triple_barrier(mk["x"], e, up, up, e + h[idx], sides)
        y = (ret > 0).astype(int)
        ok = ti < train_end
        if ok.sum() < st.min_meta_events or len(np.unique(y[ok])) < 2:
            continue
        w = A.avg_uniqueness(e[ok], ti[ok], len(mk["x"]))
        lls = []
        for tr, te in A.purged_kfold(e[ok], ti[ok], st.k_folds, st.embargo):
            if len(np.unique(y[ok][tr])) < 2:
                continue
            mdl = RandomForestClassifier(max_samples=float(np.clip(w[tr].mean(), 0.05, 1)), random_state=seed, **st.rf)
            mdl.fit(Xm[ok][tr], y[ok][tr], sample_weight=w[tr] / w[tr].mean())
            lls.append(log_loss(y[ok][te], np.clip(mdl.predict_proba(Xm[ok][te])[:, 1], 1e-6, 1 - 1e-6), labels=[0, 1]))
        ll = float(np.mean(lls)) if lls else np.inf
        if ll < best_ll:
            best_ll, best = ll, m
            fitted = RandomForestClassifier(max_samples=float(np.clip(w.mean(), 0.05, 1)), random_state=seed, **st.rf)
            fitted.fit(Xm[ok], y[ok], sample_weight=w / w.mean())
    return fitted, best, best_ll


def walk_forward(strat: Strategy, mk: dict, st: Settings = Settings(), log=print) -> dict:
    x, sig, dates = mk["x"], mk["sigma"], mk["dates"]
    n = len(x)
    prep = strat.prepare(mk)
    grid = strat.grid()
    bets = ([], [], [])
    history, trades = [], []
    for Y in range(st.first_year, dates[-1].year + 1):
        T = int(np.searchsorted(dates, pd.Timestamp(f"{Y}-01-01")))
        Tn = int(np.searchsorted(dates, pd.Timestamp(f"{Y + 1}-01-01")))
        evs, scores = [], []
        for cfg in grid:
            ev = strat.candidates(mk, prep, cfg, T)
            evs.append(ev)
            scores.append(cv_score(strat, mk, ev, cfg, T, st)[0] if ev is not None and len(ev["e"]) else -np.inf)
        scores = np.array(scores)
        b = int(np.argmax(np.where(np.isfinite(scores), scores, -1e9)))
        cfg, ev = grid[b], evs[b]
        rec = {"year": Y, "chosen": cfg, "cv_sr": float(scores[b]), "scores": scores.tolist(), "m": None, "n_trades": 0}
        if ev is None or not len(ev["e"]):
            history.append(rec)
            continue
        sc, oof, use = cv_score(strat, mk, ev, cfg, T, st)
        e_all, h_all = np.asarray(ev["e"], np.int64), np.asarray(ev["h"], np.int64)
        fitted, m_use = None, 1.0
        if st.meta and oof is not None and (oof != 0).sum() >= st.min_meta_events:
            idx = use[oof != 0]
            fitted, m_use, ll = _meta_fit(mk, ev, idx, oof[oof != 0], h_all, st, Y, T)
            rec.update({"m": m_use, "meta_logloss": ll})
            m_use = m_use or 1.0
        model = strat.fit_side(mk, ev, use, cfg)
        te = np.where((e_all >= T) & (e_all < Tn))[0]
        if len(te):
            s = strat.side(mk, ev, model, te, cfg)
            te, s = te[s != 0], s[s != 0]
        if len(te):
            if fitted is not None:
                feat = np.asarray(ev["feat"], float)[te] if "feat" in ev else np.zeros((len(te), 0))
                p = fitted.predict_proba(np.nan_to_num(np.column_stack([feat, s])))[:, 1]
                size = A.bet_size(p)
            else:
                p, size = np.full(len(te), np.nan), np.ones(len(te))
            e = e_all[te]
            up = m_use * np.maximum(sig[e], 1e-6) * np.sqrt(h_all[te])
            ti, _, _ = W.triple_barrier(x, e, up, up, e + h_all[te], s)
            bet = s * size
            act = bet != 0
            for L, v in zip(bets, (e[act], ti[act], bet[act])):
                L.append(v)
            rec["n_trades"] = int(act.sum())
            trades += [{"year": Y, "entry": str(dates[e[i]].date()), "exit": str(dates[min(ti[i], n - 1)].date()),
                        "side": int(s[i]), "p": None if np.isnan(p[i]) else float(p[i]), "size": float(size[i])} for i in range(len(e))]
        history.append(rec)
        log(f"  {strat.name} {Y}: {cfg} CV SR {rec['cv_sr']:.2f} m {rec['m']} trades {rec['n_trades']}")
    raw = A.average_active(*(np.concatenate(L) for L in bets), n) if bets[0] else np.zeros(n)
    pos = A.vol_target_position(raw, np.nan_to_num(sig, nan=1.0), st.vol_target, st.leverage_cap)
    ret, turn = A.pnl(pos[:-1], mk["r"][1:], st.cost)
    returns = pd.Series(np.r_[0.0, ret], index=dates)
    return {"returns": returns[returns.index >= f"{st.first_year}-01-01"], "position": pd.Series(pos, index=dates),
            "grid": grid, "history": history, "trades": trades, "n_trials": len(grid) * max(1, len(st.barrier_m))}


def oof_matrix(strat: Strategy, mk: dict, st: Settings = Settings(), k=10) -> pd.DataFrame:
    """Every configuration's daily P&L from purged k-fold out-of-fold sides over the whole sample: the T x N
    matrix for PBO (CSCV) and the variance of trial Sharpes for the deflated Sharpe."""
    n = len(mk["x"])
    prep = strat.prepare(mk)
    cols = {}
    for cfg in strat.grid():
        ev = strat.candidates(mk, prep, cfg, n)
        if ev is None or not len(ev["e"]):
            continue
        e, h = np.asarray(ev["e"], np.int64), np.asarray(ev["h"], np.int64)
        ok = e + h < n
        idx = np.where(ok)[0]
        side = np.zeros(len(idx))
        for tr, te in A.purged_kfold(e[idx], e[idx] + h[idx], k, st.embargo):
            side[te] = strat.side(mk, ev, strat.fit_side(mk, ev, idx[tr], cfg), idx[te], cfg)
        m = side != 0
        pos = A.average_active(e[idx][m], e[idx][m] + h[idx][m], side[m], n)
        ret, _ = A.pnl(pos[:-1], mk["r"][1:], st.cost)
        cols[str(cfg)] = np.r_[0.0, ret]
    return pd.DataFrame(cols, index=mk["dates"])
