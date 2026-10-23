"""amq.cli: the project runner behind the .mk targets. Reads config.toml and the project's strategy module.
    python -m amq.cli {data|qa|spec-lock|spec-check|spec-bump REASON|review|walkforward|report|audit}
Exit codes: 0 ok, 2 spec changed since spec-lock, 3 gate not passed (review / spec)."""
import hashlib
import importlib
import json
import os
import pickle
import sys
import time
import tomllib
from pathlib import Path

import pandas as pd

import numpy as np

from amq.audit import forensics as AU
from amq.data import eodhd as E, qa as Q
from amq.engine import walkforward as WF
from amq.report import build as RB
from amq.review import harness as RV

OUT = Path(os.environ.get("AMQ_OUT", "outputs"))


def log(m):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}", flush=True)


def status(stage, detail="", progress=None):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "status.tmp").write_text(json.dumps({"stage": stage, "detail": detail, "progress": progress,
                                                "updated": time.strftime("%Y-%m-%d %H:%M:%S")}))
    (OUT / "status.tmp").replace(OUT / "status.json")


def config():
    return tomllib.loads(Path("config.toml").read_text())


def market(c):
    m = c["market"]
    d = E.daily(m["symbol"])
    d = d[d.index >= m.get("start", "1900-01-01")]
    return WF.market(d[m.get("field", "adjusted_close")], d["volume"] if "volume" in d else None)


def strategy(c):
    return importlib.import_module(c["project"].get("strategy_module", "strategy")).Strategy(c)


def settings(c):
    w = dict(c.get("walkforward", {}))
    if "barrier_m" in w:
        w["barrier_m"] = tuple(w["barrier_m"])
    return WF.Settings(**{k: v for k, v in w.items() if k in WF.Settings.__dataclass_fields__})


def fingerprint(c):
    grid = json.dumps(strategy(c).grid(), sort_keys=True, default=str)
    return {"spec_sha": hashlib.sha256(Path("SPEC.md").read_bytes()).hexdigest(),
            "grid_sha": hashlib.sha256(grid.encode()).hexdigest(), "n_grid": len(json.loads(grid))}


def main(argv):
    cmd = argv[0] if argv else "help"
    c = config()
    if cmd == "data":
        for sym in c["data"].get("daily", []):
            d = E.daily(sym, refresh=True)
            log(f"daily {sym}: {d.index[0].date()} -> {d.index[-1].date()} ({len(d)} rows)")
        for sym in c["data"].get("intraday", []):
            d = E.intraday(sym, start=c["data"].get("intraday_start", "2010-01-01"))
            log(f"intraday {sym}: {len(d)} 5m bars")
    elif cmd == "qa":
        syms = c["data"].get("intraday", [])
        if not syms:
            log("no intraday series: nothing to check")
            return
        series = {s: pd.read_parquet(E.CACHE / f"{s}_5m.parquet") for s in syms}
        ref = c["data"].get("qa_reference")
        ref_bars = pd.read_parquet(E.CACHE / f"{ref}_5m.parquet") if ref and (E.CACHE / f"{ref}_5m.parquet").exists() else None
        rep = Q.gate(series, ref_bars)
        (OUT / "qa.json").write_text(json.dumps(rep, indent=1, default=str))
        for s, r in rep.items():
            log(f"qa {s}: bad years {r['bad_years'] or 'none'}")
    elif cmd == "spec-lock":
        fp = {**fingerprint(c), "locked": time.strftime("%Y-%m-%d %H:%M:%S")}
        Path("spec.lock").write_text(json.dumps(fp, indent=1))
        log(f"spec frozen: {fp['n_grid']} configurations")
    elif cmd == "spec-check":
        if not Path("spec.lock").exists():
            log("no spec.lock: freeze the spec first (make spec-lock)")
            sys.exit(3)
        lock, now = json.loads(Path("spec.lock").read_text()), fingerprint(c)
        if lock["spec_sha"] != now["spec_sha"] or lock["grid_sha"] != now["grid_sha"]:
            log("SPEC.md or the strategy grid changed since spec-lock: make spec-bump REASON=... (it is logged)")
            sys.exit(2)
        log("spec unchanged since lock")
    elif cmd == "spec-bump":
        f = Path("spec_changes.json")
        L = json.loads(f.read_text()) if f.exists() else []
        L.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "reason": " ".join(argv[1:]), **fingerprint(c)})
        f.write_text(json.dumps(L, indent=1))
        main(["spec-lock"])
    elif cmd == "review":
        status("review", "causality, purging, timing, null, planted")
        rep = RV.run(strategy(c), market(c), settings(c), OUT, c.get("review", {}).get("t_check", "2000-01-01"),
                     c.get("review", {}).get("null_first"), log)
        status("review done", "passed" if rep["passed"] else "FAILED")
        sys.exit(0 if rep["passed"] else 3)
    elif cmd == "walkforward":
        if not (OUT / "review_passed.json").exists():
            log("refusing: the pre-run review has not passed (make review)")
            sys.exit(3)
        status("walk-forward", "auto-calibrated, purged CV, meta-labelling")
        res = WF.walk_forward(strategy(c), market(c), settings(c), log)
        (OUT / "wf.pkl").write_bytes(pickle.dumps(res))
        status("walk-forward done", f"{len(res['history'])} years")
    elif cmd == "report":
        status("report", "PBO, CPCV, DSR, dashboard JSON")
        res = pickle.loads((OUT / "wf.pkl").read_bytes())
        rv = json.loads((OUT / "review.json").read_text()) if (OUT / "review.json").exists() else None
        p = c["project"]
        RB.build(p.get("title", p["name"]), {p.get("system_name", "System"): res}, market(c), OUT, strategy(c), settings(c),
                 review=rv, notes=c.get("report", {}).get("notes", []))
        status("done", "results.json ready: make serve", 1.0)
    elif cmd == "audit":
        # the "too good to be true" audit (amq.audit.forensics); [audit] in config.toml:
        #   rebuild = ["2015-01-01"]  point-in-time re-runs (each costs a walk-forward up to that date)
        #   provenance = "..."        where the idea came from; provenance_status = "pass" | "warn" | "fail"
        #   start = "2010-01-01"      audit window (default: the whole out-of-sample record)
        status("audit", "luck, search, market, errors, fragility")
        res = pickle.loads((OUT / "wf.pkl").read_bytes())
        R = json.loads((OUT / "results.json").read_text()) if (OUT / "results.json").exists() else {}
        oof = pd.read_pickle(OUT / "oof.pkl") if (OUT / "oof.pkl").exists() else None
        a, st, strat, mk = c.get("audit", {}), settings(c), strategy(c), market(c)

        def rebuild(dt):
            n = int(np.searchsorted(mk["dates"], pd.Timestamp(dt)))
            cut = {k: (v[:n] if hasattr(v, "__len__") and len(v) == len(mk["dates"]) else v) for k, v in mk.items()}
            log(f"point-in-time rebuild with data before {dt}")
            return WF.walk_forward(strat, cut, st, log=lambda m: None)["position"]
        prov = {"text": a["provenance"], "status": a.get("provenance_status", "warn")} if a.get("provenance") else None
        rep = AU.audit(c["project"].get("system_name", "System"), res["returns"], pd.Series(mk["r"], index=mk["dates"]),
                       res["position"], cost=st.cost, n_trials=R.get("n_trials", res["n_trials"]), var_sr=R.get("var_sr"),
                       universe=oof, pbo_universe=oof, rebuild=rebuild if a.get("rebuild") else None,
                       rebuild_dates=a.get("rebuild", []), provenance=prov, start=a.get("start"))
        rep["key"] = "system"
        out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "start": rep["period"].split(" ")[0],
               "n_trials": R.get("n_trials", res["n_trials"]), "audits": [rep], "findings": AU.summarize(rep)}
        (OUT / "audit.json").write_text(json.dumps(RB._clean(out), default=str))
        for t in rep["tests"]:
            log(f"  {t['id']:14s} {t['status']:5s} {t['title']}: {t['value']}")
        log(f"verdict: {rep['verdict_text']}")
        status("audit done", rep["verdict_text"], 1.0)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
