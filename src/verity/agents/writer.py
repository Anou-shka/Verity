"""Writer: turns a research pack into a comps table and a short note.

Every number in the note is copied from the pack's display string and is
followed by its source id, e.g. "revenue of $10,229.9m [S1]". The Writer never
calculates: comparisons such as "a premium to peers" are decided in Python and
passed in as words.

Two modes:
  - template: deterministic prose from fixed sentences (no model)
  - llm:      the strong model writes ~600 words from the pack
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..llm import LLM, llm_available
from ..tools import LABELS, VALUATION_METRICS
from ..trace import NULL_TRACER, Tracer
from .researcher import ResearchPack

COMPS_HEADERS = {"revenue": "Revenue", "revenue_growth": "Growth", "gross_margin": "Gross mgn",
                 "ebit_margin": "EBIT mgn", "roic": "ROIC", "net_debt": "Net debt",
                 "market_cap": "Mkt cap", "ev": "EV", "ev_sales": "EV/Sales",
                 "ev_ebitda": "EV/EBITDA", "pe": "P/E"}


@dataclass
class Draft:
    note: str
    comps_table: str
    mode: str


def comps_markdown(pack: ResearchPack) -> str:
    metrics = pack.comps["metrics"]
    head = "| Company | FY | " + " | ".join(COMPS_HEADERS.get(m, m) for m in metrics) + " |"
    sep = "|---|---|" + "---:|" * len(metrics)
    lines = [head, sep]
    for r in pack.comps["rows"]:
        name = f"**{r['company']}**" if r["ticker"] == pack.ticker else r["company"]
        cells = " | ".join(r["cells"][m]["display"] for m in metrics)
        lines.append(f"| {name} | {r['fiscal_year']} | {cells} |")
    return "\n".join(lines)


def write(pack: ResearchPack, tracer: Tracer = NULL_TRACER, use_llm: bool | None = None) -> Draft:
    use_llm = llm_available() if use_llm is None else use_llm
    tracer.event("agent_start", "writer", mode="llm" if use_llm else "template")
    note = _llm_write(pack, tracer) if use_llm else template_note(pack)
    tracer.event("agent_end", "writer", words=len(note.split()))
    return Draft(note, comps_markdown(pack), "llm" if use_llm else "template")


# -- template mode ------------------------------------------------------------
def _q(text: str) -> str:
    """Quote filing text verbatim; inner curly quotes become straight ones so
    the outer quote marks stay unambiguous (the checker normalises both)."""
    return "“" + text.replace("“", '"').replace("”", '"') + "”"


def _c(src) -> str:
    """A number as the note prints it: display string plus citation."""
    return f"{src.display} [{src.id}]"


def template_note(pack: ResearchPack) -> str:
    fy, p = pack.fiscal_year, pack.find
    name = pack.company
    out = [f"# {name} ({pack.ticker}): FY{fy} research note", ""]

    biz = next((q for q in pack.qualitative if q["kind"] == "business"), None)
    if biz:
        out += ["## Business", f"In its 10-K, {name} describes itself as follows: "
                f"{_q(biz['text'])} [{biz['source_id']}]", ""]

    perf = []
    rev, rev0, growth = p("revenue", fy), p("revenue", fy - 1), p("revenue_growth", fy)
    if rev and rev0 and growth:
        direction = "grew" if growth.value >= 0 else "fell"
        perf.append(f"FY{fy} revenue {direction} {_c(growth)} to {_c(rev)}, from {_c(rev0)} in FY{fy - 1}.")
    ni, eps = p("net_income", fy), p("eps_diluted", fy)
    if ni and eps:
        perf.append(f"FY{fy} net income was {_c(ni)}, or diluted EPS of {_c(eps)}.")
    ebitda = p("ebitda", fy)
    if ebitda:
        perf.append(f"FY{fy} EBITDA was {_c(ebitda)}.")
    if perf:
        out += ["## Recent performance", " ".join(perf), ""]

    marg = []
    gm, gm0 = p("gross_margin", fy), p("gross_margin", fy - 1)
    em, em0 = p("ebit_margin", fy), p("ebit_margin", fy - 1)
    if gm and gm0:
        marg.append(f"FY{fy} gross margin was {_c(gm)}, {_trend(gm.value, gm0.value)} {_c(gm0)} in FY{fy - 1}.")
    if em and em0:
        marg.append(f"FY{fy} EBIT margin was {_c(em)}, {_trend(em.value, em0.value)} {_c(em0)} in FY{fy - 1}.")
    roic = p("roic", fy)
    if roic:
        marg.append(f"FY{fy} ROIC was {_c(roic)}.")
    if marg:
        out += ["## Margins and returns", " ".join(marg), ""]

    bs = []
    cash, debt, nd = p("cash", fy), p("total_debt", fy), p("net_debt", fy)
    if cash and debt and nd:
        position = (f"a net cash position (net debt of {_c(nd)})" if nd.value < 0
                    else f"net debt of {_c(nd)}")
        bs.append(f"At the end of FY{fy} the company held cash of {_c(cash)} against total debt of "
                  f"{_c(debt)}, giving {position}.")
    ocf, capex = p("operating_cash_flow", fy), p("capex", fy)
    if ocf and capex:
        bs.append(f"FY{fy} operating cash flow was {_c(ocf)} and capex was {_c(capex)}.")
    if bs:
        out += ["## Balance sheet and cash flow", " ".join(bs), ""]

    val = []
    price, evx, pe = p("price"), pack.comps_cell("ev_ebitda"), pack.comps_cell("pe")
    med = {m: pack.ledger.get(sid) for m, sid in pack.peer_medians.items()}
    if price:
        val.append(f"The shares closed at {_c(price)} on {price.detail['as_of']}.")
    if evx and med.get("ev_ebitda"):
        val.append(f"On {pack.comps['as_of']} prices, {name} trades at an FY{fy} EV/EBITDA of {_c(evx)}, "
                   f"{_relative(evx.value, med['ev_ebitda'].value)} the peer median of "
                   f"{_c(med['ev_ebitda'])}.")
    evs = pack.comps_cell("ev_sales")
    if evs and med.get("ev_sales"):
        val.append(f"Its FY{fy} EV/Sales is {_c(evs)} against a peer median of {_c(med['ev_sales'])}.")
    if pe and med.get("pe"):
        val.append(f"Its FY{fy} P/E is {_c(pe)} against a peer median of {_c(med['pe'])}.")
    if em and med.get("ebit_margin"):
        val.append(f"For context, its FY{fy} EBIT margin of {_c(em)} is "
                   f"{_relative(em.value, med['ebit_margin'].value, 'level')} the peer median of "
                   f"{_c(med['ebit_margin'])}.")
    if val:
        out += ["## Valuation versus peers", " ".join(val), ""]

    risks = [q for q in pack.qualitative if q["kind"] == "risk"]
    if risks:
        out += ["## Key risks (from the 10-K)"]
        out += [f"{i}. {_q(r['text'])} [{r['source_id']}]" for i, r in enumerate(risks, 1)]
        out.append("")
    return "\n".join(out).strip() + "\n"


def _trend(now: float, before: float) -> str:
    if abs(now - before) < 0.0005:
        return "in line with"
    return "up from" if now > before else "down from"


def _relative(x: float, median: float, kind: str = "valuation") -> str:
    if abs(x / median - 1) < 0.05:
        return "in line with"
    if kind == "valuation":
        return "a premium to" if x > median else "a discount to"
    return "above" if x > median else "below"


# -- LLM mode -----------------------------------------------------------------
WRITER_SYSTEM = """You are the Writer in an equity research team. You write a short research note \
(about 600 words) from a research pack. Rules you must follow exactly:

1. Every number you write must be copied character-for-character from a pack line's display string \
and be immediately followed by that line's id in square brackets, e.g. "revenue of $10,229.9m [S1]".
2. Never calculate, round, convert or combine numbers. If you want a comparison, use words \
("higher than", "a premium to") only when the pack's numbers show it.
3. Always say which fiscal year a figure is for, using the form FY2025.
4. Quote risk factors or business descriptions only from the qualitative section, with their id.
5. Sections, in order: ## Business, ## Recent performance, ## Margins and returns, \
## Balance sheet and cash flow, ## Valuation versus peers, ## Key risks (exactly 3).
6. Write plain markdown. Start with a level-1 title. Do not include a table."""

REVISE_SYSTEM = WRITER_SYSTEM + """

You are now revising your note after a fact-check. Fix every issue listed: replace a wrong number \
with the correct display string and id given, fix a wrong fiscal year, and delete any sentence \
that contains an unverifiable number. Change nothing else. Return the whole revised note."""


def pack_prompt(pack: ResearchPack) -> str:
    lines = [f"Company: {pack.company} ({pack.ticker}); latest fiscal year FY{pack.fiscal_year}.",
             "", "Numbers (id: what = display string):"]
    lines += [s.brief() for s in pack.ledger.sources.values()
              if s.value is not None and (s.ticker == pack.ticker or s.kind == "computed")]
    lines += ["", "Peer comparison (same metric, other companies):"]
    for metric in ("ev_ebitda", "ev_sales", "pe"):
        for r in pack.comps["rows"]:
            cell = r["cells"].get(metric)
            if r["ticker"] != pack.ticker and cell and cell["source_id"]:
                lines.append(f"{cell['source_id']}: {r['ticker']} FY{r['fiscal_year']} "
                             f"{LABELS[metric]} = {cell['display']}")
    lines += ["", "Qualitative (id: text):"]
    lines += [f"{q['source_id']}: [{q['kind']}] {q['text']}" for q in pack.qualitative if q.get("source_id")]
    return "\n".join(lines)


def _llm_write(pack: ResearchPack, tracer: Tracer) -> str:
    llm = LLM("strong", tracer=tracer, agent="writer")
    return llm.chat(WRITER_SYSTEM, [{"role": "user", "content": pack_prompt(pack)}]).text.strip() + "\n"


def revise(draft: Draft, report, pack: ResearchPack, tracer: Tracer = NULL_TRACER) -> Draft:
    """Fix the issues the fact-checker found. One call = one revision round."""
    issues = [c for c in report.claims if c.status != "verified"]
    tracer.event("agent_start", "writer", step="revise", n_issues=len(issues))
    if draft.mode == "llm":
        llm = LLM("strong", tracer=tracer, agent="writer")
        listing = "\n".join(issue_line(c) for c in issues)
        user = f"{pack_prompt(pack)}\n\nYour note:\n{draft.note}\n\nFact-check issues:\n{listing}"
        note = llm.chat(REVISE_SYSTEM, [{"role": "user", "content": user}]).text.strip() + "\n"
    else:
        note = apply_fixes(draft.note, issues)
    tracer.event("agent_end", "writer", step="revise")
    return Draft(note, draft.comps_table, draft.mode)


def issue_line(c) -> str:
    if c.status == "wrong":
        fix = f"should be {c.correct_display} [{c.ref}]" if c.correct_display else ""
        if c.correct_year:
            fix += f" for FY{c.correct_year}"
        return f'- WRONG "{c.sentence.strip()[:200]}": {c.value_text} — {c.reason}; {fix}'
    return f'- UNVERIFIABLE "{c.sentence.strip()[:200]}": {c.value_text} — {c.reason}; delete the sentence'


def apply_fixes(note: str, issues: list) -> str:
    """Deterministic revision: patch wrong values and years, drop sentences that can't be fixed."""
    drop, edits = set(), []   # sentence spans to delete; (start, end, replacement)
    for c in issues:
        span = (c.sentence_start, c.sentence_start + len(c.sentence))
        if c.status == "unverifiable" or not (c.correct_display or c.correct_year):
            drop.add(span)
            continue
        if c.correct_display and c.value_text != c.correct_display:
            edits.append((c.start, c.end, c.correct_display))
        if c.correct_year and c.year_span:
            edits.append((c.year_span[0], c.year_span[1], f"FY{c.correct_year}"))
    edits = [e for e in edits if not any(s <= e[0] < t for s, t in drop)]
    edits += [(s, t, "") for s, t in drop]
    for s, e, rep in sorted(set(edits), key=lambda x: -x[0]):
        note = note[:s] + rep + note[e:]
    note = re.sub(r"[ \t]{2,}", " ", note)
    return re.sub(r" +\n", "\n", note)
