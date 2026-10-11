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
    investor_class: int = Field(ge=1, le=5)
    liquidity_days: int | None = Field(default=None, ge=0)
    asset_class: str | None = None
    exclusions: list[str] = Field(default_factory=list)


class AllocationArgs(BaseModel):
    amount: float = Field(gt=0)
    investor_class: int = Field(ge=1, le=5)
    liquidity_days: int | None = Field(default=None, ge=0)
    exclusions: list[str] = Field(default_factory=list)


class StressArgs(BaseModel):
    allocation: dict[str, Any]
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

    def __init__(self, audit: AuditLogger | None = None):
        self.audit = audit
        self.catalog = load_catalog()

    def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "profile_investor":
            result = profile_investor(**ProfileArgs.model_validate(arguments).model_dump()).as_dict()
        elif name == "compare_products":
            args = CompareArgs.model_validate(arguments)
            result = {"comparisons": [item.as_dict() for item in compare_products(self.catalog, **args.model_dump())]}
        elif name == "build_allocation":
            args = AllocationArgs.model_validate(arguments)
            result = build_allocation(products=self.catalog, **args.model_dump()).as_dict()
        elif name == "stress_test":
            args = StressArgs.model_validate(arguments)
            allocation_data = dict(args.allocation)
            allocation_data["holdings"] = tuple(Holding(**holding) for holding in allocation_data["holdings"])
            allocation = Allocation(**allocation_data)
            stress_args = args.model_dump(exclude={"allocation"})
            result = stress_test(allocation, **stress_args).as_dict()
        else:
            raise ValueError(f"unknown tool: {name}")
        if self.audit:
            self.audit.append("tool_call", {"tool": name, "result": result})
        return result
