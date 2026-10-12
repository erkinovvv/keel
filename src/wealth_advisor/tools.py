"""Small validated tool surface for the explicit agent loop."""

from __future__ import annotations

from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field, ValidationError, create_model

from .allocation import Allocation, Holding, build_allocation
from .audit import AuditLogger
from .catalog import compare_products, load_catalog
from .profiling import QUESTIONNAIRE, profile_investor
from .stress import stress_test
from .permissions import PermissionTier, require_tier


_QUESTION_DESCRIPTIONS = {
    "horizon": "Time until the money is needed: under_1y is less than one year; 1_3y is one to three years; 3_7y is three to seven; 7_10y is seven to ten; over_10y is more than ten.",
    "liquidity_need": "within_1d = may need some money any day; within_7d = may need some within a week; within_30d = may need some within the next month; over_30d = will not need it for at least a month or longer. Example: 'won't touch it for at least a month' maps to over_30d.",
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
    amount_cny: float | None = Field(default=None, gt=0, le=100_000_000, description="Positive investment amount in the client's currency units.")
    horizon_years: int | None = Field(default=None, ge=1, le=100)
    max_loss_fraction: float | None = Field(default=None, ge=0, le=1, description="Acceptable loss as a fraction from 0 to 1; 0.20 means 20%.")
    age: int | None = Field(default=None, ge=18, le=120)
    borrowed_money: bool | None = None


class CompareArgs(BaseModel):
    amount_cny: float | None = Field(default=None, gt=0, description="Positive comparison amount in the client's currency units.")
    horizon_years: int | None = Field(default=None, gt=0, le=100)
    liquidity_days: int | None = Field(default=None, ge=0)
    asset_class: str | None = None
    exclusions: list[str] = Field(default_factory=list)


class AllocationArgs(BaseModel):
    amount_cny: float | None = Field(default=None, gt=0, description="Positive allocation amount in the client's currency units.")
    liquidity_days: int | None = Field(default=None, ge=0)
    max_tolerable_loss_fraction: float | None = Field(default=None, ge=0, le=1, description="Maximum loss as a fraction from 0 to 1; 0.20 means 20%.")
    exclusions: list[str] = Field(default_factory=list)


class StressArgs(BaseModel):
    allocation_id: str = "latest"
    scenario: Literal["2008_gfc", "2020_covid", "2022_rate_shock", "custom"] = Field(
        default="2008_gfc",
        description="Historical scenario: use 2008_gfc for the 2008 global financial crisis.",
    )
    custom_shocks: dict[str, float] | None = None
    max_tolerable_loss_fraction: float | None = Field(default=None, ge=0, le=1, description="Maximum loss as a fraction from 0 to 1; 0.20 means 20%.")


class DraftOrderArgs(BaseModel):
    allocation_id: str = "latest"


class MarketQuotesArgs(BaseModel):
    """No arguments: server-side allowlists define the quote universe."""

    pass


_LEGACY_FIELD_NAMES = {
    "amount": "amount_cny",
    "max_loss": "max_loss_fraction",
    "max_tolerable_loss": "max_tolerable_loss_fraction",
}


def _canonical_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Translate pre-unit-explicit callers without exposing ambiguous fields to the model."""

    values = dict(arguments)
    for old_name, new_name in _LEGACY_FIELD_NAMES.items():
        if new_name in values:
            values.pop(old_name, None)
            continue
        if old_name not in values:
            continue
        value = values.pop(old_name)
        if old_name in {"max_loss", "max_tolerable_loss"} and isinstance(value, (int, float)) and value > 1:
            value /= 100
        values[new_name] = value
    return values


def _validated(model: type[BaseModel], arguments: dict[str, Any]) -> BaseModel:
    values = _canonical_arguments(arguments)
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        messages: list[str] = []
        for error in exc.errors():
            field = str(error["loc"][-1])
            value = values.get(field)
            if field in {"max_loss_fraction", "max_tolerable_loss_fraction"} and isinstance(value, (int, float)) and value > 1:
                messages.append(f"{field}={value} looks like a percent; pass {value / 100:.2f} as a fraction from 0 to 1")
            elif field == "amount_cny":
                messages.append(f"amount_cny={value!r} must be a positive amount in the client's currency units")
            elif field == "horizon_years":
                messages.append(f"horizon_years={value!r} must be a whole number from 1 to 100")
            else:
                messages.append(f"{field}={value!r} is invalid; provide a value satisfying the tool range")
        raise ValueError("; ".join(messages)) from exc


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
    {"type": "function", "function": {"name": "record_client_facts", "description": "Store validated client facts; amounts use currency units and losses use fractions.", "parameters": _provider_schema(ClientFactsArgs)}},
    {"type": "function", "function": {"name": "profile_investor", "description": "Score the enumerated investor answers.", "parameters": _provider_schema(ProfileArgs)}},
    {"type": "function", "function": {"name": "compare_products", "description": "Compare suitable catalogue products for the stored profile.", "parameters": _provider_schema(CompareArgs)}},
    {"type": "function", "function": {"name": "build_allocation", "description": "Build a deterministic suitable allocation.", "parameters": _provider_schema(AllocationArgs)}},
    {"type": "function", "function": {"name": "stress_test", "description": "Apply a deterministic historical portfolio stress.", "parameters": _provider_schema(StressArgs)}},
    {"type": "function", "function": {"name": "create_draft_orders", "description": "Create proposed simulated orders from a stored allocation.", "parameters": _provider_schema(DraftOrderArgs)}},
    {"type": "function", "function": {"name": "market_quotes", "description": "Read public allowlisted market quotes; dated fallbacks are marked stale.", "parameters": _provider_schema(MarketQuotesArgs)}},
]


def _display_percent(value: Any) -> str:
    return f"{float(value):.1%}"


def compact_tool_result(name: str, result: dict[str, Any], catalog: Iterable[Product] | None = None) -> dict[str, Any]:
    """Keep model-visible tool output high-signal without changing server-owned results."""

    product_names = {product.id: product.name for product in catalog or ()}
    if result.get("error"):
        return result
    if name == "record_client_facts":
        client = result.get("client", {})
        profile = {key: client.get(key) for key in ("amount", "horizon_years", "max_loss", "age", "borrowed_money")}
        display = "; ".join(f"{key}={value}" for key, value in profile.items() if value is not None)
        return {"client_profile": profile, "display": f"Client facts recorded: {display}."}
    if name == "profile_investor":
        profile = {
            key: result.get(key)
            for key in ("class_code", "investor_class", "capacity_class", "tolerance_class", "liquidity_days")
            if key in result
        }
        reasons = ", ".join(result.get("reason_codes", ()))
        display = (
            f"Investor profile {profile.get('class_code', 'assessed')}: capacity C{profile.get('capacity_class')}, "
            f"tolerance C{profile.get('tolerance_class')}, liquidity {profile.get('liquidity_days')} days."
        )
        if reasons:
            display += f" Reasons: {reasons}."
        profile["reason_codes"] = reasons
        return {"client_profile": profile, "display": display}
    if name == "compare_products":
        comparisons = result.get("comparisons", [])
        display_items = [
            f"{item.get('name', 'Selected fund')} ({item.get('asset_class')}, R{item.get('risk_class')}, net {_display_percent(item.get('net_return', 0))}, fee {_display_percent(item.get('fee', 0))})"
            for item in comparisons[:5]
        ]
        return {"display": "Suitable products: " + "; ".join(display_items) + "."}
    if name == "build_allocation":
        holdings = result.get("holdings", [])
        product_mix = "; ".join(
            f"{product_names.get(holding.get('product_id'), 'Selected fund')} ({holding.get('asset_class')}) {_display_percent(holding.get('weight', 0))}"
            for holding in holdings
        )
        display = (
            f"Your portfolio for C{result.get('investor_class')}: {product_mix}. "
            f"Expected return {_display_percent(result.get('expected_return', 0))}; volatility {_display_percent(result.get('volatility', 0))}."
        )
        if result.get("stress_limit_after") is not None:
            # Without this the model credits the cap to the risk class and tells the client their class set it.
            display += (
                f" Scaled back by the client's own maximum-loss answer, not by the risk class: worst historical stress loss "
                f"{_display_percent(result.get('stress_limit_before') or 0)} before, {_display_percent(result['stress_limit_after'])} after."
            )
        return {"display": display}
    if name == "stress_test":
        return {
            key: result.get(key)
            for key in ("scenario", "loss_percent", "loss_amount", "max_tolerable_loss", "mismatch")
            if key in result
        } | {
            "display": (
                f"{result.get('scenario')} stress: loss {_display_percent(result.get('loss_percent', 0))} "
                f"({result.get('loss_amount')}); limit {_display_percent(result.get('max_tolerable_loss', 0))}; "
                f"limit breached={result.get('mismatch')}."
            ),
        }
    if name == "create_draft_orders":
        orders = result.get("orders", [])
        return {"display": "Draft orders created: " + "; ".join(f"{product_names.get(order.get('product_id'), 'Selected fund')} {order.get('amount')}" for order in orders) + "."}
    if name == "market_quotes":
        return {"quotes": result.get("quotes", [])}
    return {"display": str(result)}


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

    def _allocation_id(self, allocation_id: str) -> str:
        # The model never sees allocation ids, so an id it invents means the client's latest allocation.
        if allocation_id in self.session.state.allocations:
            return allocation_id
        return self.session.state.latest_allocation_id or "latest"

    def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "record_client_facts":
            if self.session:
                require_tier(self.session.tier, PermissionTier.ADVISE)
            facts = _validated(ClientFactsArgs, arguments).model_dump(exclude_unset=True)
            if "amount_cny" in facts:
                facts["amount"] = facts.pop("amount_cny")
            if "max_loss_fraction" in facts:
                facts["max_loss"] = facts.pop("max_loss_fraction")
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
            args = _validated(CompareArgs, arguments)
            args_data = args.model_dump()
            args_data["amount"] = args_data.pop("amount_cny")
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
            args = _validated(AllocationArgs, arguments)
            args_data = args.model_dump()
            args_data["amount"] = args_data.pop("amount_cny")
            args_data["max_tolerable_loss"] = args_data.pop("max_tolerable_loss_fraction")
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
            args = _validated(StressArgs, arguments)
            if not self.session:
                raise ValueError("stress_test requires a server-side AdvisorSession")
            allocation_id = self._allocation_id(args.allocation_id)
            allocation = self.session.stored_allocation(allocation_id)
            max_loss = args.max_tolerable_loss_fraction
            if max_loss is None and self.session:
                max_loss = self.session.state.client.max_loss
            stress_result = stress_test(allocation, scenario=args.scenario, custom_shocks=args.custom_shocks, max_tolerable_loss=max_loss if max_loss is not None else 0.20)
            stress_id = f"stress-{len(self.session.state.stress_results) + 1}"
            self.session.state.stress_results[stress_id] = stress_result
            result = {"stress_id": stress_id, "allocation_id": allocation_id, **stress_result.as_dict()}
        elif name == "create_draft_orders":
            if not self.session:
                raise ValueError("create_draft_orders requires a server-side AdvisorSession")
            require_tier(self.session.tier, PermissionTier.PROPOSE)
            args = DraftOrderArgs.model_validate(arguments)
            result = {"orders": self.session.create_draft_orders(self._allocation_id(args.allocation_id))}
        elif name == "market_quotes":
            MarketQuotesArgs.model_validate(arguments)
            if not self.session:
                raise ValueError("market_quotes requires a server-side AdvisorSession")
            result = {"quotes": [quote.as_dict() for quote in self.session.market.indices(self.audit)]}
        else:
            raise ValueError(f"unknown tool: {name}")
        if self.audit:
            self.audit.append("tool_call", {"tool": name, "result": result})
        return result
