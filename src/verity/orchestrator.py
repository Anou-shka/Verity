"""Orchestrator: Researcher -> Writer -> Fact-checker -> (revise -> check) -> final.

A plain state machine. Each state does one thing and names the next state;
every step is written to the run trace.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .agents import fact_checker as fc
from .agents import researcher, writer
from .config import ROOT
from .derived import load_settings
from .llm import llm_available, provider_name
from .tools import ToolBox
from .trace import Tracer

OUTPUTS, TRACES = ROOT / "outputs", ROOT / "traces"


@dataclass
class RunResult:
    ticker: str
    pack: researcher.ResearchPack
    drafts: list[writer.Draft] = field(default_factory=list)
    reports: list[fc.Report] = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    run_id: str = ""

    @property
    def final(self) -> writer.Draft:
        return self.drafts[-1]


def run(ticker: str, use_llm: bool | None = None, write_outputs: bool = True,
        trace_path: Path | None = None, run_id: str | None = None) -> RunResult:
    use_llm = llm_available() if use_llm is None else use_llm
    mode = provider_name() if use_llm else "rules"
    run_id = run_id or f"{ticker.upper()}-{mode}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
    tracer = Tracer(trace_path or (TRACES / f"{run_id}.jsonl" if write_outputs else None), run_id)
    max_rounds = load_settings()["max_revision_rounds"]
    box = ToolBox()
    tracer.event("run_start", ticker=ticker.upper(), mode=mode)

    state, rounds = "research", 0
    result: RunResult | None = None
    checker: fc.FactChecker | None = None
    while state != "done":
        tracer.event("state", state=state, round=rounds)
        if state == "research":
            pack = researcher.research(ticker, box, tracer, use_llm=use_llm)
            result = RunResult(pack.ticker, pack, run_id=run_id)
            checker = fc.FactChecker(box.ledger, tracer)
            state = "write"
        elif state == "write":
            result.drafts.append(writer.write(result.pack, tracer, use_llm=use_llm))
            state = "check"
        elif state == "check":
            report = checker.check(result.final.note, result.pack.comps, round_=rounds,
                                   use_llm=use_llm)
            result.reports.append(report)
            needs_fix = any(c.status != "verified" for c in report.claims)
            state = "revise" if needs_fix and rounds < max_rounds else "done"
        elif state == "revise":
            result.drafts.append(writer.revise(result.final, result.reports[-1], result.pack, tracer))
            rounds += 1
            state = "check"
    result.totals = tracer.finish()
    if write_outputs:
        save(result)
    return result


def final_log(result: RunResult) -> list[dict]:
    """One row per claim in the final note, plus claims removed during revision.

    Status is verified, corrected (wrong in an earlier round, right now),
    wrong (still wrong after the last round) or unverifiable.
    """
    first, last = result.reports[0], result.reports[-1]
    wrong_before = {(c.ref, c.correct_display) for r in result.reports[:-1] for c in r.claims
                    if c.status == "wrong"}
    wrong_refs = {ref for ref, _ in wrong_before}
    rows = []
    for c in last.claims:
        status = c.status
        if status == "verified" and c.ref in wrong_refs and len(result.reports) > 1:
            status = "corrected"
        rows.append({**c.to_json(), "final_status": status})
    final_spans = {(c.value_text, c.ref) for c in last.claims}
    for r in result.reports[:-1]:
        for c in r.claims:
            if c.status == "unverifiable" and (c.value_text, c.ref) not in final_spans:
                rows.append({**c.to_json(), "final_status": "removed (unverifiable)"})
                final_spans.add((c.value_text, c.ref))
    return rows


def save(result: RunResult) -> Path:
    out = OUTPUTS / result.ticker
    out.mkdir(parents=True, exist_ok=True)
    final = result.final
    (out / "note.md").write_text(final.note + "\n## Peer comparison\n\n" + final.comps_table + "\n")
    if len(result.drafts) > 1:
        (out / "draft_round0.md").write_text(result.drafts[0].note)
    (out / "research_pack.json").write_text(json.dumps(result.pack.to_json(), indent=1, default=str))
    log = {"run_id": result.run_id, "ticker": result.ticker, "mode": result.pack.mode,
           "rounds": [r.summary() for r in result.reports], "totals": result.totals,
           "claims": final_log(result), "quotes": result.reports[-1].quotes,
           "table": result.reports[-1].table,
           "qualitative_flags": result.reports[-1].qualitative_flags}
    (out / "factcheck.json").write_text(json.dumps(log, indent=1, default=str))
    rows = result.pack.comps["rows"]
    import csv
    with (out / "comps.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "company", "fiscal_year"] + result.pack.comps["metrics"])
        for r in rows:
            w.writerow([r["ticker"], r["company"], r["fiscal_year"]] +
                       [r["cells"][m]["value"] for m in result.pack.comps["metrics"]])
    (out / "factcheck.md").write_text(factcheck_markdown(log))
    return out


def factcheck_markdown(log: dict) -> str:
    lines = [f"# Fact-check log: {log['ticker']} ({log['mode']} mode)", ""]
    lines += ["| Round | Claims | Verified | Wrong | Unverifiable |", "|---|---:|---:|---:|---:|"]
    lines += [f"| {r['round']} | {r['claims']} | {r['verified']} | {r['wrong']} | {r['unverifiable']} |"
              for r in log["rounds"]]
    t = log["totals"]
    lines += ["", f"Run: {t['llm_calls']} LLM calls ({t['llm_cache_hits']} from cache), "
              f"{t['input_tokens']:,} input + {t['output_tokens']:,} output tokens, "
              f"${t['cost_usd']:.4f}, {t['tool_calls']} tool calls, {t['seconds']}s.", ""]
    lines += ["| Claim | Status | Source | Note |", "|---|---|---|---|"]
    for c in log["claims"]:
        note = c["reason"] or ""
        lines.append(f"| {c['value_text']} | {c['final_status']} | {c['source'] or c['ref'] or '-'} | {note} |")
    lines += ["", "## Quotes", "", "| Quote | Status | Filing |", "|---|---|---|"]
    lines += [f"| {q['quote'][:90]}… | {q['status']} | {q.get('accession', '')} |" for q in log["quotes"]]
    tb = log["table"]
    lines += ["", f"Comps table: {tb.get('cells', 0)} cells re-fetched, {tb.get('wrong', 0)} mismatches."]
    return "\n".join(lines) + "\n"
