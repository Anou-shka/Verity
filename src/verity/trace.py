"""Run traces: one JSON line per agent step, tool call and LLM call.

Totals (LLM calls, tokens, cost, tool calls, time) are kept as the run goes
and written as the last line, so a trace file is a complete run record.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class Tracer:
    def __init__(self, path: Path | None = None, run_id: str = ""):
        self.path = path
        self.run_id = run_id
        self.t0 = time.monotonic()
        self.totals = {"llm_calls": 0, "llm_cache_hits": 0, "input_tokens": 0,
                       "output_tokens": 0, "cost_usd": 0.0, "tool_calls": 0}
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")

    def event(self, type: str, agent: str = "", **data) -> None:
        if type == "tool_call":
            self.totals["tool_calls"] += 1
        if type == "llm_call":
            self.totals["llm_calls"] += 1
            self.totals["llm_cache_hits"] += int(data.get("cached", False))
            self.totals["input_tokens"] += data.get("input_tokens", 0)
            self.totals["output_tokens"] += data.get("output_tokens", 0)
            self.totals["cost_usd"] += data.get("cost_usd", 0.0)
        if self.path:
            row = {"run_id": self.run_id, "t_ms": round((time.monotonic() - self.t0) * 1000),
                   "type": type, "agent": agent, **data}
            with self.path.open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")

    def finish(self) -> dict:
        totals = {**self.totals, "seconds": round(time.monotonic() - self.t0, 2),
                  "cost_usd": round(self.totals["cost_usd"], 6)}
        self.event("run_totals", **totals)
        return totals


NULL_TRACER = Tracer()
