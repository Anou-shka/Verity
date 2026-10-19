"""Experiments 1 and 2: extraction accuracy, and agent vs a no-tools baseline.

Questions: every company x 12 metrics x its latest 3 fiscal years (~360).
  agent     the Researcher's model answers with tools (get_metric etc.)
  baseline  one model call, no tools, same question
Each answer is scored against the XBRL ground truth (0.5% tolerance) and
every miss is typed: wrong year, wrong unit, wrong concept, made-up number,
or no answer.

Needs a model (VERITY_PROVIDER=anthropic|openai|ollama). Answers are cached
by the LLM adapter, so a second run with VERITY_LLM_CACHE=replay is free.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from verity.llm import LLM, llm_available, provider_name, run_tool_loop
from verity.tools import LABELS, TOOL_SCHEMAS, ToolBox, call_tool, universe
from verity.trace import Tracer

METRICS = ["revenue", "gross_profit", "operating_income", "net_income", "d_and_a", "eps_diluted",
           "total_assets", "total_equity", "cash", "total_debt", "operating_cash_flow", "capex"]
TOL = 0.005

AGENT_SYSTEM = """You answer questions about US-listed companies' annual financial statements. \
Use the tools to look the figure up; never answer from memory. Reply with JSON only: \
{"value": <number in full units, e.g. 10229900000 for $10.2bn, or 3.41 for EPS of $3.41>, \
"unit": "USD" or "USD/share"}. If you cannot find it, reply {"value": null}."""

BASELINE_SYSTEM = """You answer questions about US-listed companies' annual financial statements \
from your own knowledge. Reply with JSON only: {"value": <number in full units, e.g. 10229900000 \
for $10.2bn, or 3.41 for EPS of $3.41>, "unit": "USD" or "USD/share"}. If you do not know, reply \
{"value": null}."""


def questions(box: ToolBox | None = None) -> list[dict]:
    box = box or ToolBox()
    out = []
    for t in universe()["tickers"]:
        years = box.list_fiscal_years(t)["fiscal_years"][-3:]
        for fy in years:
            for m in METRICS:
                r = call_tool(box, "get_metric", {"ticker": t, "metric": m, "fiscal_year": fy})
                if "error" in r:
                    continue
                name = box.names[t]
                out.append({"ticker": t, "metric": m, "fiscal_year": fy, "truth": r["value"],
                            "unit": r["unit"],
                            "question": f"What was {name}'s ({t}) FY{fy} {LABELS[m]}, as reported "
                                        f"in its 10-K?"})
    return out


def classify(answer: float | None, q: dict, truths: dict) -> str:
    """correct, or the type of failure.

    truths maps (ticker, metric, fiscal_year) -> value for the whole universe.
    """
    if answer is None:
        return "no_answer"
    if _close(answer, q["truth"]):
        return "correct"
    t, m, fy = q["ticker"], q["metric"], q["fiscal_year"]
    for scale in (1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9):
        if _close(answer * scale, q["truth"]):
            return "wrong_unit"
    if any(_close(answer, v) for (tt, mm, y), v in truths.items() if tt == t and mm == m and y != fy):
        return "wrong_year"
    if any(_close(answer, v) for (tt, mm, y), v in truths.items() if tt == t and mm != m):
        return "wrong_concept"
    return "made_up"


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(abs(b) * TOL, 1e-9)


def parse_answer(text: str) -> float | None:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        v = json.loads(m.group(0)).get("value") if m else None
        return float(v) if v is not None else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def run(mode: str, qs: list[dict], tracer: Tracer) -> list[dict]:
    llm = LLM("fast", tracer=tracer, agent=f"eval_{mode}")
    out = []
    for q in qs:
        if mode == "agent":
            box = ToolBox()
            reply, _ = run_tool_loop(llm, AGENT_SYSTEM, q["question"], TOOL_SCHEMAS,
                                     lambda n, a: call_tool(box, n, a), max_turns=8)
        else:
            reply = llm.chat(BASELINE_SYSTEM, [{"role": "user", "content": q["question"]}], max_tokens=512)
        out.append({**q, "answer": parse_answer(reply.text)})
    return out


def score(rows: list[dict], truths: dict) -> dict:
    for r in rows:
        r["result"] = classify(r["answer"], r, truths)
    by_metric = defaultdict(Counter)
    for r in rows:
        by_metric[r["metric"]][r["result"]] += 1
    overall = Counter(r["result"] for r in rows)
    return {"n": len(rows), "accuracy": overall["correct"] / len(rows), "outcomes": dict(overall),
            "by_metric": {m: {"accuracy": c["correct"] / sum(c.values()), **c} for m, c in by_metric.items()}}


def main() -> dict:
    qs = questions()
    truths = {(q["ticker"], q["metric"], q["fiscal_year"]): q["truth"] for q in qs}
    if not llm_available():
        return {"status": "pending", "n_questions": len(qs),
                "reason": "needs a model: set VERITY_PROVIDER and an API key, then `make eval`"}
    tracer = Tracer()
    result = {"status": "done", "provider": provider_name(), "n_questions": len(qs)}
    for mode in ("agent", "baseline"):
        before = dict(tracer.totals)
        rows = run(mode, qs, tracer)
        result[mode] = score(rows, truths)
        result[mode]["cost"] = {k: tracer.totals[k] - before[k] for k in
                                ("llm_calls", "input_tokens", "output_tokens", "cost_usd")}
        result[mode]["failures"] = [r for r in rows if r["result"] != "correct"][:50]
    return result


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, default=str)[:3000])
