"""Groq OpenAI-compatible client with deterministic replay and model fallback."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audit import AuditLogger
from .config import Settings


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    content: str
    tool_calls: tuple[ToolCall, ...]
    model: str
    usage: dict[str, int]


class LLMClient:
    """Call Groq in live mode or serve recorded responses in replay mode."""

    def __init__(self, settings: Settings | None = None, audit: AuditLogger | None = None, client: Any | None = None):
        self.settings = settings or Settings.from_env()
        self.audit = audit
        self._client = client
        self._replay_index = 0

    def _replay_response(self, messages: list[dict[str, str]]) -> LLMResponse:
        records: list[dict[str, Any]] = []
        replay_path = Path(self.settings.replay_file)
        if replay_path.exists():
            raw = json.loads(replay_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                records = raw.get("responses", [])
            elif isinstance(raw, list):
                records = raw
        record = records[min(self._replay_index, len(records) - 1)] if records else {
            "content": "I will use the deterministic advisory tools for this request.",
            "tool_calls": [],
        }
        self._replay_index += 1
        calls = tuple(
            ToolCall(call.get("id", f"replay-{index}"), call["name"], call.get("arguments", {}) if isinstance(call.get("arguments", {}), dict) else {"_malformed_arguments": call.get("arguments")})
            for index, call in enumerate(record.get("tool_calls", []))
        )
        return LLMResponse(record.get("content", ""), calls, "replay", record.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}))

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        """Return one model response and audit its model name and token usage."""

        started = time.perf_counter()
        if self.settings.llm_mode == "replay":
            response = self._replay_response(messages)
        else:
            if not self.settings.groq_api_key:
                raise RuntimeError("GROQ_API_KEY is required when LLM_MODE is live")
            from openai import OpenAI

            if self._client is None:
                self._client = OpenAI(api_key=self.settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
            response = None
            last_error: Exception | None = None
            retry_after_seconds = 0.0
            for model in (self.settings.primary_model, *self.settings.fallback_models):
                try:
                    kwargs: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0}
                    if tools:
                        kwargs["tools"] = tools
                    if model.startswith("openai/gpt-oss"):
                        kwargs["reasoning_effort"] = "low"
                        if tools:
                            kwargs["extra_body"] = {"reasoning_format": "hidden"}
                    raw = self._client.chat.completions.create(**kwargs)
                    message = raw.choices[0].message
                    parsed_calls = []
                    for call in (message.tool_calls or []):
                        try:
                            arguments = json.loads(call.function.arguments or "{}")
                            if not isinstance(arguments, dict):
                                raise ValueError("tool arguments must be a JSON object")
                        except (TypeError, ValueError, json.JSONDecodeError):
                            arguments = {"_malformed_arguments": call.function.arguments}
                        parsed_calls.append(ToolCall(call.id, call.function.name, arguments))
                    calls = tuple(parsed_calls)
                    usage = {
                        "prompt_tokens": getattr(raw.usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(raw.usage, "completion_tokens", 0) or 0,
                        "total_tokens": getattr(raw.usage, "total_tokens", 0) or 0,
                    }
                    response = LLMResponse(message.content or "", calls, model, usage)
                    break
                except Exception as exc:
                    last_error = exc
                    if getattr(exc, "status_code", None) == 429:
                        headers = getattr(getattr(exc, "response", None), "headers", {}) or getattr(exc, "headers", {})
                        retry_after = headers.get("retry-after") or headers.get("Retry-After")
                        if retry_after is not None:
                            retry_after_seconds = max(retry_after_seconds, min(float(retry_after), 20.0))
                    if self.audit:
                        body = getattr(exc, "body", None)
                        response_body = getattr(getattr(exc, "response", None), "text", None)
                        self.audit.append(
                            "llm_error",
                            {
                                "model": model,
                                "error": type(exc).__name__,
                                "status_code": getattr(exc, "status_code", None),
                                "body": body if body is not None else response_body or str(exc),
                            },
                        )
            if response is None and retry_after_seconds:
                time.sleep(retry_after_seconds)
            if response is None:
                raise RuntimeError("all Groq models failed") from last_error
        if self.audit:
            self.audit.append("llm_call", {"model": response.model, "usage": response.usage, "mode": self.settings.llm_mode, "latency_ms": (time.perf_counter() - started) * 1000})
        return response
