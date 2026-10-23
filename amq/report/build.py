"""amq.report.build: walk-forward results -> one JSON for the AlgoMaschine dashboard (amq.report.app).

Also keeps the project's TRIAL LEDGER (<out>/ledger.json): every run appends how many configurations it tried,
and the deflated Sharpe uses the cumulative count. Never reset it to make a result look better.
"""
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from amq.afml import core as A
from amq.engine import walkforward as WF


def ledger_add(out: Path, label: str, n: int) -> int:
    f = out / "ledger.json"
    L = json.loads(f.read_text()) if f.exists() else []
    L.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "label": label, "trials": int(n)})
    f.write_text(json.dumps(L, indent=1))
    return sum(r["trials"] for r in L)


def cpcv(strat, mk, cfg, st: WF.Settings, n_groups=10, k_test=2) -> dict:
    """Combinatorial purged CV (AFML 12.4) of one fixed configuration: Sharpe of every backtest path."""
    n = len(mk["x"])
    ev = strat.candidates(mk, strat.prepare(mk), cfg, n)
    e, h = np.asarray(ev["e"], np.int64), np.asarray(ev["h"], np.int64)
    ok = e + h < n
    e, h = e[ok], h[ok]
    idx_all = np.where(ok)[0]
    splits, assign, phi = A.cpcv_paths(n_groups, k_test)
    bounds = np.array_split(np.arange(n), n_groups)
    gid = np.searchsorted([b[0] for b in bounds], e, side="right") - 1
    paths = np.zeros((phi, n))
    for s, asg in zip(splits, assign):
        test = np.isin(gid, s)
        lo, hi = min(bounds[g][0] for g in s), max(bounds[g][-1] for g in s)
        train = ~test & ~((e <= hi) & (e + h >= lo)) & ~((e > hi) & (e <= hi + int(st.embargo * n)))
        model = strat.fit_side(mk, ev, idx_all[train], cfg)
        for g, p in asg:
            m = gid == g
            sd = strat.side(mk, ev, model, idx_all[m], cfg)
            pos = A.average_active(e[m][sd != 0], (e + h)[m][sd != 0], sd[sd != 0], n)
            ret, _ = A.pnl(pos[:-1], mk["r"][1:], st.cost)
            paths[p, bounds[g]] = np.r_[0.0, ret][bounds[g]]
    sr = [float(q[q != 0].mean() / q[q != 0].std() * np.sqrt(252)) if (q != 0).sum() > 30 else None for q in paths]
    return {"config": str(cfg), "paths": phi, "splits": len(splits), "path_sharpes": sr}


def build(title, systems: dict, mk: dict, out: Path, strat=None, st: WF.Settings = WF.Settings(), periods=None,
          review: dict | None = None, notes: list | None = None) -> dict:
    """systems: {display name: walk-forward result (from WF.walk_forward) or a daily return Series}.
    The first system is the primary (PBO, CPCV and calibration refer to it; pass `strat` for those)."""
    out.mkdir(parents=True, exist_ok=True)
    dates = mk["dates"]
    bench = pd.Series(mk["r"], index=dates).fillna(0.0)
    rets = {k: (v["returns"] if isinstance(v, dict) else v).reindex(dates).fillna(0.0) for k, v in systems.items()}
    first = min(r[r != 0].index.min() for r in rets.values() if (r != 0).any())
    periods = periods or {f"{first.year}–{dates[-1].year}": str(first.date())}
    prim = next(iter(systems.values()))
    oof, pbo, cp, var_sr = None, None, None, 0.0
    if strat is not None and isinstance(prim, dict):
        oof = WF.oof_matrix(strat, mk, st)
        oof.to_pickle(out / "oof.pkl")                               # every configuration's returns: for the audit
        pbo = A.pbo_cscv(oof.loc[str(first.date()):], 16) if oof.shape[1] > 1 else None
        var_sr = float(np.var(oof.apply(lambda c: c.mean() / c.std() if c.std() > 0 else np.nan).dropna()))
        mode = Counter(str(h["chosen"]) for h in prim["history"]).most_common(1)[0][0]
        cfg = next(g for g in prim["grid"] if str(g) == mode)
        cp = cpcv(strat, mk, cfg, st)
    n_trials = ledger_add(out, title, prim["n_trials"] if isinstance(prim, dict) else 1)
    table = []
    for pname, start in periods.items():
        b = bench[bench.index >= start]
        p = A.perf(b)
        p.update({"period": pname, "system": "Benchmark buy & hold", "sharpe_ci": A.stationary_bootstrap_sr(b)})
        table.append(p)
        for name, r in rets.items():
            x = r[r.index >= start]
            p = A.perf(x, b)
            if not p:
                continue
            p.update({"period": pname, "system": name, "dsr": A.dsr(x, max(n_trials, 2), var_sr) if var_sr > 0 else None,
                      "sharpe_ci": A.stationary_bootstrap_sr(x)})
            table.append(p)
    start0 = str(first.date())
    idx = dates >= start0
    eq = lambda s: np.exp(np.log1p(s[s.index >= start0]).cumsum())  # noqa: E731
    ch = {"dates": [d.strftime("%Y-%m-%d") for d in dates[idx]], "close": np.round(mk["close"][idx], 4).tolist(),
          "volume": None if mk.get("volume") is None else np.nan_to_num(mk["volume"][idx]).tolist(),
          "bench_eq": eq(bench).round(5).tolist()}
    ch["bench_dd"] = (pd.Series(ch["bench_eq"]) / pd.Series(ch["bench_eq"]).cummax() - 1).round(5).tolist()
    sys_meta = []
    for i, (name, r) in enumerate(rets.items()):
        e_ = eq(r)
        ch[f"s{i}_eq"] = e_.round(5).tolist()
        ch[f"s{i}_dd"] = (e_ / e_.cummax() - 1).round(5).tolist()
        sys_meta.append({"key": f"s{i}", "name": name})
    res = {"title": title, "generated": time.strftime("%Y-%m-%d %H:%M"), "systems": sys_meta[:3], "charts": ch, "table": table,
           "n_trials": n_trials, "var_sr": var_sr, "pbo": None if pbo is None else {"pbo": pbo["pbo"], "n_splits": pbo["n_splits"]},
           "pbo_logits": [] if pbo is None else pbo["logits"][:3000], "cpcv": cp,
           "calibration": prim["history"] if isinstance(prim, dict) else [], "trades": prim["trades"][-500:] if isinstance(prim, dict) else [],
           "review": review, "notes": notes or []}
    (out / "results.json").write_text(json.dumps(_clean(res), default=str))
    return res


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    return o
