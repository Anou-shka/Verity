"""Researcher: gathers the numbers and qualitative points for one company.

It only uses tools, so every item in the research pack has a source id.
Two modes:
  - rules: a fixed plan of tool calls (no model, deterministic)
  - llm:   the model decides which tools to call, then summarises
           qualitative points from the filing text it read
Either way, the comps table and peer medians are built by code at the end.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..llm import LLM, llm_available, run_tool_loop
from ..tools import TOOL_SCHEMAS, Ledger, Source, ToolBox, call_tool
from ..trace import NULL_TRACER, Tracer

CURRENT_YEAR = ["revenue", "revenue_growth", "gross_margin", "operating_income", "ebit_margin",
                "net_income", "eps_diluted", "ebitda", "roic", "roe", "cash", "total_debt",
                "net_debt", "operating_cash_flow", "capex"]
PRIOR_YEAR = ["revenue", "gross_margin", "ebit_margin"]
PEER_MEDIANS = ["ev_ebitda", "ev_sales", "pe", "ebit_margin", "revenue_growth"]


@dataclass
class ResearchPack:
    ticker: str
    company: str
    fiscal_year: int
    ledger: Ledger
    qualitative: list[dict] = field(default_factory=list)   # {"kind", "text", "source_id"}
    comps: dict = field(default_factory=dict)
    peer_medians: dict = field(default_factory=dict)        # metric -> source id
    mode: str = "rules"

    def find(self, metric: str, fiscal_year: int | None = None, ticker: str | None = None,
             kind: str | None = None) -> Source | None:
        ticker = ticker or self.ticker
        for s in self.ledger.sources.values():
            if (s.ticker == ticker and s.metric == metric and s.value is not None
                    and (fiscal_year is None or s.fiscal_year == fiscal_year)
                    and (kind is None or s.kind == kind)):
                return s
        return None

    def comps_cell(self, metric: str, ticker: str | None = None) -> Source | None:
        row = next((r for r in self.comps.get("rows", []) if r["ticker"] == (ticker or self.ticker)), None)
        sid = row and row["cells"].get(metric, {}).get("source_id")
        return self.ledger.get(sid) if sid else None

    def to_json(self) -> dict:
        return {"ticker": self.ticker, "company": self.company, "fiscal_year": self.fiscal_year,
                "mode": self.mode, "qualitative": self.qualitative, "comps": self.comps,
                "peer_medians": self.peer_medians, "sources": self.ledger.to_json()}


def research(ticker: str, box: ToolBox, tracer: Tracer = NULL_TRACER, use_llm: bool | None = None,
             peers: list[str] | None = None) -> ResearchPack:
    use_llm = llm_available() if use_llm is None else use_llm
    tracer.event("agent_start", "researcher", ticker=ticker, mode="llm" if use_llm else "rules")

    def tool(name, **args):
        result = call_tool(box, name, args)
        tracer.event("tool_call", "researcher", tool=name, args=args,
                     source_id=result.get("source_id"), error=result.get("error"))
        return result

    info = tool("list_fiscal_years", ticker=ticker)
    if "error" in info:
        raise ValueError(info["error"])
    fy = info["latest"]
    pack = ResearchPack(ticker.upper(), info["company"], fy, box.ledger,
                        mode="llm" if use_llm else "rules")

    if use_llm:
        _llm_research(pack, box, tracer, tool)
    else:
        for m in CURRENT_YEAR:
            tool("get_metric", ticker=ticker, metric=m, fiscal_year=fy)
        for m in PRIOR_YEAR:
            tool("get_metric", ticker=ticker, metric=m, fiscal_year=fy - 1)
        tool("get_price", ticker=ticker)
        business = tool("get_filing_section", ticker=ticker, section="business")
        risks = tool("get_filing_section", ticker=ticker, section="risk_factors")
        if "error" not in business:
            sentence = first_description(business["text"], info["company"])
            if sentence:
                pack.qualitative.append({"kind": "business", "text": sentence,
                                         "source_id": business["source_id"]})
        if "error" not in risks:
            full = box.get_filing_section(ticker, section="risk_factors", max_chars=10**7)["text"]
            for heading in risk_headings(full)[:3]:
                pack.qualitative.append({"kind": "risk", "text": heading,
                                         "source_id": risks["source_id"]})

    # Comps and peer medians are always built by code, never by the model.
    pack.comps = tool("build_comps", tickers=peers) if peers else tool("build_comps")
    for m in PEER_MEDIANS:
        if pack.comps["rows"] and m in pack.comps["metrics"]:
            pack.peer_medians[m] = box.peer_median(pack.comps, m, exclude=pack.ticker)["source_id"]
    tracer.event("agent_end", "researcher", n_sources=len(box.ledger.sources),
                 n_qualitative=len(pack.qualitative))
    return pack


RESEARCH_SYSTEM = """You are the Researcher in an equity research team. You gather facts about one \
company using tools only. You never state a number from memory and never do arithmetic yourself: \
use get_metric for reported figures and ratios, and compute for anything else.

Gather, for the latest fiscal year (and the prior year where it helps show a trend): revenue and \
growth, gross and EBIT margins, net income, diluted EPS, EBITDA, ROIC, cash, total debt, net debt, \
operating cash flow and capex. Read the 10-K business and risk_factors sections.

When you are done, reply with JSON only, in this shape:
{"business": {"text": "<one or two sentences describing the business>", "source_id": "S.."},
 "risks": [{"text": "<one sentence>", "source_id": "S.."}, ... exactly 3 ...],
 "notes": "<anything the writer should know, e.g. data that was missing>"}
Qualitative text must contain no numbers. Cite the source_id of the filing section you read."""


def _llm_research(pack: ResearchPack, box: ToolBox, tracer: Tracer, tool) -> None:
    llm = LLM("fast", tracer=tracer, agent="researcher")
    user = (f"Company: {pack.company} ({pack.ticker}). Latest fiscal year: FY{pack.fiscal_year}. "
            f"Gather the research pack.")
    reply, _ = run_tool_loop(llm, RESEARCH_SYSTEM, user, TOOL_SCHEMAS,
                             lambda name, args: tool(name, **args))
    data = parse_json(reply.text)
    if data.get("business"):
        pack.qualitative.append({"kind": "business", **data["business"]})
    for r in data.get("risks", [])[:3]:
        pack.qualitative.append({"kind": "risk", **r})
    if data.get("notes"):
        pack.qualitative.append({"kind": "note", "text": data["notes"], "source_id": None})


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


# -- deterministic text helpers (rules mode) ---------------------------------
def first_description(text: str, company: str) -> str | None:
    """The first sentence of Item 1 that describes the company, verbatim."""
    first_word = company.split()[0].lower()
    flat = re.sub(r"\s+", " ", text)
    for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z])", flat):
        s = sent.strip()
        # drop a heading glued onto the sentence ("Overview Vertiv is ...")
        at = s.lower().find(first_word)
        if 0 < at <= 30 and s[:at].strip().replace(" ", "").isalpha():
            s = s[at:]
        if 80 <= len(s) <= 400 and (first_word in s.lower()[:80] or s.lower().startswith("we ")) \
                and re.search(r"\b(is|are|provides?|designs?|manufactures?)\b", s) \
                and not re.search(r"\d{2,}", s):
            return s
    return None


def risk_headings(text: str) -> list[str]:
    """Risk-factor headings: stand-alone one-sentence lines, quoted verbatim."""
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if (60 <= len(s) <= 220 and s.endswith(".") and s[0].isupper() and s.count(". ") == 0
                and not re.search(r"\d{2,}", s) and not s.lower().startswith(("see ", "refer"))):
            out.append(s)
    return out
