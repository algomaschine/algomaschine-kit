"""amq.ops.bench: Rust (relay_core) vs Python references for the kit's tools, equality + speed.
    python -m amq.ops.bench"""
import json
import os
import time
from pathlib import Path

import numpy as np

from amq.afml import tools as W


def _t(fn, reps=5):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        out = fn()
        ts.append(time.perf_counter() - t0)
    return out, float(np.median(ts))


def main():
    if W.rc is None:
        print("relay_core not installed: make rust")
        return
    rng = np.random.default_rng(0)
    x = np.cumsum(rng.standard_t(4, 25000) * 0.01)
    h = np.full(len(x), np.log1p(0.05))
    rows = []
    for name, py, rs in [
        ("zig-zag (Merrill filter)", lambda: W.zigzag_py(x, h), lambda: W.rc.zigzag(x, h)),
        ("CUSUM filter", lambda: W.cusum_py(np.diff(x), np.full(len(x) - 1, 0.03)), lambda: W.rc.cusum_filter(np.diff(x), np.full(len(x) - 1, 0.03))),
        ("trend scanning 5..60", lambda: W.trend_scan_py(x, 5, 60), lambda: W.rc.trend_scan(x, 5, 60, 1)),
    ]:
        a, tp = _t(py, 3)
        b, tr = _t(rs, 10)
        same = all(np.allclose(np.asarray(u, float), np.asarray(v, float), equal_nan=True) for u, v in zip(a, b))
        rows.append({"kernel": name, "python_s": tp, "rust_s": tr, "speedup": tp / tr, "identical": bool(same)})
        print(f"{name:28s} python {tp:8.4f}s  rust {tr:8.5f}s  x{tp / tr:7.1f}  identical {same}")
    out = Path(os.environ.get("AMQ_OUT", "outputs"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "bench.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
