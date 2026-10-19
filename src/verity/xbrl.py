"""Turn SEC company facts into a clean table of standard annual metrics.

Pipeline for one company:
  1. For a tag, keep 10-K facts that are annual (duration ~12 months) or sit
     on a fiscal-year-end date (instant).
  2. Label each fact with a fiscal year from its period end date.
  3. If several filings report the same period, keep the most recently filed
     value and record any difference as a restatement.
  4. For a standard metric, walk the ordered options in config/concept_map.yaml
     and take the first one with data for that year. Log which one was used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cached_property

import yaml

from .config import CONFIG_DIR
from .sec import SecClient

ANNUAL_FORMS = {"10-K", "10-K/A"}
ANNUAL_DAYS = (350, 380)  # 52/53-week years included


def load_concept_map() -> dict:
    return yaml.safe_load((CONFIG_DIR / "concept_map.yaml").read_text())


def fiscal_year_of(end: date) -> int:
    """Fiscal year = calendar year the period ends in.

    Matches how these filers label their years (Modine's FY2026 ends
    31 Mar 2026, Super Micro's FY2025 ends 30 Jun 2025). A 52/53-week
    year ending in the first week of January belongs to the prior year.
    """
    if end.month == 1 and end.day <= 7:
        return end.year - 1
    return end.year


@dataclass(frozen=True)
class Fact:
    """One reported XBRL value, with everything needed to cite it."""
    tag: str
    value: float
    unit: str
    start: date | None
    end: date
    accession: str
    form: str
    filed: str
    fiscal_year: int

    @property
    def period(self) -> str:
        return f"{self.start}..{self.end}" if self.start else f"{self.end}"


@dataclass(frozen=True)
class Restatement:
    tag: str
    fiscal_year: int
    old_value: float
    old_accession: str
    new_value: float
    new_accession: str


@dataclass
class MetricValue:
    """A standard metric for one fiscal year and the facts it came from."""
    ticker: str
    metric: str
    fiscal_year: int
    value: float | None
    unit: str
    method: str                       # tag name, or the formula used
    facts: list[Fact] = field(default_factory=list)
    note: str = ""

    @property
    def concept(self) -> str:
        return " + ".join(f.tag for f in self.facts) or self.method

    @property
    def accession(self) -> str:
        return ", ".join(sorted({f.accession for f in self.facts}))

    @property
    def period(self) -> str:
        return self.facts[0].period if self.facts else ""


class CompanyFacts:
    """Annual facts for one company, read from the SEC companyfacts JSON."""

    def __init__(self, ticker: str, raw: dict, concept_map: dict | None = None):
        self.ticker = ticker.upper()
        self.raw = raw
        self.cmap = concept_map or load_concept_map()
        self.restatements: list[Restatement] = []
        self._annual: dict[tuple[str, str, str], dict[int, Fact]] = {}

    @classmethod
    def load(cls, ticker: str, client: SecClient | None = None) -> "CompanyFacts":
        client = client or SecClient()
        return cls(ticker, client.company_facts(ticker))

    # -- step 1-3: one tag -> {fiscal_year: Fact} -------------------------
    def _rows(self, tag: str, unit: str) -> list[dict]:
        ns, _, name = tag.rpartition(":")
        concept = self.raw["facts"].get(ns or "us-gaap", {}).get(name)
        return concept["units"].get(unit, []) if concept else []

    @cached_property
    def fiscal_year_ends(self) -> set[date]:
        """End dates of every annual period reported in a 10-K."""
        ends = set()
        for concept in self.raw["facts"].get("us-gaap", {}).values():
            for rows in concept["units"].values():
                for r in rows:
                    if r["form"] in ANNUAL_FORMS and "start" in r and self._is_annual(r):
                        ends.add(date.fromisoformat(r["end"]))
        return ends

    @staticmethod
    def _is_annual(r: dict) -> bool:
        days = (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days
        return ANNUAL_DAYS[0] <= days <= ANNUAL_DAYS[1]

    def annual(self, tag: str, kind: str, unit: str) -> dict[int, Fact]:
        key = (tag, kind, unit)
        if key in self._annual:
            return self._annual[key]
        by_year: dict[int, list[Fact]] = {}
        for r in self._rows(tag, unit):
            if r["form"] not in ANNUAL_FORMS:
                continue
            end = date.fromisoformat(r["end"])
            if kind == "duration":
                if "start" not in r or not self._is_annual(r):
                    continue
                start = date.fromisoformat(r["start"])
            else:
                if "start" in r or end not in self.fiscal_year_ends:
                    continue
                start = None
            fy = fiscal_year_of(end)
            by_year.setdefault(fy, []).append(Fact(
                tag=tag, value=float(r["val"]), unit=unit, start=start, end=end,
                accession=r["accn"], form=r["form"], filed=r["filed"], fiscal_year=fy))

        chosen: dict[int, Fact] = {}
        for fy, facts in by_year.items():
            # Several fiscal-year ends can map to one label only in odd cases
            # (a changed year end); prefer the latest period end, then the
            # most recent filing.
            facts.sort(key=lambda f: (f.end, f.filed, f.accession))
            latest = facts[-1]
            chosen[fy] = latest
            for f in facts:
                if f.end == latest.end and f.value != latest.value:
                    self.restatements.append(Restatement(
                        tag, fy, f.value, f.accession, latest.value, latest.accession))
        self._annual[key] = chosen
        return chosen

    # -- step 4: standard metric -----------------------------------------
    def metric(self, metric: str, fiscal_year: int) -> MetricValue:
        spec = self.cmap["metrics"][metric]
        for option in spec["options"]:
            result = self._resolve_option(option, spec, fiscal_year)
            if result is not None:
                value, facts, method = result
                return MetricValue(self.ticker, metric, fiscal_year, value,
                                   spec["unit"], method, facts)
        reason = self.cmap.get("assume_zero", {}).get(self.ticker, {}).get(metric)
        if reason and fiscal_year in self.years():
            return MetricValue(self.ticker, metric, fiscal_year, 0.0, spec["unit"],
                               "assumed zero", note=reason)
        return MetricValue(self.ticker, metric, fiscal_year, None, spec["unit"],
                           "not reported")

    def _resolve_option(self, option, spec, fy):
        if isinstance(option, str):
            fact = self.annual(option, spec["kind"], spec["unit"]).get(fy)
            return (fact.value, [fact], option) if fact else None

        total, facts, parts = 0.0, [], []
        for sign, comps in ((1, option.get("add", [])), (-1, option.get("subtract", []))):
            for comp in comps:
                if comp.startswith("@"):
                    sub = self.metric(comp[1:], fy)
                    if sub.value is None:
                        return None
                    value, sub_facts, label = sub.value, sub.facts, sub.method
                else:
                    fact = self.annual(comp, spec["kind"], spec["unit"]).get(fy)
                    if fact is None:
                        return None
                    value, sub_facts, label = fact.value, [fact], comp
                total += sign * value
                facts += sub_facts
                parts.append(("+ " if sign > 0 else "- ") + label)
        method = " ".join(parts).removeprefix("+ ")
        return total, facts, method

    def years(self) -> list[int]:
        """Fiscal years with a reported annual revenue figure."""
        return sorted({fiscal_year_of(d) for d in self.fiscal_year_ends})

    def shares_outstanding(self) -> Fact | None:
        """Latest cover-page share count (dei), from any 10-K or 10-Q."""
        best = None
        for r in self._rows("dei:EntityCommonStockSharesOutstanding", "shares"):
            if r["form"] not in {"10-K", "10-Q", "10-K/A", "10-Q/A"}:
                continue
            if best is None or (r["filed"], r["end"]) > (best["filed"], best["end"]):
                best = r
        if best is None:
            return None
        end = date.fromisoformat(best["end"])
        return Fact("dei:EntityCommonStockSharesOutstanding", float(best["val"]), "shares",
                    None, end, best["accn"], best["form"], best["filed"], fiscal_year_of(end))


def standard_metrics(concept_map: dict | None = None) -> list[str]:
    cmap = concept_map or load_concept_map()
    return list(cmap["metrics"])
