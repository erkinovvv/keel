"""Explicit, bounded LLM orchestration loop."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from .audit import AuditLogger
from .llm import LLMClient
from .prompts import SYSTEM_PROMPT
from .security import tool_output_guard
from .tools import TOOL_SCHEMAS, ToolDispatcher


@dataclass(frozen=True)
class AgentTurn:
    content: str
    messages: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0


def trim_complete_turns(messages: list[dict[str, Any]], max_turns: int = 6) -> list[dict[str, Any]]:
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

    def run_turn(self, messages: list[dict[str, Any]]) -> AgentTurn:
        """Run at most max_steps and return both final text and complete history."""

        messages = list(messages)
        tool_results: list[dict[str, Any]] = []
        failed_calls: dict[str, int] = {}
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        started = time.perf_counter()
        for _ in range(self.max_steps):
            response = self.llm.chat(messages, TOOL_SCHEMAS)
            for key in usage:
                usage[key] += int(response.usage.get(key, 0))
            if not response.tool_calls:
                messages.append({"role": "assistant", "content": response.content})
                return AgentTurn(response.content, messages, tool_results, usage, (time.perf_counter() - started) * 1000)
            messages.append({"role": "assistant", "content": response.content or None, "tool_calls": [
                {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments)}}
                for call in response.tool_calls
            ]})
            for call in response.tool_calls:
                call_key = json.dumps({"name": call.name, "arguments": call.arguments}, sort_keys=True, separators=(",", ":"))
                try:
                    if failed_calls.get(call_key, 0) >= 2:
                        result = {
                            "error": "Tool retry limit exceeded",
                            "message": "This identical tool call has already failed twice in this turn.",
                            "hint": "Ask the client for the missing or corrected information instead of retrying the same arguments.",
                        }
                    else:
                        result = self.dispatcher.dispatch(call.name, call.arguments)
                except Exception as exc:
                    failed_calls[call_key] = failed_calls.get(call_key, 0) + 1
                    result = {
                        "error": type(exc).__name__,
                        "message": str(exc),
                        "hint": "Correct the arguments or complete the required profile step, then retry.",
                    }
                    if self.audit:
                        self.audit.append("tool_error", {"tool": call.name, "error": type(exc).__name__, "message": str(exc)})
                tool_text = json.dumps(result, separators=(",", ":"))
                if not tool_output_guard(tool_text).allowed:
                    result = {"error": "Unsafe tool output blocked", "hint": "The tool result contained instruction-like text."}
                    if self.audit:
                        self.audit.append("tool_output_blocked", {"tool": call.name})
                tool_results.append(result)
                messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": json.dumps(result, separators=(",", ":"))})
        raise RuntimeError("maximum tool steps exceeded")

    def run(self, user_message: str, history: list[dict[str, Any]] | None = None) -> str:
        """Backward-compatible one-shot wrapper around the explicit turn loop."""

        history_messages = list(history or [])
        if history_messages and history_messages[0].get("role") == "system":
            history_messages = history_messages[1:]
        messages = [self.system_message(), *trim_complete_turns(history_messages, max_turns=6), {"role": "user", "content": user_message}]
        return self.run_turn(messages).content
