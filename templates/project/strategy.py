"""Example strategy (replace with your idea): AFML CUSUM-filter events, side learned per volatility regime.

The engine calls grid(), prepare(), candidates(); fit_side()/side() learn and apply what the rule needs from
TRAINING events only. Every configuration in grid() is a trial (deflated Sharpe, PBO)."""
import numpy as np

from amq.afml import tools as W
from amq.engine.walkforward import Strategy as Base


class Strategy(Base):
    name = "cusum-regime"

    def __init__(self, config):
        self.config = config

    def grid(self):
        return [{"k": k, "h": h} for k in (1.5, 2.0, 3.0) for h in (5, 10, 21)]

    def prepare(self, mk):
        sig = np.nan_to_num(mk["sigma"], nan=np.inf)
        pct = np.full(len(sig), np.nan)
        for t in range(252, len(sig)):                      # causal volatility regime: tercile of the past year
            w = sig[t - 252:t + 1]
            pct[t] = (w < sig[t]).mean()
        return {"regime": np.digitize(np.nan_to_num(pct, nan=0.5), [1 / 3, 2 / 3])}

    def candidates(self, mk, prep, cfg, train_end):
        r = np.nan_to_num(mk["r"])
        h = cfg["k"] * np.nan_to_num(mk["sigma"], nan=np.inf)
        ix, sg = W.cusum_filter(r, h)                        # events at the close of ix; enter at ix + 1
        e = ix + 1
        ok = e < len(r)
        e, sg = e[ok], sg[ok]
        reg = prep["regime"][e - 1]
        return {"e": e, "h": np.full(len(e), cfg["h"]), "move": sg.astype(float), "regime": reg,
                "feat": np.column_stack([reg, sg])}

    def fit_side(self, mk, ev, idx, cfg):
        """Per (regime, move sign): follow or fade, from the mean forward return of training events."""
        x = mk["x"]
        e, h = ev["e"][idx], ev["h"][idx]
        fwd = x[np.minimum(e + h, len(x) - 1)] - x[e]
        table = {}
        for g in range(3):
            for s in (-1.0, 1.0):
                m = (ev["regime"][idx] == g) & (ev["move"][idx] == s)
                if m.sum() >= 10:
                    table[(g, s)] = np.sign(np.mean(fwd[m] * s))    # +1 follow the move, -1 fade it
        return table

    def side(self, mk, ev, model, idx, cfg):
        return np.array([model.get((ev["regime"][i], ev["move"][i]), 0.0) * ev["move"][i] for i in idx])
