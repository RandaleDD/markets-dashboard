const REGION_ORDER = ["US", "UK", "EZ", "DE", "CH", "CN", "JP"];

async function main() {
  const res = await fetch("data/latest.json", { cache: "no-store" });
  const data = await res.json();
  window.__data = data;

  document.getElementById("as-of").textContent = data.generated_at
    ? new Date(data.generated_at).toLocaleString()
    : "unknown";

  if (data.is_sample) {
    const banner = document.getElementById("sample-banner");
    banner.hidden = false;
    banner.textContent = "Showing sample data — the live pipeline hasn't populated this yet. See NETWORK.md / SPEC.md.";
  }

  renderEquityIndices(data);
  renderYieldCurves(data);
  renderCentralBankRates(data);
  renderInflation(data);
  renderRealYields(data);
  renderErp(data);
  renderGdp(data);
  renderCurrencies(data);
  renderCommodities(data);
  renderValuation(data);
  populateRegionSelector(data);
  renderRegionalSnapshot(data, REGION_ORDER[0]);

  setupTabs();
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------
function fmtPct(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '<span class="stub">—</span>';
  const cls = v > 0 ? "up" : v < 0 ? "down" : "";
  const sign = v > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${v.toFixed(2)}%</span>`;
}
function fmtBp(v) {
  if (v === null || v === undefined) return '<span class="stub">—</span>';
  return `${v.toFixed(0)} bp`;
}
function fmtNum(v, digits = 2) {
  if (v === null || v === undefined) return '<span class="stub">—</span>';
  return v.toFixed(digits);
}
function stubCell() {
  return '<span class="stub">not yet wired</span>';
}
function sparkline(history) {
  if (!history || history.length < 2) return "";
  const values = history.map((d) => d[1]);
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const w = 100, h = 28;
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  const stroke = up ? "var(--delta-up)" : "var(--delta-down)";
  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${points}" fill="none" stroke="${stroke}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}
function table(headers, rows) {
  const thead = `<tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr>`;
  const tbody = rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`;
}
function regionName(data, code) {
  return (data.region_names && data.region_names[code]) || code;
}

// ---------------------------------------------------------------------------
// section renderers
// ---------------------------------------------------------------------------
function renderEquityIndices(data) {
  const rows = [];
  REGION_ORDER.concat(["EM"]).forEach((region) => {
    const indices = data.equity_indices?.[region] || [];
    indices.forEach((idx) => {
      rows.push([
        `${idx.name} <span class="stub">(${regionName(data, region)}, ${idx.currency})</span>`,
        fmtNum(idx.level, idx.level > 100 ? 1 : 4),
        fmtPct(idx.chg_1d_pct),
        fmtPct(idx.chg_1w_pct),
        fmtPct(idx.chg_mtd_pct),
        fmtPct(idx.chg_ytd_pct),
        fmtPct(idx.chg_1y_pct),
        fmtPct(idx.drawdown_from_ath_pct),
        idx.realized_vol_20d_pct != null ? `${idx.realized_vol_20d_pct.toFixed(1)}%` : stubCell(),
        sparkline(idx.history_1y),
      ]);
    });
  });
  document.getElementById("panel-equities").innerHTML =
    `<h2>Equity Indices</h2><p class="section-note">Levels in local currency. 1Y sparkline.</p>` +
    table(["Index", "Level", "1D", "1W", "MTD", "YTD", "1Y", "DD from ATH", "Vol (20d)", "1Y trend"], rows);
}

function renderYieldCurves(data) {
  const rows = REGION_ORDER.map((region) => {
    const c = data.yield_curves?.[region] || {};
    const t = c.tenors || {};
    return [
      regionName(data, region),
      t["2Y"] != null ? `${t["2Y"].toFixed(2)}%` : stubCell(),
      t["5Y"] != null ? `${t["5Y"].toFixed(2)}%` : stubCell(),
      t["10Y"] != null ? `${t["10Y"].toFixed(2)}%` : stubCell(),
      t["30Y"] != null ? `${t["30Y"].toFixed(2)}%` : stubCell(),
      c["2s10s_bp"] != null ? fmtBp(c["2s10s_bp"]) : stubCell(),
    ];
  });
  const spreadRows = (data.eurozone_spread_panel || []).map((s) => [
    s.country,
    s.spread_vs_bund_bp != null ? fmtBp(s.spread_vs_bund_bp) : stubCell(),
    `<span class="stub">${s.institution}</span>`,
  ]);
  document.getElementById("panel-yields").innerHTML =
    `<h2>Government Yield Curves</h2><p class="section-note">Germany (Bund) is the Eurozone benchmark curve.</p>` +
    table(["Region", "2Y", "5Y", "10Y", "30Y", "2s10s"], rows) +
    `<h2 style="margin-top:24px">Eurozone Periphery Spread vs. Bund</h2>` +
    table(["Country", "Spread", "Source"], spreadRows);
}

function renderCentralBankRates(data) {
  const rows = REGION_ORDER.map((region) => {
    const cb = data.central_bank_rates?.[region] || {};
    return [regionName(data, region), cb.name || "", cb.rate_pct != null ? `${cb.rate_pct.toFixed(2)}%` : stubCell()];
  });
  document.getElementById("panel-cbrates").innerHTML =
    `<h2>Central Bank Policy Rates</h2><p class="section-note">Source: BIS Data Portal (CBPOL).</p>` +
    table(["Region", "Central Bank", "Policy Rate"], rows);
}

function renderInflation(data) {
  const rows = REGION_ORDER.map((region) => {
    const inf = data.inflation?.[region] || {};
    const be = data.breakeven_inflation?.[region] || {};
    return [
      regionName(data, region),
      inf.headline_cpi_yoy_pct != null ? `${inf.headline_cpi_yoy_pct.toFixed(1)}%` : stubCell(),
      be["10y"] != null ? `${be["10y"].toFixed(2)}%` : be.note ? `<span class="stub">${be.note}</span>` : stubCell(),
    ];
  });
  document.getElementById("panel-inflation").innerHTML =
    `<h2>Inflation</h2><p class="section-note">Headline CPI YoY, and 10y breakeven inflation where sourced.</p>` +
    table(["Region", "Headline CPI YoY", "10y Breakeven"], rows);
}

function renderRealYields(data) {
  const rows = REGION_ORDER.map((region) => {
    const ry = data.real_yields?.[region] || {};
    return [regionName(data, region), ry["10y_pct"] != null ? `${ry["10y_pct"].toFixed(2)}%` : ry.note ? `<span class="stub">${ry.note}</span>` : stubCell()];
  });
  document.getElementById("panel-realyields").innerHTML =
    `<h2>Real Yields</h2><p class="section-note">10y real yield. Longer lookback than other panels — real yields are judged against decades of history.</p>` +
    table(["Region", "10y Real Yield"], rows);
}

function renderErp(data) {
  const rows = REGION_ORDER.map((region) => {
    const erp = data.equity_risk_premia?.[region]?.erp_pct;
    return [regionName(data, region), erp != null ? `${erp.toFixed(2)}%` : stubCell()];
  });
  document.getElementById("panel-erp").innerHTML =
    `<h2>Equity Risk Premia</h2><p class="section-note">Forward earnings yield minus 10y govt yield, per region.</p>` +
    table(["Region", "ERP"], rows);
}

function renderGdp(data) {
  const rows = REGION_ORDER.map((region) => {
    const g = data.gdp_growth?.[region] || {};
    return [regionName(data, region), g.latest_pct != null ? `${g.latest_pct.toFixed(1)}%` : stubCell()];
  });
  document.getElementById("panel-gdp").innerHTML =
    `<h2>GDP Growth</h2><p class="section-note">Real GDP, year-on-year, same definition for every region.</p>` +
    table(["Region", "Latest growth"], rows);
}

function renderCurrencies(data) {
  const rows = (data.currencies || []).map((fx) => [
    fx.name,
    fmtNum(fx.level, 4),
    fmtPct(fx.chg_1d_pct),
    fmtPct(fx.chg_1w_pct),
    fmtPct(fx.chg_ytd_pct),
    sparkline(fx.history_1y),
  ]);
  document.getElementById("panel-currencies").innerHTML =
    `<h2>Currencies</h2>` + table(["Pair", "Level", "1D", "1W", "YTD", "1Y trend"], rows);
}

function renderCommodities(data) {
  const rows = (data.commodities || []).map((cm) => [
    cm.name,
    fmtNum(cm.level, 2),
    fmtPct(cm.chg_1d_pct),
    fmtPct(cm.chg_1w_pct),
    fmtPct(cm.chg_ytd_pct),
    sparkline(cm.history_1y),
  ]);
  document.getElementById("panel-commodities").innerHTML =
    `<h2>Commodities</h2><p class="section-note">Oil = Brent only.</p>` +
    table(["Commodity", "Level", "1D", "1W", "YTD", "1Y trend"], rows);
}

function renderValuation(data) {
  const rows = REGION_ORDER.map((region) => {
    const v = data.valuation?.[region] || {};
    return [
      regionName(data, region),
      v.name || "",
      v.forward_pe != null ? v.forward_pe.toFixed(1) : stubCell(),
      v.cape != null ? v.cape.toFixed(1) : stubCell(),
      v.dividend_yield_pct != null ? `${v.dividend_yield_pct.toFixed(1)}%` : stubCell(),
    ];
  });
  document.getElementById("panel-valuation").innerHTML =
    `<h2>Equity Valuation Metrics</h2><p class="section-note">Non-US data is realistically monthly-lag (ETF/index fact sheets) — see SPEC.md.</p>` +
    table(["Region", "Index", "Fwd P/E", "CAPE", "Div Yield"], rows);
}

function populateRegionSelector(data) {
  const sel = document.getElementById("region-selector");
  sel.innerHTML = REGION_ORDER.map((r) => `<option value="${r}">${regionName(data, r)}</option>`).join("");
  sel.addEventListener("change", (e) => renderRegionalSnapshot(data, e.target.value));
}

function renderRegionalSnapshot(data, region) {
  const indices = data.equity_indices?.[region] || [];
  const curve = data.yield_curves?.[region] || {};
  const cb = data.central_bank_rates?.[region] || {};
  const inf = data.inflation?.[region] || {};
  const gdp = data.gdp_growth?.[region] || {};

  const cards = [];
  indices.forEach((idx) => {
    cards.push(`<div class="card"><div class="label">${idx.name}</div>
      <div class="value">${fmtNum(idx.level, 1)}</div>
      <div class="sub">${fmtPct(idx.chg_1d_pct)} 1D · ${fmtPct(idx.chg_ytd_pct)} YTD</div></div>`);
  });
  const t = curve.tenors || {};
  cards.push(`<div class="card"><div class="label">10y Govt Yield</div>
    <div class="value">${t["10Y"] != null ? t["10Y"].toFixed(2) + "%" : "—"}</div>
    <div class="sub">2s10s: ${curve["2s10s_bp"] != null ? fmtBp(curve["2s10s_bp"]) : "—"}</div></div>`);
  cards.push(`<div class="card"><div class="label">Policy Rate</div>
    <div class="value">${cb.rate_pct != null ? cb.rate_pct.toFixed(2) + "%" : "—"}</div>
    <div class="sub">${cb.name || ""}</div></div>`);
  cards.push(`<div class="card"><div class="label">CPI YoY</div>
    <div class="value">${inf.headline_cpi_yoy_pct != null ? inf.headline_cpi_yoy_pct.toFixed(1) + "%" : "—"}</div></div>`);
  cards.push(`<div class="card"><div class="label">GDP Growth</div>
    <div class="value">${gdp.latest_pct != null ? gdp.latest_pct.toFixed(1) + "%" : "—"}</div></div>`);

  const fxForRegion = { UK: "gbpusd", EZ: "eurusd", CH: "eurchf", JP: "usdjpy", CN: "usdcny" }[region];
  if (fxForRegion) {
    const fx = (window.__data.currencies || []).find((f) => f.id === fxForRegion);
    if (fx) {
      cards.push(`<div class="card"><div class="label">${fx.name}</div>
        <div class="value">${fmtNum(fx.level, 4)}</div>
        <div class="sub">${fmtPct(fx.chg_1d_pct)} 1D</div></div>`);
    }
  }

  document.getElementById("snapshot-cards").innerHTML = cards.join("");
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
