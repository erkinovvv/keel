"""Explicit, bounded LLM orchestration loop."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .audit import AuditLogger
from .llm import LLMClient
from .prompts import SYSTEM_PROMPT
from .security import tool_output_guard
from .tools import TOOL_SCHEMAS, ToolDispatcher, compact_tool_result


MAX_REPLY_WORDS = 100
MAX_REPLY_CJK_CHARACTERS = 180
MAX_REPLY_PARAGRAPHS = 3
_SENTENCE_RE = re.compile(r"[^.!?。！？]+[.!?。！？]|[^.!?。！？]+$")
_ALLOCATION_REQUEST = re.compile(r"\b(?:build|create|make|design)\b.{0,30}\b(?:portfolio|allocation)\b|\bportfolio\b", re.I)
_STRESS_REQUEST = re.compile(r"\b(?:stress[- ]test|stress|crisis|drawdown)\b|\b2008\b|压力测试|危机|回撤", re.I)


def shape_reply(content: str, max_words: int = MAX_REPLY_WORDS, max_paragraphs: int = MAX_REPLY_PARAGRAPHS) -> str:
    """Apply deterministic whole-sentence and paragraph limits to model text."""

    paragraphs = [
        " ".join(paragraph.split())
        for paragraph in re.split(r"\n\s*\n", content)
        if paragraph.strip()
    ][:max_paragraphs]
    shaped: list[str] = []
    cjk = any("\u4e00" <= character <= "\u9fff" for character in content)
    limit = MAX_REPLY_CJK_CHARACTERS if cjk else max_words
    sentence_separator = "" if cjk else " "
    used = 0
    first_sentence = True
    for paragraph in paragraphs:
        sentences = [match.group(0).strip() for match in _SENTENCE_RE.finditer(paragraph)]
        selected: list[str] = []
        for sentence in sentences:
            size = len(sentence) if cjk else len(sentence.split())
            if first_sentence or used + size <= limit:
                selected.append(sentence)
                used += size
                first_sentence = False
                continue
            return "\n\n".join(shaped + ([sentence_separator.join(selected)] if selected else [])).strip()
        if selected:
            shaped.append(sentence_separator.join(selected))
    return "\n\n".join(shaped).strip()


@dataclass(frozen=True)
class AgentTurn:
    content: str
    messages: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0


def trim_complete_turns(messages: list[dict[str, Any]], max_turns: int = 4) -> list[dict[str, Any]]:
    """Trim only at user-turn boundaries so assistant tool calls never orphan tools."""

    if not messages:
        return []
    system = messages[0] if messages[0].get("role") == "system" else None
    body = messages[1:] if system else messages[:]
    turns: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for message in body:
        if message.get("role") == "user" and current:
            turns.append(current)
            current = []
        current.append(message)
    if current:
        turns.append(current)
    result = [system] if system else []
    for turn in turns[-max_turns:]:
        result.extend(turn)
    return result


class AdvisorAgent:
    """Keep the LLM at the conversation boundary while tools own all numbers."""

    def __init__(self, llm: LLMClient | None = None, dispatcher: ToolDispatcher | None = None, audit: AuditLogger | None = None, max_steps: int = 8):
        self.audit = audit
        self.llm = llm or LLMClient(audit=audit)
        self.dispatcher = dispatcher or ToolDispatcher(audit=audit)
        self.max_steps = max_steps

    def system_message(self, client_state: dict[str, Any] | None = None) -> dict[str, str]:
        state_text = json.dumps(client_state or {}, separators=(",", ":"), sort_keys=True)
        return {"role": "system", "content": f"{SYSTEM_PROMPT}\nClient state: {state_text}"}

    def _required_tool(self, messages: list[dict[str, Any]], completed_tools: set[str]) -> str | None:
        user_message = next(
            (str(message.get("content", "")) for message in reversed(messages) if message.get("role") == "user"),
            "",
        )
        session = self.dispatcher.session
        if not session or not session.state.profile:
            return None
        if _ALLOCATION_REQUEST.search(user_message) and "build_allocation" not in completed_tools and not session.state.allocations:
            return "build_allocation"
        if _STRESS_REQUEST.search(user_message) and "stress_test" not in completed_tools and session.state.allocations:
            return "stress_test"
        return None

    def _append_required_tool(self, messages: list[dict[str, Any]], tool_results: list[dict[str, Any]], name: str) -> None:
        call_id = f"required-{name}-{len(tool_results) + 1}"
        result = self.dispatcher.dispatch(name, {})
        compact_result = compact_tool_result(name, result, self.dispatcher.catalog)
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": "{}"}}],
        })
        messages.append({"role": "tool", "tool_call_id": call_id, "name": name, "content": json.dumps(compact_result, separators=(",", ":"))})
        tool_results.append(compact_result)

    def run_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | Callable[[], list[dict[str, Any]]] | None = None,
    ) -> AgentTurn:
        """Run at most max_steps and return both final text and complete history."""

        messages = list(messages)
        tool_results: list[dict[str, Any]] = []
        completed_tools: set[str] = set()
        failed_calls: dict[str, int] = {}
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        started = time.perf_counter()
        for _ in range(self.max_steps):
            available_tools = tools() if callable(tools) else (TOOL_SCHEMAS if tools is None else tools)
            response = self.llm.chat(messages, available_tools)
            for key in usage:
                usage[key] += int(response.usage.get(key, 0))
            if not response.tool_calls:
                required_tool = self._required_tool(messages, completed_tools)
                if required_tool:
                    self._append_required_tool(messages, tool_results, required_tool)
                    completed_tools.add(required_tool)
                    continue
                content = shape_reply(response.content)
                messages.append({"role": "assistant", "content": content})
                return AgentTurn(content, messages, tool_results, usage, (time.perf_counter() - started) * 1000)
            messages.append({"role": "assistant", "content": response.content or None, "tool_calls": [
                {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments)}}
                for call in response.tool_calls
            ]})
            for call in response.tool_calls:
                completed_tools.add(call.name)
                call_key = json.dumps({"name": call.name, "arguments": call.arguments}, sort_keys=True, separators=(",", ":"))
                try:
                    if failed_calls.get(call_key, 0) >= 2:
                        result = {
                            "error": "Tool retry limit exceeded",
                            "message": "This identical tool call has already failed twice in this turn.",
                        }
                    else:
                        result = self.dispatcher.dispatch(call.name, call.arguments)
                except Exception as exc:
                    failed_calls[call_key] = failed_calls.get(call_key, 0) + 1
                    result = {
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                    if self.audit:
                        self.audit.append("tool_error", {"tool": call.name, "error": type(exc).__name__, "message": str(exc)})
                tool_text = json.dumps(result, separators=(",", ":"))
                if not tool_output_guard(tool_text).allowed:
                    result = {"error": "Unsafe tool output blocked", "message": "The tool result contained instruction-like text."}
                    if self.audit:
                        self.audit.append("tool_output_blocked", {"tool": call.name})
                compact_result = compact_tool_result(call.name, result, self.dispatcher.catalog)
                tool_results.append(compact_result)
                messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": json.dumps(compact_result, separators=(",", ":"))})
        raise RuntimeError("maximum tool steps exceeded")

    def run(self, user_message: str, history: list[dict[str, Any]] | None = None) -> str:
        """Backward-compatible one-shot wrapper around the explicit turn loop."""

        history_messages = list(history or [])
        if history_messages and history_messages[0].get("role") == "system":
            history_messages = history_messages[1:]
        messages = [self.system_message(), *trim_complete_turns(history_messages, max_turns=4), {"role": "user", "content": user_message}]
        return self.run_turn(messages).content
