"""Fact-checker (the critic): finds every number in a draft and re-checks it.

1. Extract claims. Every number in the note becomes a claim: its text, unit,
   normalised value, the source id cited after it, and the fiscal year named
   nearest to it in the same sentence. Extraction is a parser, not a model,
   so no number can be skipped. In LLM mode a model also reads the note to
   flag qualitative statements that need a source.
2. Re-fetch. The cited source says what the number claims to be (company,
   metric, year). The checker fetches that value again with its own ToolBox
   and its own ledger, so it never trusts what the Writer was given.
3. Label each claim: verified, wrong (with the correct value) or
   unverifiable (no source, unknown source, or nothing to compare against).

Quoted text (“...”) is checked by looking for the quote in the filing.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field

from ..derived import load_settings
from ..fmt import UNIT_KIND, display, display_precision
from ..tools import LABELS, Ledger, Source, ToolBox, ToolError, safe_eval
from ..trace import NULL_TRACER, Tracer

NUMBER = re.compile(
    r"(?P<sign>-)?(?P<cur>\$)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<suf>\s?(?:%|x\b|bn\b|m\b|\s(?:billion|million)\b))?")
REF = re.compile(r"\s*\[(S\d+)\]")
FY = re.compile(r"\bFY(\d{4})\b")
QUOTE = re.compile(r"“([^”]{10,})”(\s*\[(S\d+)\])?")

# Words that name each metric; used to catch a correct number cited for the
# wrong thing ("EBIT margin of 36.3% [S5]" where S5 is gross margin).
SYNONYMS = {
    "revenue": ["revenue", "sales", "top line"], "gross_profit": ["gross profit"],
    "operating_income": ["operating income", "operating profit", "ebit"],
    "net_income": ["net income", "net earnings", "profit"], "eps_diluted": ["eps", "per share"],
    "d_and_a": ["d&a", "depreciation"], "cash": ["cash"], "total_debt": ["debt", "borrowings"],
    "operating_cash_flow": ["operating cash flow", "cash from operations"], "capex": ["capex", "capital expenditure"],
    "gross_margin": ["gross margin"], "ebit_margin": ["ebit margin", "operating margin"],
    "ebitda": ["ebitda"], "revenue_growth": ["grew", "growth", "fell", "increase", "decline", "rose"],
    "net_debt": ["net debt", "net cash"], "roe": ["roe", "return on equity"],
    "roic": ["roic", "return on invested capital"], "price": ["price", "closed", "shares"],
    "market_cap": ["market cap"], "ev": ["enterprise value", " ev "], "ev_ebitda": ["ev/ebitda"],
    "ev_sales": ["ev/sales"], "pe": ["p/e", "earnings multiple"],
    "total_assets": ["assets"], "total_equity": ["equity"], "shares_diluted": ["shares"],
}


@dataclass
class Claim:
    id: str
    value_text: str
    kind: str                         # money | pct | multiple | per_share | number
    value: float
    start: int
    end: int
    ref: str | None
    ref_span: tuple | None
    sentence: str
    sentence_start: int
    year: int | None
    year_span: tuple | None
    status: str = ""                  # verified | wrong | unverifiable
    reason: str = ""
    true_value: float | None = None
    correct_display: str | None = None
    correct_year: int | None = None
    source: str = ""                  # one-line description of the cited source

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    round: int
    claims: list[Claim]
    quotes: list[dict] = field(default_factory=list)
    table: dict = field(default_factory=dict)
    qualitative_flags: list[dict] = field(default_factory=list)

    @property
    def issues(self) -> list[Claim]:
        return [c for c in self.claims if c.status != "verified"] + \
               [q for q in self.quotes if q["status"] != "verified"]

    def summary(self) -> dict:
        n = {s: sum(c.status == s for c in self.claims) for s in ("verified", "wrong", "unverifiable")}
        return {"round": self.round, "claims": len(self.claims), **n,
                "quotes": len(self.quotes),
                "quotes_verified": sum(q["status"] == "verified" for q in self.quotes),
                "table_cells": self.table.get("cells", 0), "table_wrong": self.table.get("wrong", 0)}

    def to_json(self) -> dict:
        return {"summary": self.summary(), "claims": [c.to_json() for c in self.claims],
                "quotes": self.quotes, "table": self.table,
                "qualitative_flags": self.qualitative_flags}


# -- 1. extraction --------------------------------------------------------------
def _sentences(text: str) -> list[tuple[int, str]]:
    """(start offset, sentence) pairs. Splits on sentence ends and line breaks."""
    out, pos = [], 0
    for m in re.finditer(r"(?<=[.!?”])(?:\s*\[S\d+\])?\s+(?=[A-Z#“\d-])|\n+", text):
        end = m.end() if text[m.start():m.end()].strip().startswith("[") else m.start()
        out.append((pos, text[pos:end]))
        pos = m.end()
    out.append((pos, text[pos:]))
    return [(s, t) for s, t in out if t.strip()]


def extract_claims(note: str) -> list[Claim]:
    masked = _mask(note)
    claims = []
    for s_start, sent in _sentences(note):
        s_end = s_start + len(sent)
        for m in NUMBER.finditer(masked, s_start, s_end):
            parsed = _parse(m)
            if parsed is None:
                continue
            kind, value = parsed
            ref_m = REF.match(note, m.end())
            ref = ref_m.group(1) if ref_m else None
            year, yspan = _nearest_year(note, s_start, s_end, m.start())
            claims.append(Claim(f"C{len(claims) + 1}", note[m.start():m.end()].strip(), kind, value,
                                m.start(), m.start() + len(note[m.start():m.end()].rstrip()), ref,
                                (ref_m.start(), ref_m.end()) if ref_m else None,
                                sent, s_start, year, yspan))
    return claims


def _mask(note: str) -> str:
    """Blank out text whose digits are not claims: citations, FY labels, dates,
    quoted filing text and markdown list numbers. Offsets are preserved."""
    def blank(m):
        return " " * (m.end() - m.start())
    out = re.sub(r"\[S\d+\]", blank, note)
    out = re.sub(r"\bFY\d{4}\b", blank, out)
    out = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", blank, out)
    out = re.sub(r"\b\d{1,2}-[KQ](?:/A)?\b", blank, out)          # form names: 10-K, 10-Q
    out = re.sub(r"“[^”]*”", blank, out)
    out = re.sub(r"(?m)^\s*\d+\.\s", blank, out)
    out = re.sub(r"(?i)\b(item|note|section|part)\s+\d+[a-c]?\b", blank, out)
    return out


def _parse(m: re.Match) -> tuple[str, float] | None:
    num = float(m.group("num").replace(",", ""))
    suf = (m.group("suf") or "").strip().lower()
    sign = -1 if m.group("sign") else 1
    if m.group("cur"):
        mult = {"m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}.get(suf)
        return ("money", sign * num * mult) if mult else ("per_share", sign * num)
    if suf == "%":
        return "pct", sign * num / 100
    if suf == "x":
        return "multiple", num
    if suf in ("m", "million", "bn", "billion"):
        return "number", sign * num * (1e6 if suf in ("m", "million") else 1e9)
    if 1900 <= num <= 2100 and "." not in m.group("num"):
        return None                          # a calendar year
    if num < 10 and "." not in m.group("num"):
        return None                          # "3 risks", list counters
    return "number", sign * num


def _nearest_year(note, s_start, s_end, pos):
    best = None
    for m in FY.finditer(note, s_start, s_end):
        d = abs(m.start() - pos)
        if best is None or d < best[0]:
            best = (d, int(m.group(1)), (m.start(), m.end()))
    return (best[1], best[2]) if best else (None, None)


# -- 2 and 3. verification --------------------------------------------------------
class FactChecker:
    def __init__(self, ledger: Ledger, tracer: Tracer = NULL_TRACER):
        self.ledger = ledger                  # what the Writer was given (for citations only)
        self.fresh = ToolBox(Ledger())        # independent re-fetch
        self.settings = load_settings()
        self.tol = self.settings["tolerance"]
        self.tracer = tracer
        self._cache: dict[str, float | None] = {}

    def check(self, note: str, comps: dict | None = None, round_: int = 0,
              use_llm: bool = False) -> Report:
        self.tracer.event("agent_start", "fact_checker", round=round_)
        claims = extract_claims(note)
        for c in claims:
            self._verify(c)
            self.tracer.event("claim", "fact_checker", round=round_, claim=c.value_text, ref=c.ref,
                              status=c.status, reason=c.reason)
        report = Report(round_, claims, self._check_quotes(note))
        if comps:
            report.table = self.check_table(comps)
        if use_llm:
            report.qualitative_flags = self._llm_flags(note)
        self.tracer.event("agent_end", "fact_checker", **report.summary())
        return report

    def _verify(self, c: Claim) -> None:
        if not c.ref:
            c.status, c.reason = "unverifiable", "no source cited"
            return
        src = self.ledger.get(c.ref)
        if src is None or src.value is None:
            c.status, c.reason = "unverifiable", f"cited source {c.ref} does not exist or has no value"
            return
        c.source = src.brief()
        truth = self.refetch(src)
        if truth is None:
            c.status, c.reason = "unverifiable", "could not re-fetch the cited value"
            return
        c.true_value = truth
        expected = UNIT_KIND.get(src.unit, "number")
        problems = []
        if c.kind != expected and not (expected == "count" and c.kind == "number"):
            problems.append(f"unit: written as {c.kind}, source is {expected}")
        elif not self._close(c.value, truth, src.unit):
            problems.append(f"value: source says {display(truth, src.unit)}")
        if src.fiscal_year and c.year and c.year != src.fiscal_year:
            problems.append(f"year: source is FY{src.fiscal_year}, text says FY{c.year}")
            c.correct_year = src.fiscal_year
        if not problems and self._mislabeled(c, src):
            c.status = "wrong"
            c.reason = f"cited source is {LABELS.get(src.metric, src.metric)}, text describes something else"
            return
        if problems:
            c.status, c.reason = "wrong", "; ".join(problems)
            if not self._describes(c, src):
                # The words around the number don't name what the source is,
                # so this is a fabricated claim with a borrowed citation.
                # Patching the number would launder it; flag it for deletion.
                c.correct_year = None
                c.reason += f"; the text does not describe {LABELS.get(src.metric, src.metric)}"
            elif not problems[0].startswith("year"):
                c.correct_display = display(truth, src.unit)
        else:
            c.status = "verified"

    def _close(self, claimed: float, truth: float, unit: str) -> bool:
        if unit == "ratio":
            return abs(claimed - truth) <= self.tol["ratio_abs"]
        slack = display_precision(unit)
        return abs(claimed - truth) <= max(abs(truth) * self.tol["reported_rel"], slack)

    def _clause(self, c: Claim) -> str:
        """The words just before the number, back to the previous citation or comma."""
        rel = c.start - c.sentence_start
        prev = max(c.sentence.rfind("]", 0, rel), c.sentence.rfind(",", 0, rel), 0)
        return " " + c.sentence[prev:rel].lower() + " "

    def _describes(self, c: Claim, src: Source) -> bool:
        """Does the sentence name the cited metric (or a closely related one)?"""
        if not src.metric or src.metric not in SYNONYMS:
            return True
        text = " " + c.sentence.lower() + " "
        names = [m for m, ws in SYNONYMS.items() if any(w in text for w in ws)]
        return src.metric in names or any(_related(src.metric, m) for m in names)

    def _mislabeled(self, c: Claim, src: Source) -> bool:
        """True only if the words before the number name a different metric."""
        if not src.metric or src.metric not in SYNONYMS:
            return False
        clause = self._clause(c)
        if any(w in clause for w in SYNONYMS[src.metric]):
            return False
        others = [m for m, ws in SYNONYMS.items() if m != src.metric and any(w in clause for w in ws)]
        return bool(others) and not any(_related(src.metric, o) for o in others)

    # -- re-fetching ---------------------------------------------------------
    def refetch(self, src: Source) -> float | None:
        if src.id in self._cache:
            return self._cache[src.id]
        try:
            value = self._refetch(src)
        except (ToolError, ValueError, KeyError, StopIteration):
            value = None
        self._cache[src.id] = value
        return value

    def _refetch(self, src: Source) -> float | None:
        box = self.fresh
        if src.kind in ("xbrl", "derived"):
            return box.get_metric(src.ticker, src.metric, src.fiscal_year)["value"]
        if src.kind == "price":
            return box.get_price(src.ticker, src.detail["as_of"])["value"]
        if src.kind == "valuation":
            comps = box.build_comps([src.ticker], [src.metric])
            return comps["rows"][0]["cells"][src.metric]["value"]
        if src.kind == "computed":
            inputs = {k: self.refetch(self.ledger.get(v)) for k, v in src.detail.get("inputs", {}).items()}
            if src.detail.get("formula", "").startswith("median("):
                return statistics.median(v for v in inputs.values() if v is not None)
            values = {**src.detail.get("input_values", {}), **inputs}
            return safe_eval(src.detail["formula"], values)
        return None

    def check_table(self, comps: dict) -> dict:
        """The comps table is built by code; check every cell against a fresh fetch anyway."""
        cells = wrong = 0
        details = []
        for r in comps["rows"]:
            for m, cell in r["cells"].items():
                if cell["source_id"] is None:
                    continue
                cells += 1
                truth = self.refetch(self.ledger.get(cell["source_id"]))
                unit = self.ledger.get(cell["source_id"]).unit
                if truth is None or display(truth, unit) != cell["display"]:
                    wrong += 1
                    details.append({"ticker": r["ticker"], "metric": m, "shown": cell["display"],
                                    "fresh": display(truth, unit) if truth is not None else None})
        return {"cells": cells, "wrong": wrong, "details": details}

    def _check_quotes(self, note: str) -> list[dict]:
        out = []
        for m in QUOTE.finditer(note):
            quote, ref = m.group(1), m.group(3)
            src = self.ledger.get(ref) if ref else None
            if src is None or src.kind != "filing":
                out.append({"quote": quote, "ref": ref, "status": "unverifiable",
                            "reason": "no filing source cited"})
                continue
            text = self.fresh.get_filing_section(src.ticker, section=src.detail["section"],
                                                 max_chars=10**8)["text"]
            found = _norm(quote) in _norm(text)
            out.append({"quote": quote, "ref": ref, "status": "verified" if found else "wrong",
                        "reason": "" if found else "quote not found in the cited filing section",
                        "accession": src.detail.get("accession")})
        return out

    def _llm_flags(self, note: str) -> list[dict]:
        """Ask a model to point out qualitative statements that make factual claims
        without a source. Advisory only: these are listed, not auto-deleted."""
        from ..llm import LLM
        from .researcher import parse_json
        llm = LLM("fast", tracer=self.tracer, agent="fact_checker")
        reply = llm.chat(
            "You check research notes. List sentences that state a factual claim about the "
            "company (not a number) that is neither quoted from a cited filing nor obviously "
            'generic. Reply with JSON only: {"flags": [{"sentence": "...", "why": "..."}]}',
            [{"role": "user", "content": note}], max_tokens=4000)
        return parse_json(reply.text).get("flags", [])


def _related(a: str, b: str) -> bool:
    """Metrics whose words legitimately appear together (EBIT margin vs EBIT)."""
    pairs = [{"operating_income", "ebit_margin"}, {"gross_profit", "gross_margin"},
             {"net_debt", "cash"}, {"net_debt", "total_debt"}, {"revenue", "revenue_growth"},
             {"eps_diluted", "net_income"}, {"ebitda", "ev_ebitda"}, {"revenue", "ev_sales"},
             {"price", "pe"}, {"cash", "operating_cash_flow"}, {"ebitda", "operating_income"},
             {"ev_ebitda", "ev"}, {"ev_sales", "ev"}, {"shares_diluted", "eps_diluted"},
             {"price", "eps_diluted"}, {"shares_diluted", "price"}]
    return {a, b} in pairs


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()
