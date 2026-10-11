"""Small validated tool surface for the explicit agent loop."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from .allocation import Allocation, Holding, build_allocation
from .audit import AuditLogger
from .catalog import compare_products, load_catalog
from .profiling import QUESTIONNAIRE, profile_investor
from .stress import stress_test
from .permissions import PermissionTier, require_tier


_QUESTION_DESCRIPTIONS = {
    "horizon": "Time until the money is needed: under_1y is less than one year; 1_3y is one to three years; 3_7y is three to seven; 7_10y is seven to ten; over_10y is more than ten.",
    "invested_share": "Share of total savings in this investment: over_75, 50_75, 25_50, or under_25; two thirds maps to 50_75.",
    "drawdown_reaction": "Reaction to a 20% fall: sell_all means sell everything; reduce means sell some; hold means stay invested; buy_more means add money.",
}


QuestionnaireAnswers = create_model(
    "QuestionnaireAnswers",
    **{
        key: (
            Literal[tuple(spec["options"].keys())],
            Field(
                default="within_7d" if key == "liquidity_need" else ...,
                description=_QUESTION_DESCRIPTIONS.get(
                    key,
                    f"{spec['domain'].capitalize()} questionnaire answer; choose one listed option.",
                ),
            ),
        )
        for key, spec in QUESTIONNAIRE.items()
    },
)


class ProfileArgs(BaseModel):
    answers: QuestionnaireAnswers = Field(description="All enumerated investor questionnaire answers.")
    age: int | None = Field(default=None, ge=18, le=120)
    borrowed_money: bool | None = None


class ClientFactsArgs(BaseModel):
    amount: float | None = Field(default=None, gt=0, le=100_000_000)
    horizon_years: int | None = Field(default=None, ge=1, le=100)
    max_loss: float | None = Field(default=None, ge=0, le=1)
    age: int | None = Field(default=None, ge=18, le=120)
    borrowed_money: bool | None = None


class CompareArgs(BaseModel):
    amount: float | None = Field(default=None, gt=0)
    horizon_years: int | None = Field(default=None, gt=0, le=100)
    liquidity_days: int | None = Field(default=None, ge=0)
    asset_class: str | None = None
    exclusions: list[str] = Field(default_factory=list)


class AllocationArgs(BaseModel):
    amount: float | None = Field(default=None, gt=0)
    liquidity_days: int | None = Field(default=None, ge=0)
    max_tolerable_loss: float | None = Field(default=None, ge=0, le=1)
    exclusions: list[str] = Field(default_factory=list)


class StressArgs(BaseModel):
    allocation_id: str = "latest"
    scenario: Literal["2008_gfc", "2020_covid", "2022_rate_shock", "custom"] = Field(
        default="2008_gfc",
        description="Historical scenario: use 2008_gfc for the 2008 global financial crisis.",
    )
    custom_shocks: dict[str, float] | None = None
    max_tolerable_loss: float | None = Field(default=None, ge=0, le=1)


class DraftOrderArgs(BaseModel):
    allocation_id: str = "latest"


def _provider_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a self-contained function schema for providers with limited refs support."""

    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})
    for property_schema in schema.get("properties", {}).values():
        reference = property_schema.get("$ref")
        if reference:
            property_schema.clear()
            property_schema.update(definitions[reference.rsplit("/", 1)[-1]])
    def compact(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: compact(item) for key, item in value.items() if key not in {"title", "default"}}
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value

    return compact(schema)


TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "record_client_facts", "description": "Store validated client KYC facts.", "parameters": _provider_schema(ClientFactsArgs)}},
    {"type": "function", "function": {"name": "profile_investor", "description": "Score enumerated investor answers", "parameters": _provider_schema(ProfileArgs)}},
    {"type": "function", "function": {"name": "compare_products", "description": "Compare suitable catalog products.", "parameters": _provider_schema(CompareArgs)}},
    {"type": "function", "function": {"name": "build_allocation", "description": "Build a deterministic suitable allocation.", "parameters": _provider_schema(AllocationArgs)}},
    {"type": "function", "function": {"name": "stress_test", "description": "Apply a historical-style portfolio stress.", "parameters": _provider_schema(StressArgs)}},
    {"type": "function", "function": {"name": "create_draft_orders", "description": "Create proposed simulated orders from a stored allocation.", "parameters": _provider_schema(DraftOrderArgs)}},
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
        if name == "record_client_facts":
            if self.session:
                require_tier(self.session.tier, PermissionTier.ADVISE)
            facts = ClientFactsArgs.model_validate(arguments).model_dump(exclude_unset=True)
            if not facts:
                raise ValueError("at least one client fact is required")
            if self.session:
                for key, value in facts.items():
                    setattr(self.session.state.client, key, value)
                result = {"client": self.session.state.client.as_dict()}
            else:
                result = {"client": facts}
        elif name == "profile_investor":
            if self.session:
                require_tier(self.session.tier, PermissionTier.ADVISE)
            profile_args = ProfileArgs.model_validate(arguments).model_dump()
            if self.session:
                if profile_args["age"] is None:
                    profile_args["age"] = self.session.state.client.age
                if profile_args["borrowed_money"] is None:
                    profile_args["borrowed_money"] = bool(self.session.state.client.borrowed_money)
                if profile_args["age"] is not None:
                    self.session.state.client.age = profile_args["age"]
                if profile_args["borrowed_money"] is not None:
                    self.session.state.client.borrowed_money = profile_args["borrowed_money"]
            profile = profile_investor(**profile_args)
            if self.session:
                self.session.state.profile = profile
            result = profile.as_dict()
        elif name == "compare_products":
            if self.session:
                require_tier(self.session.tier, PermissionTier.ADVISE)
            args = CompareArgs.model_validate(arguments)
            args_data = args.model_dump()
            if self.session and args_data["amount"] is None:
                args_data["amount"] = self.session.state.client.amount
            if self.session and args_data["horizon_years"] is None:
                args_data["horizon_years"] = self.session.state.client.horizon_years
            if args_data["amount"] is None or args_data["horizon_years"] is None:
                raise ValueError("record amount and horizon_years before comparing products")
            args_data["investor_class"] = self._profile_class()
            if args_data["liquidity_days"] is None and self.session:
                args_data["liquidity_days"] = self.session.state.profile.liquidity_days
            if self.session:
                self.session.state.amount = args_data["amount"]
                self.session.state.horizon_years = args_data["horizon_years"]
                self.session.state.client.amount = args_data["amount"]
                self.session.state.client.horizon_years = args_data["horizon_years"]
            result = {"comparisons": [item.as_dict() for item in compare_products(self.catalog, **args_data)]}
        elif name == "build_allocation":
            if self.session:
                require_tier(self.session.tier, PermissionTier.ADVISE)
            args = AllocationArgs.model_validate(arguments)
            args_data = args.model_dump()
            if self.session and args_data["amount"] is None:
                args_data["amount"] = self.session.state.client.amount
            if args_data["amount"] is None:
                raise ValueError("record amount before building an allocation")
            args_data["investor_class"] = self._profile_class()
            if args_data["liquidity_days"] is None and self.session:
                args_data["liquidity_days"] = self.session.state.profile.liquidity_days
            if self.session:
                self.session.state.amount = args_data["amount"]
                self.session.state.client.amount = args_data["amount"]
            if self.session:
                args_data["max_tolerable_loss"] = self.session.state.client.max_loss
            allocation = build_allocation(products=self.catalog, **args_data)
            if self.session:
                allocation_id = f"allocation-{len(self.session.state.allocations) + 1}"
                self.session.state.allocations[allocation_id] = allocation
                result = {"allocation_id": allocation_id, **allocation.as_dict()}
            else:
                result = allocation.as_dict()
        elif name == "stress_test":
            if self.session:
                require_tier(self.session.tier, PermissionTier.ADVISE)
            args = StressArgs.model_validate(arguments)
            if not self.session:
                raise ValueError("stress_test requires a server-side AdvisorSession")
            allocation = self.session.stored_allocation(args.allocation_id)
            max_loss = args.max_tolerable_loss
            if max_loss is None and self.session:
                max_loss = self.session.state.client.max_loss
            stress_result = stress_test(allocation, scenario=args.scenario, custom_shocks=args.custom_shocks, max_tolerable_loss=max_loss if max_loss is not None else 0.20)
            stress_id = f"stress-{len(self.session.state.stress_results) + 1}"
            self.session.state.stress_results[stress_id] = stress_result
            result = {"stress_id": stress_id, "allocation_id": args.allocation_id, **stress_result.as_dict()}
        elif name == "create_draft_orders":
            if not self.session:
                raise ValueError("create_draft_orders requires a server-side AdvisorSession")
            require_tier(self.session.tier, PermissionTier.PROPOSE)
            args = DraftOrderArgs.model_validate(arguments)
            result = {"orders": self.session.create_draft_orders(args.allocation_id)}
        else:
            raise ValueError(f"unknown tool: {name}")
        if self.audit:
            self.audit.append("tool_call", {"tool": name, "result": result})
        return result
