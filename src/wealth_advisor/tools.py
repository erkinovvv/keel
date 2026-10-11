"""Small validated tool surface for the explicit agent loop."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .allocation import Allocation, Holding, build_allocation
from .audit import AuditLogger
from .catalog import compare_products, load_catalog
from .profiling import profile_investor
from .stress import stress_test


class ProfileArgs(BaseModel):
    answers: dict[str, str]
    age: int | None = Field(default=None, ge=18, le=120)
    borrowed_money: bool = False


class CompareArgs(BaseModel):
    amount: float = Field(gt=0)
    horizon_years: int = Field(gt=0, le=100)
    liquidity_days: int | None = Field(default=None, ge=0)
    asset_class: str | None = None
    exclusions: list[str] = Field(default_factory=list)


class AllocationArgs(BaseModel):
    amount: float = Field(gt=0)
    liquidity_days: int | None = Field(default=None, ge=0)
    exclusions: list[str] = Field(default_factory=list)


class StressArgs(BaseModel):
    allocation_id: str = "latest"
    scenario: str = "2008_gfc"
    custom_shocks: dict[str, float] | None = None
    max_tolerable_loss: float = Field(default=0.20, ge=0)


TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "profile_investor", "description": "Score enumerated investor answers", "parameters": ProfileArgs.model_json_schema()}},
    {"type": "function", "function": {"name": "compare_products", "description": "Compare suitable catalog products", "parameters": CompareArgs.model_json_schema()}},
    {"type": "function", "function": {"name": "build_allocation", "description": "Build a deterministic suitable allocation", "parameters": AllocationArgs.model_json_schema()}},
    {"type": "function", "function": {"name": "stress_test", "description": "Apply a historical-style portfolio stress", "parameters": StressArgs.model_json_schema()}},
]


class ToolDispatcher:
    """Validate tool arguments and route only known deterministic operations."""

    def __init__(self, audit: AuditLogger | None = None, session: Any = None):
        self.audit = audit
        self.session = session
        self.catalog = load_catalog()

    def _profile_class(self) -> int:
        if not self.session or not self.session.state.profile:
            raise ValueError("profile first: no investor profile is stored in this session")
        from datetime import date

        if self.session.state.profile.expires_on < date.today():
            raise ValueError("profile expired: reassess the investor before requesting advice")
        return self.session.state.profile.investor_class

    def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "profile_investor":
            profile = profile_investor(**ProfileArgs.model_validate(arguments).model_dump())
            if self.session:
                self.session.state.profile = profile
            result = profile.as_dict()
        elif name == "compare_products":
            args = CompareArgs.model_validate(arguments)
            args_data = args.model_dump()
            args_data["investor_class"] = self._profile_class()
            if args_data["liquidity_days"] is None and self.session:
                args_data["liquidity_days"] = self.session.state.profile.liquidity_days
            if self.session:
                self.session.state.amount = args.amount
                self.session.state.horizon_years = args.horizon_years
            result = {"comparisons": [item.as_dict() for item in compare_products(self.catalog, **args_data)]}
        elif name == "build_allocation":
            args = AllocationArgs.model_validate(arguments)
            args_data = args.model_dump()
            args_data["investor_class"] = self._profile_class()
            if args_data["liquidity_days"] is None and self.session:
                args_data["liquidity_days"] = self.session.state.profile.liquidity_days
            if self.session:
                self.session.state.amount = args.amount
            allocation = build_allocation(products=self.catalog, **args_data)
            if self.session:
                allocation_id = f"allocation-{len(self.session.state.allocations) + 1}"
                self.session.state.allocations[allocation_id] = allocation
                result = {"allocation_id": allocation_id, **allocation.as_dict()}
            else:
                result = allocation.as_dict()
        elif name == "stress_test":
            args = StressArgs.model_validate(arguments)
            if not self.session:
                raise ValueError("stress_test requires a server-side AdvisorSession")
            allocation = self.session.stored_allocation(args.allocation_id)
            stress_result = stress_test(allocation, scenario=args.scenario, custom_shocks=args.custom_shocks, max_tolerable_loss=args.max_tolerable_loss)
            stress_id = f"stress-{len(self.session.state.stress_results) + 1}"
            self.session.state.stress_results[stress_id] = stress_result
            result = {"stress_id": stress_id, "allocation_id": args.allocation_id, **stress_result.as_dict()}
        else:
            raise ValueError(f"unknown tool: {name}")
        if self.audit:
            self.audit.append("tool_call", {"tool": name, "result": result})
        return result
