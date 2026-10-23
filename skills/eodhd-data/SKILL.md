---
name: eodhd-data
description: Download and QA market data from EODHD the AlgoMaschine way — daily EOD, 1-minute intraday resampled to 5 minutes with chunked resumable caching, extra series, and the clock QA gate. Use when a strategy needs quotes (FX, indices, ETFs, crypto, EM FX), when adding an extra data source, or when results look too good (check timestamps first).
---

# EODHD data (amq.data)

- Token: `EODHD_API_TOKEN` env, `./.env`, or `~/.config/amq/.env`. Never print it or commit it.
- Daily: `eodhd.daily("GSPC.INDX")` -> OHLCV + adjusted_close, cached CSV in $AMQ_DATA. Full index history
  (GSPC from 1927; volume from 1950; OHLC close-only before 1962).
- Intraday: `eodhd.intraday("EURUSD.FOREX", start)` -> 5m bars from 1m, 110-day chunks cached as parquet
  (resumable), labelled by bar START in UTC, `n` = 1m bars per 5m (holes / liquidity).
- Symbols: FX `EURUSD.FOREX`, index `GSPC.INDX`, US ETF `SPY.US`, crypto `BTC-USD.CC`, VIX `VIX.INDX`.
- Alignment: `known_before(series, dates)` = last value strictly before each date. Decide on day t only with data
  known before the decision time (clock time!), trade at the next close.

## Always run the clock QA gate (`make qa`)
Payrolls spike (first Friday 08:30 NY) must sit in the 08:25-08:45 NY bars; the 5m correlation with SPY must peak
at lag 0. EODHD FX/metals intraday before 2021 was stamped in New York time labelled UTC (a 4-5 h shift that
manufactured a Sharpe-3 "strategy"). Drop failing years.

## Quote traps
- Spreads widen at the 17:00 NY rollover and at EM local opens: bid-side quotes drift mechanically as spreads
  narrow. Restrict each market to its liquid hours; verify intraday edges with bid/ask data (e.g. Dukascopy).
- NDF currencies (KRW, TWD, INR, PHP) switch quote source at the onshore open.
- **Daily FOREX metals bars change their date convention from year to year.** In some years (gold 2017, 2019, 2020; silver
  2006-2010, 2012, 2017-2021) each bar is labelled by the day its session OPENS: a "Sunday" row holds Monday's close, every
  bar sits one day early, and Friday's close appears twice. Dropping weekend rows then silently merges sessions. Check each
  year against an ETF on the same metal (GLD, SLV, PPLT, PALL): if the vendor's return on day t matches the ETF's on t+1
  better than on t, shift that year's Sun-Thu rows one weekday forward and drop its Friday row. Platinum, palladium and the indices were clean when checked (2026-09).
- ETF overnight returns: use `open * (adjusted_close / close)` against the previous adjusted close (dividends).
- FX positions held overnight earn/pay carry: add rate differentials before trusting FX trend P&L.
