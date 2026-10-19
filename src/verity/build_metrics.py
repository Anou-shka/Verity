"""Build the clean metrics tables for the whole universe.

    python -m verity.build_metrics

Writes to data/processed/:
  metrics_long.csv   one row per company x metric x fiscal year, with its source
  derived.csv        ratios computed from those metrics, with formula and inputs
  valuation.csv      market cap, EV and multiples on the valuation date
  restatements.csv   periods whose value changed between filings
  metrics_wide.csv   the readable version (USD millions, ratios in %)
"""
from __future__ import annotations

import json

import pandas as pd
import yaml

from .config import CONFIG_DIR, DATA_DIR
from .derived import derive_year, load_settings, valuation
from .sec import SecClient
from .xbrl import CompanyFacts, standard_metrics

OUT = DATA_DIR / "processed"
FIRST_YEAR = 2021
SUPPORTING = {"cost_of_revenue", "pretax_income", "income_tax"}


def universe() -> list[str]:
    return yaml.safe_load((CONFIG_DIR / "universe.yaml").read_text())["tickers"]


def build(tickers: list[str] | None = None) -> dict[str, pd.DataFrame]:
    tickers = tickers or universe()
    client, settings = SecClient(), load_settings()
    rows, drows, vrows, rrows = [], [], [], []
    for t in tickers:
        cf = CompanyFacts.load(t, client)
        years = [y for y in cf.years() if y >= FIRST_YEAR and cf.metric("revenue", y).value is not None]
        for fy in years:
            for metric in standard_metrics(cf.cmap):
                mv = cf.metric(metric, fy)
                rows.append({
                    "ticker": t, "fiscal_year": fy, "metric": metric, "value": mv.value,
                    "unit": mv.unit, "method": mv.method, "concept": mv.concept,
                    "period": mv.period, "accession": mv.accession,
                    "filed": max((f.filed for f in mv.facts), default=""),
                    "supporting": metric in SUPPORTING, "note": mv.note,
                })
            for d in derive_year(cf, fy, settings):
                drows.append({"ticker": t, "fiscal_year": fy, "metric": d.metric, "value": d.value,
                              "unit": d.unit, "formula": d.formula,
                              "inputs": json.dumps(d.inputs), "note": d.note})
        v = valuation(cf, settings)
        vrows.append({"ticker": t, "fiscal_year": v.fiscal_year, **v.values,
                      "price_date": v.price.date, "shares_accession": v.shares.accession,
                      "shares_as_of": v.shares.end, "notes": "; ".join(v.notes)})
        for r in cf.restatements:
            if r.fiscal_year >= FIRST_YEAR:
                rrows.append({"ticker": t, **r.__dict__})

    long = pd.DataFrame(rows)
    derived = pd.DataFrame(drows)
    val = pd.DataFrame(vrows)
    rest = pd.DataFrame(rrows).drop_duplicates() if rrows else pd.DataFrame()
    return {"metrics_long": long, "derived": derived, "valuation": val,
            "restatements": rest, "metrics_wide": wide_table(long, derived)}


def wide_table(long: pd.DataFrame, derived: pd.DataFrame) -> pd.DataFrame:
    """Readable table: USD in millions, ratios in %, EPS in USD."""
    a = long[~long.supporting][["ticker", "fiscal_year", "metric", "value", "unit"]]
    b = derived[["ticker", "fiscal_year", "metric", "value", "unit"]]
    df = pd.concat([a, b])
    scale = df.unit.map({"USD": 1e-6, "shares": 1e-6, "ratio": 100}).fillna(1)
    df = df.assign(value=(df.value * scale).round(2))
    order = list(dict.fromkeys(df.metric))
    wide = df.set_index(["ticker", "fiscal_year", "metric"]).value.unstack("metric")
    return wide[order].reset_index()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tables = build()
    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"{name:14s} {len(df):5d} rows -> {OUT / name}.csv")
    long = tables["metrics_long"]
    core = long[~long.supporting]
    missing = core[core.value.isna()]
    print(f"\n{len(core)} core values, {len(missing)} not reported:")
    if len(missing):
        print(missing[["ticker", "fiscal_year", "metric"]].to_string(index=False))


if __name__ == "__main__":
    main()
