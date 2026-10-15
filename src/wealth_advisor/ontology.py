"""Typed advisory ontology and lifecycle invariants.

This module describes *what* an advisory artifact is and whether it is still valid.
Financial calculations remain in profiling, catalog, allocation, stress and goals modules.
The hashes here bind those deterministic results to the exact client, goal and data versions
that produced them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Sequence


CALCULATION_VERSION = "keel-calc-2026-10-15"


class AdvisoryStage(StrEnum):
    FACT_FIND = "FACT_FIND"
    PROFILE_READY = "PROFILE_READY"
    ALLOCATION_READY = "ALLOCATION_READY"
    STRESS_READY = "STRESS_READY"
    GOAL_READY = "GOAL_READY"
    CLIENT_REVIEW = "CLIENT_REVIEW"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    ORDER_PROPOSED = "ORDER_PROPOSED"
    EXECUTED = "EXECUTED"
    STALE = "STALE"
    EXPIRED = "EXPIRED"


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    REVIEW = "review"
    ACCEPTED = "accepted"
    STALE = "stale"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class ConsentStatus(StrEnum):
    PENDING = "pending"
    SIGNED = "signed"
    REVOKED = "revoked"
    EXPIRED = "expired"


class OrderStatus(StrEnum):
    DRAFT = "draft"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXECUTED = "executed"
    CANCELLED = "cancelled"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


def canonical_hash(value: Any) -> str:
    """Return a stable SHA-256 digest for an advisory artifact or snapshot."""

    encoded = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def version_id(prefix: str, value: Any) -> str:
    """Create a readable, content-addressed version identifier."""

    return f"{prefix}-{canonical_hash(value)[:16]}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AuditReference:
    event: str
    audit_hash: str
    timestamp: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ClientFactsRecord:
    """Versioned client facts; this is separate from the backwards-compatible session DTO."""

    client_id: str
    amount_cny: float | None
    horizon_years: int | None
    liquidity_need: str | None
    max_loss_fraction: float | None
    age: int | None
    borrowed_money: bool | None
    income_stability: str | None
    emergency_fund: str | None
    invested_share: str | None
    experience: str | None
    language: str
    updated_at: str
    version: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalRecord:
    goal_id: str
    name: str
    target_cny: float
    years: int
    monthly_cny: float
    inflation_fraction: float
    priority: int
    status: str
    created_at: str
    version: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductSnapshot:
    product_id: str
    name: str
    kind: str
    asset_class: str
    region: str
    risk_class: int
    expected_return: float
    volatility: float
    fee: float
    liquidity_days: int
    min_investment: float
    issuer: str | None
    source_url: str | None
    source_name: str | None
    as_of: str | None
    catalog_version: str
    stale: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Recommendation:
    recommendation_id: str
    profile_id: str
    goal_id: str | None
    allocation_id: str
    profile_version: str
    goal_version: str | None
    catalog_version: str
    calculation_version: str
    created_at: str
    status: str
    expected_return: float
    volatility: float
    fee: float
    var_95: float
    stress_summary: dict[str, Any] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()
    rejected_alternatives: tuple[dict[str, Any], ...] = ()
    stale_reasons: tuple[str, ...] = ()
    audit_reference: AuditReference | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["audit_reference"] = self.audit_reference.as_dict() if self.audit_reference else None
        value["reason_codes"] = list(self.reason_codes)
        value["rejected_alternatives"] = list(self.rejected_alternatives)
        value["stale_reasons"] = list(self.stale_reasons)
        return value

    @property
    def fingerprint(self) -> str:
        return recommendation_fingerprint(self)


@dataclass(frozen=True)
class ClientConsent:
    consent_id: str
    recommendation_id: str
    exact_recommendation_hash: str
    risk_disclosure_hash: str
    client_confirmed_at: str | None
    confirmation_channel: str
    status: str
    audit_reference: AuditReference | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["audit_reference"] = self.audit_reference.as_dict() if self.audit_reference else None
        return value


@dataclass
class OrderProposal:
    order_id: str
    recommendation_id: str
    product_id: str
    amount_cny: float
    risk_class: int
    suitability_result: dict[str, Any]
    created_at: str
    status: str
    order_summary_hash: str
    audit_reference: AuditReference | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["audit_reference"] = self.audit_reference.as_dict() if self.audit_reference else None
        return value


_MATERIAL_FACT_FIELDS = (
    "amount", "horizon_years", "max_loss", "age", "borrowed_money",
    "liquidity_need", "income_stability", "emergency_fund", "invested_share", "experience",
)


def material_facts_changed(old: Mapping[str, Any] | None, new: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Return material fact names whose value changed, including missing→known transitions."""

    old = old or {}
    new = new or {}
    return tuple(field for field in _MATERIAL_FACT_FIELDS if old.get(field) != new.get(field))


def recommendation_fingerprint(recommendation: Recommendation | Mapping[str, Any]) -> str:
    value = recommendation.as_dict() if hasattr(recommendation, "as_dict") else dict(recommendation)
    for ignored in ("status", "stale_reasons", "audit_reference"):
        value.pop(ignored, None)
    return canonical_hash(value)


def consent_fingerprint(consent: ClientConsent | Mapping[str, Any]) -> str:
    value = consent.as_dict() if hasattr(consent, "as_dict") else dict(consent)
    value.pop("audit_reference", None)
    return canonical_hash(value)


def recommendation_stale_reasons(
    recommendation: Recommendation,
    *,
    profile_version: str | None,
    goal_version: str | None,
    catalog_version: str | None,
    calculation_version: str = CALCULATION_VERSION,
    profile_expired: bool = False,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if profile_expired:
        reasons.append("PROFILE_EXPIRED")
    if profile_version and profile_version != recommendation.profile_version:
        reasons.append("PROFILE_VERSION_CHANGED")
    if goal_version != recommendation.goal_version:
        reasons.append("GOAL_VERSION_CHANGED")
    if catalog_version and catalog_version != recommendation.catalog_version:
        reasons.append("CATALOG_VERSION_CHANGED")
    if calculation_version != recommendation.calculation_version:
        reasons.append("CALCULATION_VERSION_CHANGED")
    return tuple(dict.fromkeys(reasons))


def assert_recommendation_current(
    recommendation: Recommendation | None,
    *,
    profile_version: str | None,
    goal_version: str | None,
    catalog_version: str | None,
    profile_expired: bool = False,
) -> Recommendation:
    """Reject missing or stale advice before consent, draft orders or execution."""

    if recommendation is None:
        raise ValueError("recommendation required: build and review a plan first")
    reasons = recommendation_stale_reasons(
        recommendation,
        profile_version=profile_version,
        goal_version=goal_version,
        catalog_version=catalog_version,
        profile_expired=profile_expired,
    )
    if reasons or recommendation.status in {ArtifactStatus.STALE.value, ArtifactStatus.SUPERSEDED.value}:
        recommendation.stale_reasons = tuple(dict.fromkeys((*recommendation.stale_reasons, *reasons)))
        recommendation.status = ArtifactStatus.STALE.value
        detail = ", ".join(recommendation.stale_reasons) or "recommendation status is stale"
        raise ValueError(f"recommendation is stale; refresh the plan first ({detail})")
    return recommendation


_ALLOWED_TRANSITIONS: dict[AdvisoryStage, set[AdvisoryStage]] = {
    AdvisoryStage.FACT_FIND: {AdvisoryStage.PROFILE_READY, AdvisoryStage.ALLOCATION_READY, AdvisoryStage.EXPIRED},
    AdvisoryStage.PROFILE_READY: {AdvisoryStage.ALLOCATION_READY, AdvisoryStage.STRESS_READY, AdvisoryStage.STALE, AdvisoryStage.EXPIRED},
    AdvisoryStage.ALLOCATION_READY: {AdvisoryStage.STRESS_READY, AdvisoryStage.GOAL_READY, AdvisoryStage.CLIENT_REVIEW, AdvisoryStage.STALE},
    AdvisoryStage.STRESS_READY: {AdvisoryStage.GOAL_READY, AdvisoryStage.CLIENT_REVIEW, AdvisoryStage.CONSENT_REQUIRED, AdvisoryStage.STALE},
    AdvisoryStage.GOAL_READY: {AdvisoryStage.ALLOCATION_READY, AdvisoryStage.CLIENT_REVIEW, AdvisoryStage.CONSENT_REQUIRED, AdvisoryStage.STALE},
    AdvisoryStage.CLIENT_REVIEW: {AdvisoryStage.CONSENT_REQUIRED, AdvisoryStage.STALE},
    AdvisoryStage.CONSENT_REQUIRED: {AdvisoryStage.ORDER_PROPOSED, AdvisoryStage.STALE},
    AdvisoryStage.ORDER_PROPOSED: {AdvisoryStage.EXECUTED, AdvisoryStage.CONSENT_REQUIRED, AdvisoryStage.STALE},
    AdvisoryStage.EXECUTED: {AdvisoryStage.STALE, AdvisoryStage.EXPIRED},
    AdvisoryStage.STALE: {AdvisoryStage.PROFILE_READY, AdvisoryStage.ALLOCATION_READY, AdvisoryStage.GOAL_READY, AdvisoryStage.EXPIRED},
    AdvisoryStage.EXPIRED: {AdvisoryStage.FACT_FIND, AdvisoryStage.PROFILE_READY},
}


def transition_stage(current: AdvisoryStage, target: AdvisoryStage) -> AdvisoryStage:
    """Validate a lifecycle transition; no prompt can bypass this function."""

    if target == current:
        return current
    if target not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid advisory stage transition: {current.value} -> {target.value}")
    return target


def catalog_version(products: Sequence[Any]) -> str:
    """Hash the loaded product facts so a changed universe invalidates advice."""

    rows = []
    for product in sorted(products, key=lambda item: item.id):
        value = product.as_dict() if hasattr(product, "as_dict") else dict(product)
        rows.append(value)
    return version_id("catalog", rows)
