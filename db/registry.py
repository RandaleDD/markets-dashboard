"""
Every series the pipeline can actually fetch, as one flat list.

This is the bridge between `fetch/universe.py` (which says what the dashboard
tracks and how to fetch it) and `data/markets.db` (which stores it). It adds no
new source knowledge -- it walks universe.py and re-expresses it one row per
stored series, keyed by the identifier DATA-CATALOG.csv uses.

Two things it settles that universe.py's panel-shaped structures cannot:

  - **Granularity.** A yield-curve region in universe.py is one dict holding
    four tenors; here it is four series. One BIS CPI response carries both the
    YoY rate and the index level under different unit codes; here that is two
    series. The database stores series, not panels.
  - **Deduplication.** Six of the eight cross-asset correlation legs are series
    already stored for other panels. They resolve to the same `series_id` and
    are fetched and stored once, not twice.

`fetch_kwargs` are passed straight to the named function in `fetch/sources.py`.
`bounded` says whether that function honours `start=` (verified per source, see
its docstring) -- it drives whether the daily run makes a narrow request or
takes the whole small snapshot and lets ON CONFLICT discard the overlap.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fetch import universe

# A source that returns HTTP 200 and parses cleanly can still be years out of
# date. "ok" means "fresh enough for its publication cadence"; anything older
# is "stale". "policy" is deliberately loose (a rate sits unchanged for months,
# and BIS stops emitting observations between moves); "annual" allows for
# normal publication lag on yearly national accounts.
#
# `weekly` is the dashboard's own cadence, not a source's: the run happens on
# Saturday and stores each week's Friday close, so the freshest observation is
# at most 7 days old straight after a run. 14 days gives a week of slack, which
# means a single skipped Saturday run shows up as stale rather than passing.
#
# Lives here rather than in pipeline.py because it is now a per-series column
# in `series_catalog` -- the database, the staleness check and the JSON export
# all read the same numbers.
# `monthly_lagged` exists for ONS's monthly GDP specifically: it dates an
# observation to the FIRST of the month it describes and publishes ~6 weeks
# after that month ends, so the newest figure is permanently 72-105 days old
# even when the release is bang on time. Under the plain `monthly` threshold it
# would read stale forever, which is precisely the kind of permanently-red
# indicator that trains you to ignore the staleness check.
MAX_AGE_DAYS = {"weekly": 14, "monthly": 70, "monthly_lagged": 120,
                "quarterly": 200, "policy": 150, "annual": 730}

# Expected spacing between observations, for gap detection. "irregular" opts a
# series out: a policy rate genuinely has no cadence between decisions.
PERIODICITY_OF_CADENCE = {"weekly": "weekly", "monthly": "monthly",
                          "monthly_lagged": "monthly", "quarterly": "quarterly",
                          "annual": "annual", "policy": "irregular"}

# Sources that publish more often than the dashboard stores. Their fetched
# history is reduced to one observation per completed week -- the last actual
# close on or before each Friday -- before anything is inserted. See
# `db/ingest.to_weekly`.
DOWNSAMPLED_TO_WEEKLY = {"weekly", "policy"}


@dataclass(frozen=True)
class Series:
    series_id: str
    category: str
    region: str | None
    description: str
    unit: str
    cadence: str                      # key into MAX_AGE_DAYS
    source: str                       # human-readable institution
    fetcher: str                      # function name in fetch.sources
    fetch_kwargs: dict = field(default_factory=dict)
    bounded: bool = False             # honours start=
    revisable: bool = False           # gets real vintage_date handling
    native_periodicity: str | None = None
    # Bootstrap-only overrides, e.g. the BoE's deep archive zips.
    archive_kwargs: dict | None = None

    @property
    def max_age_days(self) -> int:
        return MAX_AGE_DAYS[self.cadence]

    @property
    def periodicity(self) -> str:
        return self.native_periodicity or PERIODICITY_OF_CADENCE[self.cadence]

    @property
    def store_weekly(self) -> bool:
        """True when the source publishes faster than the dashboard stores."""
        return self.cadence in DOWNSAMPLED_TO_WEEKLY


# Which fetcher each curve source uses, and whether it can be asked for a
# window. Mirrors pipeline.py's old _fetch_curve_tenor dispatcher, which the
# database path replaces.
_CURVE_SOURCES = {
    "fred":       ("fetch_fred", True),
    "bundesbank": ("fetch_bundesbank", False),   # accepts startPeriod, ignores it
    "ecb":        ("fetch_ecb", True),
    "boe_glc":    ("fetch_boe_glc", False),      # current-month workbook only
    "mof":        ("fetch_mof_jgb", False),      # one stitched file, no window
    "norges":     ("fetch_norges_curve", True),
}

_CURVE_SOURCE_NAMES = {
    "fred": "FRED", "bundesbank": "Deutsche Bundesbank", "ecb": "ECB Data Portal",
    "boe_glc": "Bank of England GLC", "mof": "Japan MOF", "norges": "Norges Bank",
}


def _curve_series(prefix: str, category: str, curves: dict, unit: str,
                  kind: str) -> list[Series]:
    out = []
    for region, cfg in curves.items():
        src = cfg["source"]
        if src not in _CURVE_SOURCES:
            continue  # chinabond / snb: no fetcher, so nothing to store
        fetcher, bounded = _CURVE_SOURCES[src]
        cadence = _cadence(cfg)
        for tenor, key in cfg["tenors"].items():
            if not key:
                continue  # no source for this tenor (CH 2/5/30y, NO 30y)
            kwargs = {"which": cfg.get("glc_file", "nominal"), "tenor_years": key} \
                if src == "boe_glc" else {_curve_arg(src): key}
            out.append(Series(
                series_id=f"{prefix}.{region}.{tenor}",
                category=category, region=region,
                description=f"{region} {kind}, {tenor}"
                            + (f" ({cfg['basis']})" if cfg.get("basis") else ""),
                unit=unit, cadence=cadence, source=_CURVE_SOURCE_NAMES[src],
                fetcher=fetcher, fetch_kwargs=kwargs, bounded=bounded,
                # The daily path reads the current-month workbook; bootstrap
                # reads the multi-decade archive zip instead.
                archive_kwargs={**kwargs, "archive": True} if src == "boe_glc" else None,
            ))
    return out


def _cadence(cfg: dict) -> str:
    """
    A curve's stored cadence. universe.py still describes each curve by how
    often its SOURCE publishes; anything published daily is stored weekly.
    """
    return "weekly" if cfg.get("cadence", "daily") == "daily" else cfg["cadence"]


def _curve_arg(src: str) -> str:
    return {"fred": "series_id", "bundesbank": "series_key", "ecb": "series_key",
            "mof": "tenor", "norges": "tenor"}[src]


def all_series() -> list[Series]:
    """Every series with a working fetcher today, in a stable order."""
    out: list[Series] = []

    # --- Prices: equities, volatility, FX, commodities, bond proxies -------
    for idx in universe.EQUITY_INDICES:
        if not idx.get("yahoo"):
            continue
        out.append(Series(
            series_id=f"equity.{idx['region']}.{idx['id']}", category="Equity index",
            region=idx["region"], description=f"{idx['name']} — daily close level",
            unit=f"index points ({idx['currency']})", cadence="weekly",
            source=f"Yahoo Finance, {idx['yahoo']}", fetcher="fetch_yahoo",
            fetch_kwargs={"ticker": idx["yahoo"]}, bounded=True))

    for v in universe.VOLATILITY_INDICES:
        if not v.get("yahoo"):
            continue  # VSTOXX has no free source; nothing to store
        out.append(Series(
            series_id=v["series_id"], category="Volatility index", region=v["region"],
            description=f"{v['name']} — volatility index", unit="index points",
            cadence="weekly", source=f"Yahoo Finance, {v['yahoo']}",
            fetcher="fetch_yahoo", fetch_kwargs={"ticker": v["yahoo"]}, bounded=True))

    for fx in universe.CURRENCIES:
        out.append(Series(
            series_id=f"fx.{fx['id']}", category="Currency", region=None,
            description=f"{fx['name']} — daily close",
            unit="exchange rate (level)", cadence="weekly",
            source=f"Yahoo Finance, {fx['yahoo']}", fetcher="fetch_yahoo",
            fetch_kwargs={"ticker": fx["yahoo"]}, bounded=True))

    for cm in universe.COMMODITIES:
        out.append(Series(
            series_id=f"commodity.{cm['id']}", category="Commodity", region="Global",
            description=f"{cm['name']} ({cm['exchange']}, {cm['contract']})",
            unit=cm["unit"], cadence="weekly",
            source=f"Yahoo Finance, {cm['yahoo']}", fetcher="fetch_yahoo",
            fetch_kwargs={"ticker": cm["yahoo"]}, bounded=True))

    # The only cross-asset legs that are not already stored for another panel.
    for leg in universe.CROSS_ASSET_SET:
        if not leg["series_id"].startswith("bond_proxy."):
            continue
        out.append(Series(
            series_id=leg["series_id"], category="Cross-asset proxy", region="Global",
            description=f"{leg['label']} total-return proxy — correlation heatmap bond leg",
            unit="index points (ETF price)", cadence="weekly",
            source=f"Yahoo Finance, {leg['yahoo']}", fetcher="fetch_yahoo",
            fetch_kwargs={"ticker": leg["yahoo"]}, bounded=True))

    # --- Policy rates -------------------------------------------------------
    for cb in universe.CENTRAL_BANKS:
        if cb.get("mirror_of"):
            continue  # Germany reads the EZ series at export; it is not a series
        out.append(Series(
            series_id=f"policy_rate.{cb['region']}", category="Policy rate",
            region=cb["region"], description=cb["name"], unit="%",
            # BIS emits a value every calendar day, repeating the standing rate
            # between decisions, so this is downsampled with everything else.
            # The cost is that a mid-week decision is dated to that week's
            # Friday rather than to the decision day itself.
            cadence="policy", source=f"BIS CBPOL, D.{cb['bis_ref_area']}",
            fetcher="fetch_bis_policy_rate",
            fetch_kwargs={"ref_area": cb["bis_ref_area"]}, bounded=True,
            native_periodicity="irregular"))

    # --- CPI: one response, two unit codes, therefore two series ------------
    from fetch.sources import CPI_UNIT_INDEX, CPI_UNIT_YOY
    for region, cfg in universe.INFLATION_CPI.items():
        out.append(Series(
            series_id=f"cpi.{region}", category="CPI", region=region,
            description=f"{region} headline CPI, year-on-year", unit="% YoY",
            cadence="monthly", source=f"BIS WS_LONG_CPI, M.{cfg['ref_area']}",
            fetcher="fetch_bis_cpi",
            fetch_kwargs={"ref_area": cfg["ref_area"], "unit": CPI_UNIT_YOY},
            bounded=True, revisable=True))
        # The index level, from the same response under unit_measure 628. The
        # annualised QoQ figure is derived from it, so it has to be stored.
        out.append(Series(
            series_id=f"cpi.{region}.index", category="CPI", region=region,
            description=f"{region} headline CPI, index level "
                        f"(same BIS response as cpi.{region}, unit_measure 628)",
            unit="index level", cadence="monthly",
            source=f"BIS WS_LONG_CPI, M.{cfg['ref_area']}", fetcher="fetch_bis_cpi",
            fetch_kwargs={"ref_area": cfg["ref_area"], "unit": CPI_UNIT_INDEX},
            bounded=True, revisable=True))

    # --- GDP levels ---------------------------------------------------------
    for region, cfg in universe.GDP_GROWTH.items():
        cadence = cfg.get("cadence", "annual" if cfg.get("freq") == "A" else "quarterly")
        if cfg["source"] == "ons":
            fetcher, kwargs, bounded = "fetch_ons_timeseries", {
                "series_code": cfg["ons_series"], "dataset": cfg["ons_dataset"]}, False
            source = f"ONS, {cfg['ons_dataset'].upper()}/{cfg['ons_series'].upper()}"
        elif cfg["source"] == "eurostat":
            fetcher, kwargs, bounded = "fetch_eurostat", {
                "dataset": cfg["eurostat_dataset"],
                "filters": cfg["eurostat_filters"]}, True
            source = f"Eurostat, {cfg['eurostat_dataset']}"
        else:
            fetcher, kwargs, bounded = "fetch_fred", {"series_id": cfg["series"]}, True
            source = f"FRED, {cfg['series']}"
        out.append(Series(
            series_id=f"gdp.{region}", category="GDP growth", region=region,
            description=cfg.get("definition")
                        or f"{region} real GDP, chain-linked volume, seasonally "
                           f"adjusted (level; YoY/QoQ derived downstream)",
            unit="index/level (national currency, chain-linked)", cadence=cadence,
            source=source, fetcher=fetcher, fetch_kwargs=kwargs, bounded=bounded,
            revisable=True))

    # --- Yield curves, nominal and real -------------------------------------
    out += _curve_series("curve", "Yield curve (nominal)", universe.YIELD_CURVES,
                         "%", "govt yield")
    out += _curve_series("real_yield", "Yield curve (real)", universe.REAL_YIELD_CURVES,
                         "%", "real yield")

    # --- Inflation expectations ---------------------------------------------
    for region, cfg in universe.INFLATION_EXPECTATIONS.items():
        if cfg.get("kind") == "unavailable" or not cfg.get("source"):
            continue
        for block, sub in (("market", cfg), ("model", cfg.get("model"))):
            if not sub:
                continue
            # US distinguishes market from model in its identifier; the UK has
            # only a market curve, and its catalog id carries no block segment.
            infix = f".{block}" if region == "US" else ""
            for label, key in sub["tenors"].items():
                if sub["source"] == "fred":
                    fetcher, kwargs, bounded = "fetch_fred", {"series_id": key}, True
                    source, cadence = f"FRED, {key}", ("weekly" if block == "market" else "monthly")
                else:
                    fetcher = "fetch_boe_glc"
                    kwargs = {"which": cfg.get("glc_file", "inflation"), "tenor_years": key}
                    bounded, source, cadence = False, "Bank of England GLC", "weekly"
                out.append(Series(
                    series_id=f"inflexp.{region}{infix}.{label}",
                    category=f"Inflation expectations ({block})", region=region,
                    description=f"{region} {block}-implied inflation, {label}, "
                                f"{sub.get('basis') or cfg.get('basis')} basis",
                    unit="%", cadence=cadence, source=source, fetcher=fetcher,
                    fetch_kwargs=kwargs, bounded=bounded,
                    archive_kwargs=({**kwargs, "archive": True}
                                    if fetcher == "fetch_boe_glc" else None)))

    # --- Euro-area sovereign spreads ----------------------------------------
    #
    # Stored as the underlying YIELDS, not as spreads. The catalog's "bp" unit
    # describes the derived figure the dashboard shows; the spread itself is
    # computed at export from both legs of this same ECB series family, which
    # is what keeps the two legs on one source and one vintage (see CLAUDE.md).
    bench = universe.EUROZONE_SPREAD_BENCHMARK
    out.append(Series(
        series_id="spread_benchmark.DE", category="Eurozone spread (benchmark leg)",
        region="DE", description=f"{bench['country']} long-term government bond "
                                 f"yield, ECB convergence series (benchmark leg)",
        unit="%", cadence="monthly", source=f"ECB Data Portal, {bench['ecb_key']}",
        fetcher="fetch_ecb", fetch_kwargs={"series_key": bench["ecb_key"]}, bounded=True))
    for entry in universe.EUROZONE_SPREAD_PANEL:
        code = entry["ecb_key"].split(".")[1]
        out.append(Series(
            series_id=f"spread.{code}", category="Eurozone spread", region="EZ",
            description=f"{entry['country']} long-term government bond yield, ECB "
                        f"convergence series (spread vs. spread_benchmark.DE "
                        f"derived at export)",
            unit="%", cadence="monthly", source=f"ECB Data Portal, {entry['ecb_key']}",
            fetcher="fetch_ecb", fetch_kwargs={"series_key": entry["ecb_key"]},
            bounded=True))

    # --- Valuation and equity risk premium ----------------------------------
    out.append(Series(
        series_id="valuation.US.cape", category="Valuation", region="US",
        description="US CAPE / Shiller P/E, S&P 500", unit="ratio (x)",
        cadence="monthly", source="Shiller/Yale, ie_data.xls",
        fetcher="fetch_shiller_cape", bounded=False))
    out.append(Series(
        series_id="erp.US", category="Equity risk premium", region="US",
        description="US implied ERP (FCFE basis), S&P 500", unit="%",
        cadence="annual", source="Damodaran/NYU Stern, histimpl.xls",
        fetcher="fetch_damodaran_erp", bounded=False))

    # --- Credit spreads and liquidity ---------------------------------------
    for cs in universe.CREDIT_SPREADS:
        out.append(Series(
            series_id=cs["series_id"], category="Credit spread", region=cs["region"],
            description=f"{cs['name']} (ICE BofA option-adjusted spread)",
            unit="%", cadence="weekly", source=f"FRED, {cs['series']}",
            fetcher="fetch_fred", fetch_kwargs={"series_id": cs["series"]}, bounded=True))

    for li in universe.LIQUIDITY_INDICATORS:
        out.append(Series(
            series_id=li["series_id"], category="Liquidity cycle", region=li["region"],
            description=li["name"], unit=li["unit"],
            cadence=li.get("cadence", "quarterly"), source=f"FRED, {li['series']}",
            fetcher="fetch_fred", fetch_kwargs={"series_id": li["series"]},
            bounded=True, revisable=True))

    _assert_unique(out)
    return out


def _assert_unique(series: list[Series]) -> None:
    seen = set()
    for s in series:
        if s.series_id in seen:
            raise ValueError(f"duplicate series_id in registry: {s.series_id}")
        seen.add(s.series_id)


def by_id() -> dict[str, Series]:
    return {s.series_id: s for s in all_series()}


# Series whose values genuinely get revised after first release, and therefore
# need a real vintage_date. Everything else writes vintage_date = date, so the
# mechanism is present but inert -- see DATABASE-PLAN.md "Revisions".
def revisable_ids() -> set[str]:
    return {s.series_id for s in all_series() if s.revisable}
