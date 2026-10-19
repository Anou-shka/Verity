"""Model adapter: Anthropic, OpenAI or a local Ollama model, plus a replay cache.

Agents talk to one small interface, `LLM.chat(system, messages, tools)`, in a
provider-neutral message format:

    {"role": "user", "content": "..."}
    {"role": "assistant", "content": "...", "tool_calls": [{"id", "name", "input"}]}
    {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}

Replay cache: every response is stored under data/llm_cache/ keyed by a hash
of the request. VERITY_LLM_CACHE=replay serves only from the cache (no key,
no cost); "auto" (default) uses the cache and calls the model on a miss.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field

from .config import DATA_DIR
from .trace import NULL_TRACER, Tracer

CACHE_DIR = DATA_DIR / "llm_cache"

# USD per million tokens (input, output). Unknown models are costed at 0 and
# flagged in the trace.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
DEFAULT_MODELS = {
    "anthropic": {"fast": "claude-haiku-5-5", "strong": "claude-opus-5-5"},
    "openai": {"fast": "", "strong": ""},          # set VERITY_FAST_MODEL / VERITY_STRONG_MODEL
    "ollama": {"fast": "llama3.1:8b", "strong": "llama3.1:8b"},
}
# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}


class LLMError(Exception):
    pass


class ReplayMiss(LLMError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw: list | None = None          # provider content blocks, echoed back unchanged
    cached: bool = False

    def as_message(self) -> dict:
        msg = {"role": "assistant", "content": self.text,
               "tool_calls": [asdict(c) for c in self.tool_calls]}
        if self.raw is not None:
            msg["raw"] = self.raw
        return msg


def provider_name() -> str:
    return os.getenv("VERITY_PROVIDER", "rules").lower()


def llm_available() -> bool:
    """True when agents should use a model rather than the rules path."""
    return provider_name() in ("anthropic", "openai", "ollama")


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = PRICES.get(model, (0.0, 0.0))
    return (input_tokens * p_in + output_tokens * p_out) / 1e6


class LLM:
    def __init__(self, role: str = "strong", provider: str | None = None,
                 tracer: Tracer = NULL_TRACER, agent: str = ""):
        self.provider = (provider or provider_name()).lower()
        if self.provider not in DEFAULT_MODELS:
            raise LLMError(f"VERITY_PROVIDER={self.provider!r}: use anthropic, openai or ollama")
        env = "VERITY_FAST_MODEL" if role == "fast" else "VERITY_STRONG_MODEL"
        self.model = os.getenv(env) or DEFAULT_MODELS[self.provider][role]
        if not self.model:
            raise LLMError(f"set {env} for provider {self.provider}")
        self.effort = os.getenv("VERITY_EFFORT", "medium")
        self.cache_mode = os.getenv("VERITY_LLM_CACHE", "auto")
        self.tracer, self.agent = tracer, agent

    # -- public ---------------------------------------------------------
    def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int = 16000) -> Reply:
        key = self._key(system, messages, tools, max_tokens)
        path = CACHE_DIR / key[:2] / f"{key}.json"
        t0 = time.monotonic()
        if self.cache_mode != "off" and path.exists():
            reply = Reply(**{**json.loads(path.read_text()), "cached": True})
            reply.tool_calls = [ToolCall(**c) for c in reply.tool_calls]
        elif self.cache_mode == "replay":
            raise ReplayMiss(f"no cached response for {self.agent} call {key[:12]} "
                             f"(VERITY_LLM_CACHE=replay)")
        else:
            reply = getattr(self, f"_{self.provider}")(system, messages, tools, max_tokens)
            reply.cost_usd = cost(reply.model or self.model, reply.input_tokens, reply.output_tokens)
            if self.cache_mode != "off":
                path.parent.mkdir(parents=True, exist_ok=True)
                body = asdict(reply)
                body.pop("cached")
                path.write_text(json.dumps(body, default=str))
        self.tracer.event("llm_call", self.agent, provider=self.provider, model=reply.model or self.model,
                          cached=reply.cached, input_tokens=reply.input_tokens,
                          output_tokens=reply.output_tokens,
                          cost_usd=0.0 if reply.cached else reply.cost_usd,
                          price_known=self.model in PRICES or self.provider == "ollama",
                          stop_reason=reply.stop_reason, n_tool_calls=len(reply.tool_calls),
                          ms=round((time.monotonic() - t0) * 1000))
        return reply

    def _key(self, system, messages, tools, max_tokens) -> str:
        neutral = [{k: v for k, v in m.items() if k != "raw"} for m in messages]
        blob = json.dumps({"provider": self.provider, "model": self.model, "effort": self.effort,
                           "system": system, "messages": neutral, "tools": tools or [],
                           "max_tokens": max_tokens}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    # -- Anthropic --------------------------------------------------------
    def _anthropic(self, system, messages, tools, max_tokens) -> Reply:
        import anthropic

        client = anthropic.Anthropic()
        kwargs = {"model": self.model, "max_tokens": max_tokens, "system": system,
                  "messages": _to_anthropic(messages),
                  "output_config": {"effort": self.effort}}
        if tools:
            kwargs["tools"] = tools
        if self.model in FALLBACK_MODELS:
            # On a safety-classifier decline, the API re-runs the request on
            # Anthropic's recommended fallback model instead of refusing.
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        try:
            resp = client.beta.messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"cannot reach the Anthropic API: {e}") from e
        if resp.stop_reason == "refusal":
            raise LLMError(f"model declined the request ({getattr(resp, 'stop_details', None)})")
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        return Reply(text, calls, resp.stop_reason, resp.model, resp.usage.input_tokens,
                     resp.usage.output_tokens,
                     raw=[b.model_dump(exclude_none=True) for b in resp.content])

    # -- OpenAI -----------------------------------------------------------
    def _openai(self, system, messages, tools, max_tokens) -> Reply:
        from openai import OpenAI

        client = OpenAI()
        kwargs = {"model": self.model, "messages": _to_openai(system, messages),
                  "max_completion_tokens": max_tokens}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"],
                "parameters": t["input_schema"]}} for t in tools]
        resp = client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = [ToolCall(c.id, c.function.name, json.loads(c.function.arguments or "{}"))
                 for c in (msg.tool_calls or [])]
        return Reply(msg.content or "", calls, resp.choices[0].finish_reason, resp.model,
                     resp.usage.prompt_tokens, resp.usage.completion_tokens)

    # -- Ollama -----------------------------------------------------------
    def _ollama(self, system, messages, tools, max_tokens) -> Reply:
        import requests

        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        body = {"model": self.model, "stream": False, "options": {"num_predict": max_tokens},
                "messages": _to_openai(system, messages, ollama=True)}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"],
                "parameters": t["input_schema"]}} for t in tools]
        try:
            r = requests.post(f"{host}/api/chat", json=body, timeout=600)
            r.raise_for_status()
        except requests.RequestException as e:
            raise LLMError(f"Ollama call failed: {e}") from e
        data = r.json()
        msg = data.get("message", {})
        calls = [ToolCall(f"call_{i}", c["function"]["name"], c["function"].get("arguments") or {})
                 for i, c in enumerate(msg.get("tool_calls") or [])]
        return Reply(msg.get("content", ""), calls, data.get("done_reason", ""), self.model,
                     data.get("prompt_eval_count", 0), data.get("eval_count", 0))


# -- message format conversion ---------------------------------------------
def _to_anthropic(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            if m.get("raw") is not None:
                out.append({"role": "assistant", "content": m["raw"]})
                continue
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["input"]}
                       for c in m.get("tool_calls", [])]
            out.append({"role": "assistant", "content": blocks})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if m.get("is_error"):
                block["is_error"] = True
            # all results for one assistant turn go back in a single user message
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def _to_openai(system: str, messages: list[dict], ollama: bool = False) -> list[dict]:
    out = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "assistant":
            msg = {"role": "assistant", "content": m.get("content", "")}
            if m.get("tool_calls"):
                msg["tool_calls"] = [{"id": c["id"], "type": "function", "function": {
                    "name": c["name"],
                    "arguments": c["input"] if ollama else json.dumps(c["input"])}}
                    for c in m["tool_calls"]]
            out.append(msg)
        elif m["role"] == "tool":
            msg = {"role": "tool", "content": m["content"]}
            msg["tool_name" if ollama else "tool_call_id"] = m["name"] if ollama else m["tool_call_id"]
            out.append(msg)
        else:
            out.append({"role": "user", "content": m["content"]})
    return out


def run_tool_loop(llm: LLM, system: str, user: str, tools: list[dict], execute,
                  max_turns: int = 30) -> tuple[Reply, list[dict]]:
    """The agent loop: ask, run the tools it asks for, repeat until it stops.

    `execute(name, input) -> dict` runs one tool. Errors go back to the
    model as tool results so it can correct itself.
    """
    messages: list[dict] = [{"role": "user", "content": user}]
    for _ in range(max_turns):
        reply = llm.chat(system, messages, tools)
        messages.append(reply.as_message())
        if not reply.tool_calls:
            return reply, messages
        for call in reply.tool_calls:
            result = execute(call.name, call.input)
            messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                             "content": json.dumps(result, default=str)[:20000],
                             "is_error": "error" in result})
    raise LLMError(f"agent did not finish within {max_turns} turns")
