"""OpenAI-compatible provider failover with deterministic offline replay."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .audit import AuditLogger
from .config import ProviderConfig, Settings


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
    provider: str = "replay"
    key_index: int | None = None


class LLMClient:
    """Call ordered providers in live mode or recorded responses in replay mode."""

    def __init__(
        self,
        settings: Settings | None = None,
        audit: AuditLogger | None = None,
        client: Any | None = None,
        provider_clients: dict[Any, Any] | None = None,
        providers: tuple[ProviderConfig, ...] | None = None,
    ):
        self.settings = settings or Settings.from_env()
        self.audit = audit
        self._client = client
        self._provider_clients = dict(provider_clients or {})
        self._providers_override = providers
        self._cooldowns: dict[tuple[str, int, str], float] = {}
        self._daily_cooldowns: set[tuple[str, int]] = set()
        self._key_organizations: dict[tuple[str, int], str] = {}
        self._replay_index = 0

    def _configured_providers(self) -> tuple[ProviderConfig, ...]:
        if self._providers_override is not None:
            return self._providers_override
        if self.settings.providers:
            return self.settings.providers
        return (
            ProviderConfig(
                "groq",
                "https://api.groq.com/openai/v1",
                "GROQ_API_KEY",
                (self.settings.primary_model, *self.settings.fallback_models),
                self.settings.groq_api_key,
                self.settings.groq_api_keys,
            ),
            ProviderConfig(
                "cerebras",
                "https://api.cerebras.ai/v1",
                "CEREBRAS_API_KEY",
                self.settings.cerebras_models,
                self.settings.cerebras_api_key,
            ),
        )

    def _provider_keys(self, provider: ProviderConfig) -> tuple[str, ...]:
        ordered = (*provider.api_keys, provider.api_key or os.getenv(provider.api_key_env) or "")
        return tuple(dict.fromkeys(key for key in ordered if key))

    def _provider_client(self, provider: ProviderConfig, key_index: int, key: str) -> Any:
        cache_key = (provider.name, key_index)
        if cache_key in self._provider_clients:
            return self._provider_clients[cache_key]
        if provider.name in self._provider_clients:
            return self._provider_clients[provider.name]
        if self._client is not None and not self._provider_clients:
            self._provider_clients[cache_key] = self._client
            return self._client
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=provider.base_url)
        self._provider_clients[cache_key] = client
        return client

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status == 429 or isinstance(status, int) and status >= 500:
            return True
        name = type(exc).__name__.casefold()
        text = str(exc).casefold()
        if "timeout" in name or "timeout" in text:
            return True
        return any(term in text for term in ("quota", "rate limit", "too many requests", "temporarily unavailable"))

    @staticmethod
    def _daily_quota(exc: Exception) -> bool:
        message = str(getattr(exc, "body", None) or exc).casefold()
        return any(term in message for term in ("tokens per day", "requests per day", "daily quota", "tpd", "rpd"))

    @staticmethod
    def _organization(exc: Exception) -> str | None:
        message = str(getattr(exc, "body", None) or exc)
        match = re.search(r"\b(?:organization|org)(?:\s+id)?\s*[:=]?\s*[`'\"]?([a-z0-9_-]{4,})", message, re.I)
        return match.group(1) if match else None

    @staticmethod
    def _retry_after(exc: Exception) -> float | None:
        headers = getattr(getattr(exc, "response", None), "headers", {}) or getattr(exc, "headers", {})
        value = headers.get("retry-after") or headers.get("Retry-After")
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _seconds_until_next_utc_day() -> float:
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return (tomorrow - now).total_seconds()

    def _cool_key(self, provider: ProviderConfig, key_index: int, model: str, exc: Exception) -> float:
        daily = self._daily_quota(exc)
        duration = self._seconds_until_next_utc_day() if daily else self._retry_after(exc) or 60.0
        organization = self._organization(exc)
        if organization:
            self._key_organizations[(provider.name, key_index)] = organization
        indices = [key_index]
        if daily:
            self._daily_cooldowns.add((provider.name, key_index))
        until = time.monotonic() + duration
        models = provider.models if daily else (model,)
        for index in indices:
            for cooled_model in models:
                cooldown_key = (provider.name, index, cooled_model)
                self._cooldowns[cooldown_key] = max(until, self._cooldowns.get(cooldown_key, 0.0))
            if self.audit:
                self.audit.append("llm_key_cooldown", {"provider": provider.name, "key_index": index, "organization": organization, "seconds": duration, "daily_quota": daily})
        return duration

    def _safe_error(self, exc: Exception) -> str:
        body = getattr(exc, "body", None)
        response_body = getattr(getattr(exc, "response", None), "text", None)
        message = str(body if body is not None else response_body or exc)
        for provider in self._configured_providers():
            for key in self._provider_keys(provider):
                message = message.replace(key, "[REDACTED_API_KEY]")
        return message

    def _replay_response(self, messages: list[dict[str, str]]) -> LLMResponse:
        records: list[dict[str, Any]] = []
        replay_path = Path(self.settings.replay_file)
        if replay_path.exists():
            raw = json.loads(replay_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                records = raw.get("responses", [])
            elif isinstance(raw, list):
                records = raw
        if self._replay_index < len(records):
            record = records[self._replay_index]
        else:
            client_text = next(
                (str(message.get("content", "")) for message in reversed(messages) if message.get("role") == "user"),
                "",
            )
            if any("\u4e00" <= character <= "\u9fff" for character in client_text):
                content = "实时对话需要在 .env 中设置 GROQ_API_KEY，并将 LLM_MODE=live。问卷、投资组合、崩溃演练、目标、比较、压力测试、执行和报告等其他步骤都可以离线运行。"
            else:
                content = "Live conversation needs a GROQ_API_KEY in .env and LLM_MODE=live. Every other step (questionnaire, portfolio, rehearsal, goal, comparison, stress test, execution, report) works offline."
            record = {"content": content, "tool_calls": []}
        self._replay_index += 1
        calls = tuple(
            ToolCall(call.get("id", f"replay-{index}"), call["name"], call.get("arguments", {}) if isinstance(call.get("arguments", {}), dict) else {"_malformed_arguments": call.get("arguments")})
            for index, call in enumerate(record.get("tool_calls", []))
        )
        return LLMResponse(record.get("content", ""), calls, "replay", record.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}))

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        """Return one response, trying keys then models then providers in order."""

        started = time.perf_counter()
        if self.settings.llm_mode == "replay":
            response = self._replay_response(messages)
        else:
            response = self._live_response(messages, tools)
        if self.audit:
            self.audit.append("llm_call", {
                "provider": response.provider,
                "model": response.model,
                "key_index": response.key_index,
                "usage": response.usage,
                "prompt_tokens": response.usage["prompt_tokens"],
                "completion_tokens": response.usage["completion_tokens"],
                "total_tokens": response.usage["total_tokens"],
                "mode": self.settings.llm_mode,
                "latency_ms": (time.perf_counter() - started) * 1000,
            })
        return response

    def _parse_response(self, raw: Any, provider: str, model: str, key_index: int) -> LLMResponse:
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
        usage = {
            "prompt_tokens": getattr(raw.usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(raw.usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(raw.usage, "total_tokens", 0) or 0,
        }
        return LLMResponse(message.content or "", tuple(parsed_calls), model, usage, provider, key_index)

    def _live_response(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> LLMResponse:
        last_error: Exception | None = None
        for chain_attempt in range(3):
            all_retryable = True
            configured_keys = 0
            retry_after_values: list[float] = []
            for provider in self._configured_providers():
                keys = self._provider_keys(provider)
                if not keys:
                    if self.audit:
                        self.audit.append("llm_provider_skipped", {"provider": provider.name, "reason": "missing_api_key", "api_key_env": provider.api_key_env})
                    continue
                configured_keys += len(keys)
                provider_unavailable = False
                for model in provider.models:
                    for key_index, key in enumerate(keys):
                        cooldown_active = self._cooldowns.get((provider.name, key_index, model), 0.0) > time.monotonic()
                        daily_cooldown_active = (provider.name, key_index) in self._daily_cooldowns and cooldown_active
                        if cooldown_active and (chain_attempt == 0 or daily_cooldown_active):
                            continue
                        try:
                            kwargs: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0}
                            if tools:
                                kwargs["tools"] = tools
                            if provider.name == "groq" and model.startswith("openai/gpt-oss"):
                                kwargs["reasoning_effort"] = "low"
                                if tools:
                                    kwargs["extra_body"] = {"reasoning_format": "hidden"}
                            client = self._provider_client(provider, key_index, key)
                            raw = client.chat.completions.create(**kwargs)
                            return self._parse_response(raw, provider.name, model, key_index)
                        except Exception as exc:
                            last_error = exc
                            retryable = self._is_retryable(exc)
                            all_retryable = all_retryable and retryable
                            status = getattr(exc, "status_code", None)
                            quota = "quota" in str(exc).casefold() or self._daily_quota(exc)
                            if status == 429 or quota:
                                retry_after = self._retry_after(exc)
                                if retry_after is not None:
                                    retry_after_values.append(retry_after)
                                self._cool_key(provider, key_index, model, exc)
                            if self.audit:
                                self.audit.append("llm_error", {
                                    "provider": provider.name,
                                    "model": model,
                                    "key_index": key_index,
                                    "error": type(exc).__name__,
                                    "status_code": status,
                                    "retryable": retryable,
                                    "body": self._safe_error(exc),
                                })
                            if status == 429 or quota:
                                continue
                            if retryable:
                                provider_unavailable = True
                            break
                    if provider_unavailable:
                        break
                if provider_unavailable:
                    continue
            if not configured_keys:
                raise RuntimeError("no configured LLM provider has an API key") from last_error
            if not all_retryable or chain_attempt >= 2:
                break
            active_cooldowns = [until - time.monotonic() for until in self._cooldowns.values() if until > time.monotonic()]
            wait_seconds = min(30.0, min(retry_after_values)) if retry_after_values else (min(30.0, max(0.0, min(active_cooldowns))) if active_cooldowns else 1.0)
            if self.audit:
                self.audit.append("llm_retry_wait", {"attempt": chain_attempt + 1, "wait_seconds": wait_seconds, "reason": "all_providers_retryable"})
            time.sleep(wait_seconds)
        raise RuntimeError("all configured LLM providers failed") from last_error
