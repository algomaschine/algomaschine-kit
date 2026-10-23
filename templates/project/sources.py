"""Extra data sources for this idea. Each loader returns a daily pd.Series indexed by date, and features must be
aligned so the value used on day t was known before the decision (amq.data.eodhd.known_before)."""
import pandas as pd

from amq.data import eodhd as E


def vix_close() -> pd.Series:
    """Example: the VIX close (16:15 NY, i.e. AFTER the S&P close): use known_before or shift(1)."""
    return E.daily("VIX.INDX")["close"]
