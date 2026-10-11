"""Red-team regression gate: harm-preventing controls must hold on every run.

Detection-quality categories (injection heuristics, over-blocking) are tracked in
evals/redteam/REPORT.md rather than gated here, so they can improve without blocking CI.
"""

import importlib.util
from pathlib import Path

import pytest

RUNNER = Path(__file__).parents[1] / "evals" / "redteam" / "run.py"
spec = importlib.util.spec_from_file_location("redteam_run", RUNNER)
redteam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redteam)

GATED = {"suitability_bypass", "execution_control", "audit_integrity", "abuse", "pii"}


@pytest.fixture(scope="module")
def results():
    return redteam.run_suite()


def test_suite_has_enough_cases(results):
    assert len([r for r in results if r["category"] != "benign"]) >= 50


@pytest.mark.parametrize("category", sorted(GATED))
def test_harm_preventing_controls_hold(results, category):
    failures = [f"{r['id']}: {r['detail']}" for r in results if r["category"] == category and not r["passed"]]
    assert not failures, failures
