import pytest

from wealth_advisor.config import Settings
from wealth_advisor.ontology import (
    AdvisoryStage,
    Recommendation,
    assert_recommendation_current,
    material_facts_changed,
    transition_stage,
)
from wealth_advisor.permissions import PermissionTier
from wealth_advisor.session import AdvisorSession


ANSWERS = {
    "horizon": "7_10y",
    "liquidity_need": "over_30d",
    "income_stability": "stable",
    "emergency_fund": "over_6_months",
    "invested_share": "under_25",
    "drawdown_reaction": "hold",
    "experience": "good",
    "goal": "growth",
}


def session(tmp_path, tier=PermissionTier.PROPOSE):
    return AdvisorSession(Settings(llm_mode="replay", audit_log=tmp_path / "audit.jsonl"), tier)


def prepared(tmp_path, tier=PermissionTier.PROPOSE):
    current = session(tmp_path, tier)
    current.dispatcher.dispatch("record_client_facts", {"amount_cny": 200_000, "horizon_years": 8, "max_loss_fraction": 0.20, "age": 28})
    current.dispatcher.dispatch("profile_investor", {"answers": ANSWERS, "age": 28, "borrowed_money": False})
    current.dispatcher.dispatch("build_allocation", {})
    return current


def test_material_facts_and_stage_transitions_are_explicit():
    assert material_facts_changed({"amount": 10, "age": 30}, {"amount": 10, "age": 31}) == ("age",)
    assert transition_stage(AdvisoryStage.FACT_FIND, AdvisoryStage.PROFILE_READY) == AdvisoryStage.PROFILE_READY
    with pytest.raises(ValueError, match="invalid advisory stage"):
        transition_stage(AdvisoryStage.FACT_FIND, AdvisoryStage.EXECUTED)


def test_recommendation_is_bound_to_versions(tmp_path):
    current = prepared(tmp_path)
    recommendation = current.state.recommendation
    assert recommendation is not None
    assert recommendation.catalog_version
    assert recommendation.calculation_version
    assert recommendation.fingerprint
    assert_recommendation_current(
        recommendation,
        profile_version=current.current_profile_version(),
        goal_version=current.current_goal_version(),
        catalog_version=current.current_catalog_version(),
    )


def test_material_change_stales_recommendation_and_blocks_drafts(tmp_path):
    current = prepared(tmp_path)
    assert current.state.recommendation.status == "review"
    current.dispatcher.dispatch("record_client_facts", {"max_loss_fraction": 0.05})
    assert current.state.recommendation.status == "stale"
    assert "CLIENT_FACTS_CHANGED" in current.state.recommendation.stale_reasons
    with pytest.raises(ValueError, match="recommendation is stale"):
        current.create_draft_orders()


def test_goal_change_stales_recommendation_and_refresh_replaces_it(tmp_path):
    current = prepared(tmp_path)
    first_id = current.state.recommendation.recommendation_id
    current.dispatcher.dispatch("plan_goal", {"target_cny": 500_000, "years": 8, "monthly_cny": 2_000})
    assert current.state.recommendation.status == "stale"
    refreshed = current.dispatcher.dispatch("refresh_recommendation", {"reason": "goal_changed"})
    assert refreshed["allocation_id"]
    assert current.state.recommendation.recommendation_id != first_id
    assert current.state.recommendation.status == "review"
