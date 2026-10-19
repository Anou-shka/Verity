"""Derived metrics, all computed in Python from the XBRL metrics table.

Each derived value carries its formula and the inputs it used, so it can be
traced back to the underlying facts. No LLM is involved in any of this.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import yaml

from .config import CONFIG_DIR
from .prices import Price, get_price
from .xbrl import CompanyFacts, Fact, MetricValue


def load_settings() -> dict:
    return yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text())


@dataclass
class Derived:
    ticker: str
    metric: str
    fiscal_year: int
    value: float | None
    unit: str            # ratio, USD, x
    formula: str
    inputs: dict[str, float | None] = field(default_factory=dict)
    note: str = ""


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


def _avg(a, b):
    """Average of opening and closing balance; closing alone if no opening."""
    if a is None:
        return None
    return a if b is None else (a + b) / 2


def split_factor(ticker: str, filed: str, settings: dict) -> float:
    """How many post-split shares one share filed on `filed` has become."""
    factor = 1.0
    for s in settings.get("splits", {}).get(ticker, []):
        if str(filed) < str(s["date"]):
            factor *= s["ratio"]
    return factor


def derive_year(cf: CompanyFacts, fy: int, settings: dict) -> list[Derived]:
    m = {k: cf.metric(k, fy).value for k in
         ("revenue", "gross_profit", "operating_income", "d_and_a", "net_income",
          "total_equity", "total_debt", "cash", "pretax_income", "income_tax")}
    prev = {k: cf.metric(k, fy - 1).value for k in ("revenue", "total_equity", "total_debt", "cash")}
    t = cf.ticker
    out = []

    def add(metric, value, unit, formula, inputs, note=""):
        out.append(Derived(t, metric, fy, value, unit, formula, inputs, note))

    add("gross_margin", _div(m["gross_profit"], m["revenue"]), "ratio",
        "gross_profit / revenue", {"gross_profit": m["gross_profit"], "revenue": m["revenue"]})
    add("ebit_margin", _div(m["operating_income"], m["revenue"]), "ratio",
        "operating_income / revenue", {"operating_income": m["operating_income"], "revenue": m["revenue"]})
    ebitda = None if None in (m["operating_income"], m["d_and_a"]) else m["operating_income"] + m["d_and_a"]
    add("ebitda", ebitda, "USD", "operating_income + d_and_a",
        {"operating_income": m["operating_income"], "d_and_a": m["d_and_a"]})
    growth = _div(m["revenue"], prev["revenue"])
    add("revenue_growth", None if growth is None else growth - 1, "ratio",
        "revenue / revenue_prior_year - 1", {"revenue": m["revenue"], "revenue_prior_year": prev["revenue"]})
    net_debt = None if None in (m["total_debt"], m["cash"]) else m["total_debt"] - m["cash"]
    add("net_debt", net_debt, "USD", "total_debt - cash", {"total_debt": m["total_debt"], "cash": m["cash"]})

    avg_eq = _avg(m["total_equity"], prev["total_equity"])
    add("roe", _div(m["net_income"], avg_eq), "ratio",
        "net_income / average(total_equity, total_equity_prior_year)",
        {"net_income": m["net_income"], "total_equity": m["total_equity"],
         "total_equity_prior_year": prev["total_equity"]},
        "" if prev["total_equity"] is not None else "closing equity only (no prior year)")

    # ROIC = EBIT x (1 - tax rate) / average invested capital (equity + debt - cash)
    rate, rate_note = _div(m["income_tax"], m["pretax_income"]), ""
    if rate is None or not 0 <= rate <= 0.5:
        rate, rate_note = settings["fallback_tax_rate"], "statutory tax rate used (effective rate not meaningful)"
    ic = _invested_capital(m["total_equity"], m["total_debt"], m["cash"])
    ic_prev = _invested_capital(prev["total_equity"], prev["total_debt"], prev["cash"])
    nopat = None if m["operating_income"] is None else m["operating_income"] * (1 - rate)
    add("roic", _div(nopat, _avg(ic, ic_prev)), "ratio",
        "operating_income * (1 - tax_rate) / average(equity + debt - cash)",
        {"operating_income": m["operating_income"], "tax_rate": rate,
         "invested_capital": ic, "invested_capital_prior_year": ic_prev}, rate_note)
    return out


def _invested_capital(equity, debt, cash):
    return None if None in (equity, debt, cash) else equity + debt - cash


@dataclass
class Valuation:
    ticker: str
    fiscal_year: int              # latest fiscal year (LFY) used for the multiples
    price: Price
    shares: Fact
    values: dict[str, float | None]
    formulas: dict[str, str]
    notes: list[str] = field(default_factory=list)


def valuation(cf: CompanyFacts, settings: dict, on: date | str | None = None) -> Valuation:
    """Market cap, EV and multiples on the valuation date, on LFY financials."""
    on = on or settings["valuation_date"]
    fy = max(y for y in cf.years() if cf.metric("revenue", y).value is not None)
    price = get_price(cf.ticker, on)
    shares = cf.shares_outstanding()
    notes = []

    eps = cf.metric("eps_diluted", fy)
    eps_adj = None
    if eps.value is not None:
        factor = split_factor(cf.ticker, eps.facts[0].filed, settings)
        eps_adj = eps.value / factor
        if factor != 1:
            notes.append(f"FY{fy} diluted EPS {eps.value:.2f} divided by {factor:g} for a later stock split")
    share_factor = split_factor(cf.ticker, shares.filed, settings)
    if share_factor != 1:
        notes.append(f"cover-page shares multiplied by {share_factor:g} for a later stock split")

    revenue = cf.metric("revenue", fy).value
    derived = {d.metric: d.value for d in derive_year(cf, fy, settings)}
    market_cap = price.close * shares.value * share_factor
    ev = None if derived["net_debt"] is None else market_cap + derived["net_debt"]
    values = {
        "price": price.close,
        "shares_outstanding": shares.value * share_factor,
        "market_cap": market_cap,
        "net_debt": derived["net_debt"],
        "ev": ev,
        "revenue": revenue,
        "ebitda": derived["ebitda"],
        "eps_diluted": eps_adj,
        "ev_ebitda": _div(ev, derived["ebitda"]),
        "ev_sales": _div(ev, revenue),
        "pe": _div(price.close, eps_adj),
    }
    formulas = {
        "market_cap": "price * shares_outstanding",
        "ev": "market_cap + net_debt (LFY balance sheet; minorities and leases ignored)",
        "ev_ebitda": "ev / ebitda (LFY)",
        "ev_sales": "ev / revenue (LFY)",
        "pe": "price / eps_diluted (LFY, split-adjusted)",
    }
    return Valuation(cf.ticker, fy, price, shares, values, formulas, notes)
