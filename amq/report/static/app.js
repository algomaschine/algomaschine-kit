"use strict";
/* AlgoMaschine results dashboard (algomaschine-kit): any project's results.json and audit.json. Every chart card has a "?"
   (plain-English explanation) and a full-screen button; charts follow their container; dotted terms explain themselves. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const FONT = "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
const T = () => ({ ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"), grid: css("--grid"), axis: css("--axis"),
  surface: css("--surface"), raised: css("--raised"), ring2: css("--ring-2"), volume: css("--volume"),
  s: [css("--s3"), css("--s1"), css("--s2")], bench: css("--bench"), pos: css("--div-pos"), neg: css("--div-neg") });
const charts = {};
const cache = {};
const rendered = {};
const minus = (s) => String(s).replace(/(^|[^\w.])-(?=\d)/g, "$1−");
const pct = (x, d = 1) => (x == null || !isFinite(x) ? "–" : minus((x * 100).toFixed(d) + "%"));
const num = (x, d = 2) => (x == null || !isFinite(x) ? "–" : minus(Number(x).toFixed(d)));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const term = (k, label) => `<span class="term" tabindex="0" data-term="${k}">${label}</span>`;

const GLOSS = {
  cagr: ["CAGR", "Compound annual growth rate: the constant yearly return that turns the starting capital into the final capital."],
  vol: ["Volatility", "How much returns swing: the annualised standard deviation of daily returns."],
  sharpe: ["Sharpe ratio", "Average return divided by volatility, per year: reward per unit of risk. Above 1 is rare for a daily strategy; far above 2 usually signals an error."],
  sortino: ["Sortino ratio", "Like the Sharpe ratio, but only downside swings count as risk."],
  maxdd: ["Maximum drawdown", "The largest fall from a previous peak."],
  calmar: ["Calmar ratio", "Annual growth divided by the maximum drawdown."],
  hit: ["Hit rate", "Share of days with a position on which the system made money."],
  psr: ["Probabilistic Sharpe ratio", "The probability that the true Sharpe ratio is above zero, given the record's length and fat tails."],
  dsr: ["Deflated Sharpe ratio", "The probability that the Sharpe ratio beats the best of all the configurations tried, had none of them any skill. Below 0.95 is not evidence."],
  beta: ["Beta", "Sensitivity to the market: 1 moves with it, 0 ignores it."],
  alpha: ["Alpha", "Return per year not explained by the market's moves."],
  pbo: ["Probability of backtest overfitting", "How often the best configuration on one half of the history ranks below the median on the other half."],
  tvalue: ["t-value", "How many standard errors an average lies from zero."],
};
const EXPLAIN = {
  main: ["The traded market and the value of $1 invested in the system, walked forward: every year's trades were chosen with data from before that year.",
    "Two scales compares with the market's level; one scale compares growth directly. Drag or scroll to zoom.",
    "A smooth line is not evidence on its own: the Audit tab asks whether luck, the market, the search or an error could explain it."],
  dd: ["How far the system and buy-and-hold were below their previous peak on each day.", "Deeper and longer valleys mean more pain.",
    "Shallow drawdowns often reflect time spent in cash rather than skill."],
  perf: ["Standard statistics for each period, net of costs.", "Hover a heading for its definition; compare the Sharpe interval and the deflated Sharpe ratio.",
    "A deflated Sharpe ratio below 0.95 means the result is not significant once every trial is counted."],
  cal: ["The configuration the calibration chose each year, using purged cross-validation on data before that year.",
    "Stable choices suggest a robust setting; erratic jumps suggest noise.", "The calibration never sees the year it trades."],
  pbo: ["Results of thousands of in-sample/out-of-sample splits of the history.", "Bars left of zero: the best configuration in-sample fell below the median out of sample.",
    "A low share on the left means choosing among configurations was meaningful. It says nothing about profitability."],
  cpcv: ["Several complete backtest paths built from different train/test splits, for the most frequently chosen configuration.",
    "Each bar is one path's Sharpe ratio, sorted. Teal paths made money, red paths lost.", "One path can be lucky; a robust rule shows most paths in profit."],
  review: ["Tests of the machinery itself, run before any real-data walk-forward.", "Every line must pass.", "If the machine finds profits in noise, its real results mean nothing."],
  trades: ["The most recent trades, with the meta-model's probability and the bet size.", "Side is long or short; size scales the position.", "Shows what the system actually did."],
  findings: ["The audit's main conclusions in plain words.", "Each point refers to tests listed below.", "The part to read if you read nothing else."],
  detail: ["The full record of every test.", "Value, pass rule, reason and source for each.", "The rules were fixed before the results were seen."],
};

// ------------------------------------------------------------------ helpers: charts, axes, legends
async function get(url) {
  if (cache[url]) return cache[url];
  const j = await (await fetch(url, { cache: "no-store" })).json();
  if (!j.pending) cache[url] = j;
  return j;
}
const ro = typeof ResizeObserver !== "undefined"
  ? new ResizeObserver((es) => es.forEach((e) => { const c = charts[e.target.id]; if (c && e.contentRect.width > 0) c.resize(); })) : null;
function chart(id) {
  const el = document.getElementById(id);
  if (charts[id]) charts[id].dispose();
  charts[id] = echarts.init(el, null, { renderer: "canvas" });
  if (ro) ro.observe(el);
  return charts[id];
}
const base = (t) => ({ textStyle: { color: t.ink2, fontFamily: FONT, fontSize: 12 },
  tooltip: { backgroundColor: t.raised, borderColor: t.ring2, borderWidth: 1, textStyle: { color: t.ink, fontSize: 12, fontFamily: FONT }, confine: true,
    extraCssText: "border-radius:6px;box-shadow:0 6px 18px rgba(0,0,0,0.12);" }, animationDuration: 250 });
const axisStyle = (t, extra = {}) => ({ axisLine: { lineStyle: { color: t.axis } }, axisTick: { show: false },
  axisLabel: { color: t.muted, fontSize: 11, hideOverlap: true }, splitLine: { lineStyle: { color: t.grid } }, ...extra });
const GRID = { left: 4, right: 14, top: 10, bottom: 4, containLabel: true };
const TIME_LABELS = { year: "{yyyy}", month: "{MMM}", day: "{d} {MMM}", hour: "", minute: "", second: "", millisecond: "" };
function logTicks(lo, hi) {
  const out = [];
  for (let k = Math.floor(Math.log10(lo)); k <= Math.ceil(Math.log10(hi)); k++) [1, 2, 5].forEach((m) => { const v = m * 10 ** k; if (v >= lo && v <= hi) out.push(v); });
  return out;
}
const fmtLevel = (x) => (x >= 1000 ? +(x / 1000).toFixed(1) + "k" : String(+x.toPrecision(3)));
function logAxis(t, values, extra = {}) {
  const v = values.filter((x) => x > 0 && isFinite(x));
  const lo = Math.min(...v) * 0.94, hi = Math.max(...v) * 1.06, ticks = logTicks(lo, hi);
  return { type: "log", min: lo, max: hi, ...axisStyle(t), axisLabel: { color: t.muted, fontSize: 11, customValues: ticks, formatter: fmtLevel },
    axisTick: { show: false, customValues: ticks }, ...extra };
}
const zoomSlider = (t, extra = {}) => ({ type: "slider", height: 20, bottom: 8, borderColor: t.ring2, textStyle: { color: t.muted },
  fillerColor: "rgba(128,128,128,0.10)", handleStyle: { color: t.surface, borderColor: t.axis }, moveHandleStyle: { color: t.axis },
  dataBackground: { lineStyle: { color: t.axis }, areaStyle: { color: t.grid } },
  selectedDataBackground: { lineStyle: { color: t.ink2 }, areaStyle: { color: t.axis, opacity: 0.35 } },
  emphasis: { handleStyle: { borderColor: t.ink2 }, moveHandleStyle: { color: t.ink2 } }, ...extra });
function legendFor(id, items, interactive = true) {
  const el = document.getElementById(id);
  let lg = el.previousElementSibling;
  if (!lg || !lg.classList.contains("legend")) { lg = document.createElement("div"); lg.className = "legend"; el.before(lg); }
  lg.innerHTML = items.map((it) => interactive
    ? `<button type="button" class="lg-item" data-name="${esc(it.name)}" aria-pressed="true" title="Show or hide"><span class="sw ${it.kind || "line"}" style="--c:${it.color}"></span>${esc(it.name)}</button>`
    : `<span class="lg-item"><span class="sw ${it.kind || "line"}" style="--c:${it.color}"></span>${esc(it.name)}</span>`).join("");
  if (interactive) lg.querySelectorAll("button.lg-item").forEach((b) => b.addEventListener("click", () => {
    b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
    charts[id].dispatchAction({ type: "legendToggleSelect", name: b.dataset.name });
  }));
}
const _ctx = (() => { try { return document.createElement("canvas").getContext("2d"); } catch (e) { return null; } })();
const textW = (s, size = 11) => { if (!_ctx) return String(s).length * size * 0.58; _ctx.font = `${size}px ${FONT}`; return _ctx.measureText(String(s)).width; };
function catGrid(labels, maxW, extra = {}) {
  const w = Math.ceil(Math.min(maxW, Math.max(40, ...labels.map((l) => textW(l) * 1.15 + 6))));
  return { grid: { left: w + 16, right: 40, top: 8, bottom: 24, containLabel: false, ...extra }, labelWidth: w };
}

// ------------------------------------------------------------------ card tools, glossary, routing, theme
function enhanceCards() {
  $$("figure.card").forEach((card) => {
    if (card.dataset.enhanced) return;
    card.dataset.enhanced = "1";
    const head = $(".card-head", card);
    if (!head) return;
    const tools = document.createElement("div");
    tools.className = "card-tools";
    const ex = EXPLAIN[card.dataset.explain];
    if (ex) {
      const b = document.createElement("button");
      b.className = "tool"; b.type = "button"; b.textContent = "?"; b.title = "What am I looking at?";
      b.setAttribute("aria-expanded", "false"); b.setAttribute("aria-label", "Explain this panel");
      const panel = document.createElement("div");
      panel.className = "explain"; panel.hidden = true;
      panel.innerHTML = `<p><b>What it shows.</b> ${ex[0]}</p><p><b>How to read it.</b> ${ex[1]}</p><p><b>Why it matters.</b> ${ex[2]}</p>`;
      head.after(panel);
      b.addEventListener("click", () => { panel.hidden = !panel.hidden; b.setAttribute("aria-expanded", String(!panel.hidden)); resizeIn(card); });
      tools.appendChild(b);
    }
    if ($(".chart", card)) {
      const m = document.createElement("button");
      m.className = "tool"; m.type = "button"; m.title = "Full screen"; m.setAttribute("aria-label", "Show this chart full screen");
      m.innerHTML = `<svg aria-hidden="true"><use href="#i-expand"/></svg>`;
      m.addEventListener("click", () => toggleMax(card));
      tools.appendChild(m);
    }
    head.appendChild(tools);
  });
}
function resizeIn(card) { setTimeout(() => $$(".chart", card).forEach((el) => charts[el.id] && charts[el.id].resize()), 60); }
function maxButton(card, on) {
  const b = $$(".tool", card).find((x) => x.querySelector("use"));
  if (b) { b.innerHTML = `<svg aria-hidden="true"><use href="#i-${on ? "collapse" : "expand"}"/></svg>`; b.title = on ? "Exit full screen" : "Full screen"; }
}
function toggleMax(card) {
  if (document.fullscreenEnabled && card.requestFullscreen) {
    if (document.fullscreenElement === card) document.exitFullscreen(); else card.requestFullscreen().catch(() => fallbackMax(card));
  } else fallbackMax(card);
}
function fallbackMax(card) {
  const on = !card.classList.contains("is-max");
  $$(".card.is-max").forEach((c) => { c.classList.remove("is-max"); maxButton(c, false); });
  card.classList.toggle("is-max", on);
  document.body.classList.toggle("has-max", on);
  maxButton(card, on);
  resizeIn(card);
}
document.addEventListener("fullscreenchange", () => $$("figure.card").forEach((c) => { maxButton(c, document.fullscreenElement === c); resizeIn(c); }));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $$(".card.is-max").forEach((c) => fallbackMax(c)); });
const tip = $("#tip");
function showTip(el) {
  const g = GLOSS[el.dataset.term];
  if (!g) return;
  tip.innerHTML = `<b>${g[0]}</b><br>${g[1]}`;
  tip.hidden = false;
  const r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(Math.max(8, r.left), window.innerWidth - w - 8) + "px";
  tip.style.top = (r.bottom + 8 + h > window.innerHeight - 8 ? Math.max(8, r.top - h - 8) : r.bottom + 8) + "px";
}
const hideTip = () => { tip.hidden = true; };
document.addEventListener("mouseover", (e) => { const el = e.target.closest && e.target.closest(".term"); if (el) showTip(el); });
document.addEventListener("mouseout", (e) => { if (e.target.closest && e.target.closest(".term")) hideTip(); });
document.addEventListener("focusin", (e) => { if (e.target.classList && e.target.classList.contains("term")) showTip(e.target); });
document.addEventListener("focusout", hideTip);
window.addEventListener("scroll", hideTip, { passive: true });

const TABS = ["results", "audit"];
let current = "results";
function route() { const h = location.hash.replace("#", ""); show(TABS.includes(h) ? h : "results"); }
function show(tab) {
  current = tab;
  $$(".tabs a[data-tab]").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  TABS.forEach((s) => ($("#tab-" + s).hidden = s !== tab));
  if (!rendered[tab]) { rendered[tab] = true; ({ results: renderResults, audit: renderAudit })[tab](); }
  setTimeout(() => Object.values(charts).forEach((c) => c.resize()), 60);
}
window.addEventListener("hashchange", route);
$("#theme").addEventListener("click", () => {
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("am-theme", next); } catch (e) {}
  for (const k in rendered) rendered[k] = false;
  show(current);
});
async function pollStatus() {
  try {
    const s = await (await fetch("api/status", { cache: "no-store" })).json();
    const st = s.status;
    const busy = st && st.stage && !/done/.test(st.stage);
    $("#status").innerHTML = `<span><span class="dot ${busy ? "busy" : "on"}"></span>${busy ? esc(st.stage) : "Live"}</span>`;
  } catch (e) { $("#status").innerHTML = `<span><span class="dot bad"></span>Offline</span>`; }
}

// ------------------------------------------------------------------ results
let scale = "dual";
$$("[data-scale]").forEach((b) => b.addEventListener("click", () => {
  scale = b.dataset.scale; $$("[data-scale]").forEach((x) => x.setAttribute("aria-pressed", x === b)); if (cache["api/results"]) mainChart(cache["api/results"]); }));

async function renderResults() {
  const R = await get("api/results");
  if (R.pending) {
    $("#pending").hidden = false; $("#pending").textContent = "No results yet: the walk-forward has not finished. This page refreshes itself.";
    rendered.results = false; setTimeout(() => { if (current === "results") renderResults(); }, 20000); return;
  }
  $("#pending").hidden = true;
  $("#title").textContent = R.title;
  $("#meta").textContent = `Generated ${R.generated} · ${R.systems.map((s) => s.name).join(" · ")} · benchmark: buy & hold of the traded market`;
  mainChart(R);
  rest(R);
}

function mainChart(R) {
  const t = T(), c = R.charts;
  const dual = scale === "dual";
  const pts = (arr) => arr.map((y, i) => [c.dates[i], y]);
  const hasVol = Array.isArray(c.volume);
  $("#main-sub").textContent = dual ? `Left axis: market level (log scale). Right axis: value of $1 invested in the system.${hasVol ? " Lower panel: daily volume." : ""}`
    : `Value of $1 invested in the system and in buy-and-hold.${hasVol ? " Lower panel: daily volume." : ""}`;
  const sys = R.systems.map((s, i) => ({ name: s.name, type: "line", showSymbol: false, data: pts(c[s.key + "_eq"]), yAxisIndex: dual ? 1 : 0,
    lineStyle: { width: 1.8, color: t.s[i] }, itemStyle: { color: t.s[i] } }));
  const bench = dual ? { name: "Market (left axis)", type: "line", showSymbol: false, data: pts(c.close), yAxisIndex: 0, lineStyle: { width: 1.2, color: t.bench }, itemStyle: { color: t.bench } }
    : { name: "Buy & hold", type: "line", showSymbol: false, data: pts(c.bench_eq), yAxisIndex: 0, lineStyle: { width: 1.2, color: t.bench }, itemStyle: { color: t.bench } };
  legendFor("c-main", [{ name: bench.name, color: t.bench }, ...R.systems.map((s, i) => ({ name: s.name, color: t.s[i] }))]
    .concat(hasVol ? [{ name: "Volume", color: t.volume, kind: "bar" }] : []));
  const y0 = dual ? { ...logAxis(t, c.close), gridIndex: 0 } : { type: "value", gridIndex: 0, scale: true, ...axisStyle(t), axisLabel: { color: t.muted, fontSize: 11, formatter: (x) => "$" + x.toFixed(x >= 10 ? 0 : 2) } };
  chart("c-main").setOption({ ...base(t), tooltip: { ...base(t).tooltip, trigger: "axis", axisPointer: { type: "cross", link: [{ xAxisIndex: "all" }], label: { backgroundColor: t.ink2 } },
      valueFormatter: (x) => (x == null ? "–" : Math.abs(x) > 1e6 ? (x / 1e9).toFixed(2) + "B" : Number(x).toFixed(2)) },
    axisPointer: { link: [{ xAxisIndex: "all" }] }, legend: { show: false },
    grid: hasVol ? [{ left: 58, right: 62, top: 12, bottom: "31%" }, { left: 58, right: 62, top: "73%", bottom: 46 }] : [{ left: 58, right: 62, top: 12, bottom: 46 }],
    xAxis: [{ type: "time", gridIndex: 0, ...axisStyle(t, { splitLine: { show: false } }), axisLabel: { show: !hasVol, color: t.muted, fontSize: 11, hideOverlap: true, formatter: TIME_LABELS } }]
      .concat(hasVol ? [{ type: "time", gridIndex: 1, ...axisStyle(t, { splitLine: { show: false } }), axisLabel: { color: t.muted, fontSize: 11, hideOverlap: true, formatter: TIME_LABELS } }] : []),
    yAxis: [y0, { type: "value", gridIndex: 0, position: "right", show: dual, scale: true, ...axisStyle(t, { splitLine: { show: false } }), axisLabel: { color: t.muted, fontSize: 11, formatter: (x) => "$" + x.toFixed(2) } }]
      .concat(hasVol ? [{ type: "value", gridIndex: 1, ...axisStyle(t), splitNumber: 2, axisLabel: { color: t.muted, fontSize: 11, formatter: (x) => (x >= 1e9 ? x / 1e9 + "B" : x >= 1e6 ? x / 1e6 + "M" : x) } }] : []),
    dataZoom: [{ type: "inside", xAxisIndex: hasVol ? [0, 1] : [0] }, zoomSlider(t, { xAxisIndex: hasVol ? [0, 1] : [0] })],
    series: [bench, ...sys].concat(hasVol ? [{ name: "Volume", type: "bar", xAxisIndex: 1, yAxisIndex: 2, data: pts(c.volume), itemStyle: { color: t.volume }, large: true }] : []) });
  const dds = [{ name: "Buy & hold", data: c.bench_dd, color: t.bench }, ...R.systems.map((s, i) => ({ name: s.name, data: c[s.key + "_dd"], color: t.s[i] }))];
  legendFor("c-dd", dds.map((s) => ({ name: s.name, color: s.color })));
  chart("c-dd").setOption({ ...base(t), tooltip: { ...base(t).tooltip, trigger: "axis", valueFormatter: (x) => pct(x) }, legend: { show: false }, grid: GRID,
    xAxis: { type: "time", ...axisStyle(t, { splitLine: { show: false } }), axisLabel: { color: t.muted, fontSize: 11, hideOverlap: true, formatter: TIME_LABELS } },
    yAxis: { type: "value", max: 0, ...axisStyle(t), axisLabel: { color: t.muted, fontSize: 11, formatter: (x) => pct(x, 0) } }, dataZoom: [{ type: "inside" }],
    series: dds.map((s) => ({ name: s.name, type: "line", showSymbol: false, data: pts(s.data), lineStyle: { width: 1.5, color: s.color }, itemStyle: { color: s.color } })) });
}

function rest(R) {
  const t = T();
  const prim = R.table.find((r) => r.system === (R.systems[0] || {}).name) || {};
  $("#tiles").innerHTML = [["Growth a year", pct(prim.cagr)], ["Sharpe ratio", `${num(prim.sharpe)} <span class="small muted">[${num(prim.sharpe_ci && prim.sharpe_ci[0])}, ${num(prim.sharpe_ci && prim.sharpe_ci[1])}]</span>`],
    ["Max drawdown", pct(prim.maxdd)], ["Deflated Sharpe", num(prim.dsr)], ["PBO", R.pbo ? num(R.pbo.pbo) : "–"]]
    .map(([l, v]) => `<div class="tile"><div class="v">${v}</div><div class="l">${esc(l)}</div></div>`).join("");
  $("#ntrials").textContent = `${R.n_trials} trials`;
  const H = [["Period"], ["System", null, "left"], ["CAGR", "cagr"], ["Volatility", "vol"], ["Sharpe [95% CI]", "sharpe"], ["Sortino", "sortino"], ["Max drawdown", "maxdd"],
    ["Calmar", "calmar"], ["Hit rate", "hit"], ["PSR", "psr"], ["DSR", "dsr"], ["Beta", "beta"], ["Alpha / year", "alpha"]];
  $("#t-perf").innerHTML = `<table><thead><tr>${H.map(([h, k, a]) => `<th${a ? ' style="text-align:left"' : ""}>${k ? term(k, h) : h}</th>`).join("")}</tr></thead><tbody>` +
    R.table.map((r) => `<tr><td>${esc(r.period)}</td><td style="text-align:left">${esc(r.system)}</td><td>${pct(r.cagr)}</td><td>${pct(r.vol)}</td><td>${num(r.sharpe)} [${num(r.sharpe_ci && r.sharpe_ci[0])}, ${num(r.sharpe_ci && r.sharpe_ci[1])}]</td><td>${num(r.sortino)}</td><td>${pct(r.maxdd)}</td><td>${num(r.calmar)}</td><td>${pct(r.hit, 0)}</td><td>${num(r.psr0)}</td><td>${num(r.dsr)}</td><td>${num(r.beta)}</td><td>${pct(r.alpha_ann)}</td></tr>`).join("") + "</tbody></table>";
  const cal = (R.calibration || []).filter((h) => h.chosen);
  const lab = (c) => (typeof c === "object" && !Array.isArray(c) ? Object.entries(c).map(([k, v]) => `${k} ${v}`).join(" · ") : String(c));
  const cats = [...new Set(cal.map((h) => lab(h.chosen)))];
  const cg = catGrid(cats, 220, { top: 12, bottom: 28 });
  const ys = cal.map((h) => h.year), span = Math.max(1, Math.max(...ys) - Math.min(...ys));
  const step = [1, 2, 5, 10, 20].find((s) => span / s <= 7) || 20;
  const yMin = Math.floor(Math.min(...ys) / step) * step, yMax = Math.ceil(Math.max(...ys) / step) * step;
  chart("c-cal").setOption({ ...base(t), tooltip: { ...base(t).tooltip, formatter: (p) => { const h = cal[p.dataIndex]; return `<b>${h.year}</b> ${esc(lab(h.chosen))}<br>CV Sharpe ${num(h.cv_sr)} · trades ${h.n_trades}`; } },
    grid: cg.grid, xAxis: { type: "value", min: yMin, max: yMax, interval: step, ...axisStyle(t), axisLabel: { color: t.muted, fontSize: 11, formatter: (x) => String(x) } },
    yAxis: { type: "category", data: cats, ...axisStyle(t), axisLabel: { color: t.ink2, fontSize: 11, width: cg.labelWidth, overflow: "truncate" } },
    series: [{ type: "scatter", data: cal.map((h) => [h.year, lab(h.chosen), h.cv_sr]), symbolSize: (v) => 6 + 3 * Math.max(0, Math.min(4, v[2] || 0)), itemStyle: { color: t.s[0], borderColor: t.surface, borderWidth: 1 } }] });
  const bins = {}; (R.pbo_logits || []).forEach((x) => { const b = Math.round(x * 4) / 4; bins[b] = (bins[b] || 0) + 1; });
  const bk = Object.keys(bins).map(Number).sort((a, b) => a - b);
  $("#pbo-sub").innerHTML = R.pbo ? `${term("pbo", "PBO")} = <b>${num(R.pbo.pbo)}</b> across ${Number(R.pbo.n_splits).toLocaleString("en-US")} splits. Bars left of zero: the in-sample best fell below the median out of sample.` : "Not computed (needs several configurations).";
  chart("c-pbo").setOption({ ...base(t), tooltip: { ...base(t).tooltip, trigger: "axis" }, grid: { ...GRID, top: 12 },
    xAxis: { type: "category", data: bk.map((b) => b.toFixed(2)), ...axisStyle(t), axisLabel: { color: t.muted, fontSize: 11, hideOverlap: true, formatter: (x) => minus(x) } },
    yAxis: { type: "value", ...axisStyle(t) },
    series: [{ type: "bar", barCategoryGap: "8%", data: bk.map((b) => ({ value: bins[b], itemStyle: { color: b <= 0 ? t.neg : t.pos, borderRadius: [3, 3, 0, 0] } })) }] });
  const pv = ((R.cpcv || {}).path_sharpes || []).filter((x) => x != null);
  $("#cpcv-sub").textContent = R.cpcv ? `Configuration ${R.cpcv.config} · ${R.cpcv.splits} splits → ${R.cpcv.paths} paths. ${pv.filter((x) => x > 0).length} of ${pv.length} paths have a positive Sharpe ratio.` : "Not computed.";
  const pvs = pv.map((x, i) => [x, `Path ${i + 1}`]).sort((a, b) => a[0] - b[0]);
  chart("c-cpcv").setOption({ ...base(t), tooltip: { ...base(t).tooltip, trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (x) => num(x) }, grid: { ...GRID, top: 8, right: 40 },
    xAxis: { type: "value", ...axisStyle(t), axisLabel: { color: t.muted, fontSize: 11, formatter: (x) => num(x, 1) } },
    yAxis: { type: "category", data: pvs.map((p) => p[1]), ...axisStyle(t), axisLabel: { color: t.ink2, fontSize: 11 } },
    series: [{ type: "bar", barWidth: "58%", data: pvs.map(([x]) => ({ value: x, itemStyle: { color: x >= 0 ? t.pos : t.neg, borderRadius: x >= 0 ? [0, 3, 3, 0] : [3, 0, 0, 3] } })),
      label: { show: true, position: "right", color: t.ink2, fontSize: 11, formatter: (p) => num(p.value) },
      markLine: { symbol: "none", silent: true, lineStyle: { color: t.muted }, label: { show: false }, data: [{ xAxis: 0 }] } }] });
  const rv = R.review && R.review.hard ? Object.entries(R.review.hard) : [];
  $("#review").innerHTML = rv.length ? `<table class="checks"><tbody>${rv.map(([k, v]) => `<tr><td>${badge(v.ok ? "pass" : "fail")}</td><td class="wrap" style="text-align:left">${esc(k)}<div class="small muted">${esc(v.detail)}</div></td></tr>`).join("")}</tbody></table>`
    : "<p class='muted'>No review attached: run <code>make review</code>.</p>";
  $("#notes").innerHTML = (R.notes || []).map((n) => `<p>${esc(n)}</p>`).join("") || "<p class='muted'>None recorded.</p>";
  $("#t-trades").innerHTML = `<table><thead><tr><th>Entry</th><th>Exit</th><th>Side</th><th>Probability (meta-model)</th><th>Size</th></tr></thead><tbody>` +
    (R.trades || []).slice(-60).reverse().map((x) => `<tr><td>${x.entry}</td><td>${x.exit}</td><td>${x.side > 0 ? "long" : "short"}</td><td>${num(x.p)}</td><td>${num(x.size, 1)}</td></tr>`).join("") + "</tbody></table>";
}

// ------------------------------------------------------------------ audit
const ICON = { pass: "✓", warn: "!", fail: "✕", info: "i" };
const LABEL = { pass: "Pass", warn: "Warn", fail: "Fail", info: "Info" };
const badge = (s, text) => `<span class="badge ${s}"><span class="ic" aria-hidden="true">${ICON[s]}</span>${text || LABEL[s]}</span>`;
const VCLASS = { "not proven": "not-proven", inconclusive: "inconclusive", credible: "credible" };
const VBADGE = { "not proven": "fail", inconclusive: "warn", credible: "pass" };
let auditSel = 0;
function auditNote(a) {
  const m = a.audits[0];
  $("#audit-note").innerHTML = `<b>Before you read the numbers.</b> The <a href="#audit">Audit</a>'s verdict on ${esc(m.name)} is <b>${esc(m.verdict)}</b>: ${esc(m.verdict_text.split(":").slice(1).join(":").trim())}`;
}
async function renderAudit() {
  const a = await get("api/audit");
  if (a.pending) { $("#audit-pending").hidden = false; $("#audit-pending").innerHTML = "No audit yet: run <code>make audit</code> after <code>make report</code>."; rendered.audit = false; return; }
  $("#audit-pending").hidden = true;
  const A = a.audits;
  $("#audit-meta").textContent = `Computed ${a.generated} · ${a.n_trials} trials in the ledger`;
  $("#verdicts").innerHTML = A.map((x) => `<div class="verdict ${VCLASS[x.verdict]}"><div class="name">${esc(x.name)}</div><div class="period">${esc(x.period)}</div>
    <div class="v">${badge(VBADGE[x.verdict], x.verdict === "not proven" ? "Not proven" : x.verdict === "inconclusive" ? "Inconclusive" : "Credible so far")}</div>
    <div class="counts">${["pass", "warn", "fail"].map((s) => badge(s, `${x.summary[s]} ${LABEL[s].toLowerCase()}`)).join("")}</div>
    <div class="sr">Sharpe ratio ${num(x.sharpe)}. ${esc(cap(x.verdict_text.split(":").slice(1).join(":").trim()))}</div></div>`).join("");
  $("#findings").innerHTML = (a.findings || []).map((f) => `<li>${f}</li>`).join("");
  $("#detail-seg").innerHTML = A.length > 1 ? A.map((x, i) => `<button type="button" aria-pressed="false" data-i="${i}">${esc(x.name)}</button>`).join("") : "";
  $$("#detail-seg button").forEach((b) => b.addEventListener("click", () => auditDetail(A, +b.dataset.i)));
  auditDetail(A, Math.min(auditSel, A.length - 1));
  auditNote(a);
}
function auditDetail(A, i) {
  auditSel = i;
  const x = A[i];
  $$("#detail-seg button").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.i === i)));
  $("#detail-title").textContent = `All tests · ${x.name} · ${x.period}`;
  let g = null;
  $("#tests").innerHTML = x.tests.map((t) => {
    const head = t.group !== g ? `<h3 style="margin:10px 0 2px">${esc((g = t.group))}</h3>` : "";
    return `${head}<div class="test"><div>${badge(t.status)}</div><div><span class="t">${esc(t.title)}</span></div>
      <div class="val" style="grid-column:2">${esc(t.value)}</div><div class="rule">Rule: ${esc(t.rule)}</div><div class="why">${esc(t.why)}</div><div class="ref">${esc(t.ref)}</div></div>`;
  }).join("");
}

enhanceCards();
route();
pollStatus();
setInterval(pollStatus, 20000);
get("api/audit").then((a) => { if (!a.pending) auditNote(a); }).catch(() => {});
