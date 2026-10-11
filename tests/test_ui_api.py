"""Web UI API contract: suitability is enforced server-side and numbers carry provenance."""

from fastapi.testclient import TestClient

from wealth_advisor.ui.server import app

ANSWERS = {
    "horizon": "3_7y",
    "income_stability": "mixed",
    "emergency_fund": "3_6_months",
    "invested_share": "25_50",
    "drawdown_reaction": "hold",
    "experience": "good",
    "goal": "growth",
}


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LLM_MODE", "replay")
    return TestClient(app)


def _profile(client: TestClient) -> dict:
    questions = {q["key"]: q for q in client.get("/api/questionnaire").json()}
    answers = {key: value for key, value in ANSWERS.items() if key in questions}
    for key, question in questions.items():  # tolerate questions added to the engine later
        answers.setdefault(key, question["options"][len(question["options"]) // 2]["key"])
    response = client.post("/api/profile", json={"answers": answers, "age": 35, "amount": 100_000, "horizon_years": 10, "max_loss": 0.2})
    assert response.status_code == 200, response.text
    return response.json()


def test_full_flow_with_provenance(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    profile = _profile(client)
    assert profile["provenance"]["source"] == "profiling.profile_investor"
    allocation = client.post("/api/allocation", json={}).json()
    assert abs(sum(h["weight"] for h in allocation["allocation"]["holdings"]) - 1) < 1e-9
    assert len(allocation["provenance"]["audit_hash"]) == 64
    assert client.get("/api/compare").status_code == 200
    stress = client.get("/api/stress").json()
    assert {s["key"] for s in stress["scenarios"]} >= {"2008_gfc"}
    audit = client.get("/api/audit").json()
    assert audit["valid"] and audit["total"] >= 4


def test_allocation_above_assessed_class_is_blocked(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    level = _profile(client)["profile"]["investor_class"]
    if level < 5:
        response = client.post("/api/allocation", json={"investor_class": level + 1})
        assert response.status_code == 403


def test_steps_require_a_profile(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/api/allocation", json={}).status_code == 409
    assert client.get("/api/stress").status_code == 409
