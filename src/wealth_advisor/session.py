"""Server-owned advisory session state and the UI-facing session contract."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
from typing import Any

from .agent import AdvisorAgent, AgentTurn, trim_complete_turns
from .account import SimulatedAccount
from .allocation import Allocation
from .audit import AuditLogger
from .config import Settings
from .llm import LLMClient
from .permissions import PermissionTier
from .permissions import ConfirmationTokenStore, PermissionDenied, require_tier
from .profiling import InvestorProfile
from .compliance import output_guard
from .security import GuardDecision, PromptGuardClassifier, RateLimiter, input_guard
from .stress import StressResult
from .tools import ToolDispatcher
from .tools import TOOL_SCHEMAS


@dataclass
class ClientFacts:
    """Server-side facts collected during conversational KYC."""

    amount: float | None = None
    horizon_years: int | None = None
    max_loss: float | None = None
    age: int | None = None
    borrowed_money: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "horizon_years": self.horizon_years,
            "max_loss": self.max_loss,
            "age": self.age,
            "borrowed_money": self.borrowed_money,
        }


@dataclass
class SessionState:
    """Mutable server-side state; the model only sees the compact summary."""

    profile: InvestorProfile | None = None
    client: ClientFacts = field(default_factory=ClientFacts)
    amount: float | None = None
    horizon_years: int | None = None
    allocations: dict[str, Allocation] = field(default_factory=dict)
    stress_results: dict[str, StressResult] = field(default_factory=dict)
    draft_orders: dict[str, Any] = field(default_factory=dict)
    account: Any = None

    @property
    def latest_allocation_id(self) -> str | None:
        return next(reversed(self.allocations), None)

    def summary(self) -> dict[str, Any]:
        """Return only non-sensitive identifiers and profile facts for the model."""

        client_profile = None
        if self.profile:
            client_profile = {
                "class_code": self.profile.class_code,
                "investor_class": self.profile.investor_class,
                "capacity_class": self.profile.capacity_class,
                "tolerance_class": self.profile.tolerance_class,
                "liquidity_days": self.profile.liquidity_days,
                "reason_codes": list(self.profile.reason_codes),
            }
        return {
            "profile_class": self.profile.class_code if self.profile else None,
            "client_profile": client_profile,
            "profile_expires_on": self.profile.expires_on.isoformat() if self.profile else None,
            "client": self.client.as_dict(),
            "amount": self.client.amount if self.client.amount is not None else self.amount,
            "horizon_years": self.client.horizon_years if self.client.horizon_years is not None else self.horizon_years,
            "latest_allocation_id": self.latest_allocation_id,
            "allocation_ids": list(self.allocations),
            "stress_result_ids": list(self.stress_results),
        }


class AdvisorSession:
    """Own conversation history and deterministic advisory artifacts on the server."""

    def __init__(
        self,
        settings: Settings | None = None,
        tier: PermissionTier = PermissionTier.ADVISE,
    ):
        self.settings = settings or Settings.from_env()
        self.tier = tier
        if self.settings.kill_switch and self.tier > PermissionTier.ADVISE:
            self.tier = PermissionTier.ADVISE
        self.state = SessionState()
        self.state.account = SimulatedAccount(cash=self.settings.simulated_cash)
        self.audit = AuditLogger(self.settings.audit_log)
        self.dispatcher = ToolDispatcher(audit=self.audit, session=self)
        self.agent = AdvisorAgent(
            llm=LLMClient(settings=self.settings, audit=self.audit),
            dispatcher=self.dispatcher,
            audit=self.audit,
            max_steps=self.settings.max_tool_steps,
        )
        self.messages: list[dict[str, Any]] = []
        self._tool_results: list[dict[str, Any]] = []
        self.rate_limiter = RateLimiter(max_calls=self.settings.max_session_turns)
        self.confirmation_tokens = ConfirmationTokenStore()
        self.prompt_guard = PromptGuardClassifier(self.settings, self.audit)

    def _messages_for_turn(self, user_message: str) -> list[dict[str, Any]]:
        system = self.agent.system_message(self.state.summary())
        if self._contains_complete_fact_summary(user_message):
            system["content"] += "\nThis first message contains a complete fact pattern; do not greet or ask for the goal. Save facts, score the profile, and proceed with the requested advice now."
        system["content"] += f"\n{self._language_instruction(user_message)}"
        history = trim_complete_turns(self.messages, max_turns=4)
        return [system, *history, {"role": "user", "content": user_message}]

    @staticmethod
    def _language_instruction(message: str) -> str:
        """Select a deterministic response language from the latest client message."""

        if any("\u4e00" <= character <= "\u9fff" for character in message):
            return "请用中文回复。"
        return "Reply in English."

    @staticmethod
    def _contains_complete_fact_summary(message: str) -> bool:
        """Detect a complete first-message fact pattern without interpreting its values."""

        patterns = (
            r"\d[\d,]*(?:\.\d+)?", r"\b(?:year|years|month|months|short|long)\b",
            r"(?:loss|lose|fall|drop|down).{0,20}\d+\s*%", r"(?:within|need|liquid|week|day|month)",
            r"(?:income|salary|stable|unstable)", r"(?:emergency|expenses|cash reserve)",
            r"(?:savings|net worth|invested|two thirds|half|quarter)", r"(?:sell|reduce|hold|buy more)",
            r"(?:experience|know|familiar|deposit|fund)", r"(?:goal|income|growth|preserve|house|flat|retire)",
        )
        return all(re.search(pattern, message, re.I) for pattern in patterns)

    def _tools_for_state(self) -> list[dict[str, Any]]:
        """Expose only tools valid for the current advisory stage."""

        if not self.state.profile:
            names = {"record_client_facts", "profile_investor"}
        elif not self.state.allocations:
            names = {"build_allocation", "compare_products"}
        else:
            names = {"stress_test", "compare_products", "build_allocation"}
        return [tool for tool in TOOL_SCHEMAS if tool["function"]["name"] in names]

    def send(self, user_message: str) -> str:
        """Run one complete turn while retaining only valid, complete dialogue turns."""

        if not user_message.strip():
            raise ValueError("user_message must not be empty")
        if not self.rate_limiter.allow():
            self.audit.append("guard_blocked", {"guard": "rate_limit"})
            return "This session has reached its request limit. Please try again later."
        guard: GuardDecision = input_guard(user_message, classifier=self.prompt_guard.score)
        self.audit.append("input_guard", {"allowed": guard.allowed, "reasons": guard.reasons, "pii_redacted": guard.pii_redacted, "injection_score": guard.injection_score})
        if not guard.allowed:
            return "I cannot process instruction-like requests. Please describe your financial goal directly."
        turn: AgentTurn = self.agent.run_turn(self._messages_for_turn(guard.text), tools=self._tools_for_state)
        self._tool_results.extend(turn.tool_results)
        recommendation = bool(self.state.profile and (self.state.allocations or self.state.stress_results))
        client_messages = [message["content"] for message in self.messages if message.get("role") == "user"]
        client_messages.append(guard.text)
        guarded_output = output_guard(
            turn.content,
            [*self._tool_results, self.snapshot()],
            recommendation=recommendation,
            client_messages=client_messages,
        )
        if not guarded_output.allowed:
            language = "Chinese" if any("\u4e00" <= character <= "\u9fff" for character in guard.text) else "the client's language"
            feedback = (
                f"Rewrite your last answer in {language}, under 120 words, with no tables. "
                "Use only figures present in the tool results or in the client's messages. "
                f"Do not use these ungrounded figures: {', '.join(guarded_output.ungrounded_numbers) or 'none'}. "
                "Do not make guarantees; keep the advisory workflow and explain the deterministic result."
            )
            regeneration_messages = [*turn.messages[:-1], {"role": "user", "content": feedback}]
            regenerated = self.agent.run_turn(regeneration_messages, tools=[])
            self._tool_results.extend(regenerated.tool_results)
            guarded_regenerated = output_guard(
                regenerated.content,
                [*self._tool_results, self.snapshot()],
                recommendation=recommendation,
                client_messages=client_messages,
            )
            if guarded_regenerated.allowed:
                self.audit.append(
                    "output_guard",
                    {"allowed": True, "regenerated": True, "rejected_ungrounded": list(guarded_output.ungrounded_numbers)},
                )
                turn = regenerated
                guarded_output = guarded_regenerated
            else:
                fallback = self._state_fallback_message(self.snapshot(), language)
                self.audit.append(
                    "output_guard",
                    {
                        "allowed": True,
                        "regenerated": True,
                        "fallback": True,
                        "rejected_ungrounded": list(guarded_output.ungrounded_numbers),
                        "regeneration_ungrounded": list(guarded_regenerated.ungrounded_numbers),
                    },
                )
                guarded_output = type(guarded_output)(True, fallback, ("SAFE_OUTPUT_FALLBACK",), ())
        turn.messages[-1]["content"] = guarded_output.message
        self.messages = trim_complete_turns(turn.messages, max_turns=4)
        self.audit.append("session_turn", {"message_count": len(self.messages), "state": self.state.summary(), "usage": turn.usage, "latency_ms": turn.latency_ms})
        return guarded_output.message

    @staticmethod
    def _state_fallback_message(snapshot: dict[str, Any], language: str) -> str:
        """Describe only advisory artifacts actually present in a session snapshot."""

        profile = snapshot.get("profile")
        allocation = snapshot.get("allocation")
        stress_results = snapshot.get("stress_results")
        client = snapshot.get("client") or {}
        if language == "Chinese":
            if profile is None:
                return "请先告诉我您计划投资的金额，以及这笔钱何时可能需要使用。"
            if allocation is None:
                return "您的投资者画像已经记录。下一步我可以为您建立合适的资产配置。"
            if not stress_results:
                return "您的资产配置已经保存。下一步我可以运行历史压力测试。"
            return "您的资产配置和压力测试已经保存。下一步可以先查看结果，或在下单前进行崩溃演练。"

        if profile is None:
            if client.get("amount") is None:
                return "What amount are you considering investing?"
            if client.get("horizon_years") is None:
                return "How long can this money remain invested?"
            if client.get("max_loss") is None:
                return "When might you need access to the money, and what percentage loss could you accept in a bad year?"
            if client.get("age") is None:
                return "Please share your age, income stability, emergency cash buffer, and main investment goal."
            if client.get("borrowed_money") is None:
                return "Is any of this money borrowed, and how would you react to a 20% fall?"
            return "Please share your investment experience, share of savings invested, and main goal."
        class_code = profile.get("class_code") if isinstance(profile, dict) else None
        class_text = f" ({class_code})" if class_code else ""
        if allocation is None:
            return f"Your investor profile{class_text} is recorded. Next I can build a suitable allocation."
        if not stress_results:
            return f"Your investor profile{class_text} and allocation are recorded. Next I can run a historical stress test."
        return f"Your investor profile{class_text}, allocation, and stress test are recorded. Next, review the result or try the Crash Rehearsal before any orders."

    def stored_allocation(self, allocation_id: str = "latest") -> Allocation:
        """Resolve a server-side allocation identifier for non-LLM callers."""

        resolved = self.state.latest_allocation_id if allocation_id == "latest" else allocation_id
        if not resolved or resolved not in self.state.allocations:
            raise ValueError("allocation not found; build an allocation first")
        return self.state.allocations[resolved]

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable projection for UI synchronization."""

        account = self.state.account
        latest_id = self.state.latest_allocation_id
        return {
            "profile": self.state.profile.as_dict() if self.state.profile else None,
            "client": self.state.client.as_dict(),
            "latest_allocation_id": latest_id,
            "allocation": self.state.allocations[latest_id].as_dict() if latest_id else None,
            "allocations": {key: value.as_dict() for key, value in self.state.allocations.items()},
            "stress_results": {key: value.as_dict() for key, value in self.state.stress_results.items()},
            "draft_orders": {key: value.as_dict() if hasattr(value, "as_dict") else value for key, value in self.state.draft_orders.items()},
            "account": {
                "cash": account.cash if account else None,
                "holdings": dict(account.holdings) if account else {},
                "orders": {key: value.as_dict() for key, value in account.orders.items()} if account else {},
            },
            "tier": self.tier.name if hasattr(self.tier, "name") else str(self.tier),
            "tier_value": int(self.tier),
        }

    def _require_profile(self) -> InvestorProfile:
        from datetime import date

        if not self.state.profile:
            raise ValueError("profile first: no investor profile is stored in this session")
        if self.state.profile.expires_on < date.today():
            raise ValueError("profile expired: reassess the investor before executing orders")
        return self.state.profile

    def create_draft_orders(self, allocation_id: str = "latest") -> list[dict[str, object]]:
        """Create proposed simulated orders at T2 after server-side checks."""

        require_tier(self.tier, PermissionTier.PROPOSE)
        profile = self._require_profile()
        allocation = self.stored_allocation(allocation_id)
        orders = self.state.account.create_draft_orders(
            allocation,
            self.dispatcher.catalog,
            profile,
            max_order_amount=self.settings.max_order_amount,
            max_daily_order_amount=self.settings.max_daily_order_amount,
            max_orders_per_session=self.settings.max_orders_per_session,
            cooling_off_days=self.settings.cooling_off_days,
        )
        for order in orders:
            self.state.draft_orders[order.order_id] = order
        result = [order.as_dict() for order in orders]
        self.audit.append("draft_orders_created", {"allocation_id": allocation_id, "orders": result})
        return result

    def issue_confirmation_token(self, order_id: str) -> str:
        """Issue a human-held token through the UI/CLI path, outside model messages."""

        require_tier(self.tier, PermissionTier.EXECUTE)
        order = self.state.draft_orders.get(order_id)
        if order is None:
            raise ValueError("order not found")
        token = self.confirmation_tokens.issue(order.order_id, order.summary())
        self.audit.append("confirmation_token_issued", {"order_id": order_id})
        return token

    def confirm_order(self, order_id: str, token: str) -> dict[str, object]:
        """Consume a one-time human token and execute exactly the approved order."""

        require_tier(self.tier, PermissionTier.EXECUTE)
        self._require_profile()
        order = self.state.draft_orders.get(order_id)
        if order is None:
            raise ValueError("order not found")
        if not self.confirmation_tokens.consume(order_id, token, order.summary()):
            self.audit.append("order_rejected", {"order_id": order_id, "reason": "invalid_or_reused_confirmation_token"})
            raise PermissionDenied("invalid or reused confirmation token")
        executed = self.state.account.execute(order_id)
        self.audit.append("order_executed", {"order": executed.as_dict()})
        return executed.as_dict()
