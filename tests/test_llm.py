"""LLM adapter: message conversion, replay cache and cost, without any API key."""
import json

import pytest

from verity import llm as L


def test_anthropic_conversion_groups_tool_results():
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "a", "name": "get_metric", "input": {"x": 1}},
                {"id": "b", "name": "get_price", "input": {}}]},
            {"role": "tool", "tool_call_id": "a", "name": "get_metric", "content": "{}"},
            {"role": "tool", "tool_call_id": "b", "name": "get_price", "content": "{}", "is_error": True}]
    out = L._to_anthropic(msgs)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert [b["type"] for b in out[1]["content"]] == ["tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["a", "b"]
    assert out[2]["content"][1]["is_error"] is True


def test_raw_assistant_content_is_echoed_unchanged():
    raw = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "ok"}]
    out = L._to_anthropic([{"role": "user", "content": "q"},
                           {"role": "assistant", "content": "ok", "raw": raw}])
    assert out[1]["content"] is raw


def test_openai_conversion():
    out = L._to_openai("sys", [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "a", "name": "f", "input": {"k": 1}}]},
        {"role": "tool", "tool_call_id": "a", "name": "f", "content": "{}"}])
    assert out[0] == {"role": "system", "content": "sys"}
    assert json.loads(out[1]["tool_calls"][0]["function"]["arguments"]) == {"k": 1}
    assert out[2]["tool_call_id"] == "a"


def test_cost():
    assert L.cost("claude-opus-5-5", 1_000_000, 100_000) == pytest.approx(4.0 + 2.0)
    assert L.cost("unknown-model", 10, 10) == 0.0


def test_record_then_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("VERITY_PROVIDER", "anthropic")
    calls = []

    def fake(self, system, messages, tools, max_tokens):
        calls.append(1)
        return L.Reply("answer", [L.ToolCall("t1", "get_metric", {"a": 1})], "tool_use",
                       self.model, 100, 20)
    monkeypatch.setattr(L.LLM, "_anthropic", fake)

    monkeypatch.setenv("VERITY_LLM_CACHE", "auto")
    first = L.LLM("strong").chat("sys", [{"role": "user", "content": "q"}])
    assert not first.cached and first.cost_usd > 0 and len(calls) == 1

    monkeypatch.setenv("VERITY_LLM_CACHE", "replay")
    again = L.LLM("strong").chat("sys", [{"role": "user", "content": "q"}])
    assert again.cached and again.text == "answer" and again.tool_calls[0].name == "get_metric"
    assert len(calls) == 1
    with pytest.raises(L.ReplayMiss):
        L.LLM("strong").chat("sys", [{"role": "user", "content": "different"}])


def test_tool_loop(monkeypatch, tmp_path):
    monkeypatch.setattr(L, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("VERITY_PROVIDER", "anthropic")
    replies = iter([L.Reply("", [L.ToolCall("1", "get_metric", {"m": "revenue"})], "tool_use"),
                    L.Reply("done", [], "end_turn")])
    monkeypatch.setattr(L.LLM, "_anthropic", lambda *a: next(replies))
    seen = []
    reply, msgs = L.run_tool_loop(L.LLM("fast"), "sys", "go", [], lambda n, a: seen.append(n) or {"v": 1})
    assert reply.text == "done" and seen == ["get_metric"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]
