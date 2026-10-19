"""LLM mode end to end with a scripted fake model (no API key, no cost).

Checks that the researcher's tool loop, the LLM writer, the revision call and
the fact-checker's qualitative flags all run, and that a wrong number the
"model" writes is caught and fixed.
"""
import json
import re

import pytest

from verity import llm as L
from verity.orchestrator import run


def fake_model(self, system, messages, tools, max_tokens):
    user = messages[0]["content"]
    if system.startswith("You are the Researcher"):
        if len(messages) == 1:     # first turn: call a tool
            return L.Reply("", [L.ToolCall("t1", "get_metric",
                                           {"ticker": "VRT", "metric": "revenue", "fiscal_year": 2025}),
                                L.ToolCall("t2", "get_filing_section", {"ticker": "VRT", "section": "business"})],
                           "tool_use", self.model, 500, 50)
        biz = json.loads(messages[-1]["content"])["source_id"]
        return L.Reply(json.dumps({"business": {"text": "Vertiv makes data-centre power and cooling equipment.",
                                                "source_id": biz},
                                   "risks": [{"text": "Customer concentration.", "source_id": biz}]}),
                       [], "end_turn", self.model, 800, 120)
    if system.startswith("You check research notes"):
        return L.Reply('{"flags": []}', [], "end_turn", self.model, 300, 10)
    rev = re.search(r"(S\d+): VRT FY2025 revenue = (\S+)", user)
    if "Fact-check issues" in user:     # revision: use the correction offered
        fix = re.search(r"should be (\S+) \[(S\d+)\]", user)
        text = f"# Vertiv\n\n## Recent performance\nFY2025 revenue was {fix.group(1)} [{fix.group(2)}].\n"
    else:                               # first draft: get the number wrong on purpose
        text = f"# Vertiv\n\n## Recent performance\nFY2025 revenue was $10,529.9m [{rev.group(1)}].\n"
    return L.Reply(text, [], "end_turn", self.model, 2000, 300)


def test_llm_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(L, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("VERITY_PROVIDER", "anthropic")
    monkeypatch.setattr(L.LLM, "_anthropic", fake_model)
    res = run("VRT", write_outputs=False)
    assert res.pack.mode == "llm"
    first, last = res.reports[0], res.reports[-1]
    assert [c.status for c in first.claims] == ["wrong"]
    assert [c.status for c in last.claims] == ["verified"]
    assert "$10,229.9m" in res.final.note
    t = res.totals
    assert t["llm_calls"] >= 5 and t["cost_usd"] > 0 and t["tool_calls"] >= 2
