---
name: algomaschine-reports
description: Build AlgoMaschine-branded infographics, live dashboards and white papers for quant results — the logotype as designed, a calm established style, validated palette, required panels (equity vs benchmark with volume and the two-scale toggle, drawdowns, performance table with CIs/DSR, calibration history, PBO, CPCV, review checks, audit verdict and tests, alpha atlas and decay), plain-English explanations for non-quant readers, full-screen responsive charts with no overlapping text. Use whenever results of a trading system are presented, charted, served as a web page or written up.
---

# AlgoMaschine reports

## Brand and house style
- **The logotype is never redrawn or simplified.** Use `brand/mark.svg` (the neon mark with its glow) and the white
  Montserrat Light wordmark (letter-spacing ~0.09em, its soft glow) exactly as designed, on the near-black plate
  `#14161a` (the AlgoMaschine Intelligence palette: black, white, gold): the top bar and the footer band are always that colour, in both themes. The mark is the favicon.
- Everything else is calm and established, never "neon": flat surfaces, hairline borders, 6 px radii, no glows,
  gradients or text-shadows outside the lockup. Inter for the interface (tabular figures), Source Serif 4 for long-form
  text, JetBrains Mono for code. Light and dark themes follow the OS preference, with a toggle.
- Typographic minus (−) for negative numbers; sentence-case headings; no emoji; status always icon + label.

## Palette (teal and amber validated earlier with the dataviz validator; the blue third colour and the gold ramp are new, so re-run the validator before relying on them)
- Systems, fixed order: light `#00928a`, `#a8690a`, `#3b5ba5` on `#ffffff`; dark `#1fa39c`, `#bd7f17`, `#7f9fe0` on `#15171a`.
  Benchmark = neutral reference line (`#5b6170` light / `#9aa1ad` dark), thinner and always labelled.
- Diverging (gain/loss): teal pole, red pole, neutral midpoint. Sequential: one gold ramp. Status colours are reserved.
- More than 3 series -> small multiples or an HTML legend with toggles, never new hues.

## Required panels for a trading-system result
1. Price with volume bars and the systems' equity: "two scales" (price left on a log axis with 1-2-5 ticks, systems right)
   plus a one-click "one scale · growth of $1" view (the honest comparison). Time axes, year labels.
2. Drawdowns. 3. Performance table: CAGR, vol, Sharpe [bootstrap 95% CI], Sortino, max DD, Calmar, hit rate,
   PSR, DSR (trial ledger), beta, alpha, per period. 4. Calibration history (config chosen each year).
5. PBO histogram of CSCV logits. 6. CPCV path Sharpes as sorted bars (teal positive, red negative). 7. Review checklist.
8. The audit (skill: backtest-audit): verdict cards, plain-English findings, the test matrix, every test's value, rule,
   reason and source. Put a one-line audit verdict above the results so nobody reads the equity curve first.
9. Caveats (data flags, costs, carry, dividends, interest). For multi-alpha systems add the alpha atlas (rows = alphas by
   first selection, cells = yearly net t, rings = years live) and the decay curve.

## For readers who are not quants
- Every chart card has a "?" panel: what it shows, how to read it, why it matters. Every table heading and technical term
  is a dotted-underlined glossary term with a plain definition on hover, focus or tap.
- Each page opens with an "In plain words" box. Rule names from the factory get a plain-English translation.
- A Method page (kit: `amq/report/static/method.html`) or a full white paper explains every method with its motivation,
  formulas (KaTeX), algorithms and schematic SVG diagrams; numbers in it are read live from the results JSON.

## Layout rules (no overlapping text, anywhere)
- No in-canvas chart titles or ECharts legends: titles and legends are HTML above the chart (legends wrap, click toggles).
- `grid.containLabel` for simple charts; for horizontal bars measure the category labels and reserve that width.
- Chart heights follow the viewport (`clamp()`), a ResizeObserver resizes charts, and every chart can go full screen
  (Fullscreen API with a fixed-overlay fallback). Tables scroll horizontally inside their card on phones.
- Diagrams: check every label against every line; put captions and legends where no line can cross them.

## How
`amq.report.build.build(...)` -> results.json; `make audit` -> audit.json; `make serve` -> token-protected dashboard on a
free port (`amq.report.app`: Results, Audit, Method). Verify with real screenshots, not only code review:
`~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell --no-sandbox
--hide-scrollbars --window-size=1440,4000 --virtual-time-budget=15000 --screenshot=out.png URL` (desktop, 390 px phone,
dark via `--force-dark-mode`), and run the page script in jsdom for runtime errors.
