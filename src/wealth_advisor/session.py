"""Server-owned advisory session state and the UI-facing session contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent import AdvisorAgent, AgentTurn, trim_complete_turns
from .account import SimulatedAccount
from .allocation import Allocation
from .audit import AuditLogger
from .config import Settings
from .permissions import PermissionTier
from .permissions import ConfirmationTokenStore, PermissionDenied, require_tier
from .profiling import InvestorProfile
from .compliance import output_guard
from .security import GuardDecision, RateLimiter, input_guard
from .stress import StressResult
from .tools import ToolDispatcher


@dataclass
class SessionState:
    """Mutable server-side state; the model only sees the compact summary."""

    profile: InvestorProfile | None = None
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

        return {
            "profile_class": self.profile.class_code if self.profile else None,
            "profile_expires_on": self.profile.expires_on.isoformat() if self.profile else None,
            "amount": self.amount,
            "horizon_years": self.horizon_years,
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
            llm=None,
            dispatcher=self.dispatcher,
            audit=self.audit,
            max_steps=self.settings.max_tool_steps,
        )
        self.messages: list[dict[str, Any]] = []
        self.rate_limiter = RateLimiter(max_calls=self.settings.max_session_turns)
        self.confirmation_tokens = ConfirmationTokenStore()

    def _messages_for_turn(self, user_message: str) -> list[dict[str, Any]]:
        system = self.agent.system_message(self.state.summary())
        history = trim_complete_turns(self.messages, max_turns=6)
        return [system, *history, {"role": "user", "content": user_message}]

    def send(self, user_message: str) -> str:
        """Run one complete turn while retaining only valid, complete dialogue turns."""

        if not user_message.strip():
            raise ValueError("user_message must not be empty")
        if not self.rate_limiter.allow():
            self.audit.append("guard_blocked", {"guard": "rate_limit"})
            return "This session has reached its request limit. Please try again later."
        guard: GuardDecision = input_guard(user_message)
        self.audit.append("input_guard", {"allowed": guard.allowed, "reasons": guard.reasons, "pii_redacted": guard.pii_redacted, "injection_score": guard.injection_score})
        if not guard.allowed:
            return "I cannot process instruction-like requests. Please describe your financial goal directly."
        turn: AgentTurn = self.agent.run_turn(self._messages_for_turn(guard.text))
        recommendation = bool(self.state.profile and (self.state.allocations or self.state.stress_results))
        guarded_output = output_guard(turn.content, turn.tool_results, recommendation=recommendation)
        if not guarded_output.allowed:
            self.audit.append("output_guard", {"allowed": False, "reasons": guarded_output.reasons})
        turn.messages[-1]["content"] = guarded_output.message
        self.messages = trim_complete_turns(turn.messages, max_turns=6)
        self.audit.append("session_turn", {"message_count": len(self.messages), "state": self.state.summary()})
        return guarded_output.message

    def stored_allocation(self, allocation_id: str = "latest") -> Allocation:
        """Resolve a server-side allocation identifier for non-LLM callers."""

        resolved = self.state.latest_allocation_id if allocation_id == "latest" else allocation_id
        if not resolved or resolved not in self.state.allocations:
            raise ValueError("allocation not found; build an allocation first")
        return self.state.allocations[resolved]

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
