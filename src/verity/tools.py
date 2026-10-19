"""The tools agents call. Plain Python functions plus JSON schemas.

Every value a tool returns is registered in a Ledger and gets a source id
("S7"). The Writer must cite that id next to each number, and the
fact-checker uses it to know what the number claims to be.
"""
from __future__ import annotations

import ast
import operator
import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date

import yaml

from .config import CONFIG_DIR
from .derived import derive_year, load_settings, valuation
from .fmt import display
from .prices import get_price as _get_price
from .sec import SecClient
from .xbrl import CompanyFacts, load_concept_map

DERIVED_METRICS = {"gross_margin": "ratio", "ebit_margin": "ratio", "ebitda": "USD",
                   "revenue_growth": "ratio", "net_debt": "USD", "roe": "ratio", "roic": "ratio"}
VALUATION_METRICS = {"price": "USD/shares", "shares_outstanding": "shares", "market_cap": "USD",
                     "ev": "USD", "ev_ebitda": "x", "ev_sales": "x", "pe": "x"}
LABELS = {
    "revenue": "revenue", "gross_profit": "gross profit", "operating_income": "operating income (EBIT)",
    "net_income": "net income", "d_and_a": "D&A", "eps_diluted": "diluted EPS",
    "shares_diluted": "diluted shares", "total_assets": "total assets", "total_equity": "total equity",
    "cash": "cash", "total_debt": "total debt", "operating_cash_flow": "operating cash flow",
    "capex": "capex", "gross_margin": "gross margin", "ebit_margin": "EBIT margin", "ebitda": "EBITDA",
    "revenue_growth": "revenue growth", "net_debt": "net debt", "roe": "ROE", "roic": "ROIC",
    "price": "share price", "shares_outstanding": "shares outstanding", "market_cap": "market cap",
    "ev": "enterprise value", "ev_ebitda": "EV/EBITDA", "ev_sales": "EV/Sales", "pe": "P/E",
}
SECTIONS = {"business": "1", "risk_factors": "1a", "mdna": "7"}   # section -> 10-K item number


def universe() -> dict:
    return yaml.safe_load((CONFIG_DIR / "universe.yaml").read_text())


@dataclass
class Source:
    """One value an agent was given, and where it came from."""
    id: str
    kind: str                 # xbrl | derived | valuation | price | computed | filing
    ticker: str | None
    metric: str | None
    fiscal_year: int | None
    value: float | None
    unit: str | None
    display: str
    label: str
    detail: dict = field(default_factory=dict)

    def brief(self) -> str:
        """One line a model can read: id, what, value, provenance."""
        where = self.detail.get("accession") or self.detail.get("formula") or self.detail.get("as_of", "")
        fy = f" FY{self.fiscal_year}" if self.fiscal_year else ""
        return f"{self.id}: {self.ticker or ''}{fy} {self.label} = {self.display} ({self.kind}; {where})"


class Ledger:
    def __init__(self):
        self.sources: dict[str, Source] = {}
        self._keys: dict[tuple, str] = {}

    def add(self, kind, ticker, metric, fiscal_year, value, unit, label, **detail) -> Source:
        key = (kind, ticker, metric, fiscal_year, detail.get("formula"), detail.get("as_of"),
               detail.get("section"))
        if key in self._keys:
            return self.sources[self._keys[key]]
        sid = f"S{len(self.sources) + 1}"
        src = Source(sid, kind, ticker, metric, fiscal_year, value, unit,
                     display(value, unit) if unit else "", label, detail)
        self.sources[sid] = src
        self._keys[key] = sid
        return src

    def get(self, sid: str) -> Source | None:
        return self.sources.get(sid)

    def to_json(self) -> list[dict]:
        return [asdict(s) for s in self.sources.values()]


class ToolError(Exception):
    pass


class ToolBox:
    """Tools bound to one ledger. Company data is loaded once and reused."""

    def __init__(self, ledger: Ledger | None = None, client: SecClient | None = None):
        self.ledger = ledger or Ledger()
        self.client = client or SecClient()
        self.settings = load_settings()
        self.names = universe()["names"]
        self._cf: dict[str, CompanyFacts] = {}
        self._cmap = load_concept_map()

    def company(self, ticker: str) -> CompanyFacts:
        t = ticker.upper()
        if t not in self._cf:
            try:
                self._cf[t] = CompanyFacts(t, self.client.company_facts(t), self._cmap)
            except KeyError:
                raise ToolError(f"unknown ticker {ticker}")
        return self._cf[t]

    # -- tools -------------------------------------------------------------
    def list_fiscal_years(self, ticker: str) -> dict:
        cf = self.company(ticker)
        years = [y for y in cf.years() if y >= 2019 and cf.metric("revenue", y).value is not None]
        return {"ticker": cf.ticker, "company": self.names.get(cf.ticker, cf.ticker),
                "fiscal_years": years, "latest": max(years)}

    def get_metric(self, ticker: str, metric: str, fiscal_year: int) -> dict:
        cf, fy = self.company(ticker), int(fiscal_year)
        if metric in self._cmap["metrics"]:
            mv = cf.metric(metric, fy)
            if mv.value is None:
                raise ToolError(f"{cf.ticker} does not report {metric} for FY{fy}")
            src = self.ledger.add(
                "xbrl", cf.ticker, metric, fy, mv.value, mv.unit, LABELS.get(metric, metric),
                concept=mv.method, period=mv.period, accession=mv.accession,
                filed=max(f.filed for f in mv.facts) if mv.facts else "", note=mv.note)
        elif metric in DERIVED_METRICS:
            d = next(d for d in derive_year(cf, fy, self.settings) if d.metric == metric)
            if d.value is None:
                raise ToolError(f"cannot compute {metric} for {cf.ticker} FY{fy} (missing inputs)")
            src = self.ledger.add("derived", cf.ticker, metric, fy, d.value, d.unit,
                                  LABELS[metric], formula=d.formula, inputs=d.inputs, note=d.note)
        else:
            raise ToolError(f"unknown metric {metric!r}")
        return self._result(src)

    def get_metric_history(self, ticker: str, metric: str, years: list[int]) -> dict:
        out = []
        for y in years:
            try:
                out.append(self.get_metric(ticker, metric, y))
            except ToolError as e:
                out.append({"fiscal_year": y, "error": str(e)})
        return {"ticker": ticker.upper(), "metric": metric, "history": out}

    def compute(self, expression: str, inputs: dict, unit: str = "number") -> dict:
        """Safe arithmetic. Inputs are numbers or source ids ("S3")."""
        values, used = {}, {}
        for name, v in inputs.items():
            if isinstance(v, str) and re.fullmatch(r"S\d+", v):
                src = self.ledger.get(v)
                if src is None or src.value is None:
                    raise ToolError(f"unknown source id {v}")
                values[name], used[name] = src.value, v
            else:
                values[name] = float(v)
        result = safe_eval(expression, values)
        src = self.ledger.add("computed", None, None, None, result, unit,
                              f"computed {expression}", formula=expression, inputs=used,
                              input_values=values)
        return self._result(src)

    def get_price(self, ticker: str, on: str | None = None) -> dict:
        p = _get_price(ticker, on or str(self.settings["valuation_date"]))
        src = self.ledger.add("price", p.ticker, "price", None, p.close, "USD/shares",
                              "share price", as_of=str(p.date), source=p.source)
        return self._result(src)

    def get_filing_section(self, ticker: str, form: str = "10-K", section: str = "business",
                           max_chars: int = 6000) -> dict:
        if section not in SECTIONS:
            raise ToolError(f"section must be one of {list(SECTIONS)}")
        filing = self.client.filing_index(ticker, (form,))[0]
        text = self.client.filing_text(filing["url"])
        body = extract_section(text, SECTIONS[section])
        if not body:
            raise ToolError(f"could not find {section} in {filing['accession']}")
        src = self.ledger.add("filing", ticker.upper(), None, None, None, None,
                              f"{form} {section}", section=section, accession=filing["accession"],
                              url=filing["url"], report_date=filing["report_date"])
        return {"source_id": src.id, "accession": filing["accession"], "url": filing["url"],
                "section": section, "chars": len(body), "text": body[:max_chars]}

    def build_comps(self, tickers: list[str] | None = None, metrics: list[str] | None = None) -> dict:
        """Peer table on each company's latest fiscal year; every cell cited."""
        tickers = [t.upper() for t in (tickers or universe()["tickers"])]
        metrics = metrics or COMPS_METRICS
        rows = []
        for t in tickers:
            cf = self.company(t)
            v = valuation(cf, self.settings)
            row = {"ticker": t, "company": self.names.get(t, t), "fiscal_year": v.fiscal_year,
                   "cells": {}}
            for m in metrics:
                if m in VALUATION_METRICS:
                    src = self._valuation_source(t, m, v)
                else:
                    try:
                        src = self.ledger.get(self.get_metric(t, m, v.fiscal_year)["source_id"])
                    except ToolError:
                        row["cells"][m] = {"value": None, "display": "n/a", "source_id": None}
                        continue
                row["cells"][m] = {"value": src.value, "display": src.display, "source_id": src.id}
            rows.append(row)
        return {"as_of": str(self.settings["valuation_date"]), "metrics": metrics, "rows": rows}

    def peer_median(self, comps: dict, metric: str, exclude: str | None = None) -> dict:
        vals = {r["ticker"]: r["cells"][metric] for r in comps["rows"]
                if r["ticker"] != exclude and r["cells"][metric]["value"] is not None}
        med = statistics.median(c["value"] for c in vals.values())
        unit = VALUATION_METRICS.get(metric) or DERIVED_METRICS.get(metric) or "x"
        src = self.ledger.add("computed", None, metric, None, med, unit,
                              f"peer median {LABELS.get(metric, metric)}",
                              formula=f"median({metric}) over {len(vals)} peers",
                              inputs={t: c["source_id"] for t, c in vals.items()})
        return self._result(src)

    # -- helpers ---------------------------------------------------------
    def _valuation_source(self, t: str, m: str, v) -> Source:
        detail = {"formula": v.formulas.get(m, ""), "as_of": str(v.price.date),
                  "accession": v.shares.accession if m in ("shares_outstanding", "market_cap") else "",
                  "notes": "; ".join(v.notes)}
        fy = None if m in ("price", "shares_outstanding", "market_cap") else v.fiscal_year
        return self.ledger.add("valuation", t, m, fy, v.values[m], VALUATION_METRICS[m],
                               LABELS[m], **detail)

    def _result(self, src: Source) -> dict:
        out = {"source_id": src.id, "ticker": src.ticker, "metric": src.metric,
               "fiscal_year": src.fiscal_year, "value": src.value, "unit": src.unit,
               "display": src.display}
        out.update({k: v for k, v in src.detail.items() if k in
                    ("concept", "period", "accession", "formula", "as_of", "note")})
        return out


COMPS_METRICS = ["revenue", "revenue_growth", "gross_margin", "ebit_margin", "roic",
                 "net_debt", "market_cap", "ev", "ev_sales", "ev_ebitda", "pe"]


# -- safe arithmetic -------------------------------------------------------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
        ast.UAdd: operator.pos}


def safe_eval(expression: str, names: dict[str, float]) -> float:
    """Evaluate + - * / ** and parentheses over named numbers. Nothing else."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise ToolError(f"unknown name {node.id!r} in expression")
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ToolError(f"not allowed in expression: {ast.dump(node)[:60]}")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ToolError(f"bad expression: {e}")
    try:
        return ev(tree)
    except ZeroDivisionError:
        raise ToolError("division by zero")


_ITEM = re.compile(r"(?im)^[\s\u200b]*item[\s\xa0]*(\d{1,2}[a-c]?)\b[^\n]{0,160}$")


def extract_section(text: str, item: str) -> str:
    """Text of one 10-K item: from its heading to the next item heading.

    Headings are matched only at the start of a line, so cross-references
    ("see Item 1A. Risk Factors") don't count. The table of contents lists
    every heading too, so take the longest span.
    """
    heads = [(m.start(), m.end(), m.group(1).lower()) for m in _ITEM.finditer(text)]
    best = ""
    for i, (start, end, num) in enumerate(heads):
        if num != item:
            continue
        stop = next((h[0] for h in heads[i + 1:] if h[2] != item), len(text))
        body = text[end:stop]
        if len(body) > len(best):
            best = body
    return best.strip()


# -- JSON schemas for the model ---------------------------------------------
ALL_METRICS = sorted(set(LABELS) - set(VALUATION_METRICS))

TOOL_SCHEMAS = [
    {"name": "list_fiscal_years",
     "description": "Fiscal years with annual 10-K data for a company, and the latest one.",
     "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}},
                      "required": ["ticker"], "additionalProperties": False}},
    {"name": "get_metric",
     "description": "One annual metric from the company's 10-K XBRL data (or a ratio computed "
                    "from it). Returns value, unit, display string, source_id and provenance.",
     "input_schema": {"type": "object", "properties": {
         "ticker": {"type": "string"},
         "metric": {"type": "string", "enum": ALL_METRICS},
         "fiscal_year": {"type": "integer"}},
         "required": ["ticker", "metric", "fiscal_year"], "additionalProperties": False}},
    {"name": "get_metric_history",
     "description": "The same metric for several fiscal years.",
     "input_schema": {"type": "object", "properties": {
         "ticker": {"type": "string"},
         "metric": {"type": "string", "enum": ALL_METRICS},
         "years": {"type": "array", "items": {"type": "integer"}}},
         "required": ["ticker", "metric", "years"], "additionalProperties": False}},
    {"name": "compute",
     "description": "Safe arithmetic (+ - * / ** and parentheses) on named inputs. Inputs may be "
                    "numbers or source ids like 'S3'. Use this for any calculation; never do "
                    "arithmetic yourself.",
     "input_schema": {"type": "object", "properties": {
         "expression": {"type": "string"},
         "inputs": {"type": "object", "additionalProperties": {"type": ["number", "string"]}},
         "unit": {"type": "string", "enum": ["USD", "ratio", "x", "USD/shares", "number"],
                  "description": "Unit of the result, so it is displayed correctly."}},
         "required": ["expression", "inputs"], "additionalProperties": False}},
    {"name": "get_price",
     "description": "Closing share price on a date (default: the valuation date), with the date it is for.",
     "input_schema": {"type": "object", "properties": {
         "ticker": {"type": "string"}, "on": {"type": "string", "description": "YYYY-MM-DD"}},
         "required": ["ticker"], "additionalProperties": False}},
    {"name": "get_filing_section",
     "description": "Text of a section of the latest 10-K: business, risk_factors or mdna. "
                    "Use for qualitative points only; cite its source_id.",
     "input_schema": {"type": "object", "properties": {
         "ticker": {"type": "string"},
         "form": {"type": "string", "enum": ["10-K"]},
         "section": {"type": "string", "enum": list(SECTIONS)}},
         "required": ["ticker", "section"], "additionalProperties": False}},
    {"name": "build_comps",
     "description": "Peer comparison table on each company's latest fiscal year and the "
                    "valuation-date price. Every cell has a source_id.",
     "input_schema": {"type": "object", "properties": {
         "tickers": {"type": "array", "items": {"type": "string"}},
         "metrics": {"type": "array", "items": {"type": "string"}}},
         "required": [], "additionalProperties": False}},
]


def call_tool(box: ToolBox, name: str, args: dict) -> dict:
    """Dispatch a model's tool call. Errors come back as data, not exceptions."""
    fn = {"list_fiscal_years": box.list_fiscal_years, "get_metric": box.get_metric,
          "get_metric_history": box.get_metric_history, "compute": box.compute,
          "get_price": box.get_price, "get_filing_section": box.get_filing_section,
          "build_comps": box.build_comps}.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(**args)
    except (ToolError, TypeError, ValueError) as e:
        return {"error": str(e)}
