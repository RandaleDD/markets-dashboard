let DATA = null;
let REGION_ORDER = ["US", "UK", "EZ", "DE", "CH", "CN", "JP", "NO"];
// The Macroeconomics tab's regions: the eight plus India and Brazil, which are
// sourced for macro alone and so appear nowhere else (see universe.MACRO_REGIONS).
let MACRO_ORDER = REGION_ORDER;
const SERIES = {};          // "kind:id" -> {name, history}
let openChart = null;       // key of the currently expanded chart row

async function main() {
  const res = await fetch("data/latest.json", { cache: "no-store" });
  DATA = await res.json();
  window.__data = DATA;
  if (Array.isArray(DATA.regions) && DATA.regions.length) REGION_ORDER = DATA.regions;
  const macroRegions = (DATA.macro || {}).regions;
  MACRO_ORDER = Array.isArray(macroRegions) && macroRegions.length ? macroRegions : REGION_ORDER;

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
function table(headers, rows, groups) {
  // Optional `groups`: [[label, span, className?], ...] -- a band of column-
  // group headings above the real ones. Spans must add up to headers.length.
  const band = groups
    ? `<tr class="group-head">${groups.map(([label, span, cls]) =>
        `<th colspan="${span}"${cls ? ` class="${cls}"` : ""}>${label}</th>`).join("")}</tr>`
    : "";
  const thead = band + `<tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr>`;
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

/** The percentile context as one line of plain text, for a tooltip. */
function ctxText(context) {
  if (!context) return "";
  return CTX_WINDOW_ORDER.filter((k) => context[k]).map((k) => {
    const w = context[k];
    return `${ordinal(w.pct)} percentile vs ${k === "full" ? "full history" : `last ${k}`} (since ${w.since})`;
  }).join("; ");
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
// 1W and 1M are not offered as chart periods; they exist so the currency
// conversion can rebuild the table's 1W and 1M columns over the same windows
// the Python side uses. They must be here: slicePeriod falls back to 365 days
// for a key it does not know, which would quietly turn a one-week return into
// a one-year one.
const PERIOD_DAYS = { "1W": 7, "1M": 31, "3M": 91, "1Y": 365, "2Y": 731, "3Y": 1096, "5Y": 1827,
                      "10Y": 3653, "20Y": 7305 };

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

// Colour follows the series, never its position in the selection. Indexing by
// position repainted every surviving line whenever one was switched off, so
// the same series changed colour under the reader. Each chart keeps a sticky
// key -> slot map: a series keeps its slot while it stays selected, a new one
// takes the lowest free slot (so the most distinct colours are used first),
// and a slot is released only when its series is switched off.
const colorSlots = {};
function stableColors(chart, keys) {
  const m = colorSlots[chart] || (colorSlots[chart] = new Map());
  [...m.keys()].forEach((k) => { if (!keys.includes(k)) m.delete(k); });
  keys.forEach((k) => {
    if (m.has(k)) return;
    const used = new Set(m.values());
    let slot = 0;
    while (used.has(slot) && slot < SERIES_VARS.length) slot++;
    m.set(k, slot % SERIES_VARS.length);
  });
  return (k) => seriesColor(m.get(k));
}

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

// The class matters: `.axis` and `.grid` are only ever styled as descendants
// of a chart class, so an unclassed <svg> here left the tick labels at the SVG
// default (black, ~16px) and the gridlines at stroke:none -- invisible. Both
// the Equity and Rates top charts render through this one function.
function chartFrame(inner, yTicks, y, xLabels, yLabelFmt) {
  const grid = yTicks.map((v) =>
    `<line class="grid" x1="${CH_L}" x2="${CHART_W - CH_R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/>` +
    `<text class="axis" x="${CH_L - 8}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end">${yLabelFmt(v)}</text>`
  ).join("");
  return `<svg class="frame-chart" viewBox="0 0 ${CHART_W} ${CHART_H}" preserveAspectRatio="xMidYMid meet" role="img">
      ${grid}${xLabels}${inner}
    </svg>`;
}

// Axis dates as "Sep '25". Six full ISO dates crowd a 900-unit axis into an
// unreadable row; the year is what carries meaning at this density.
const AXIS_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function axisDate(iso) {
  const [y, m] = String(iso).split("-");
  if (!m) return iso;
  return `${AXIS_MONTHS[parseInt(m, 10) - 1]} '${y.slice(2)}`;
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
 *
 * A line may set `step: true` to be drawn step-after rather than straight.
 * That is not decoration: a policy rate holds its value until the day it
 * changes, so sloping between two meetings would draw rate moves that never
 * happened. `opts.noteHtml` overrides the caption for charts that are not
 * price levels. `opts.presliced` skips the per-line window cut, for a caller
 * that has already put every line on a common window (see priceLevelBlock).
 *
 * Three more options, for the GDP chart and the snapshot panel:
 *   `opts.dashFrom` (ISO date) draws every line DASHED from its last point
 *     before that date onward, behind a shaded "projection" zone -- forecast
 *     years must never read as data that has happened;
 *   `opts.xFmt` / `opts.yFmt` replace the axis label formatters;
 *   `opts.zeroLine` draws a baseline at 0 when the range spans it.
 */
function dateChart(lines, period, rebase, opts) {
  const presliced = opts && opts.presliced;
  const cut = lines.map((l) => ({ ...l, pts: presliced ? l.points : slicePeriod(l.points, period) }))
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

  const xFmt = (opts && opts.xFmt) || axisDate;
  const n = Math.min(6, spine.length);
  let xLabels = "";
  for (let i = 0; i < n; i++) {
    const p = spine[Math.round((i / (n - 1)) * (spine.length - 1))];
    xLabels += `<text class="axis" x="${x(p[0]).toFixed(1)}" y="${CHART_H - 10}" text-anchor="${i === 0 ? "start" : i === n - 1 ? "end" : "middle"}">${xFmt(p[0])}</text>`;
  }

  const dashFrom = opts && opts.dashFrom;
  const polyline = (pts, color, dashed) =>
    `<polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.9" stroke-linejoin="round" stroke-linecap="round"${dashed ? ' stroke-dasharray="5 4"' : ""}/>`;
  const paths = shaped.map((l) => {
    const pts = [];
    // Index of the first projected point; the dashed run starts one point
    // earlier so the two runs join instead of leaving a gap.
    let split = dashFrom ? l.pts.findIndex((p) => p[0] >= dashFrom) : -1;
    l.vals.forEach((v, i) => {
      const px = x(l.pts[i][0]).toFixed(1), py = y(v).toFixed(1);
      // Step-after: carry the previous level across to this date, then drop.
      if (l.step && i > 0) pts.push(`${px},${y(l.vals[i - 1]).toFixed(1)}`);
      pts.push(`${px},${py}`);
    });
    if (split < 0 || l.step) return polyline(pts, l.color, false);
    const join = Math.max(0, split - 1);
    return (join > 0 ? polyline(pts.slice(0, join + 1), l.color, false) : "") +
           polyline(pts.slice(join), l.color, true);
  }).join("");

  let proj = "";
  if (dashFrom && new Date(dashFrom).getTime() <= t1) {
    const px = Math.max(CH_L, x(dashFrom));
    proj = `<rect class="proj-zone" x="${px.toFixed(1)}" y="${CH_T}" width="${(CHART_W - CH_R - px).toFixed(1)}" height="${CHART_H - CH_T - CH_B}"/>` +
           `<line class="proj-line" x1="${px.toFixed(1)}" x2="${px.toFixed(1)}" y1="${CH_T}" y2="${CHART_H - CH_B}"/>` +
           `<text class="proj-label" x="${(px + 6).toFixed(1)}" y="${CH_T + 12}">IMF PROJECTION</text>`;
  }
  const zero = opts && opts.zeroLine && lo < 0 && hi > 0
    ? `<line class="zero-line" x1="${CH_L}" x2="${CHART_W - CH_R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}"/>`
    : "";

  const base100 = rebase
    ? `<line class="grid" x1="${CH_L}" x2="${CHART_W - CH_R}" y1="${y(100).toFixed(1)}" y2="${y(100).toFixed(1)}" stroke-dasharray="3 3"/>`
    : "";

  const fmt = (opts && opts.yFmt) ||
    (rebase ? (v) => v.toFixed(0) : (v) => v.toFixed(Math.abs(hi) < 20 ? 2 : 0));
  const caption = (opts && opts.noteHtml) || (rebase
    ? `Indexed to 100 at ${cut[0].pts[0][0]}, so lines in different currencies and at different levels can be compared. Values are relative, not price levels.`
    : `Level in local currency. Weekly closes.`);
  return chartFrame(proj + base100 + zero + paths, ticks, y, xLabels, fmt) + chartLegend(shaped) +
    `<div class="chart-note">${caption}</div>`;
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

let eqSel = { ids: ["sp500"], period: "1Y", currency: "Local" };

// ---------------------------------------------------------------------------
// Currency conversion for the equity tab.
//
// Every index is published in its own currency, which makes the levels
// incomparable and, more importantly, makes the RETURNS incomparable: a 10%
// gain in yen is not a 10% gain to a franc investor if the yen fell 12%. This
// converts a whole history series, so the chart and every derived figure in
// the table move together.
//
// The FX series are Yahoo's `XXXYYY=X`, quoted as YYY per 1 XXX. `usdPer` is
// therefore built as "how many USD is one unit of this currency", and any
// cross is that ratio -- USD is the pivot because that is what is tracked.
// NOK has no direct USD cross in the payload, so it is derived from EUR/NOK
// and EUR/USD; HKD was added to CURRENCIES purely so the Hang Seng could be
// converted at all.
// ---------------------------------------------------------------------------
const CONVERT_TO = ["Local", "USD", "GBP", "EUR", "CHF"];

/** A Map of isoDate -> value for one payload series id. */
function fxMap(id) {
  const fx = (DATA.currencies || []).find((f) => f.id === id);
  const m = new Map();
  (fx && fx.history ? fx.history : []).forEach(([d, v]) => m.set(d, v));
  return m;
}

/**
 * USD per one unit of `ccy`, as a Map keyed by date.
 * Returns null for a currency with no route to USD, so the caller can say so
 * rather than silently showing unconverted numbers.
 */
function usdPer(ccy) {
  if (ccy === "USD") return "identity";
  const eurusd = fxMap("eurusd");
  if (ccy === "EUR") return eurusd;
  if (ccy === "GBP") return fxMap("gbpusd");
  // Quoted the other way round (units per USD), so invert.
  const inverted = { CHF: "usdchf", JPY: "usdjpy", CNY: "usdcny", HKD: "usdhkd" }[ccy];
  if (inverted) {
    const m = fxMap(inverted), out = new Map();
    m.forEach((v, d) => { if (v) out.set(d, 1 / v); });
    return out;
  }
  if (ccy === "NOK") {
    // EUR/NOK and EUR/USD give USD/NOK without a direct cross being tracked.
    const eurnok = fxMap("eurnok"), out = new Map();
    eurnok.forEach((v, d) => {
      const eu = eurusd.get(d);
      if (v && eu) out.set(d, eu / v);
    });
    return out;
  }
  return null;
}

/**
 * Convert a [[iso, value], ...] history from `from` into `to`.
 *
 * Dates with no FX quote are DROPPED rather than carried forward: an index
 * close paired with a stale rate is a wrong number, and both series are weekly
 * Friday closes so the overlap is near-total in practice.
 */
function convertHistory(history, from, to) {
  if (!history || !history.length || to === "Local" || from === to) return history;
  const a = usdPer(from), b = usdPer(to);
  if (!a || !b) return null;
  const rate = (m, d) => (m === "identity" ? 1 : m.get(d));
  const out = [];
  history.forEach(([d, v]) => {
    const ra = rate(a, d), rb = rate(b, d);
    if (ra == null || rb == null || !rb) return;
    out.push([d, (v * ra) / rb]);
  });
  return out.length > 1 ? out : null;
}

/** pct change between the first and last points of a window, or null. */
function pctOver(history, period) {
  const pts = slicePeriod(history || [], period);
  if (pts.length < 2 || !pts[0][1]) return null;
  return (pts[pts.length - 1][1] / pts[0][1] - 1) * 100;
}

/**
 * Recompute the table figures for one index in `ccy`.
 *
 * Returns the index unchanged for "Local". Otherwise every displayed number is
 * rebuilt from the converted history, because a return in another currency is
 * genuinely a different number -- not the local return with a note attached.
 * Percentile context is dropped: it was measured on the local-currency series
 * and would be a different distribution here, so showing it would be wrong.
 */
function inCurrency(idx, ccy) {
  if (ccy === "Local" || idx.currency === ccy) return idx;
  const hist = convertHistory(idx.history, idx.currency, ccy);
  if (!hist) return { ...idx, unconvertible: true };
  const last = hist[hist.length - 1][1];
  let peak = -Infinity, dd = 0;
  hist.forEach(([, v]) => { peak = Math.max(peak, v); });
  if (peak > 0) dd = (last / peak - 1) * 100;
  // Annualised from weekly log-ish returns, matching transform/returns.py.
  const rets = [];
  for (let i = 1; i < hist.length; i++) {
    if (hist[i - 1][1]) rets.push(hist[i][1] / hist[i - 1][1] - 1);
  }
  const tail = rets.slice(-13);
  let vol = null;
  if (tail.length >= 8) {
    const mean = tail.reduce((x, y) => x + y, 0) / tail.length;
    const varr = tail.reduce((x, y) => x + (y - mean) ** 2, 0) / (tail.length - 1);
    vol = Math.sqrt(varr) * Math.sqrt(52) * 100;
  }
  return {
    ...idx, history: hist, level: last, currency: ccy, converted: true,
    chg_1w_pct: pctOver(hist, "1W"), chg_mtd_pct: pctOver(hist, "1M"),
    chg_ytd_pct: pctOver(hist, "YTD"), chg_1y_pct: pctOver(hist, "1Y"),
    drawdown_from_ath_pct: dd, realized_vol_13w_pct: vol,
    drawdown_context: null, vol_context: null,
  };
}

function renderEquities() {
  const all = equityList();
  if (!all.length) { document.getElementById("panel-equities").innerHTML = `<h2>Equity Indices</h2>` + note("No index data."); return; }

  let chosen = eqSel.ids.filter((id) => all.some((i) => i.id === id));
  if (!chosen.length) chosen = [all[0].id];
  const ccy = CONVERT_TO.includes(eqSel.currency) ? eqSel.currency : "Local";
  // More than one line means different currencies and levels on one axis, so
  // indexing is not optional -- it is the only way the comparison means
  // anything. A single line keeps its real level. Converting to a common
  // currency does NOT remove the need: levels still differ by orders of
  // magnitude between, say, the Nikkei and the SMI.
  const rebase = chosen.length > 1;
  const colorOf = stableColors("equities", chosen);
  const lines = chosen.map((id) => {
    const idx = inCurrency(all.find((x) => x.id === id), ccy);
    return { label: idx.name, points: idx.history || [], color: colorOf(id) };
  });

  const periods = DATA.chart_periods || ["3M", "YTD", "1Y", "2Y", "3Y", "5Y"];
  const indexChips = all.map((idx) => {
    const on = chosen.includes(idx.id);
    const c = on ? colorOf(idx.id) : "";
    return `<button class="chip${on ? " active" : ""}" data-eq-id="${idx.id}"${on ? ` data-swatch style="--chip-color:${c}"` : ""}>${idx.name}</button>`;
  }).join("");
  const periodChips = periods.map((p) =>
    `<button class="chip${p === eqSel.period ? " active" : ""}" data-eq-period="${p}">${p}</button>`).join("");
  const ccyChips = CONVERT_TO.map((c) =>
    `<button class="chip${c === ccy ? " active" : ""}" data-eq-ccy="${c}">${c}</button>`).join("");

  // The currency must be impossible to forget: it changes every number on the
  // tab, and a reader returning to it later has no other way to tell that the
  // figures are not in local currency. Hence a banner, not just an active chip.
  const ccyBanner = ccy === "Local" ? "" :
    `<div class="ccy-banner">All figures converted to <strong>${ccy}</strong>
       — levels, returns, drawdown and volatility. Currency moves are inside
       every number here.</div>`;

  const headers = ["Index", "Level", "1W", "1M", "YTD", "1Y", "DD from ATH",
                   "Vol (13w)", "P/E", "P/B", "EV/EBITDA"];
  const rows = [];
  REGION_ORDER.concat(["EM"]).forEach((region) => {
    const indices = (DATA.equity_indices || {})[region] || [];
    if (!indices.length) return;
    rows.push({ band: region === "EM" ? "Emerging Markets" : regionName(region) });
    // Valuation is per COUNTRY, not per index -- see the note under the table.
    const val = (DATA.valuation || {})[region] || {};
    const mult = (key) => {
      const m = (val.multiples || {})[key];
      return m && m.value != null ? m.value.toFixed(2) : dash();
    };
    indices.forEach((raw) => {
      const idx = inCurrency(raw, ccy);
      const ccyTag = idx.unconvertible
        ? `<span class="stub">${raw.currency}, no ${ccy} cross</span>`
        : `<span class="ccy">${idx.currency}</span>`;
      // className, not a wrapper span: the indent belongs to the row's
      // relationship with the band above it, not to the index name.
      rows.push({ className: "idx-row", cells: [
        `<span class="has-tip" data-tip="${indexTip(raw)}">${idx.name}</span> ${ccyTag}`,
        fmtNum(idx.level, (idx.level || 0) > 100 ? 1 : 4),
        fmtPct(idx.chg_1w_pct), fmtPct(idx.chg_mtd_pct),
        fmtPct(idx.chg_ytd_pct), fmtPct(idx.chg_1y_pct),
        fmtPct(idx.drawdown_from_ath_pct) + ctxTag(idx.drawdown_context),
        (idx.realized_vol_13w_pct != null ? `${idx.realized_vol_13w_pct.toFixed(1)}%` : dash()) + ctxTag(idx.vol_context),
        mult("pe"), mult("pb"), mult("ev_ebitda"),
      ] });
    });
  });

  document.getElementById("panel-equities").innerHTML =
    `<h2>Equity Indices</h2>` +
    `<div class="chart-panel">
       <div class="chart-controls">
         <div class="control-group"><span class="control-label">Index</span>${indexChips}</div>
         <div class="control-group"><span class="control-label">Period</span>${periodChips}</div>
         <div class="control-group control-group-ccy"><span class="control-label">Currency</span>${ccyChips}</div>
       </div>
       ${ccyBanner}
       <div class="chart-figure">${dateChart(lines, eqSel.period, rebase,
          ccy === "Local" ? null : { noteHtml: `Converted to ${ccy}. Weekly closes.` })}</div>
     </div>` +
    // A second, shorter reminder directly above the table: the chart banner
    // can be scrolled past, and the table is where the numbers get read off.
    (ccy === "Local" ? "" :
      `<div class="ccy-banner ccy-banner-slim">Table figures below are in <strong>${ccy}</strong>, not local currency.</div>`) +
    note(`Weekly closes (Friday, or the last session before it). ${ccy === "Local" ? "Levels in local currency" : `Levels converted to ${ccy}`}; volatility is annualised from 13 weeks of weekly returns, and drawdown is measured on weekly closes, so an intra-week trough that recovered by Friday does not appear. Hover an index name for how it is weighted and whether its level includes dividends — the DAX and MDAX are total-return indices and are not comparable on level with the price-return ones beside them.`) +
    tableWithRaw(headers, rows) +
    `<p class="section-note">P/E, P/B and EV/EBITDA are <strong>country
      aggregates, not index multiples</strong> — Damodaran's median across all
      listed companies in that country, which is why every index in a country
      shows the same figure and why they cannot be read as the valuation of
      that specific index. Europe is the exception and is a cap-weighted
      aggregate rather than a median, so it is not comparable with the country
      rows either. Annual, and not cyclically adjusted. Percentile context is
      dropped when a currency other than Local is selected: it was measured on
      the local-currency series and would be a different distribution here.</p>`;

  document.querySelectorAll("[data-eq-id]").forEach((b) =>
    b.addEventListener("click", () => {
      const id = b.getAttribute("data-eq-id");
      const at = eqSel.ids.indexOf(id);
      if (at >= 0) { if (eqSel.ids.length > 1) eqSel.ids.splice(at, 1); }
      else eqSel.ids.push(id);
      renderEquities();
    }));
  document.querySelectorAll("[data-eq-ccy]").forEach((b) =>
    b.addEventListener("click", () => { eqSel.currency = b.getAttribute("data-eq-ccy"); renderEquities(); }));
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
    const cls = (!Array.isArray(r) && r.className) ? ` class="${r.className}"` : "";
    return `<tr${cls}>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`;
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

// What kind of quantity each row is. A survey mean and a market breakeven are
// different measurements with different biases, so the badge says which rather
// than letting them read as one series.
const KIND_LABELS = { market: "market-implied", model: "model-implied", survey: "survey-based" };
function kindLabel(kind) {
  return KIND_LABELS[kind] || `${kind}-implied`;
}
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
  const colorOf = stableColors("curves", regions);
  const lines = regions.map((r) => ({
    label: regionName(r) + (((DATA.yield_curves || {})[r] || {}).unofficial ? " (unofficial source)" : ""),
    values: curveValuesOn(r, curveSel.date),
    color: colorOf(r),
  }));
  const chips = REGION_ORDER.map((r) => {
    const has = (DATA.yield_curves || {})[r];
    if (!has) return "";
    const on = regions.includes(r);
    const c = on ? colorOf(r) : "";
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

/** "2026-08-01" -> "August 2026", for a figure that measures a whole month. */
function monthLabel(iso) {
  if (!iso) return dash();
  const [y, m] = String(iso).split("-");
  const full = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"];
  const idx = parseInt(m, 10) - 1;
  return full[idx] ? `${full[idx]} ${y}` : iso;
}

/**
 * The euro area's sovereign risk premium in aggregate, and current — unlike
 * the per-country table above it, which can only ever be monthly.
 */
function aggregateRiskPremium() {
  const a = ((DATA.eurozone_spreads || {}).aggregate_risk_premium) || {};
  if (a.spread_bp == null) return "";
  return `<h2 class="mt">${a.name || "Euro area sovereign risk premium"}</h2>` +
    note(a.basis || "") +
    table(["Measure", "Spread", "As of"],
          [["All euro area issuers less AAA issuers, 5y",
            fmtBp(a.spread_bp) + ctxTag(a.context), a.as_of || dash()]]);
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
    // Regions with no source are simply absent from the payload now. They used
    // to render an empty row plus a paragraph explaining the blank, which was
    // five rows of nothing on a table of eight -- and a permanently empty row
    // is one you learn to scroll past. The reasons are kept in
    // data/DATA-CATALOG.csv and fetch/universe.py, where they belong.
    if (!e || e.kind === "unavailable") return;
    push(regionName(region), `<span class="badge badge-${e.kind}">${kindLabel(e.kind)}</span>`,
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
  // "Month" states what the figure measures; "As of" is the date it is filed
  // under. Without the first, a month-average dated to the 1st reads as a
  // stale daily quote sitting beside genuinely daily curves.
  const spreadRows = (sp.rows || []).map((r) => [
    r.country, pctPlain(r.yield_pct, 3),
    (r.spread_bp != null ? fmtBp(r.spread_bp) : dash()) + ctxTag(r.context),
    monthLabel(r.as_of), r.as_of || dash(),
  ]);

  document.getElementById("panel-yields").innerHTML =
    `<h2>Government Yield Curves</h2>` +
    curvePanel() +
    note("Nominal sovereign curves. The Eurozone row is the ECB's euro area curve across <em>all</em> government issuers at <em>all</em> ratings — Bunds, OATs, BTPs and Bonos together, fitted with a Svensson model — while Germany is the single-issuer Bund curve. They are deliberately different measures: the ECB's AAA-only curve tracks the Bund so closely it would simply duplicate the Germany row. Switzerland is the SNB's own curve, which was never retired — it moved cubes in 2025.") +
    table(nominalHeaders, curveRows(DATA.yield_curves, false)) +

    `<h2 class="mt">Euro-Area Sovereign Spreads vs. ${sp.benchmark || "Bund"}</h2>` +
    note(`Both legs are the same ECB long-term rate series, so no cross-publisher gap enters the spread. Benchmark: ${sp.benchmark || "—"} at ${sp.benchmark_yield_pct != null ? sp.benchmark_yield_pct.toFixed(3) + "%" : "—"}. <strong>This table is monthly and will always read behind the daily curves above</strong> — it is the Maastricht convergence-criterion yield, published as a month average, and no free per-country euro sovereign yield exists at any higher frequency. Taking France, Italy and Spain from three national publishers instead would put a methodology gap inside the spread. The aggregate measure below is the same quantity, current.`) +
    table(["Country", "10y yield", "Spread", "Month", "As of"], spreadRows) +
    aggregateRiskPremium() +

    `<h2 class="mt">Real Yields</h2>` +
    note("Inflation-linked yields. Note the basis differs: US TIPS reference CPI, UK index-linked gilts reference RPI.") +
    table(realHeaders, curveRows(DATA.real_yield_curves, true)) +

    `<h2 class="mt">Market-Implied Inflation</h2>` +
    note("Breakeven / implied inflation, on the same tenor columns as the curves above. These are not comparable across regions: UK figures are RPI-based and historically run roughly 0.8–1.0pp above the equivalent CPI rate, and the euro area figure is a survey rather than a market breakeven. Only regions with a source are listed — Germany, Switzerland, China, Japan and Norway have none, structurally in the Swiss and Norwegian cases, whose governments issue no inflation-linked debt at all.") +
    tableWithRaw(inflHeaders, inflationRows(inflHeaders.length)) +

    `<h2 class="mt">Credit Spreads</h2>` +
    note("What the market charges for corporate credit risk, in basis points over government bonds. Every row here is an option-adjusted spread — adjusted for issuers' rights to call bonds early. FRED serves them on a rolling three-year window under an ICE licensing limit, so percentile context can only be measured against that window. OAS is not published free for any currency but the dollar, which is why the euro row is high yield and why the non-OAS column in Cost of Capital exists.") +
    table(["Region", "Index", "Grade", "Spread", "As of"],
      (DATA.credit_spreads || []).map((c) => [
        c.region === "EM" ? "Emerging Markets" : regionName(c.region),
        c.name, `<span class="ccy">${c.grade}</span>`,
        c.spread_bp != null ? `${c.spread_bp} bp${ctxTag(c.context)}` : dash(),
        c.as_of || dash(),
      ])) +

    `<h2 class="mt">Cost of Capital</h2>` +
    note(DATA.cost_of_capital_note || "") +
    table(["Region", "Risk-free (nominal 10y)", "IG credit spread",
           "Equity risk premium", "Cost of equity", "Cost of debt"],
      REGION_ORDER.map((region) => {
        const s2 = (DATA.cost_of_capital || {})[region];
        // A region that can build neither rate is absent from the payload
        // rather than shown as a row of dashes.
        if (!s2) return null;
        const L = s2.legs || {};
        const supp = (s2.supplementary || {}).credit_spread_to_govt;
        // Which spread actually fed the cost of debt. Where a region has no
        // OAS, the non-OAS spread is used and the cell says so -- the two are
        // different measures and the table must not let them read alike.
        const usedNonOas = L.credit_spread == null && supp != null;
        const spreadCell = L.credit_spread != null
          ? pctPlain(L.credit_spread)
          : (supp != null
              ? `${pctPlain(supp)} <span class="ccy">non-OAS</span>`
              : dash());
        const rate = (v, formula) => v != null
          ? `<span class="has-tip" data-tip="${formula}"><strong>${v.toFixed(2)}%</strong></span>`
          : dash();
        return [
          regionName(region),
          pctPlain(L.risk_free),
          spreadCell,
          pctPlain(L.erp),
          rate(s2.cost_of_equity, (s2.formulae || {}).cost_of_equity || ""),
          rate(s2.cost_of_debt, (s2.formulae || {}).cost_of_debt || "") +
            (usedNonOas ? `<span class="ccy"> est.</span>` : ""),
        ];
      }).filter(Boolean)) +
    `<p class="section-note">A blank cost of equity or cost of debt means one of
      its two legs is not sourced for that region, not that the rate is zero —
      a half-built discount rate is worse than a blank, because it looks like a
      number you could use. Option-adjusted spreads are published free for the
      dollar only, so the euro and sterling IG spreads are constructed here
      (an IG bond ETF's yield to worst less the government curve at the same
      duration) and marked <span class="ccy">non-OAS</span> and
      <span class="ccy">est.</span> — they are estimates of where those indices
      trade, not published indices, and must not be read as equivalent to the
      US figure beside them.</p>`;

  wireCurveControls();
}

// Which macro series the chart can draw, and how each behaves. `step` is not
// cosmetic -- see dateChart.
const MACRO_SERIES = [
  { key: "gdp_yoy", label: "GDP growth (YoY)", step: false },
  { key: "cpi_yoy", label: "Inflation (CPI YoY)", step: false },
  { key: "policy_rate", label: "Policy rate", step: true },
];
// Module-level so the selection survives any other control on the panel, every
// one of which re-runs renderMacro wholesale.
let macroSel = { regions: ["CH"], series: ["gdp_yoy", "cpi_yoy", "policy_rate"], period: "5Y" };

function macroChartBlock() {
  const hist = (DATA.macro || {}).history || {};
  const available = MACRO_SERIES.filter((m) => Object.keys(hist[m.key] || {}).length);
  if (!available.length) return "";

  let regions = macroSel.regions.filter((r) => MACRO_ORDER.includes(r));
  if (!regions.length) regions = [MACRO_ORDER[0]];
  let series = macroSel.series.filter((k) => available.some((m) => m.key === k));
  if (!series.length) series = [available[0].key];

  // One line per (region, series) pair. Naming both in the label matters: with
  // several of each selected the legend is the only thing telling them apart.
  const lines = [];
  const pairs = [];
  regions.forEach((region) => series.forEach((key) => {
    if (((hist[key] || {})[region] || []).length >= 2) pairs.push(`${region}|${key}`);
  }));
  const colorOf = stableColors("macro", pairs);
  regions.forEach((region) => {
    series.forEach((key) => {
      const meta = MACRO_SERIES.find((m) => m.key === key);
      const points = (hist[key] || {})[region] || [];
      if (points.length < 2) return;
      lines.push({
        label: regions.length > 1 ? `${regionName(region)} — ${meta.label}` : meta.label,
        points, step: meta.step, color: colorOf(`${region}|${key}`),
      });
    });
  });

  const chip = (attr, value, label, on, idx) =>
    `<button class="chip${on ? " active" : ""}" data-${attr}="${value}"` +
    `${on && idx != null ? ` data-swatch style="--chip-color:${seriesColor(idx)}"` : ""}>${label}</button>`;

  const regionChips = MACRO_ORDER.map((r) =>
    chip("macro-region", r, regionName(r), regions.includes(r))).join("");
  const seriesChips = available.map((m) =>
    chip("macro-series", m.key, m.label, series.includes(m.key))).join("");
  const periodChips = (DATA.chart_periods || []).map((pd) =>
    chip("macro-period", pd, pd, pd === macroSel.period)).join("");

  // rebase is forced OFF: these are already rates in percent, and indexing a
  // growth rate to 100 would turn "inflation fell to 2%" into a number with no
  // meaning. Everything shares one axis honestly because everything is a %.
  const figure = lines.length
    ? dateChart(lines, macroSel.period, false,
                { noteHtml: (DATA.macro || {}).history_note || "" })
    : `<div class="chart-empty">Nothing selected.</div>`;

  return `<h2>Growth, Inflation and Policy Rates</h2>` +
    `<div class="chart-panel">
       <div class="chart-controls">
         <div class="control-group"><span class="control-label">Region</span>${regionChips}</div>
         <div class="control-group"><span class="control-label">Series</span>${seriesChips}</div>
         <div class="control-group"><span class="control-label">Period</span>${periodChips}</div>
       </div>
       <div class="chart-figure">${figure}</div>
     </div>`;
}

/** Toggle `value` in `list`, refusing to empty it — an empty chart is a dead end —
 *  and, given `max`, refusing to grow it past that. */
function toggleChip(list, value, max) {
  const at = list.indexOf(value);
  if (at >= 0) { if (list.length > 1) list.splice(at, 1); }
  else if (max == null || list.length < max) list.push(value);
  return list;
}

// The palette has eight series colours, and ten regions now reach the macro
// tab. Rather than cycle a colour onto a second line, a region chart takes at
// most eight regions at once; a ninth chip is disabled until one is dropped.
const MAX_LINES = SERIES_VARS.length;
const FULL_TIP = `At most ${SERIES_VARS.length} regions at once, so every line keeps its own colour. Deselect one to add this.`;
// Default region set for a chart: everything available, up to the cap,
// preferring the eight core regions over the macro-only two.
const defaultRegions = (available) => available.slice(0, MAX_LINES);

// ---------------------------------------------------------------------------
// Price levels across regions
//
// Every line is rebased to 100 at ONE common month. That is the whole point
// and it is not what dateChart does by itself: slicePeriod cuts each line back
// from its OWN last date, and releases end on different months (Japan runs two
// behind the US), so each line would otherwise set its 100 on a different
// month and the comparison would be quietly off by those months' inflation.
// The window is therefore anchored on the newest release among the selected
// regions, and the base is the first month on or after its start that EVERY
// selected line has -- the US has no October 2025 print, and skipping a
// month for everyone beats inventing one for the US. Lines are trimmed to
// start at that base and handed to dateChart `presliced`, so its own per-line
// cut cannot move anyone's start again.
// ---------------------------------------------------------------------------
let plSel = { regions: null, ccy: "Local", period: "5Y" };
const PL_PERIOD_MONTHS = { "3M": 3, "1Y": 12, "2Y": 24, "3Y": 36, "5Y": 60, "10Y": 120, "20Y": 240 };

function monthsBetween(a, b) {
  const [ya, ma] = a.split("-").map(Number), [yb, mb] = b.split("-").map(Number);
  return (yb - ya) * 12 + (mb - ma);
}

function priceLevelBlock() {
  const pl = (DATA.macro || {}).price_levels;
  if (!pl) return "";
  const view = plSel.ccy === "CHF" ? "chf" : "local";
  const hist = (pl.history || {})[view] || {};
  const meta = pl.regions || {};
  const available = MACRO_ORDER.filter((r) => (hist[r] || []).length > 1);
  if (!available.length) return "";
  if (!plSel.regions) plSel.regions = defaultRegions(available);
  let regions = plSel.regions.filter((r) => available.includes(r));
  if (!regions.length) regions = [available[0]];

  // Months, not days: these are month-start dates, and a 91-day "3M" cutoff
  // lands on the 2nd and silently makes it a two-month window. YTD is based on
  // the previous December, the convention for a year-to-date price change.
  const end = regions.map((r) => hist[r][hist[r].length - 1][0]).sort().pop();
  const [ey, em] = end.split("-").map(Number);
  const back = plSel.period === "YTD" ? em : (PL_PERIOD_MONTHS[plSel.period] || 12);
  const cut = new Date(Date.UTC(ey, em - 1 - back, 1));
  const cutISO = cut.toISOString().slice(0, 10);

  // A region whose history starts after the window opens cannot be put on the
  // common base; it is left out and named, rather than moving everyone's base.
  const tooShort = regions.filter((r) => hist[r][0][0] > cutISO);
  const drawn = regions.filter((r) => !tooShort.includes(r));
  const shared = drawn.length
    ? hist[drawn[0]].map((p) => p[0]).filter((d) => d >= cutISO &&
        drawn.every((r) => hist[r].some((p) => p[0] === d)))
    : [];
  const base = shared[0];

  const colorOf = stableColors("prices", regions);
  const lines = base ? drawn.map((r) => ({
    label: `${regionName(r)} <span class="ccy">${(meta[r] || {}).basis || ""}</span>`,
    points: hist[r].filter((p) => p[0] >= base), color: colorOf(r),
  })).filter((l) => l.points.length > 1) : [];

  const chip = (attr, value, label, on, color) =>
    `<button class="chip${on ? " active" : ""}" data-${attr}="${value}"` +
    `${on && color ? ` data-swatch style="--chip-color:${color}"` : ""}>${label}</button>`;
  const plFull = plSel.regions.length >= MAX_LINES;
  const regionChips = available.map((r) => {
    const on = regions.includes(r);
    return chip("pl-region", r, regionName(r), on, on ? colorOf(r) : null)
      .replace("<button", !on && plFull ? `<button aria-disabled="true" data-tip="${FULL_TIP}"` : "<button");
  }).join("");
  const ccyChips = ["Local", "CHF"].map((c) =>
    chip("pl-ccy", c, c === "Local" ? "Local currency" : "In CHF", plSel.ccy === c)).join("");
  const periodChips = (pl.periods || DATA.chart_periods || []).map((pd) =>
    chip("pl-period", pd, pd, pd === plSel.period)).join("");

  const shortNote = tooShort.length
    ? ` Not shown for ${plSel.period}: ` + tooShort.map((r) =>
        `${regionName(r)} (${(meta[r] || {}).basis || "index"} starts ${monthLabel(hist[r][0][0])})`).join(", ") + "."
    : "";
  const caption = base
    ? `<strong>Indexed to 100 at ${monthLabel(base)}</strong> for every line. ${pl.note || ""}` +
      (view === "chf" ? ` ${pl.chf_note || ""}` : "") + shortNote
    : "";
  const figure = lines.length
    ? dateChart(lines, plSel.period, true, { noteHtml: caption, presliced: true })
    : `<div class="chart-empty">Not enough history for ${plSel.period}.${shortNote}</div>`;

  // Change over the window, base to each region's own latest month. The
  // annualised rate uses the months actually elapsed, so a region whose newest
  // print is older is not marked down for it; under a year it is left blank,
  // because an annualised few months of a NOT seasonally adjusted index is
  // mostly the season.
  const rows = base ? drawn.map((r) => {
    const pts = hist[r].filter((p) => p[0] >= base);
    const last = pts[pts.length - 1];
    const ratio = last[1] / pts[0][1];
    const months = monthsBetween(base, last[0]);
    const ann = months >= 12 ? (Math.pow(ratio, 12 / months) - 1) * 100 : null;
    return [regionName(r), `<span class="ccy">${(meta[r] || {}).basis || ""}</span>`,
            // Uncoloured: green for "prices rose 25%" would read as good news.
            `${ratio >= 1 ? "+" : ""}${pctPlain((ratio - 1) * 100, 1)}`,
            ann == null ? dash() : pctPlain(ann, 1),
            monthLabel(last[0])];
  }) : [];

  return `<h2 class="mt">Price Levels</h2>` +
    note(`How far consumer prices have risen in each region since the start of the window${view === "chf" ? ", measured in Swiss francs" : ""}. A level, not a rate: a line at 120 means prices are 20% higher than at the base month.`) +
    `<div class="chart-panel">
       <div class="chart-controls">
         <div class="control-group"><span class="control-label">Region</span>${regionChips}</div>
         <div class="control-group"><span class="control-label">Measured in</span>${ccyChips}</div>
         <div class="control-group"><span class="control-label">Period</span>${periodChips}</div>
       </div>
       <div class="chart-figure">${figure}</div>
     </div>` +
    (rows.length
      ? table(["Region", "Basis", `Change since ${monthLabel(base)}`, "Annualised", "Latest month"], rows)
      : "");
}

// ---------------------------------------------------------------------------
// Growth & inflation, one table
//
// Real GDP, CPI and nominal GDP side by side with the IMF's forecasts for this
// year and next. The YoY / QoQ switch moves every historical column at once,
// so a row never mixes the two horizons. GDP is seasonally adjusted at source;
// CPI is NSA at source and its 3-month rate is seasonally adjusted in the
// export (transform/growth), so the QoQ view is like-for-like across the row.
//
// Trend arrows compare two numbers and say which in their tooltip:
//   history  - the latest quarter annualised against the year-on-year rate,
//              i.e. is momentum running above or below the annual pace;
//   forecast - this year's IMF figure against the latest actual YoY, and next
//              year's against this year's.
// They are uncoloured on purpose: faster inflation is not good news.
// ---------------------------------------------------------------------------
let giSel = { basis: "yoy" };
const TREND_FLAT_PP = 0.25;

function trendArrow(now, then, what) {
  if (now == null || then == null) return "";
  const d = now - then;
  const dir = d > TREND_FLAT_PP ? "up" : d < -TREND_FLAT_PP ? "down" : "flat";
  const glyph = { up: "▲", down: "▼", flat: "▶" }[dir];
  const word = { up: "above", down: "below", flat: "within ±0.25pp of" }[dir];
  const tip = `${what.now} (${now.toFixed(1)}%) is ${word} ${what.then} (${then.toFixed(1)}%)` +
              (dir === "flat" ? "." : `, by ${Math.abs(d).toFixed(1)}pp.`);
  return `<span class="trend ${dir === "flat" ? "flat" : ""}" data-tip="${tip}">${glyph}</span>`;
}

function growthInflationBlock() {
  const macro = DATA.macro || {};
  const fc = macro.forecasts || {};
  const [ya, yb] = (fc.years || []).map(String);
  const qoq = giSel.basis === "qoq";
  const horizon = qoq ? "latest quarter, annualised" : "year on year";
  const esc = (t) => String(t || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;");
  const edition = fc.edition ? fc.edition.replace("World Economic Outlook, ", "WEO ") : "WEO";
  const pct = (v) => (v == null ? "—" : `${v.toFixed(1)}%`);

  // A value with its details behind a hover, not printed under it: the table
  // shows numbers and direction, the tooltip carries period, the other
  // horizon, where the figure sits in its own history, and the basis.
  const cell = (v, arrow, tipLines) => v == null ? dash()
    : `<span class="has-tip" data-tip="${esc(tipLines.filter(Boolean).join("<br>"))}">${pctPlain(v, 1)}</span>${arrow}`;

  const latest = (row, k, label, period, extra) => {
    const yoy = row[k.yoy], q = row[k.qoq];
    return cell(qoq ? q : yoy, trendArrow(q, yoy, { now: "The latest quarter annualised", then: "the year-on-year rate" }), [
      `<strong>${label}, ${period || ""}</strong>`,
      `Year on year: ${pct(yoy)} · latest quarter annualised: ${pct(q)}`,
      ctxText(qoq ? row[k.qctx] : row[k.ctx]),
      ...(extra || []),
    ]);
  };
  const forecast = (v, prev, prevWhat, label, year, extra) =>
    cell(v, trendArrow(v, prev, { now: `The IMF's ${year} forecast`, then: prevWhat }),
         [`<strong>${label}, ${year} (IMF projection)</strong>`, `Source: ${edition}`, ...(extra || [])]);

  const rows = MACRO_ORDER.map((r) => {
    const g = (macro.gdp || {})[r] || {};
    const i = (macro.inflation || {})[r] || {};
    const f = (fc.regions || {})[r] || {};
    const fg = f.gdp || {}, fn = f.nominal || {}, fi = f.cpi || {};
    const scope = f.scope_note ? [`<em>${f.scope_note}</em>`] : [];
    const mark = f.scope_note ? `<span class="trend flat" data-tip="${esc(f.scope_note)}">*</span>` : "";
    const name = g.basis
      ? `<span class="has-tip" data-tip="${esc(`GDP here is ${g.basis}. ${macro.gdp_definition || ""}`)}">${regionName(r)}</span>`
      : regionName(r);
    return [
      name,
      latest(g, { yoy: "yoy_pct", qoq: "qoq_ann_pct", ctx: "context", qctx: "qoq_ann_context" },
             "Real GDP", g.period_label, g.basis ? [`Basis: ${g.basis}`] : []),
      forecast(fg[ya], g.yoy_pct, "the latest real GDP year-on-year rate", "Real GDP growth", ya, scope) + mark,
      forecast(fg[yb], fg[ya], `its ${ya} forecast`, "Real GDP growth", yb, scope) + mark,
      latest(g, { yoy: "nominal_yoy_pct", qoq: "nominal_qoq_ann_pct", ctx: "nominal_context", qctx: "nominal_qoq_ann_context" },
             "Nominal GDP", g.nominal_period_label, g.nominal_basis ? [`Basis: ${g.nominal_basis}`] : []),
      forecast(fn[ya], g.nominal_yoy_pct, "the latest nominal GDP year-on-year rate", "Nominal GDP growth", ya,
               [fc.nominal_definition, ...scope]) + mark,
      forecast(fn[yb], fn[ya], `its ${ya} forecast`, "Nominal GDP growth", yb,
               [fc.nominal_definition, ...scope]) + mark,
      latest(i, { yoy: "q_yoy_pct", qoq: "q_qoq_ann_pct", ctx: "q_context", qctx: "q_qoq_ann_context" },
             "CPI", i.q_period_label ? `${i.q_period_label} average` : "", [
               `Measured over GDP's quarter, so the row describes one period.`,
               i.yoy_pct != null ? `Newest monthly print: ${i.yoy_pct.toFixed(1)}% YoY (${i.period_label})` : "",
               i.basis ? `Index: ${i.basis}` : ""]),
      forecast(fi[ya], i.yoy_pct, `the latest CPI year-on-year rate (${i.period_label || "newest month"})`, "CPI inflation, annual average", ya),
      forecast(fi[yb], fi[ya], `its ${ya} forecast`, "CPI inflation, annual average", yb),
    ];
  });

  const head = (label, sub, tip) =>
    `<span class="has-tip" data-tip="${esc(tip)}">${label}</span>` +
    (sub ? `<span class="cell-sub">${sub}</span>` : "");
  const fcSub = (y) => `IMF · ${y}`;
  // The switch above sets the horizon; each Latest heading repeats it.
  const latestSub = qoq ? "QoQ ann." : "YoY";
  const latestTip = (what) => `The newest published ${what}, ${horizon} (set by the switch above). Hover a figure for its period, the other horizon and where it sits in its own history.`;
  const tbl = table(
    ["Region",
     head("Latest", latestSub, `${latestTip("real GDP growth")}<br><br>${macro.gdp_definition || ""}`),
     head("CY FC", fcSub(ya), `Real GDP growth forecast for the current calendar year (${ya}). ${fc.definition || ""}`),
     head("NY FC", fcSub(yb), `Real GDP growth forecast for next calendar year (${yb}). ${fc.definition || ""}`),
     head("Latest", latestSub, `${latestTip("nominal GDP growth")}<br><br>${macro.nominal_gdp_definition || ""}`),
     head("CY FC", fcSub(ya), `Nominal GDP growth forecast for ${ya}. ${fc.nominal_definition || ""}`),
     head("NY FC", fcSub(yb), `Nominal GDP growth forecast for ${yb}. ${fc.nominal_definition || ""}`),
     head("Latest", latestSub, `Headline consumer price inflation, ${horizon}, measured over the SAME QUARTER as the GDP figures (the quarter's average index), so a row describes one period. The quarter-on-quarter rate is seasonally adjusted here, not by the statistics office. Even aligned, real growth plus CPI need not equal nominal growth: nominal GDP is deflated by the GDP deflator, which prices what an economy produces, not what households buy.`),
     head("CY FC", fcSub(ya), `CPI inflation forecast for ${ya}: the change in the ANNUAL AVERAGE price level, which differs from a year-on-year print. ${fc.definition || ""}`),
     head("NY FC", fcSub(yb), `CPI inflation forecast for ${yb}, annual average. ${fc.definition || ""}`)],
    rows,
    [["", 1], ["Real GDP growth", 3], ["Nominal GDP growth", 3], ["Inflation", 3]]);

  const switchChips = [["yoy", "Year on year"], ["qoq", "Latest quarter, annualised"]].map(([k, l]) =>
    `<button class="chip${giSel.basis === k ? " active" : ""}" data-gi-basis="${k}">${l}</button>`).join("");

  return `<h2 class="mt">Growth &amp; Inflation</h2>` +
    note(`Latest figures beside the IMF's forecasts (${edition}) for the current year (CY) and next (NY). Hover any heading for its definition and any figure for its details. Arrows: ▲/▼ is more than 0.25pp above/below what it is compared with, ▶ within that — on latest figures, the latest quarter's pace against the year-on-year rate; on forecasts, CY against the latest actual and NY against CY. India and Brazil appear on this tab only.`) +
    `<div class="chart-controls basis-switch"><div class="control-group"><span class="control-label">Latest figures</span>${switchChips}</div></div>` +
    `<div class="gi-table">${tbl}</div>`;
}

// ---------------------------------------------------------------------------
// GDP across regions
//
// IMF WEO, annual, for every region: one publisher and one edition, so the
// three measures and the projections line up. Projection years are drawn
// dashed behind a shaded zone. Every region in a window shares the same base
// year -- the data are annual, so unlike the price-level chart there is no
// ragged month end to reconcile.
// ---------------------------------------------------------------------------
let gdpSel = { regions: null, measure: "nominal_usd", display: "absolute", period: "20Y" };
const GDP_MEASURES = [["real_index", "Real"], ["nominal_usd", "Nominal (USD)"], ["ppp", "PPP"]];

function fmtBn(v) {
  if (v === 0) return "0";
  const t = v / 1000;
  return t >= 10 ? `${t.toFixed(0)}tn` : t >= 1 ? `${t.toFixed(1)}tn` : `${v.toFixed(0)}bn`;
}

function gdpChartBlock() {
  const gl = (DATA.macro || {}).gdp_levels;
  if (!gl) return "";
  const hist = (gl.history || {})[gdpSel.measure] || {};
  const available = MACRO_ORDER.filter((r) => (hist[r] || []).length > 1);
  const everywhere = MACRO_ORDER.filter((r) =>
    GDP_MEASURES.some(([m]) => ((gl.history || {})[m] || {})[r]));
  if (!everywhere.length) return "";
  if (!gdpSel.regions) gdpSel.regions = defaultRegions(
    ["US", "EZ", "CN", "JP", "IN", "UK", "BR", "CH"].filter((r) => everywhere.includes(r))
      .concat(everywhere.filter((r) => !["US", "EZ", "CN", "JP", "IN", "UK", "BR", "CH"].includes(r))));
  const realOnly = gdpSel.measure === "real_index";
  const indexed = realOnly || gdpSel.display === "indexed";
  let regions = gdpSel.regions.filter((r) => available.includes(r));

  const P = gl.projection_from;
  const lastActual = P != null ? P - 1 : null;
  const year = (iso) => parseInt(iso.slice(0, 4), 10);
  const lastYear = regions.length
    ? Math.max(...regions.map((r) => year(hist[r][hist[r].length - 1][0]))) : null;
  const anchor = lastActual != null ? lastActual : lastYear;
  let base = null;
  const tooShort = [];
  if (regions.length && anchor != null) {
    const firsts = regions.map((r) => year(hist[r][0][0]));
    if (gdpSel.period === "Max") {
      // Indexed lines need one common base year, so Max starts where the
      // shortest selected history does; absolute levels can each start early.
      base = indexed ? Math.max(...firsts) : Math.min(...firsts);
    } else {
      base = anchor - parseInt(gdpSel.period, 10);
      regions.forEach((r, k) => { if (firsts[k] > base) tooShort.push(r); });
    }
  }
  const drawn = regions.filter((r) => !tooShort.includes(r));
  const colorOf = stableColors("gdp", gdpSel.regions.filter((r) => everywhere.includes(r)));
  const lines = base != null ? drawn.map((r) => ({
    label: regionName(r),
    points: hist[r].filter((p) => year(p[0]) >= base), color: colorOf(r),
  })).filter((l) => l.points.length > 1) : [];

  const chip = (attr, value, label, on, color, disabled, tip) =>
    `<button class="chip${on ? " active" : ""}" data-${attr}="${value}"` +
    `${on && color ? ` data-swatch style="--chip-color:${color}"` : ""}` +
    `${disabled ? ` aria-disabled="true" data-tip="${tip}"` : ""}>${label}</button>`;
  const gdpFull = gdpSel.regions.length >= MAX_LINES;
  const regionChips = everywhere.map((r) => {
    const on = gdpSel.regions.includes(r);
    const missing = !available.includes(r);
    return chip("gdp-region", r, regionName(r), on && !missing, on && !missing ? colorOf(r) : null,
                missing || (!on && gdpFull),
                missing ? `No ${GDP_MEASURES.find(([m]) => m === gdpSel.measure)[1]} series for ${regionName(r)}`
                        : FULL_TIP);
  }).join("");
  const measureChips = GDP_MEASURES.map(([m, l]) =>
    chip("gdp-measure", m, l, gdpSel.measure === m)).join("");
  const displayChips = [["absolute", "Absolute"], ["indexed", "Indexed"]].map(([d, l]) =>
    chip("gdp-display", d, l, indexed ? d === "indexed" : d === "absolute", null,
         realOnly && d === "absolute",
         "Real GDP is a volume in each region's own currency; there is no common unit to compare levels in, so it is shown indexed only.")).join("");
  const periodChips = (gl.periods || []).map((pd) =>
    chip("gdp-period", pd, pd, pd === gdpSel.period)).join("");

  const unavailable = ((gl.unavailable || {})[gdpSel.measure] || []).filter((r) => gdpSel.regions.includes(r));
  const notes = [];
  if (indexed && base != null) notes.push(`<strong>Indexed to 100 in ${base}</strong> for every line.`);
  if (!indexed) notes.push(`<strong>${(gl.units || {})[gdpSel.measure] || ""}</strong>.`);
  if (P != null) notes.push(`Dashed, ${P} onward: IMF projections (${gl.edition || "WEO"}); ${lastActual} and earlier are actuals or IMF estimates.`);
  notes.push(gl.note || "");
  if (unavailable.length) notes.push(`No line for ${unavailable.map(regionName).join(", ")}: the IMF publishes no ${gdpSel.measure === "ppp" ? "PPP" : ""} aggregate for it.`);
  if (tooShort.length) notes.push(`Not shown for ${gdpSel.period}: ${tooShort.map((r) => `${regionName(r)} (IMF series starts ${year(hist[r][0][0])})`).join(", ")}.`);
  const caption = notes.join(" ");

  const figure = lines.length
    ? dateChart(lines, gdpSel.period, indexed, {
        noteHtml: caption, presliced: true,
        dashFrom: P != null ? `${P}-01-01` : null,
        xFmt: (iso) => iso.slice(0, 4),
        yFmt: indexed ? (v) => v.toFixed(0) : fmtBn,
      })
    : `<div class="chart-empty">Nothing to draw for this selection. ${caption}</div>`;

  // Growth over the window to the last actual year, then the IMF's projected
  // growth from there to its last projection year. Compound annual rates, so
  // windows of different length compare. In USD terms for Nominal: a dollar
  // rate, which includes the currency's move against the dollar.
  const cagr = (a, b, n) => (a > 0 && b > 0 && n > 0 ? (Math.pow(b / a, 1 / n) - 1) * 100 : null);
  const at = (pts, y) => { const p = pts.find((q) => year(q[0]) === y); return p ? p[1] : null; };
  const rows = lines.map((l, k) => {
    const r = drawn[k], pts = l.points;
    const endA = anchor != null ? at(pts, anchor) : null;
    const lastP = pts[pts.length - 1];
    const b0 = pts[0][1];
    const level = endA == null ? dash()
      : indexed ? (endA / b0 * 100).toFixed(1) : fmtBn(endA);
    const hist_ = endA == null ? null : cagr(b0, endA, anchor - year(pts[0][0]));
    const proj = endA == null ? null : cagr(endA, lastP[1], year(lastP[0]) - anchor);
    return [regionName(r), level, hist_ == null ? dash() : pctPlain(hist_, 1),
            proj == null ? dash() : pctPlain(proj, 1)];
  });
  const lastProj = lines.length ? Math.max(...lines.map((l) => year(l.points[l.points.length - 1][0]))) : null;

  return `<h2 class="mt">GDP by Region</h2>` +
    note(`How large each economy is, and how fast it has grown, on the IMF's annual figures. <strong>Nominal (USD)</strong> converts at market exchange rates, so a currency's fall shrinks an economy in this view; <strong>PPP</strong> converts at purchasing-power parity; <strong>Real</strong> strips out inflation and is indexed only.`) +
    `<div class="chart-panel">
       <div class="chart-controls">
         <div class="control-group"><span class="control-label">Region</span>${regionChips}</div>
         <div class="control-group"><span class="control-label">Measure</span>${measureChips}</div>
         <div class="control-group"><span class="control-label">Display</span>${displayChips}</div>
         <div class="control-group"><span class="control-label">Period</span>${periodChips}</div>
       </div>
       <div class="chart-figure">${figure}</div>
     </div>` +
    (rows.length
      ? table(["Region", `${anchor} ${indexed ? `(${base} = 100)` : "level"}`,
               `Growth p.a. ${base}–${anchor}`, `IMF projection p.a. ${anchor}–${lastProj}`], rows)
      : "");
}

function renderMacro() {
  // Germany is dropped here and only here: its "policy rate" is the ECB's,
  // mirrored, so listing it was the same number twice. It stays in the payload
  // because the Regional Snapshot's Germany view still needs a rate to show.
  const rateRows = MACRO_ORDER.filter((region) => {
    const cb = (DATA.macro.policy_rates || {})[region] || {};
    return !cb.mirror_of;
  }).map((region) => {
    const cb = (DATA.macro.policy_rates || {})[region] || {};
    return [regionName(region), pctPlain(cb.rate_pct) + ctxTag(cb.context), cb.as_of || dash()];
  });

  // The regime map that used to sit here was removed from the page on
  // 2026-10-22 at Marco's request; its coordinates are still exported
  // (payload `regime`) and nothing reads them.
  document.getElementById("panel-macro").innerHTML =
    macroChartBlock() +
    growthInflationBlock() +
    gdpChartBlock() +
    priceLevelBlock() +

    `<h2 class="mt">Central Bank Policy Rates</h2>` +
    note("Source: BIS Data Portal (CBPOL), all regions on one endpoint. Germany is not listed: it has no independent policy rate, and showing the ECB's figure under a German heading would be the same number twice. A policy rate legitimately sits unchanged for months, so an older date is not a stale figure.") +
    table(["Region", "Policy Rate", "As of"], rateRows);

  // Every control on this panel re-runs the whole render, so all listeners are
  // (re-)attached here rather than once at boot.
  const on = (attr, fn) => document.querySelectorAll(`[data-${attr}]`).forEach((b) =>
    b.addEventListener("click", () => {
      // aria-disabled rather than `disabled`: a disabled button fires no
      // mouse events, so its tooltip explaining WHY could never show.
      if (b.getAttribute("aria-disabled") === "true") return;
      fn(b.getAttribute(`data-${attr}`));
      renderMacro();
    }));
  on("macro-region", (v) => toggleChip(macroSel.regions, v));
  on("macro-series", (v) => toggleChip(macroSel.series, v));
  on("macro-period", (v) => { macroSel.period = v; });
  on("gi-basis", (v) => { giSel.basis = v; });
  on("gdp-region", (v) => toggleChip(gdpSel.regions, v, MAX_LINES));
  on("gdp-measure", (v) => { gdpSel.measure = v; });
  on("gdp-display", (v) => { gdpSel.display = v; });
  on("gdp-period", (v) => { gdpSel.period = v; });
  on("pl-region", (v) => toggleChip(plSel.regions, v, MAX_LINES));
  on("pl-ccy", (v) => { plSel.ccy = v; });
  on("pl-period", (v) => { plSel.period = v; });
}

function renderCurrencies() {
  const headers = ["Pair", "Level", "1W", "YTD", "1Y trend"];
  const rows = [];
  (DATA.currencies || []).forEach((fx) => {
    const cells = [fx.name, fmtNum(fx.level, 4) + ctxTag(fx.context), fmtPct(fx.chg_1w_pct), fmtPct(fx.chg_ytd_pct)];
    chartableRows(`fx:${fx.id}`, fx.name, fx.history, cells, headers.length).forEach((r) => rows.push(r));
  });

  // Replaced the "cost of hedging back to CHF" table on 2026-09-21. That was a
  // policy-rate differential labelled as a hedging cost: it left out the
  // cross-currency basis and used policy rates where forwards price off OIS,
  // so it was a floor that read like an estimate. This is the thing that
  // actually moves currencies over long horizons instead.
  const rr = DATA.real_rates || {};
  const rrRows = (rr.rows || []).map((r) => {
    const label = regionName(r.region) + (r.is_home ? ` <span class="ccy">(home)</span>` : "");
    if (r.real_rate_pct == null) {
      return [label, pctPlain(r.nominal_2y_pct), pctPlain(r.cpi_yoy_pct, 1),
              `<span class="stub">no ${r.missing_leg}</span>`, dash()];
    }
    const d = r.differential_vs_home_pct;
    return [
      label,
      pctPlain(r.nominal_2y_pct),
      pctPlain(r.cpi_yoy_pct, 1) + (r.cpi_basis ? ` <span class="ccy">${r.cpi_basis}</span>` : ""),
      `<strong class="${r.real_rate_pct >= 0 ? "up" : "down"}">${r.real_rate_pct.toFixed(2)}%</strong>`,
      r.is_home
        ? `<span class="ccy">—</span>`
        : (d != null
            ? `<span class="${d >= 0 ? "up" : "down"}"><strong>${d >= 0 ? "+" : ""}${d.toFixed(2)}pp</strong></span>`
            : dash()),
    ];
  });
  let realHtml = "";
  if (rrRows.length) {
    const caveats = (rr.caveats || []).map((c) => `<li>${c}</li>`).join("");
    realHtml =
      `<h2 class="mt">Real Rate Differentials vs. ${regionName(rr.home_region || "CH")}</h2>` +
      `<div class="approx-warning">
         <strong>A long-horizon driver, not a signal.</strong> ${rr.method || ""}
         <ul>${caveats}</ul>
       </div>` +
      table([`Region`, `Nominal ${rr.rate_leg || "2y"}`, `Inflation (${rr.inflation_leg || "CPI YoY"})`,
             `Real rate`, `vs. ${regionName(rr.home_region || "CH")}`], rrRows);
  }

  document.getElementById("panel-currencies").innerHTML =
    `<h2>Currencies</h2>` + note("Click a trend to open a chart.") +
    tableWithRaw(headers, rows) + realHtml;
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
  // One table, not two. The scorecard and the country multiples were both
  // eight rows keyed by the same region order, and their coverage is
  // complementary rather than overlapping -- the US has a CAPE and no
  // multiples, the other seven have multiples and no CAPE -- so splitting them
  // put a region's valuation on two tables and left each half full of dashes.
  const COLS = 9;
  const mult = (v, key) => (v.multiples || {})[key];
  const multCell = (v, key) => {
    const m = mult(v, key);
    return m && m.value != null ? `${m.value.toFixed(2)}${ctxTag(m.context)}` : dash();
  };

  const rows = [];
  REGION_ORDER.forEach((region) => {
    const v = (DATA.valuation || {})[region] || {};
    const e = (DATA.equity_risk_premia || {})[region] || {};
    // CAPE carries its own as-of: Shiller's file ends well before the
    // multiples' vintage, and one shared "As of" would quietly date the CAPE
    // to a year it does not belong to.
    const capeCell = v.cape != null
      ? `<span class="has-tip" data-tip="Shiller cyclically-adjusted P/E${v.cape_as_of ? `, as of ${v.cape_as_of}` : ""}"><strong>${v.cape.toFixed(1)}</strong></span>${ctxTag(v.cape_context)}`
      : dash();
    const erpCell = e.erp_pct != null
      ? `<span class="has-tip" data-tip="Damodaran implied equity risk premium${e.as_of ? `, as of ${e.as_of}` : ""}"><strong>${e.erp_pct.toFixed(2)}%</strong></span>${ctxTag(e.context)}`
      : dash();

    // Europe's multiples are a cap-weighted aggregate, not a median, so the
    // row says which it is rather than letting the column heading imply one.
    const scopeTag = v.multiples_is_aggregate
      ? ` <span class="ccy">Europe, cap-weighted</span>` : "";
    rows.push([
      regionName(region), (v.name || "") + scopeTag, capeCell,
      multCell(v, "pe"), multCell(v, "pb"), multCell(v, "ps"), multCell(v, "ev_ebitda"),
      erpCell,
      v.multiples_as_of || e.as_of || v.cape_as_of || dash(),
    ]);

    // The Eurozone is blank across the row, and the reason is a scope decision
    // rather than pending work, so it is stated where it applies instead of
    // being left to the reader to find in the note below.
    if (v.cape == null && e.erp_pct == null && !v.multiples) {
      rows.push(`<tr><td class="commentary" colspan="${COLS}">No bloc-level source: Damodaran publishes member states with no euro-area aggregate, and Germany's figure is not a stand-in for it. Descoped, not pending — see <code>data/DATA-CATALOG.csv</code>.</td></tr>`);
    }
  });

  const erpCovered = REGION_ORDER.filter((r) => ((DATA.equity_risk_premia || {})[r] || {}).erp_pct != null).length;
  const multCovered = REGION_ORDER.filter((r) => ((DATA.valuation || {})[r] || {}).multiples).length;

  document.getElementById("panel-valuation").innerHTML =
    `<h2>Valuation</h2>` +
    note(`Three different bases sit on this row, and they are not comparable with each other. <strong>CAPE</strong> is cyclically adjusted — price over ten years of inflation-adjusted earnings — and is US-only by design, because it needs a long earnings history that exists for the S&amp;P 500 and not for the other indices. <strong>P/E, P/B, P/S and EV/EBITDA</strong> are Damodaran's country aggregates: the <strong>median</strong> across listed companies in each country, on <strong>trailing</strong> figures, not cyclically adjusted, and only from 2020 on because earlier vintages of the source publish means instead. <strong>ERP</strong> is the implied equity risk premium for that country's risk bucket, so the Aaa sovereigns share a figure. ${erpCovered} of ${REGION_ORDER.length} regions have an ERP and ${multCovered} have multiples. One row differs in kind: <strong>Europe</strong> is a cap-weighted aggregate across the region rather than a median across one country, because no euro-area median exists and STOXX Europe 600 is itself pan-European — a different statistic, marked on the row, and not comparable with the medians above and below it. Hover CAPE or ERP for its own as-of date, which differs from the multiples' vintage.`) +
    tableWithRaw(["Region", "Index", "CAPE", "P/E", "P/B", "P/S", "EV/EBITDA", "ERP", "As of"], rows) +

    `<p class="section-note"><strong>Known gaps on this tab.</strong> CAPE is US-only and will stay that way — it needs a long cyclically-adjusted earnings history that exists for the S&amp;P 500 and not elsewhere. The country multiples start in 2020, because Damodaran's earlier files publish means rather than medians. Europe carries no P/S, because the regional source publishes none. Still unsourced: dividend yields, forward (rather than trailing) multiples, and any true euro-area aggregate — the Europe row is wider than the euro area, deliberately. See <code>data/DATA-CATALOG.csv</code>.</p>`;
}


// ---------------------------------------------------------------------------
// Cross-asset correlation heatmap
// Correlation is polarity data, so the scale is diverging: two poles with a
// NEUTRAL GRAY midpoint (never a rainbow, never a hue at zero), per the
// dataviz skill. Blue = negative, red = positive, gray = uncorrelated.
// ---------------------------------------------------------------------------
let corrWindow = null;

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
    // The window keys are WEEK counts (window_weeks), and the payload has said
    // so since storage went weekly -- this label read "52d" until 2026-09-21,
    // the last daily-grain residue on the page.
    `<button class="period-btn${k === w ? " active" : ""}" data-corr-window="${k}">${k}W</button>`
  ).join("");

  let grid = "";
  {
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
  }

  const legend = `
    <div class="corr-legend">
      <span>−1 inverse</span>
      <span class="ramp" style="background:linear-gradient(to right, ${pal.neg}, ${pal.mid}, ${pal.pos})"></span>
      <span>+1 together</span>
    </div>`;

  return `<h2 class="mt">Cross-Asset Correlation</h2>` +
    note(`${corr.note || ""} Window: ${m.window_weeks} weeks, ${m.start} to ${m.as_of} (n=${m.n_obs}).`) +
    `<div class="period-bar">${buttons}</div>` + legend + grid;
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

// ---------------------------------------------------------------------------
// Snapshot: 10-year yield against nominal GDP growth
//
// The long rate an economy borrows at, set against how fast its nominal income
// grows. Both are percent, so one axis is honest; the gap (r - g) is the
// headline. Two different kinds of source by nature -- a market yield and a
// statistical release -- and the GDP leg runs a quarter or more behind, which
// the dates under the headline say.
// ---------------------------------------------------------------------------
let snapSel = { region: null, rgPeriod: "10Y" };
const RG_PERIODS = ["5Y", "10Y", "20Y"];

function rateVsGrowthPanel(region) {
  const h = (DATA.macro || {}).history || {};
  const ten = (h.yield_10y || {})[region] || [];
  const nom = (h.gdp_nominal_yoy || {})[region] || [];
  if (ten.length < 2 || nom.length < 2) return "";
  const gdp = ((DATA.macro || {}).gdp || {})[region] || {};
  const curve = (DATA.yield_curves || {})[region] || {};
  const r = (curve.tenors || {})["10Y"], g = gdp.nominal_yoy_pct;

  // One window for both lines, cut back from the newer of the two ends, so the
  // lagging GDP line does not start later than the yield.
  const end = [ten[ten.length - 1][0], nom[nom.length - 1][0]].sort().pop();
  const cutoff = new Date(new Date(end).getTime() - PERIOD_DAYS[snapSel.rgPeriod] * 86400000)
    .toISOString().slice(0, 10);
  const cut = (pts) => pts.filter((p) => p[0] >= cutoff);
  const colorOf = stableColors("rg", ["ten", "nom"]);
  const lines = [
    { label: "10-year government yield", points: cut(ten), color: colorOf("ten") },
    { label: "Nominal GDP growth, YoY" + (gdp.nominal_basis ? ` <span class="ccy">${gdp.nominal_basis}</span>` : ""),
      points: cut(nom), color: colorOf("nom") },
  ].filter((l) => l.points.length > 1);

  // The gap's average over the window, on the months both legs have, so the
  // headline can be read against what is normal for this economy.
  const nomBy = new Map(cut(nom).map((p) => [p[0], p[1]]));
  const gaps = cut(ten).filter((p) => nomBy.has(p[0])).map((p) => p[1] - nomBy.get(p[0]));
  const avgGap = gaps.length ? gaps.reduce((a, b) => a + b, 0) / gaps.length : null;

  let headline = "";
  if (r != null && g != null) {
    const gap = r - g;
    const read = gap < 0
      ? `The 10-year yield is <strong>below</strong> nominal growth: long-term borrowing costs less than the economy's income is growing.`
      : `The 10-year yield is <strong>above</strong> nominal growth: long-term borrowing costs more than the economy's income is growing.`;
    headline = `<div class="rg-headline">
        <span><span class="control-label">r − g</span> <span class="rg-value">${gap >= 0 ? "+" : ""}${gap.toFixed(1)}pp</span></span>
        <span class="rg-read">${read}${avgGap != null ? ` Over the ${snapSel.rgPeriod} window the gap averaged ${avgGap >= 0 ? "+" : ""}${avgGap.toFixed(1)}pp.` : ""}
          <span class="cell-sub">10y ${r.toFixed(2)}%${curve.as_of ? ` (${curve.as_of})` : ""} less nominal GDP ${g.toFixed(1)}% YoY (${gdp.nominal_period_label || ""}).</span></span>
      </div>`;
  }
  const chips = RG_PERIODS.map((pd) =>
    `<button class="chip${pd === snapSel.rgPeriod ? " active" : ""}" data-rg-period="${pd}">${pd}</button>`).join("");
  const figure = lines.length
    ? dateChart(lines, snapSel.rgPeriod, false, {
        presliced: true, zeroLine: true, yFmt: (v) => `${v.toFixed(0)}%`,
        noteHtml: "Monthly. The yield is the last weekly close in each month; nominal GDP is the year-on-year growth of the current-price series, carried across the months of its quarter. A line ends at its own latest release, so the GDP line stops a quarter or more before the yield. Two different publishers by nature — a market price and a national-accounts release." })
    : `<div class="chart-empty">Not enough history.</div>`;
  return `<div class="snap-panel"><h3 class="snap-head">10-year yield vs nominal growth</h3>
      ${headline}
      <div class="chart-panel">
        <div class="chart-controls"><div class="control-group"><span class="control-label">Period</span>${chips}</div></div>
        <div class="chart-figure">${figure}</div>
      </div></div>`;
}

function renderSnapshot(region) {
  snapSel.region = region;
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
      ${hero(gdp.basis ? `Real GDP YoY (${gdp.basis})` : "Real GDP YoY", pctPlain(gdp.yoy_pct, 1))}
      ${hero(lead ? lead.name + " YTD" : "Equities YTD", lead ? fmtPct(lead.chg_ytd_pct) : dash())}
      ${miniCurve(region)}
    </div>`;

  const equityLines = indices.map((idx) =>
    snapLine(`<span class="has-tip" data-tip="${indexTip(idx)}">${idx.name}</span>`,
             fmtNum(idx.level, (idx.level || 0) > 100 ? 1 : 4), idx.chg_ytd_pct,
             `1W ${fmtPct(idx.chg_1w_pct)} · 1Y ${fmtPct(idx.chg_1y_pct)} · vol ${idx.realized_vol_13w_pct != null ? idx.realized_vol_13w_pct.toFixed(1) + "%" : "—"}${idx.as_of ? " · " + idx.as_of : ""}`));

  const rateLines = CURVE_TENORS.map((k) =>
    t[k] != null ? snapLine(k, pctPlain(t[k]), null) : "").concat([
    curve["2s10s_bp"] != null ? snapLine("2s10s", fmtBp(curve["2s10s_bp"]), null) : "",
    real && (real.tenors || {})["10Y"] != null
      ? snapLine("10y real", pctPlain(real.tenors["10Y"]), null,
                 [real.basis, real.as_of].filter(Boolean).join(" \u00b7 ")) : "",
    curve.as_of ? snapLine("Curve as of", `<span class="ccy">${curve.as_of}</span>`, null) : "",
  ]);

  const expTenors = exp.tenors || {};
  const expKey = Object.keys(expTenors).find((k) => expTenors[k] != null);
  const macroLines = [
    snapLine("Policy rate", pctPlain(cb.rate_pct), null,
             [cb.name, cb.as_of].filter(Boolean).join(" \u00b7 ")),
    snapLine("CPI YoY", pctPlain(inf.yoy_pct, 1), null,
             [inf.period_label, inf.qoq_ann_pct != null
               ? `latest quarter annualised ${inf.qoq_ann_pct.toFixed(1)}%` : "",
               inf.basis]
               .filter(Boolean).join(" \u00b7 ")),
    snapLine("Real GDP YoY", pctPlain(gdp.yoy_pct, 1), null,
             [gdp.period_label, gdp.qoq_ann_pct != null
               ? `latest quarter annualised ${gdp.qoq_ann_pct.toFixed(1)}%` : "annual series"]
               .filter(Boolean).join(" \u00b7 ")),
    // The published current-price series, not real GDP plus CPI -- see the
    // Growth & Inflation table's note on the deflator.
    gdp.nominal_yoy_pct !== undefined
      ? snapLine("Nominal GDP YoY", pctPlain(gdp.nominal_yoy_pct, 1), null,
                 [gdp.nominal_period_label, gdp.nominal_qoq_ann_pct != null
                   ? `latest quarter annualised ${gdp.nominal_qoq_ann_pct.toFixed(1)}%` : "",
                  gdp.nominal_basis || "current prices"]
                   .filter(Boolean).join(" \u00b7 "))
      : "",
    // Regions with no market-implied source are simply omitted now, rather
    // than carrying a permanent "not sourced" line.
    expKey
      ? snapLine("Implied inflation", pctPlain(expTenors[expKey]), null,
                 `${expKey.replace(/_/g, " ")} · ${exp.basis || ""}`)
      : "",
  ];

  const mult = val.multiples || {};
  const valLines = [
    val.cape != null ? snapLine("CAPE", val.cape.toFixed(1), null,
                                [val.name, val.cape_as_of].filter(Boolean).join(" \u00b7 ")) : "",
    mult.pe ? snapLine("P/E (trailing)", mult.pe.value.toFixed(1), null,
                       [val.multiples_is_aggregate ? "Cap-weighted aggregate, Europe"
                                                   : "Median across listed companies",
                        val.multiples_as_of].filter(Boolean).join(" \u00b7 ")) : "",
    mult.pb ? snapLine("P/B", mult.pb.value.toFixed(2), null) : "",
    mult.ev_ebitda ? snapLine("EV/EBITDA", mult.ev_ebitda.value.toFixed(1), null) : "",
    erp.erp_pct != null ? snapLine("Equity risk premium", `${erp.erp_pct.toFixed(2)}%`, null, erp.method || "") : "",
    cc.cost_of_equity != null
      ? snapLine("Cost of equity", `${cc.cost_of_equity.toFixed(2)}%`, null,
                 (cc.formulae || {}).cost_of_equity || "")
      : "",
    cc.cost_of_debt != null
      ? snapLine("Cost of debt", `${cc.cost_of_debt.toFixed(2)}%`, null,
                 (cc.formulae || {}).cost_of_debt || "")
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
    rateVsGrowthPanel(region) +
    `<p class="section-note">Commodities are global and live on their own tab.
      Percentages beside a level are year-to-date. <strong>Each figure carries
      its own date</strong>, and they differ by design: equity and curve levels
      are last Friday's close, CPI is the month it measures, GDP the quarter,
      and valuation multiples are annual. A macro figure is labelled by the
      PERIOD it covers, not the day it was filed.</p>`;

  document.querySelectorAll("[data-rg-period]").forEach((b) =>
    b.addEventListener("click", () => {
      snapSel.rgPeriod = b.getAttribute("data-rg-period");
      renderSnapshot(snapSel.region);
    }));
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
