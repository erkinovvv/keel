"""Explicit, bounded LLM orchestration loop."""

from __future__ import annotations

import json
from typing import Any

from .audit import AuditLogger
from .llm import LLMClient
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SCHEMAS, ToolDispatcher


class AdvisorAgent:
    """Keep the LLM at the conversation boundary while tools own all numbers."""

    def __init__(self, llm: LLMClient | None = None, dispatcher: ToolDispatcher | None = None, audit: AuditLogger | None = None, max_steps: int = 8):
        self.audit = audit
        self.llm = llm or LLMClient(audit=audit)
        self.dispatcher = dispatcher or ToolDispatcher(audit=audit)
        self.max_steps = max_steps

    def run(self, user_message: str, history: list[dict[str, Any]] | None = None) -> str:
        """Run at most max_steps of model/tool exchange and return the final text."""

        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend((history or [])[-6:])
        messages.append({"role": "user", "content": user_message})
        for _ in range(self.max_steps):
            response = self.llm.chat(messages, TOOL_SCHEMAS)
            if not response.tool_calls:
                return response.content
            messages.append({"role": "assistant", "content": response.content, "tool_calls": [
                {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments)}}
                for call in response.tool_calls
            ]})
            for call in response.tool_calls:
                result = self.dispatcher.dispatch(call.name, call.arguments)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, separators=(",", ":"))})
        raise RuntimeError("maximum tool steps exceeded")

