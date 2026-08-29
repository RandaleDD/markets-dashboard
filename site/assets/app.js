let DATA = null;
let REGION_ORDER = ["US", "UK", "EZ", "DE", "CH", "CN", "JP", "NO"];
const SERIES = {};          // "kind:id" -> {name, history}
let openChart = null;       // key of the currently expanded chart row

async function main() {
  const res = await fetch("data/latest.json", { cache: "no-store" });
  DATA = await res.json();
  window.__data = DATA;
  if (Array.isArray(DATA.regions) && DATA.regions.length) REGION_ORDER = DATA.regions;

  document.getElementById("as-of").textContent = DATA.generated_at
    ? new Date(DATA.generated_at).toLocaleString()
    : "unknown";

  if (DATA.is_sample) {
    const banner = document.getElementById("sample-banner");
    banner.hidden = false;
    banner.textContent = "Showing sample data — the live pipeline hasn't populated this yet.";
  }

  renderEquities();
  renderYields();
  renderMacro();
  renderCurrencies();
  renderCommodities();
  renderValuation();
  renderCrossAsset();
  populateRegionSelector();
  renderSnapshot(REGION_ORDER[0]);
  setupTabs();
  setupChartToggles();
  setupTooltips();
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------
function fmtPct(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return stubCell();
  const cls = v > 0 ? "up" : v < 0 ? "down" : "";
  const sign = v > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${v.toFixed(digits)}%</span>`;
}
function fmtBp(v) {
  if (v === null || v === undefined) return stubCell();
  const cls = v > 0 ? "up" : v < 0 ? "down" : "";
  return `<span class="${cls}">${v.toFixed(0)} bp</span>`;
}
function fmtNum(v, digits = 2) {
  if (v === null || v === undefined) return stubCell();
  return v.toFixed(digits);
}
function pctPlain(v, digits = 2) {
  if (v === null || v === undefined) return stubCell();
  return `${v.toFixed(digits)}%`;
}
function stubCell() {
  return '<span class="stub">not yet wired</span>';
}
function dash() {
  return '<span class="stub">—</span>';
}
function regionName(code) {
  return (DATA.region_names && DATA.region_names[code]) || code;
}
function note(text) {
  return text ? `<p class="section-note">${text}</p>` : "";
}

function sparkline(history) {
  if (!history || history.length < 2) return "";
  const values = history.map((d) => d[1]);
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const w = 100, h = 28;
  const points = values.map((v, i) =>
    `${((i / (values.length - 1)) * w).toFixed(1)},${(h - ((v - min) / range) * h).toFixed(1)}`
  ).join(" ");
  const up = values[values.length - 1] >= values[0];
  const stroke = up ? "var(--delta-up)" : "var(--delta-down)";
  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${points}" fill="none" stroke="${stroke}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}

/**
 * table(headers, rows) where each row is either
 *   - an array of cell strings, or
 *   - {band: "REGION NAME"} for a full-width section band, or
 *   - {cells: [...], attrs: 'data-x="y"', className: "..."}
 */
function table(headers, rows) {
  const thead = `<tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr>`;
  const body = rows.map((r) => {
    if (r && r.band !== undefined) {
      return `<tr class="region-band"><td colspan="${headers.length}">${r.band}</td></tr>`;
    }
    const cells = Array.isArray(r) ? r : r.cells;
    const attrs = (!Array.isArray(r) && r.attrs) ? " " + r.attrs : "";
    const cls = (!Array.isArray(r) && r.className) ? ` class="${r.className}"` : "";
    return `<tr${cls}${attrs}>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`;
  }).join("");
  return `<div class="table-wrap"><table><thead>${thead}</thead><tbody>${body}</tbody></table></div>`;
}


// ---------------------------------------------------------------------------
// Percentile / z-score context
// Descriptive only: where a reading sits against its own history. Never a
// composite score, never a cheap/expensive judgement.
// ---------------------------------------------------------------------------
const CTX_WINDOW_ORDER = ["10y", "5y", "full"];

function ordinal(n) {
  const v = Math.round(n);
  if (v % 100 >= 11 && v % 100 <= 13) return `${v}th`;
  return `${v}${["th", "st", "nd", "rd"][v % 10] || "th"}`;
}

/** Small inline annotation, or "" when no window resolved (hidden, not N/A). */
function ctxTag(context) {
  if (!context) return "";
  const key = CTX_WINDOW_ORDER.find((k) => context[k]);
  if (!key) return "";
  const c = context[key];
  const label = key === "full" ? "full" : key;
  const detail = CTX_WINDOW_ORDER
    .filter((k) => context[k])
    .map((k) => {
      const w = context[k];
      const z = w.z != null ? `, z ${w.z > 0 ? "+" : ""}${w.z.toFixed(2)}` : "";
      return `${k === "full" ? "full history" : k}: ${ordinal(w.pct)} pctl${z} (n=${w.n}, since ${w.since})`;
    })
    .join(" \u00b7 ");
  return ` <span class="pctl" title="${detail}">${ordinal(c.pct)} ${label}</span>`;
}

// ---------------------------------------------------------------------------
// Expandable chart
// ---------------------------------------------------------------------------
const PERIOD_DAYS = { "3M": 91, "1Y": 365, "2Y": 731, "3Y": 1096, "5Y": 1827 };

function slicePeriod(history, period) {
  if (!history || !history.length) return [];
  const last = new Date(history[history.length - 1][0]);
  let cutoff;
  if (period === "YTD") {
    cutoff = new Date(Date.UTC(last.getUTCFullYear(), 0, 1));
  } else {
    cutoff = new Date(last.getTime() - (PERIOD_DAYS[period] || 365) * 86400000);
  }
  return history.filter((p) => new Date(p[0]) >= cutoff);
}

function lineChart(history, period) {
  const pts = slicePeriod(history, period);
  if (pts.length < 2) return `<div class="chart-empty">Not enough history for ${period}.</div>`;

  const W = 760, H = 240, PAD_L = 58, PAD_R = 12, PAD_T = 14, PAD_B = 28;
  const vals = pts.map((p) => p[1]);
  let min = Math.min(...vals), max = Math.max(...vals);
  if (min === max) { min -= 1; max += 1; }
  const padY = (max - min) * 0.08;
  min -= padY; max += padY;

  const x = (i) => PAD_L + (i / (pts.length - 1)) * (W - PAD_L - PAD_R);
  const y = (v) => PAD_T + (1 - (v - min) / (max - min)) * (H - PAD_T - PAD_B);

  const ticks = 4;
  let grid = "";
  for (let i = 0; i <= ticks; i++) {
    const v = min + ((max - min) * i) / ticks;
    const yy = y(v);
    grid += `<line class="grid" x1="${PAD_L}" x2="${W - PAD_R}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}"/>`;
    grid += `<text class="axis" x="${PAD_L - 8}" y="${(yy + 3.5).toFixed(1)}" text-anchor="end">${v.toFixed(2)}</text>`;
  }

  const nLabels = Math.min(5, pts.length);
  let xlabels = "";
  for (let i = 0; i < nLabels; i++) {
    const idx = Math.round((i / (nLabels - 1)) * (pts.length - 1));
    xlabels += `<text class="axis" x="${x(idx).toFixed(1)}" y="${H - 8}" text-anchor="${i === 0 ? "start" : i === nLabels - 1 ? "end" : "middle"}">${pts[idx][0]}</text>`;
  }

  const poly = pts.map((p, i) => `${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  const stroke = up ? "var(--delta-up)" : "var(--delta-down)";
  const change = ((vals[vals.length - 1] / vals[0] - 1) * 100);

  return `
    <div class="chart-head">
      <span class="chart-range">${pts[0][0]} → ${pts[pts.length - 1][0]}</span>
      <span class="chart-change ${change >= 0 ? "up" : "down"}">${change >= 0 ? "+" : ""}${change.toFixed(2)}% over ${period}</span>
    </div>
    <svg class="line-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img">
      ${grid}${xlabels}
      <polyline points="${poly}" fill="none" stroke="${stroke}" stroke-width="1.8" stroke-linejoin="round"/>
    </svg>`;
}

// ---------------------------------------------------------------------------
// Multi-series charts.
//
// The Equity and Rates tabs each open with one large chart above their table,
// driven by chips rather than by expanding a table row. Two shapes are needed:
// a time series (x = date) and a curve (x = tenor, a category axis), so they
// are two small functions rather than one configurable one.
// ---------------------------------------------------------------------------
const SERIES_VARS = ["--series-1", "--series-2", "--series-3", "--series-4",
                     "--series-5", "--series-6", "--series-7", "--series-8"];
const seriesColor = (i) => `var(${SERIES_VARS[i % SERIES_VARS.length]})`;

const CHART_W = 900, CHART_H = 300, CH_L = 60, CH_R = 16, CH_T = 16, CH_B = 34;

function niceTicks(min, max, count) {
  if (min === max) { min -= 1; max += 1; }
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || mag * 10;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const out = [];
  for (let v = lo; v <= hi + step * 1e-9; v += step) out.push(v);
  return out;
}

function chartFrame(inner, yTicks, y, xLabels, yLabelFmt) {
  const grid = yTicks.map((v) =>
    `<line class="grid" x1="${CH_L}" x2="${CHART_W - CH_R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/>` +
    `<text class="axis" x="${CH_L - 8}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end">${yLabelFmt(v)}</text>`
  ).join("");
  return `<svg viewBox="0 0 ${CHART_W} ${CHART_H}" preserveAspectRatio="xMidYMid meet" role="img">
      ${grid}${xLabels}${inner}
    </svg>`;
}

function chartLegend(lines) {
  return `<div class="chart-legend">` + lines.map((l) =>
    `<span class="legend-item"><span class="legend-swatch" style="background:${l.color}"></span>${l.label}</span>`
  ).join("") + `</div>`;
}

/**
 * Time-series chart. `lines` is [{label, points: [[isoDate, value], ...]}].
 *
 * rebase=true indexes every line to 100 at its first point in the window,
 * which is the only way several indices in different currencies and at wildly
 * different levels can be read against each other. It is forced on whenever
 * more than one line is shown, and the y-axis label says so.
 */
function dateChart(lines, period, rebase) {
  const cut = lines.map((l) => ({ ...l, pts: slicePeriod(l.points, period) }))
                   .filter((l) => l.pts.length > 1);
  if (!cut.length) return `<div class="chart-empty">Not enough history for ${period}.</div>`;

  const shaped = cut.map((l) => {
    const base = l.pts[0][1];
    const vals = rebase && base ? l.pts.map((p) => (p[1] / base) * 100) : l.pts.map((p) => p[1]);
    return { ...l, vals };
  });

  const allVals = shaped.flatMap((l) => l.vals);
  const ticks = niceTicks(Math.min(...allVals), Math.max(...allVals), 5);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const y = (v) => CH_T + (1 - (v - lo) / (hi - lo)) * (CHART_H - CH_T - CH_B);

  // All lines share the longest x-domain so they stay on a common time axis.
  const spine = shaped.reduce((a, b) => (b.pts.length > a.pts.length ? b : a)).pts;
  const t0 = new Date(spine[0][0]).getTime();
  const t1 = new Date(spine[spine.length - 1][0]).getTime();
  const x = (iso) => CH_L + ((new Date(iso).getTime() - t0) / (t1 - t0 || 1)) * (CHART_W - CH_L - CH_R);

  const n = Math.min(6, spine.length);
  let xLabels = "";
  for (let i = 0; i < n; i++) {
    const p = spine[Math.round((i / (n - 1)) * (spine.length - 1))];
    xLabels += `<text class="axis" x="${x(p[0]).toFixed(1)}" y="${CHART_H - 10}" text-anchor="${i === 0 ? "start" : i === n - 1 ? "end" : "middle"}">${p[0]}</text>`;
  }

  const paths = shaped.map((l) =>
    `<polyline points="${l.vals.map((v, i) => `${x(l.pts[i][0]).toFixed(1)},${y(v).toFixed(1)}`).join(" ")}" fill="none" stroke="${l.color}" stroke-width="1.9" stroke-linejoin="round" stroke-linecap="round"/>`
  ).join("");

  const base100 = rebase
    ? `<line class="grid" x1="${CH_L}" x2="${CHART_W - CH_R}" y1="${y(100).toFixed(1)}" y2="${y(100).toFixed(1)}" stroke-dasharray="3 3"/>`
    : "";

  const fmt = rebase ? (v) => v.toFixed(0) : (v) => v.toFixed(Math.abs(hi) < 20 ? 2 : 0);
  return chartFrame(base100 + paths, ticks, y, xLabels, fmt) + chartLegend(shaped) +
    `<div class="chart-note">${rebase
      ? `Indexed to 100 at ${cut[0].pts[0][0]}, so lines in different currencies and at different levels can be compared. Values are relative, not price levels.`
      : `Level in local currency. Weekly closes.`}</div>`;
}

/** Yield-curve chart: x is the tenor, a category axis, not a date. */
function curveShapeChart(lines, tenors) {
  const present = tenors.filter((t) => lines.some((l) => l.values[t] != null));
  if (present.length < 2 || !lines.length) {
    return `<div class="chart-empty">Not enough of the curve is sourced to plot it.</div>`;
  }
  const allVals = lines.flatMap((l) => present.map((t) => l.values[t]).filter((v) => v != null));
  const ticks = niceTicks(Math.min(...allVals), Math.max(...allVals), 5);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const y = (v) => CH_T + (1 - (v - lo) / (hi - lo)) * (CHART_H - CH_T - CH_B);
  const x = (i) => CH_L + (i / (present.length - 1)) * (CHART_W - CH_L - CH_R);

  const xLabels = present.map((t, i) =>
    `<text class="axis" x="${x(i).toFixed(1)}" y="${CHART_H - 10}" text-anchor="middle">${t}</text>`).join("");

  const paths = lines.map((l) => {
    // A curve with a hole (Switzerland has no 5y or 30y) is drawn as the
    // segments that exist, never bridged across the gap.
    const pts = present.map((t, i) => (l.values[t] != null ? `${x(i).toFixed(1)},${y(l.values[t]).toFixed(1)}` : null));
    const segs = [];
    let run = [];
    pts.forEach((p) => { if (p) { run.push(p); } else { if (run.length > 1) segs.push(run); run = []; } });
    if (run.length > 1) segs.push(run);
    const dots = pts.filter(Boolean).map((p) => {
      const [px, py] = p.split(",");
      return `<circle cx="${px}" cy="${py}" r="3" fill="${l.color}"/>`;
    }).join("");
    return segs.map((sg) => `<polyline points="${sg.join(" ")}" fill="none" stroke="${l.color}" stroke-width="1.9" stroke-linejoin="round"/>`).join("") + dots;
  }).join("");

  return chartFrame(paths, ticks, y, xLabels, (v) => `${v.toFixed(2)}%`) + chartLegend(lines);
}

// ---------------------------------------------------------------------------
// Hover tooltips. One floating node, positioned at the cursor, so a long
// definition never widens a table column.
// ---------------------------------------------------------------------------
function setupTooltips() {
  let pop = null;
  const hide = () => { if (pop) { pop.remove(); pop = null; } };
  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest("[data-tip]");
    if (!t) return;
    hide();
    pop = document.createElement("div");
    pop.className = "tip-pop";
    pop.innerHTML = t.getAttribute("data-tip");
    document.body.appendChild(pop);
    const r = t.getBoundingClientRect();
    const w = pop.offsetWidth, h = pop.offsetHeight;
    let left = r.left, top = r.bottom + 8;
    if (left + w > window.innerWidth - 12) left = window.innerWidth - w - 12;
    if (top + h > window.innerHeight - 12) top = r.top - h - 8;
    pop.style.left = `${Math.max(12, left)}px`;
    pop.style.top = `${Math.max(12, top)}px`;
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest("[data-tip]")) hide();
  });
  window.addEventListener("scroll", hide, true);
}

function chartRow(key, colspan, activePeriod) {
  const periods = (DATA.chart_periods || ["3M", "YTD", "1Y", "2Y", "3Y", "5Y"]);
  const buttons = periods.map((p) =>
    `<button class="period-btn${p === activePeriod ? " active" : ""}" data-chart-key="${key}" data-period="${p}">${p}</button>`
  ).join("");
  const series = SERIES[key];
  return `<tr class="chart-row" data-chart-for="${key}"><td colspan="${colspan}">
      <div class="chart-wrap">
        <div class="chart-title">${series ? series.name : ""}</div>
        <div class="period-bar">${buttons}</div>
        <div class="chart-body" data-chart-body="${key}">${lineChart(series ? series.history : [], activePeriod)}</div>
      </div>
    </td></tr>`;
}

function setupChartToggles() {
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-chart-toggle]");
    if (trigger) {
      const key = trigger.getAttribute("data-chart-toggle");
      const row = document.querySelector(`tr[data-chart-for="${CSS.escape(key)}"]`);
      if (!row) return;
      const isOpen = row.classList.contains("open");
      document.querySelectorAll("tr.chart-row.open").forEach((r) => r.classList.remove("open"));
      document.querySelectorAll("[data-chart-toggle].expanded").forEach((t) => t.classList.remove("expanded"));
      if (!isOpen) {
        row.classList.add("open");
        trigger.classList.add("expanded");
        openChart = key;
      } else {
        openChart = null;
      }
      return;
    }
    const cw = e.target.closest("[data-corr-window]");
    if (cw) { corrWindow = cw.getAttribute("data-corr-window"); renderCrossAsset(); return; }
    const ct = e.target.closest("[data-corr-table]");
    if (ct) { corrTableView = !corrTableView; renderCrossAsset(); return; }
    const btn = e.target.closest(".period-btn");
    if (btn) {
      const key = btn.getAttribute("data-chart-key");
      const period = btn.getAttribute("data-period");
      const body = document.querySelector(`[data-chart-body="${CSS.escape(key)}"]`);
      if (body && SERIES[key]) body.innerHTML = lineChart(SERIES[key].history, period);
      btn.parentElement.querySelectorAll(".period-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
    }
  });
}

/** Builds the two rows (data row + hidden chart row) for a chartable series. */
function chartableRows(key, name, history, cells, colspan) {
  SERIES[key] = { name, history: history || [] };
  const hasHistory = history && history.length > 1;
  const trend = hasHistory
    ? `<span class="trend-cell" data-chart-toggle="${key}" role="button" tabindex="0" title="Click to open chart">${sparkline(history)}<span class="expand-hint">▾</span></span>`
    : dash();
  return [
    { cells: cells.concat([trend]) },
    hasHistory ? { cells: [], band: undefined, raw: true, key } : null,
  ].filter(Boolean).map((r) => r.raw ? chartRow(key, colspan, "1Y") : r);
}

// ---------------------------------------------------------------------------
// Panels
// ---------------------------------------------------------------------------

/** Every tracked index as one flat list, in tab order, EM last. */
function equityList() {
  const out = [];
  REGION_ORDER.concat(["EM"]).forEach((region) => {
    ((DATA.equity_indices || {})[region] || []).forEach((idx) =>
      out.push({ ...idx, region }));
  });
  return out;
}

/** The hover card on an index name: what it is, how weighted, what basis. */
function indexTip(idx) {
  const rows = [
    idx.weighting ? `<span class="tip-row">${idx.weighting}</span>` : "",
    idx.basis ? `<span class="tip-row">${idx.basis}</span>` : "",
    `<span class="tip-row">Quoted in ${idx.currency}.</span>`,
  ].join("");
  return `<span class="tip-title">${idx.name}</span>${rows}`.replace(/"/g, "&quot;");
}

let eqSel = { ids: ["sp500"], period: "1Y" };

function renderEquities() {
  const all = equityList();
  if (!all.length) { document.getElementById("panel-equities").innerHTML = `<h2>Equity Indices</h2>` + note("No index data."); return; }

  let chosen = eqSel.ids.filter((id) => all.some((i) => i.id === id));
  if (!chosen.length) chosen = [all[0].id];
  // More than one line means different currencies and levels on one axis, so
  // indexing is not optional -- it is the only way the comparison means
  // anything. A single line keeps its real level.
  const rebase = chosen.length > 1;
  const lines = chosen.map((id, i) => {
    const idx = all.find((x) => x.id === id);
    return { label: idx.name, points: idx.history || [], color: seriesColor(i) };
  });

  const periods = DATA.chart_periods || ["3M", "YTD", "1Y", "2Y", "3Y", "5Y"];
  const indexChips = all.map((idx) => {
    const on = chosen.includes(idx.id);
    const c = on ? seriesColor(chosen.indexOf(idx.id)) : "";
    return `<button class="chip${on ? " active" : ""}" data-eq-id="${idx.id}"${on ? ` data-swatch style="--chip-color:${c}"` : ""}>${idx.name}</button>`;
  }).join("");
  const periodChips = periods.map((p) =>
    `<button class="chip${p === eqSel.period ? " active" : ""}" data-eq-period="${p}">${p}</button>`).join("");

  const headers = ["Index", "Level", "1W", "1M", "YTD", "1Y", "DD from ATH", "Vol (13w)"];
  const rows = [];
  REGION_ORDER.concat(["EM"]).forEach((region) => {
    const indices = (DATA.equity_indices || {})[region] || [];
    if (!indices.length) return;
    rows.push({ band: region === "EM" ? "Emerging Markets" : regionName(region) });
    indices.forEach((idx) => {
      rows.push([
        `<span class="has-tip" data-tip="${indexTip(idx)}">${idx.name}</span> <span class="ccy">${idx.currency}</span>`,
        fmtNum(idx.level, (idx.level || 0) > 100 ? 1 : 4),
        fmtPct(idx.chg_1w_pct), fmtPct(idx.chg_mtd_pct),
        fmtPct(idx.chg_ytd_pct), fmtPct(idx.chg_1y_pct),
        fmtPct(idx.drawdown_from_ath_pct) + ctxTag(idx.drawdown_context),
        (idx.realized_vol_13w_pct != null ? `${idx.realized_vol_13w_pct.toFixed(1)}%` : dash()) + ctxTag(idx.vol_context),
      ]);
    });
  });

  document.getElementById("panel-equities").innerHTML =
    `<h2>Equity Indices</h2>` +
    `<div class="chart-panel">
       <div class="chart-controls">
         <div class="control-group"><span class="control-label">Index</span>${indexChips}</div>
         <div class="control-group"><span class="control-label">Period</span>${periodChips}</div>
       </div>
       <div class="chart-figure">${dateChart(lines, eqSel.period, rebase)}</div>
     </div>` +
    note("Weekly closes (Friday, or the last session before it). Levels in local currency; volatility is annualised from 13 weeks of weekly returns, and drawdown is measured on weekly closes, so an intra-week trough that recovered by Friday does not appear. Hover an index name for how it is weighted and whether its level includes dividends.") +
    tableWithRaw(headers, rows);

  document.querySelectorAll("[data-eq-id]").forEach((b) =>
    b.addEventListener("click", () => {
      const id = b.getAttribute("data-eq-id");
      const at = eqSel.ids.indexOf(id);
      if (at >= 0) { if (eqSel.ids.length > 1) eqSel.ids.splice(at, 1); }
      else eqSel.ids.push(id);
      renderEquities();
    }));
  document.querySelectorAll("[data-eq-period]").forEach((b) =>
    b.addEventListener("click", () => { eqSel.period = b.getAttribute("data-eq-period"); renderEquities(); }));
}

/** table() variant that lets pre-rendered <tr> strings through. */
function tableWithRaw(headers, rows) {
  const thead = `<tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr>`;
  const body = rows.map((r) => {
    if (typeof r === "string") return r;
    if (r && r.band !== undefined) return `<tr class="region-band"><td colspan="${headers.length}">${r.band}</td></tr>`;
    const cells = Array.isArray(r) ? r : r.cells;
    return `<tr>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`;
  }).join("");
  return `<div class="table-wrap"><table><thead>${thead}</thead><tbody>${body}</tbody></table></div>`;
}

function curveRows(source, showBasis) {
  return REGION_ORDER.map((region) => {
    const c = (source || {})[region];
    if (!c) return null;
    const t = c.tenors || {};
    const flag = c.lagged ? ` <span class="flag">${c.cadence}, lagged</span>` : "";
    const cc = c.context || {};
    const cells = [
      regionName(region) + flag,
      pctPlain(t["2Y"]) + ctxTag(cc["2Y"]), pctPlain(t["5Y"]) + ctxTag(cc["5Y"]),
      pctPlain(t["10Y"]) + ctxTag(cc["10Y"]), pctPlain(t["30Y"]) + ctxTag(cc["30Y"]),
      c["2s10s_bp"] != null ? fmtBp(c["2s10s_bp"]) : dash(),
      c.as_of || dash(),
    ];
    if (showBasis) cells.splice(1, 0, c.basis || dash());
    return cells;
  }).filter(Boolean);
}

// --- Rates tab -------------------------------------------------------------
const CURVE_TENORS = ["2Y", "5Y", "10Y", "30Y"];
// Inflation tenors, kept as their own column set so the table lines up
// column-for-column with the curve tables above it.
const INFL_TENORS = [["1y", "1Y"], ["2y", "2Y"], ["5y", "5Y"], ["10y", "10Y"], ["5y5y_fwd", "5y5y fwd"]];
let curveSel = { regions: ["US"], date: null };

/** Tenor values for one region as they stood on (or before) `dateISO`. */
function curveValuesOn(region, dateISO) {
  const c = (DATA.yield_curves || {})[region] || {};
  if (!dateISO) return c.tenors || {};
  const hist = c.tenor_history || {};
  const out = {};
  CURVE_TENORS.forEach((t) => {
    const pts = hist[t] || [];
    let v = null;
    for (const p of pts) { if (p[0] <= dateISO) v = p[1]; else break; }
    out[t] = v;
  });
  return out;
}

function curveDateBounds() {
  let min = null, max = null;
  Object.values(DATA.yield_curves || {}).forEach((c) => {
    Object.values(c.tenor_history || {}).forEach((pts) => {
      if (!pts.length) return;
      if (min === null || pts[0][0] < min) min = pts[0][0];
      if (max === null || pts[pts.length - 1][0] > max) max = pts[pts.length - 1][0];
    });
  });
  return { min, max };
}

function curvePanel() {
  const regions = curveSel.regions.length ? curveSel.regions : ["US"];
  const lines = regions.map((r, i) => ({
    label: regionName(r) + (((DATA.yield_curves || {})[r] || {}).unofficial ? " (unofficial source)" : ""),
    values: curveValuesOn(r, curveSel.date),
    color: seriesColor(i),
  }));
  const chips = REGION_ORDER.map((r) => {
    const has = (DATA.yield_curves || {})[r];
    if (!has) return "";
    const on = regions.includes(r);
    const c = on ? seriesColor(regions.indexOf(r)) : "";
    return `<button class="chip${on ? " active" : ""}" data-curve-region="${r}"${on ? ` data-swatch style="--chip-color:${c}"` : ""}>${regionName(r)}</button>`;
  }).join("");
  const b = curveDateBounds();
  const shown = curveSel.date || b.max || "";

  return `<div class="chart-panel">
      <div class="chart-controls">
        <div class="control-group"><span class="control-label">Region</span>${chips}</div>
        <div class="control-group">
          <span class="control-label">As of</span>
          <input type="date" id="curve-date" value="${shown}" min="${b.min || ""}" max="${b.max || ""}"/>
          <button class="chip${curveSel.date ? "" : " active"}" id="curve-now">Current</button>
        </div>
      </div>
      <div class="chart-figure">${curveShapeChart(lines, CURVE_TENORS)}</div>
      <div class="chart-note">${curveSel.date
        ? `Curve as it stood on the last weekly close on or before ${curveSel.date}. History runs three years.`
        : `Latest stored curve. Pick a date to see the curve as it stood then.`}</div>
    </div>`;
}

function wireCurveControls() {
  document.querySelectorAll("[data-curve-region]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const r = btn.getAttribute("data-curve-region");
      const at = curveSel.regions.indexOf(r);
      if (at >= 0) { if (curveSel.regions.length > 1) curveSel.regions.splice(at, 1); }
      else curveSel.regions.push(r);
      renderYields();
    }));
  const d = document.getElementById("curve-date");
  if (d) d.addEventListener("change", (e) => { curveSel.date = e.target.value || null; renderYields(); });
  const now = document.getElementById("curve-now");
  if (now) now.addEventListener("click", () => { curveSel.date = null; renderYields(); });
}

/**
 * Inflation-expectation rows on the same tenor columns as the curve tables.
 * Commentary is not squeezed into a cell -- it gets its own full-width row
 * underneath, left-aligned, so it never wraps a column out of shape.
 */
function inflationRows(colCount) {
  const rows = [];
  const push = (label, badge, basis, tenors, ctx, commentary) => {
    const cells = [label, `${badge} <span class="ccy">${basis || ""}</span>`];
    INFL_TENORS.forEach(([key]) => {
      const v = tenors[key];
      cells.push(v != null ? `<strong>${v.toFixed(2)}%</strong>${ctxTag((ctx || {})[key])}` : dash());
    });
    rows.push(cells);
    if (commentary) rows.push(`<tr><td class="commentary" colspan="${colCount}">${commentary}</td></tr>`);
  };
  REGION_ORDER.forEach((region) => {
    const e = (DATA.inflation_expectations || {})[region];
    if (!e) return;
    if (e.kind === "unavailable") {
      rows.push([regionName(region), `<span class="stub">not sourced</span>`].concat(INFL_TENORS.map(() => dash())));
      rows.push(`<tr><td class="commentary" colspan="${colCount}">${e.note || "No free market-implied source."}</td></tr>`);
      return;
    }
    push(regionName(region), `<span class="badge badge-${e.kind}">${e.kind}-implied</span>`,
         e.basis, e.tenors || {}, e.context || {}, e.note);
    // Only the 1y model point is kept: there is no 1-year TIPS breakeven, so a
    // model is the only way to show it. The model's 5y and 10y are dropped as
    // redundant -- the market breakevens for those sit on the row above.
    if (e.model && (e.model.tenors || {})["1y"] != null) {
      push(`${regionName(region)} <span class="ccy">(1y only)</span>`,
           `<span class="badge badge-model">model-implied</span>`, e.model.basis,
           { "1y": e.model.tenors["1y"] }, {},
           "Cleveland Fed model (TIPS, inflation swaps and surveys blended). Shown only at 1 year, because no 1-year TIPS breakeven is published; at 5 and 10 years the market breakeven on the row above is the direct measure.");
    }
  });
  return rows;
}

function renderYields() {
  const nominalHeaders = ["Region", "2Y", "5Y", "10Y", "30Y", "2s10s", "As of"];
  const realHeaders = ["Region", "Basis", "2Y", "5Y", "10Y", "30Y", "2s10s", "As of"];
  const inflHeaders = ["Region", "Basis"].concat(INFL_TENORS.map(([, label]) => label));

  const sp = DATA.eurozone_spreads || { rows: [] };
  const spreadRows = (sp.rows || []).map((r) => [
    r.country, pctPlain(r.yield_pct, 3),
    (r.spread_bp != null ? fmtBp(r.spread_bp) : dash()) + ctxTag(r.context), r.as_of || dash(),
  ]);

  document.getElementById("panel-yields").innerHTML =
    `<h2>Government Yield Curves</h2>` +
    curvePanel() +
    note("Nominal sovereign curves. The Eurozone row is the ECB's all-bonds euro area curve — a blend across euro area sovereigns — while Germany is the single-issuer Bund curve. They are deliberately different measures. Switzerland is the one unofficial source on this dashboard and carries 2y and 10y only; the SNB retired its own curve in July 2025.") +
    table(nominalHeaders, curveRows(DATA.yield_curves, false)) +

    `<h2 class="mt">Euro-Area Sovereign Spreads vs. ${sp.benchmark || "Bund"}</h2>` +
    note(`Both legs come from the same ECB long-term rate series, so the spread is not distorted by mixing sources. Benchmark: ${sp.benchmark || "—"} at ${sp.benchmark_yield_pct != null ? sp.benchmark_yield_pct.toFixed(3) + "%" : "—"} (${sp.cadence || "monthly"}).`) +
    table(["Country", "10y yield", "Spread", "As of"], spreadRows) +

    `<h2 class="mt">Real Yields</h2>` +
    note("Inflation-linked yields. Note the basis differs: US TIPS reference CPI, UK index-linked gilts reference RPI.") +
    table(realHeaders, curveRows(DATA.real_yield_curves, true)) +

    `<h2 class="mt">Market-Implied Inflation</h2>` +
    note("Breakeven / implied inflation, on the same tenor columns as the curves above. These are not comparable across regions: UK figures are RPI-based and historically run roughly 0.8–1.0pp above the equivalent CPI rate.") +
    tableWithRaw(inflHeaders, inflationRows(inflHeaders.length)) +

    `<h2 class="mt">Credit Spreads</h2>` +
    note("What the market charges for corporate credit risk, in basis points over government bonds. These are option-adjusted spreads — adjusted for issuers' rights to call bonds early. FRED serves them on a rolling three-year window under an ICE licensing limit, so percentile context can only be measured against that window.") +
    table(["Region", "Index", "Grade", "Spread", "As of"],
      (DATA.credit_spreads || []).map((c) => [
        c.region === "EM" ? "Emerging Markets" : regionName(c.region),
        c.name, `<span class="ccy">${c.grade}</span>`,
        c.spread_bp != null ? `${c.spread_bp} bp${ctxTag(c.context)}` : dash(),
        c.as_of || dash(),
      ])) +

    `<h2 class="mt">Cost of Capital</h2>` +
    note("The nominal building blocks of a discount rate, laid out leg by leg. The risk-free leg is the nominal 10y government yield, not a real yield: the equity risk premium beside it is itself measured against a nominal government yield, so pairing it with a real rate would remove inflation twice.") +
    table(["Region", "Risk-free (nominal 10y)", "Credit spread", "Equity risk premium", "Total", "Coverage"],
      REGION_ORDER.map((region) => {
        const s2 = (DATA.cost_of_capital || {})[region];
        if (!s2) return null;
        const L = s2.legs || {};
        const cov = s2.complete
          ? '<span class="badge badge-market">all 3 legs</span>'
          : (s2.total_pct != null
              ? `<span class="flag">partial — no ${s2.missing_labels.join(", ").toLowerCase()}</span>`
              : `<span class="stub">no legs sourced</span>`);
        return [
          regionName(region), pctPlain(L.risk_free), pctPlain(L.credit_spread),
          pctPlain(L.erp),
          s2.total_pct != null
            ? `<strong>${s2.total_pct.toFixed(2)}%</strong>${s2.complete ? "" : "*"}`
            : dash(),
          cov,
        ];
      }).filter(Boolean)) +
    `<p class="section-note">* A partial total sums only the legs that are sourced, so it is not comparable with a complete stack.</p>`;

  wireCurveControls();
}

function renderMacro() {
  const rateRows = REGION_ORDER.map((region) => {
    const cb = (DATA.macro.policy_rates || {})[region] || {};
    return [regionName(region), pctPlain(cb.rate_pct) + ctxTag(cb.context), cb.as_of || dash()];
  });
  const infRows = REGION_ORDER.map((region) => {
    const i = (DATA.macro.inflation || {})[region] || {};
    return [regionName(region), pctPlain(i.yoy_pct, 1) + ctxTag(i.context), pctPlain(i.qoq_ann_pct, 1), i.as_of || dash()];
  });
  const gdpRows = REGION_ORDER.map((region) => {
    const g = (DATA.macro.gdp || {})[region] || {};
    return [
      regionName(region), pctPlain(g.yoy_pct, 1),
      g.qoq_ann_pct != null ? pctPlain(g.qoq_ann_pct, 1) : `<span class="stub">n/a (annual series)</span>`,
      g.as_of || dash(),
    ];
  });

  const quarters = regimeQuarters();
  let regimeBlock = "";
  if (quarters.length) {
    const idx = regimeIndex == null ? quarters.length - 1 : regimeIndex;
    const selected = quarters[idx];
    regimeBlock =
      `<h2>Growth / Inflation Regime Map</h2>` +
      `<p class="regime-explain">
         <strong>How to read this.</strong> Each region sits at its latest growth rate
         (left to right) and inflation rate (bottom to top), so the chart is a
         picture of where economies actually are, not a forecast. The two
         dividing lines are the long-run averages, which split the space into
         four quadrants: <em>top-right</em> is growth with inflation
         (overheating), <em>top-left</em> is weak growth with high inflation
         (stagflationary), <em>bottom-left</em> is weak growth with cooling
         prices (disinflationary slowdown), and <em>bottom-right</em> is growth
         without inflation (the benign quadrant). What matters more than the
         quadrant is the <em>direction of travel</em> — step the quarter slider
         back and watch which way a region has been moving. Positions shift
         with data revisions, and the quadrant names describe the data, not
         what to do about it.
       </p>` +
      note((DATA.regime && DATA.regime.axis_definition) || "") +
      `<div class="regime-controls">
         <label for="regime-slider">Quarter: <strong id="regime-label">${selected}</strong></label>
         <input id="regime-slider" type="range" min="0" max="${quarters.length - 1}" value="${idx}" step="1"/>
       </div>` +
      regimeChart(selected);
  }

  document.getElementById("panel-macro").innerHTML =
    regimeBlock +
    `<h2 class="mt">GDP Growth</h2>` +
    note(DATA.macro.gdp_definition || "") +
    table(["Region", "Real GDP YoY", "QoQ annualised", "As of"], gdpRows) +

    `<h2 class="mt">Inflation</h2>` +
    note("Headline consumer prices. Year-on-year, plus the latest quarter annualised — the second is noisier but turns sooner.") +
    table(["Region", "CPI YoY", "QoQ annualised", "As of"], infRows) +

    `<h2 class="mt">Central Bank Policy Rates</h2>` +
    note("Source: BIS Data Portal (CBPOL), all regions on one endpoint; Germany mirrors the ECB. A policy rate legitimately sits unchanged for months, so an older date is not a stale figure.") +
    table(["Region", "Policy Rate", "As of"], rateRows);

  const slider = document.getElementById("regime-slider");
  if (slider) {
    slider.addEventListener("input", (e) => {
      regimeIndex = parseInt(e.target.value, 10);
      renderMacro();
    });
  }
}

function renderCurrencies() {
  const headers = ["Pair", "Level", "1W", "YTD", "1Y trend"];
  const rows = [];
  (DATA.currencies || []).forEach((fx) => {
    const cells = [fx.name, fmtNum(fx.level, 4) + ctxTag(fx.context), fmtPct(fx.chg_1w_pct), fmtPct(fx.chg_ytd_pct)];
    chartableRows(`fx:${fx.id}`, fx.name, fx.history, cells, headers.length).forEach((r) => rows.push(r));
  });

  const hedges = DATA.fx_hedging || [];
  let hedgeHtml = "";
  if (hedges.length) {
    const caveats = (hedges[0].caveats || []).map((c) => `<li>${c}</li>`).join("");
    hedgeHtml =
      `<h2 class="mt">Cost of Hedging back to CHF</h2>` +
      `<div class="approx-warning">
         <strong>Approximation, not a market quote.</strong> This is
         ${hedges[0].method || ""}. Cross-currency basis swaps are interbank OTC
         instruments with no free feed, so this is the covered-interest-parity
         proxy — the dominant driver of hedging cost, but not the traded price.
         <ul>${caveats}</ul>
       </div>` +
      table(["Exposure", "Foreign policy rate", "CHF policy rate", "Approx. annual cost"],
        hedges.map((h) => [
          h.name,
          pctPlain(h.foreign_rate_pct),
          pctPlain(h.chf_rate_pct),
          h.cost_pct != null
            ? `<span class="${h.direction === "cost" ? "down" : "up"}"><strong>${h.cost_pct > 0 ? "−" : "+"}${Math.abs(h.cost_pct).toFixed(2)}%</strong></span> <span class="ccy">per year, ${h.direction === "cost" ? "paid to hedge" : "earned by hedging"}</span>`
            : dash(),
        ]));
  }

  document.getElementById("panel-currencies").innerHTML =
    `<h2>Currencies</h2>` + note("Click a trend to open a chart.") +
    tableWithRaw(headers, rows) + hedgeHtml;
}

function renderCommodities() {
  const headers = ["Commodity", "Contract", "Unit", "Level", "1W", "YTD", "1Y trend"];
  const rows = [];
  (DATA.commodities || []).forEach((cm) => {
    const cells = [
      cm.name,
      `<span class="ccy">${cm.exchange || ""} ${cm.contract || ""}</span>`,
      `<span class="ccy">${cm.unit || ""}</span>`,
      fmtNum(cm.level, 2) + ctxTag(cm.context), fmtPct(cm.chg_1w_pct), fmtPct(cm.chg_ytd_pct),
    ];
    chartableRows(`commodity:${cm.id}`, `${cm.name} (${cm.unit || ""})`, cm.history, cells, headers.length).forEach((r) => rows.push(r));
  });
  document.getElementById("panel-commodities").innerHTML =
    `<h2>Commodities</h2>` +
    note("Every row states its exchange, contract and unit — 'natural gas' means different things in the US and Europe, and copper is quoted per pound on COMEX but per tonne on the LME.") +
    tableWithRaw(headers, rows);
}

function renderValuation() {
  const scoreRows = REGION_ORDER.map((region) => {
    const v = (DATA.valuation || {})[region] || {};
    const e = (DATA.equity_risk_premia || {})[region] || {};
    const hasAny = v.cape != null || e.erp_pct != null;
    return [
      regionName(region),
      v.cape != null ? `<strong>${v.cape.toFixed(1)}</strong>${ctxTag(v.cape_context)}` : dash(),
      e.erp_pct != null ? `<strong>${e.erp_pct.toFixed(2)}%</strong>${ctxTag(e.context)}` : dash(),
      // The only region that reaches this branch is the Eurozone, and it is
      // descoped rather than pending: Damodaran publishes member states with
      // no bloc aggregate. Saying "awaiting sourcing" would promise work that
      // is deliberately not going to happen.
      hasAny ? "" : `<span class="stub">no bloc-level source — see DATA-CATALOG.csv</span>`,
    ];
  });
  const erpCovered = REGION_ORDER.filter((r) => ((DATA.equity_risk_premia || {})[r] || {}).erp_pct != null).length;

  const mult = (v, key) => (v.multiples || {})[key];
  const multCell = (v, key) => {
    const m = mult(v, key);
    return m && m.value != null ? `${m.value.toFixed(2)}${ctxTag(m.context)}` : dash();
  };
  const detailRows = REGION_ORDER.map((region) => {
    const v = (DATA.valuation || {})[region] || {};
    const e = (DATA.equity_risk_premia || {})[region] || {};
    return [
      regionName(region), v.name || "",
      multCell(v, "pe"), multCell(v, "pb"), multCell(v, "ps"), multCell(v, "ev_ebitda"),
      v.multiples_as_of || v.cape_as_of || e.as_of || dash(),
    ];
  });

  document.getElementById("panel-valuation").innerHTML =
    `<h2>Valuation Scorecard</h2>` +
    note(`CAPE and equity risk premium across regions, with each reading's percentile against its own history. CAPE is US-only by design — it needs a long cyclically-adjusted earnings history that exists for the S&amp;P 500 and not for the other indices. <strong>${erpCovered} of ${REGION_ORDER.length} regions have an ERP.</strong> The Eurozone is blank on both because Damodaran publishes member states with no bloc aggregate, and Germany's figure is not a stand-in for it.`) +
    table(["Region", "CAPE", "ERP", ""], scoreRows) +

    `<p class="section-note"><strong>Known gaps on this tab.</strong> CAPE is US-only and will stay that way — it needs a long cyclically-adjusted earnings history that exists for the S&amp;P 500 and not elsewhere. The country multiples below start in 2020, because Damodaran's earlier files publish means rather than medians. Still unsourced: dividend yields, forward (rather than trailing) multiples, and any Eurozone-level figure at all. Filling these is the main outstanding job on this tab — see <code>data/DATA-CATALOG.csv</code>.</p>` +

    `<h2 class="mt">Country Multiples</h2>` +
    note("Damodaran's country aggregates: the <strong>median</strong> across listed companies in each country, on <strong>trailing</strong> earnings, book, sales and EBITDA. These are not cyclically adjusted, so they are not comparable to the CAPE above — and the median basis only starts in 2020, because the earlier vintages of the source publish means instead.") +
    table(["Region", "Index", "P/E", "P/B", "P/S", "EV/EBITDA", "As of"], detailRows);
}


// ---------------------------------------------------------------------------
// Growth / inflation regime quadrant map
// Axes are the CHANGE in the year-on-year rate over one quarter — direction of
// travel, not level. Quadrant names describe the data, nothing more.
// ---------------------------------------------------------------------------
let regimeIndex = null;   // which quarter is selected; null = latest

function regimeQuarters() {
  const regions = (DATA.regime && DATA.regime.regions) || {};
  const dates = new Set();
  Object.values(regions).forEach((pts) => (pts || []).forEach((p) => dates.add(p.date)));
  return Array.from(dates).sort();
}

function regimeChart(quarterDate) {
  const regions = (DATA.regime && DATA.regime.regions) || {};
  const pts = [];
  REGION_ORDER.forEach((r) => {
    const series = regions[r] || [];
    if (!series.length) return;
    // Nearest point at or before the selected quarter, so regions reporting on
    // a lag still plot rather than vanishing.
    const eligible = series.filter((p) => p.date <= quarterDate);
    const p = eligible.length ? eligible[eligible.length - 1] : null;
    if (p) pts.push({ region: r, ...p, lagged: p.date !== quarterDate,
                      annual: p.delta_basis === "year" });
  });
  if (!pts.length) return `<div class="chart-empty">No regime data.</div>`;

  const W = 720, H = 460, PAD = 54;
  const xs = pts.map((p) => p.growth_delta), ys = pts.map((p) => p.inflation_delta);
  const bound = (arr) => {
    const m = Math.max(0.5, ...arr.map((v) => Math.abs(v)));
    return m * 1.25;
  };
  const bx = bound(xs), by = bound(ys);
  const X = (v) => PAD + ((v + bx) / (2 * bx)) * (W - 2 * PAD);
  const Y = (v) => H - PAD - ((v + by) / (2 * by)) * (H - 2 * PAD);

  const quadLabels = [
    { x: W - PAD - 6, y: PAD + 14, t: "growth ↑ · inflation ↑", anchor: "end" },
    { x: PAD + 6, y: PAD + 14, t: "growth ↓ · inflation ↑", anchor: "start" },
    { x: W - PAD - 6, y: H - PAD - 8, t: "growth ↑ · inflation ↓", anchor: "end" },
    { x: PAD + 6, y: H - PAD - 8, t: "growth ↓ · inflation ↓", anchor: "start" },
  ].map((q) => `<text class="quad-label" x="${q.x}" y="${q.y}" text-anchor="${q.anchor}">${q.t}</text>`).join("");

  const dots = pts.map((p) => {
    const cx = X(p.growth_delta), cy = Y(p.inflation_delta);
    const title = `${regionName(p.region)} — ${p.date}\nGrowth ${p.growth_yoy.toFixed(2)}% YoY (${p.growth_delta >= 0 ? "+" : ""}${p.growth_delta.toFixed(2)}pp this quarter)\nInflation ${p.inflation_yoy.toFixed(2)}% YoY (${p.inflation_delta >= 0 ? "+" : ""}${p.inflation_delta.toFixed(2)}pp this quarter)${p.lagged ? "\n(latest available — reports on a lag)" : ""}`;
    return `<g class="regime-pt${p.lagged ? " lagged" : ""}"><title>${title}</title>
      <circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="6"/>
      <text x="${(cx + 9).toFixed(1)}" y="${(cy + 4).toFixed(1)}">${p.region}${p.lagged ? "*" : ""}${p.annual ? "†" : ""}</text></g>`;
  }).join("");

  const anyLagged = pts.some((p) => p.lagged);
  const anyAnnual = pts.some((p) => p.annual);
  return `
    <svg class="regime-chart" viewBox="0 0 ${W} ${H}" role="img">
      <line class="axis-line" x1="${PAD}" x2="${W - PAD}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}"/>
      <line class="axis-line" x1="${X(0).toFixed(1)}" x2="${X(0).toFixed(1)}" y1="${PAD}" y2="${H - PAD}"/>
      ${quadLabels}
      <text class="axis" x="${W / 2}" y="${H - 14}" text-anchor="middle">← growth slowing   ·   Δ real GDP YoY (pp per quarter)   ·   growth accelerating →</text>
      <text class="axis" transform="translate(16 ${H / 2}) rotate(-90)" text-anchor="middle">← inflation falling   ·   Δ CPI YoY (pp)   ·   rising →</text>
      ${dots}
    </svg>
    ${anyLagged ? `<p class="section-note">* latest available reading; that region publishes on a lag.</p>` : ""}
    ${anyAnnual ? `<p class="section-note">† only an annual GDP series exists for this region, so its horizontal move spans a year rather than a quarter and is not comparable with the others on that axis.</p>` : ""}`;
}


// ---------------------------------------------------------------------------
// Cross-asset correlation heatmap
// Correlation is polarity data, so the scale is diverging: two poles with a
// NEUTRAL GRAY midpoint (never a rainbow, never a hue at zero), per the
// dataviz skill. Blue = negative, red = positive, gray = uncorrelated.
// ---------------------------------------------------------------------------
let corrWindow = null;
let corrTableView = false;

function corrPalette() {
  const cs = getComputedStyle(document.documentElement);
  const read = (n, fb) => (cs.getPropertyValue(n) || "").trim() || fb;
  return {
    neg: read("--div-neg", "#2a78d6"),
    mid: read("--div-mid", "#f0efec"),
    pos: read("--div-pos", "#e34948"),
  };
}

function hexToRgb(h) {
  const m = h.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(m.slice(i, i + 2), 16));
}

/** Diverging fill: interpolate pole -> neutral midpoint by |r|. */
function corrColor(v, pal) {
  if (v === null || v === undefined) return "transparent";
  const t = Math.min(1, Math.abs(v));
  const pole = hexToRgb(v >= 0 ? pal.pos : pal.neg);
  const mid = hexToRgb(pal.mid);
  const c = mid.map((m, i) => Math.round(m + (pole[i] - m) * t));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

/** Label ink picked by cell luminance so the number stays readable on any step. */
function inkFor(v, pal) {
  if (v === null || v === undefined) return "var(--text-muted)";
  const rgb = corrColor(v, pal).match(/\d+/g).map(Number);
  const lum = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255;
  return lum > 0.55 ? "#0b0b0b" : "#ffffff";
}

function correlationBlock() {
  const corr = DATA.correlation || {};
  const windows = Object.keys(corr.windows || {}).sort((a, b) => +a - +b);
  if (!windows.length) return "";
  const w = corrWindow && corr.windows[corrWindow] ? corrWindow : windows[0];
  const m = corr.windows[w];
  if (!m || !m.labels || !m.labels.length) {
    return `<h2 class="mt">Cross-Asset Correlation</h2>` + note("Not enough overlapping history.");
  }
  const pal = corrPalette();

  const buttons = windows.map((k) =>
    `<button class="period-btn${k === w ? " active" : ""}" data-corr-window="${k}">${k}d</button>`
  ).join("");

  let grid = "";
  if (!corrTableView) {
    const head = `<tr><th class="corner"></th>${m.labels.map((l) => `<th class="col-head"><span>${l}</span></th>`).join("")}</tr>`;
    const body = m.labels.map((rowLabel, i) => {
      const cells = m.matrix[i].map((v, j) => {
        if (v === null) return `<td class="corr-cell empty" title="insufficient overlap">—</td>`;
        const title = `${rowLabel} vs ${m.labels[j]}: ${v >= 0 ? "+" : ""}${v.toFixed(3)} over ${m.window_weeks} weeks (${m.start} to ${m.as_of})`;
        return `<td class="corr-cell" style="background:${corrColor(v, pal)};color:${inkFor(v, pal)}" title="${title}">${v >= 0 ? "+" : ""}${v.toFixed(2)}</td>`;
      }).join("");
      return `<tr><th class="row-head">${rowLabel}</th>${cells}</tr>`;
    }).join("");
    grid = `<div class="table-wrap"><table class="corr-grid"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
  } else {
    const rows = [];
    for (let i = 0; i < m.labels.length; i++) {
      for (let j = i + 1; j < m.labels.length; j++) {
        const v = m.matrix[i][j];
        rows.push([m.labels[i], m.labels[j], v === null ? dash() : `${v >= 0 ? "+" : ""}${v.toFixed(3)}`]);
      }
    }
    grid = table(["Asset A", "Asset B", "Correlation"], rows);
  }

  const legend = `
    <div class="corr-legend">
      <span>−1 inverse</span>
      <span class="ramp" style="background:linear-gradient(to right, ${pal.neg}, ${pal.mid}, ${pal.pos})"></span>
      <span>+1 together</span>
    </div>`;

  return `<h2 class="mt">Cross-Asset Correlation</h2>` +
    note(`${corr.note || ""} Window: ${m.window_weeks} weeks, ${m.start} to ${m.as_of} (n=${m.n_obs}).`) +
    `<div class="period-bar">${buttons}
       <button class="period-btn${corrTableView ? " active" : ""}" data-corr-table="1">${corrTableView ? "Heatmap view" : "Table view"}</button>
     </div>` + legend + grid;
}

function renderCrossAsset() {
  document.getElementById("panel-crossasset").innerHTML =
    `<h2>Cross-Asset Correlations</h2>` + correlationBlock();
}

function populateRegionSelector() {
  const sel = document.getElementById("region-selector");
  sel.innerHTML = REGION_ORDER.map((r) => `<option value="${r}">${regionName(r)}</option>`).join("");
  sel.addEventListener("change", (e) => renderSnapshot(e.target.value));
}

// ---------------------------------------------------------------------------
// Regional snapshot — a one-page cheat sheet, not a wall of one-value boxes.
//
// A banner carries the four numbers you would quote from memory, with a
// thumbnail of the region's own yield curve beside them; everything else sits
// in dense label/value/change lines grouped by theme.
// ---------------------------------------------------------------------------
function snapLine(label, value, delta, sub) {
  const d = delta == null ? "" :
    `<span class="d ${delta >= 0 ? "up" : "down"}">${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%</span>`;
  return `<div class="snap-line"><span class="k">${label}</span><span class="v">${value}</span>${d || "<span class='d'></span>"}` +
         (sub ? `<span class="sub">${sub}</span>` : "") + `</div>`;
}

function snapBlock(title, lines) {
  const body = lines.filter(Boolean).join("");
  if (!body) return "";
  return `<div class="snap-block"><h3>${title}</h3><div class="snap-lines">${body}</div></div>`;
}

/** A small inline sketch of the region's nominal curve for the banner. */
function miniCurve(region) {
  const t = ((DATA.yield_curves || {})[region] || {}).tenors || {};
  const pts = CURVE_TENORS.map((k, i) => [i, t[k]]).filter((p) => p[1] != null);
  if (pts.length < 2) return "";
  const vals = pts.map((p) => p[1]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (lo === hi) { lo -= 0.5; hi += 0.5; }
  const W = 132, H = 42;
  const x = (i) => 4 + (i / (CURVE_TENORS.length - 1)) * (W - 8);
  const y = (v) => 6 + (1 - (v - lo) / (hi - lo)) * (H - 12);
  const poly = pts.map((p) => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  const dots = pts.map((p) => `<circle cx="${x(p[0]).toFixed(1)}" cy="${y(p[1]).toFixed(1)}" r="1.9" fill="var(--accent)"/>`).join("");
  return `<div class="snap-curve"><svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Nominal yield curve">
      <polyline points="${poly}" fill="none" stroke="var(--accent)" stroke-width="1.6" stroke-linejoin="round"/>${dots}
    </svg><div class="chart-note" style="text-align:center;margin:0">2Y → 30Y</div></div>`;
}

function renderSnapshot(region) {
  const indices = (DATA.equity_indices || {})[region] || [];
  const curve = (DATA.yield_curves || {})[region] || {};
  const real = (DATA.real_yield_curves || {})[region];
  const exp = (DATA.inflation_expectations || {})[region] || {};
  const cb = (DATA.macro.policy_rates || {})[region] || {};
  const inf = (DATA.macro.inflation || {})[region] || {};
  const gdp = (DATA.macro.gdp || {})[region] || {};
  const val = (DATA.valuation || {})[region] || {};
  const erp = (DATA.equity_risk_premia || {})[region] || {};
  const cc = (DATA.cost_of_capital || {})[region] || {};
  const t = curve.tenors || {};
  const lead = indices[0];

  const hero = (k, v) => `<div class="hero-stat"><span class="hk">${k}</span><span class="hv">${v}</span></div>`;
  const banner = `<div class="snap-hero">
      <span class="hero-region">${regionName(region)}</span>
      ${hero("Policy rate", pctPlain(cb.rate_pct))}
      ${hero("10y", pctPlain(t["10Y"]))}
      ${hero("CPI YoY", pctPlain(inf.yoy_pct, 1))}
      ${hero("Real GDP YoY", pctPlain(gdp.yoy_pct, 1))}
      ${hero(lead ? lead.name + " YTD" : "Equities YTD", lead ? fmtPct(lead.chg_ytd_pct) : dash())}
      ${miniCurve(region)}
    </div>`;

  const equityLines = indices.map((idx) =>
    snapLine(`<span class="has-tip" data-tip="${indexTip(idx)}">${idx.name}</span>`,
             fmtNum(idx.level, (idx.level || 0) > 100 ? 1 : 4), idx.chg_ytd_pct,
             `1W ${fmtPct(idx.chg_1w_pct)} · 1Y ${fmtPct(idx.chg_1y_pct)} · vol ${idx.realized_vol_13w_pct != null ? idx.realized_vol_13w_pct.toFixed(1) + "%" : "—"}`));

  const rateLines = CURVE_TENORS.map((k) =>
    t[k] != null ? snapLine(k, pctPlain(t[k]), null) : "").concat([
    curve["2s10s_bp"] != null ? snapLine("2s10s", fmtBp(curve["2s10s_bp"]), null) : "",
    real && (real.tenors || {})["10Y"] != null
      ? snapLine("10y real", pctPlain(real.tenors["10Y"]), null, real.basis || "") : "",
  ]);

  const expTenors = exp.tenors || {};
  const expKey = Object.keys(expTenors).find((k) => expTenors[k] != null);
  const macroLines = [
    snapLine("Policy rate", pctPlain(cb.rate_pct), null, cb.name || ""),
    snapLine("CPI YoY", pctPlain(inf.yoy_pct, 1), null,
             inf.qoq_ann_pct != null ? `Latest quarter annualised ${inf.qoq_ann_pct.toFixed(1)}%` : ""),
    snapLine("Real GDP YoY", pctPlain(gdp.yoy_pct, 1), null,
             gdp.qoq_ann_pct != null ? `Latest quarter annualised ${gdp.qoq_ann_pct.toFixed(1)}%` : "Annual series"),
    expKey
      ? snapLine("Implied inflation", pctPlain(expTenors[expKey]), null,
                 `${expKey.replace(/_/g, " ")} · ${exp.basis || ""}`)
      : snapLine("Implied inflation", `<span class="stub">not sourced</span>`, null, ""),
  ];

  const mult = val.multiples || {};
  const valLines = [
    val.cape != null ? snapLine("CAPE", val.cape.toFixed(1), null, val.name || "") : "",
    mult.pe ? snapLine("P/E (trailing)", mult.pe.value.toFixed(1), null, "Median across listed companies") : "",
    mult.pb ? snapLine("P/B", mult.pb.value.toFixed(2), null) : "",
    mult.ev_ebitda ? snapLine("EV/EBITDA", mult.ev_ebitda.value.toFixed(1), null) : "",
    erp.erp_pct != null ? snapLine("Equity risk premium", `${erp.erp_pct.toFixed(2)}%`, null, erp.method || "") : "",
    cc.total_pct != null
      ? snapLine("Cost of capital", `${cc.total_pct.toFixed(2)}%${cc.complete ? "" : "*"}`, null,
                 cc.complete ? "All three legs sourced" : `Partial — no ${(cc.missing_labels || []).join(", ").toLowerCase()}`)
      : "",
  ];

  const fxForRegion = { UK: "gbpusd", EZ: "eurusd", DE: "eurusd", CH: "eurchf", JP: "usdjpy", CN: "usdcny", NO: "eurnok", US: "dxy" }[region];
  const fx = (DATA.currencies || []).find((f) => f.id === fxForRegion);
  const fxLines = [fx ? snapLine(fx.name, fmtNum(fx.level, 4), fx.chg_ytd_pct,
                                 `1W ${fmtPct(fx.chg_1w_pct)}`) : ""];

  document.getElementById("snapshot-body").innerHTML = banner + `<div class="snap-grid">` +
    snapBlock("Equities", equityLines) +
    snapBlock("Rates", rateLines) +
    snapBlock("Macro", macroLines) +
    snapBlock("Valuation &amp; cost of capital", valLines) +
    snapBlock("Currency", fxLines) +
    `</div>` +
    `<p class="section-note">Commodities are global and live on their own tab. Percentages beside a level are year-to-date.</p>`;
}

function setupTabs() {
  const buttons = document.querySelectorAll("nav.tabs button");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      document.querySelectorAll("section.panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(btn.dataset.target).classList.add("active");
    });
  });
}

main().catch((err) => {
  console.error(err);
  document.querySelector("main").innerHTML =
    `<p style="color:var(--delta-down)">Failed to load data/latest.json — ${err.message}. Run the pipeline first (see README).</p>`;
});
