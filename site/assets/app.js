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
  populateRegionSelector();
  renderSnapshot(REGION_ORDER[0]);
  setupTabs();
  setupChartToggles();
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
function renderEquities() {
  const headers = ["Index", "Level", "1D", "1W", "MTD", "YTD", "1Y", "DD from ATH", "Vol (20d)", "1Y trend"];
  const rows = [];
  REGION_ORDER.concat(["EM"]).forEach((region) => {
    const indices = (DATA.equity_indices || {})[region] || [];
    if (!indices.length) return;
    rows.push({ band: region === "EM" ? "Emerging Markets" : regionName(region) });
    indices.forEach((idx) => {
      const key = `equity:${idx.id}`;
      const cells = [
        `${idx.name} <span class="ccy">${idx.currency}</span>`,
        fmtNum(idx.level, (idx.level || 0) > 100 ? 1 : 4),
        fmtPct(idx.chg_1d_pct), fmtPct(idx.chg_1w_pct), fmtPct(idx.chg_mtd_pct),
        fmtPct(idx.chg_ytd_pct), fmtPct(idx.chg_1y_pct),
        fmtPct(idx.drawdown_from_ath_pct) + ctxTag(idx.drawdown_context),
        (idx.realized_vol_20d_pct != null ? `${idx.realized_vol_20d_pct.toFixed(1)}%` : dash()) + ctxTag(idx.vol_context),
      ];
      chartableRows(key, idx.name, idx.history, cells, headers.length).forEach((r) => rows.push(r));
    });
  });
  document.getElementById("panel-equities").innerHTML =
    `<h2>Equity Indices</h2>` +
    note("Levels in local currency. Click any trend sparkline to open a chart and change the period.") +
    tableWithRaw(headers, rows);
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

function renderYields() {
  const nominalHeaders = ["Region", "2Y", "5Y", "10Y", "30Y", "2s10s", "As of"];
  const realHeaders = ["Region", "Basis", "2Y", "5Y", "10Y", "30Y", "2s10s", "As of"];

  // Inflation expectations, with tenor and index basis always stated.
  const expRows = [];
  REGION_ORDER.forEach((region) => {
    const e = (DATA.inflation_expectations || {})[region];
    if (!e) return;
    if (e.kind === "unavailable") {
      expRows.push([regionName(region), dash(), `<span class="stub">${e.note || "No free market-implied source."}</span>`]);
      return;
    }
    const t = e.tenors || {};
    const ec = e.context || {};
    const parts = Object.keys(t).map((k) => `${k.replace("_", " ")}: <strong>${t[k] != null ? t[k].toFixed(2) + "%" : "—"}</strong>${ctxTag(ec[k])}`).join(" &nbsp;·&nbsp; ");
    expRows.push([
      regionName(region),
      `<span class="badge badge-${e.kind}">${e.kind}-implied</span> <span class="ccy">${e.basis || ""}</span>`,
      parts + (e.note ? `<div class="stub small">${e.note}</div>` : ""),
    ]);
    if (e.model) {
      const mt = e.model.tenors || {};
      const mparts = Object.keys(mt).map((k) => `${k}: <strong>${mt[k] != null ? mt[k].toFixed(2) + "%" : "—"}</strong>`).join(" &nbsp;·&nbsp; ");
      expRows.push([
        `${regionName(region)} <span class="ccy">(model)</span>`,
        `<span class="badge badge-model">model-implied</span> <span class="ccy">${e.model.basis || ""}</span>`,
        mparts + `<div class="stub small">${e.model.note || ""}</div>`,
      ]);
    }
  });

  const sp = DATA.eurozone_spreads || { rows: [] };
  const spreadRows = (sp.rows || []).map((r) => [
    r.country, pctPlain(r.yield_pct, 3),
    (r.spread_bp != null ? fmtBp(r.spread_bp) : dash()) + ctxTag(r.context), r.as_of || dash(),
  ]);

  document.getElementById("panel-yields").innerHTML =
    `<h2>Government Yield Curves</h2>` +
    note("Nominal sovereign curves. The Eurozone row is the ECB's all-bonds euro area curve — a blend across euro area sovereigns — while Germany is the single-issuer Bund curve. They are deliberately different measures.") +
    table(nominalHeaders, curveRows(DATA.yield_curves, false)) +

    `<h2 class="mt">Real Yields</h2>` +
    note("Inflation-linked yields. Note the basis differs: US TIPS reference CPI, UK index-linked gilts reference RPI.") +
    table(realHeaders, curveRows(DATA.real_yield_curves, true)) +

    `<h2 class="mt">Market-Implied Inflation</h2>` +
    note("Breakeven / implied inflation with the tenor and index basis stated for each. These are not directly comparable across regions: UK figures are RPI-based and historically run roughly 0.8–1.0pp above the equivalent CPI rate. Where no inflation-linked market exists, the practitioner standard is the zero-coupon inflation swap, which has no free feed.") +
    table(["Region", "Type", "Tenors"], expRows) +

    `<h2 class="mt">Cost of Capital</h2>` +
    note(DATA.cost_of_capital_note || "") +
    table(["Region", "Real risk-free (10y)", "IG credit spread", "Equity risk premium", "Total", "Coverage"],
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
          regionName(region), pctPlain(L.real_risk_free), pctPlain(L.credit_spread),
          pctPlain(L.erp),
          s2.total_pct != null
            ? `<strong>${s2.total_pct.toFixed(2)}%</strong>${s2.complete ? "" : "*"}`
            : dash(),
          cov,
        ];
      }).filter(Boolean)) +
    `<p class="section-note">* A partial total sums only the legs that are sourced, so it is not comparable with a complete stack.</p>` +

    `<h2 class="mt">Euro-Area Sovereign Spreads vs. ${sp.benchmark || "Bund"}</h2>` +
    note(`Both legs come from the same ECB long-term rate series, so the spread is not distorted by mixing sources. Benchmark: ${sp.benchmark || "—"} at ${sp.benchmark_yield_pct != null ? sp.benchmark_yield_pct.toFixed(3) + "%" : "—"} (${sp.cadence || "monthly"}).`) +
    table(["Country", "10y yield", "Spread", "As of"], spreadRows);
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
  document.getElementById("panel-macro").innerHTML =
    `<h2>Central Bank Policy Rates</h2>` +
    note("Source: BIS Data Portal (CBPOL); Norges Bank for Norway. A policy rate legitimately sits unchanged for months, so an older date is not a stale figure.") +
    table(["Region", "Policy Rate", "As of"], rateRows) +

    `<h2 class="mt">Inflation</h2>` +
    note("Headline consumer prices. Year-on-year, plus the latest quarter annualised — the second is noisier but turns sooner.") +
    table(["Region", "CPI YoY", "QoQ annualised", "As of"], infRows) +

    `<h2 class="mt">GDP Growth</h2>` +
    note(DATA.macro.gdp_definition || "") +
    table(["Region", "Real GDP YoY", "QoQ annualised", "As of"], gdpRows);
}

function renderCurrencies() {
  const headers = ["Pair", "Level", "1D", "1W", "YTD", "1Y trend"];
  const rows = [];
  (DATA.currencies || []).forEach((fx) => {
    const cells = [fx.name, fmtNum(fx.level, 4) + ctxTag(fx.context), fmtPct(fx.chg_1d_pct), fmtPct(fx.chg_1w_pct), fmtPct(fx.chg_ytd_pct)];
    chartableRows(`fx:${fx.id}`, fx.name, fx.history, cells, headers.length).forEach((r) => rows.push(r));
  });
  document.getElementById("panel-currencies").innerHTML =
    `<h2>Currencies</h2>` + note("Click a trend to open a chart.") + tableWithRaw(headers, rows);
}

function renderCommodities() {
  const headers = ["Commodity", "Contract", "Unit", "Level", "1D", "1W", "YTD", "1Y trend"];
  const rows = [];
  (DATA.commodities || []).forEach((cm) => {
    const cells = [
      cm.name,
      `<span class="ccy">${cm.exchange || ""} ${cm.contract || ""}</span>`,
      `<span class="ccy">${cm.unit || ""}</span>`,
      fmtNum(cm.level, 2) + ctxTag(cm.context), fmtPct(cm.chg_1d_pct), fmtPct(cm.chg_1w_pct), fmtPct(cm.chg_ytd_pct),
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
      hasAny ? "" : `<span class="stub">awaiting non-US valuation sourcing</span>`,
    ];
  });
  const covered = REGION_ORDER.filter((r) => ((DATA.valuation || {})[r] || {}).cape != null).length;

  const detailRows = REGION_ORDER.map((region) => {
    const v = (DATA.valuation || {})[region] || {};
    const e = (DATA.equity_risk_premia || {})[region] || {};
    return [
      regionName(region), v.name || "",
      v.forward_pe != null ? v.forward_pe.toFixed(1) : dash(),
      v.dividend_yield_pct != null ? `${v.dividend_yield_pct.toFixed(1)}%` : dash(),
      e.method ? `<span class="ccy">${e.method}</span>` : dash(),
      v.cape_as_of || e.as_of || dash(),
    ];
  });

  document.getElementById("panel-valuation").innerHTML =
    `<h2>Valuation Scorecard</h2>` +
    note(`CAPE and equity risk premium across regions, with each reading's percentile against its own history. <strong>${covered} of ${REGION_ORDER.length} regions have CAPE today</strong> — non-US coverage needs ETF fact-sheet parsing (SPEC.md Phase 4) and is not implemented, so the empty rows are a known sourcing gap, not a load failure.`) +
    table(["Region", "CAPE", "ERP", ""], scoreRows) +

    `<h2 class="mt">Valuation Detail</h2>` +
    note("Forward P/E and dividend yield are the fields awaiting non-US sourcing.") +
    table(["Region", "Index", "Fwd P/E", "Div Yield", "ERP method", "As of"], detailRows);
}

function populateRegionSelector() {
  const sel = document.getElementById("region-selector");
  sel.innerHTML = REGION_ORDER.map((r) => `<option value="${r}">${regionName(r)}</option>`).join("");
  sel.addEventListener("change", (e) => renderSnapshot(e.target.value));
}

function card(label, value, sub) {
  return `<div class="card"><div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
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
  const t = curve.tenors || {};

  const equityCards = indices.map((idx) =>
    card(idx.name, fmtNum(idx.level, 1), `${fmtPct(idx.chg_1d_pct)} 1D · ${fmtPct(idx.chg_ytd_pct)} YTD`)
  ).join("") || `<div class="card empty">No index tracked for this region.</div>`;

  const rateCards = [
    card("2Y", pctPlain(t["2Y"]), ""),
    card("10Y", pctPlain(t["10Y"]), `2s10s: ${curve["2s10s_bp"] != null ? curve["2s10s_bp"].toFixed(0) + " bp" : "—"}`),
    card("30Y", pctPlain(t["30Y"]), ""),
    real ? card("10Y real", pctPlain((real.tenors || {})["10Y"]), real.basis || "") : "",
  ].join("");

  const expTenors = exp.tenors || {};
  const expKey = Object.keys(expTenors)[0];
  const macroCards = [
    card("Policy rate", pctPlain(cb.rate_pct), cb.name || ""),
    card("CPI YoY", pctPlain(inf.yoy_pct, 1), `QoQ ann: ${inf.qoq_ann_pct != null ? inf.qoq_ann_pct.toFixed(1) + "%" : "—"}`),
    card("Real GDP YoY", pctPlain(gdp.yoy_pct, 1), gdp.qoq_ann_pct != null ? `QoQ ann: ${gdp.qoq_ann_pct.toFixed(1)}%` : "annual series"),
    expKey
      ? card("Implied inflation", pctPlain(expTenors[expKey]), `${expKey.replace("_", " ")} · ${exp.basis || ""}`)
      : card("Implied inflation", dash(), "no free market-implied source"),
  ].join("");

  const fxForRegion = { UK: "gbpusd", EZ: "eurusd", DE: "eurusd", CH: "eurchf", JP: "usdjpy", CN: "usdcny", NO: "eurnok", US: "dxy" }[region];
  const fx = (DATA.currencies || []).find((f) => f.id === fxForRegion);
  const fxCards = fx ? card(fx.name, fmtNum(fx.level, 4), `${fmtPct(fx.chg_1d_pct)} 1D · ${fmtPct(fx.chg_ytd_pct)} YTD`) : `<div class="card empty">—</div>`;

  const valCards = [
    card("CAPE", val.cape != null ? val.cape.toFixed(1) : dash(), val.name || ""),
    card("ERP", erp.erp_pct != null ? erp.erp_pct.toFixed(2) + "%" : dash(), erp.method || ""),
  ].join("");

  document.getElementById("snapshot-body").innerHTML =
    `<h3 class="snap-head">Equities</h3><div class="cards">${equityCards}</div>` +
    `<h3 class="snap-head">Rates &amp; Curve</h3><div class="cards">${rateCards}</div>` +
    `<h3 class="snap-head">Macro</h3><div class="cards">${macroCards}</div>` +
    `<h3 class="snap-head">Valuation</h3><div class="cards">${valCards}</div>` +
    `<h3 class="snap-head">FX</h3><div class="cards">${fxCards}</div>`;
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
