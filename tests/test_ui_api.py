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


def test_human_confirmation_flow(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _profile(client)
    client.post("/api/allocation", json={})
    assert client.post("/api/orders/draft").status_code == 403  # advice-only until the disclosure is signed
    assert client.post("/api/consent", json={"full_name": "Test Client", "accepted": True}).json()["tier"] == "EXECUTE"
    orders = [o for o in client.post("/api/orders/draft").json()["orders"] if not o["cooling_off"]]
    ids = [o["order_id"] for o in orders]
    tokens = client.post("/api/orders/tokens", json={"order_ids": ids}).json()["tokens"]
    forged = client.post("/api/orders/confirm", json={"tokens": {ids[0]: "forged"}}).json()
    assert forged["executed"] == [] and forged["failed"]
    tokens = client.post("/api/orders/tokens", json={"order_ids": ids}).json()["tokens"]
    result = client.post("/api/orders/confirm", json={"tokens": tokens}).json()
    assert len(result["executed"]) == len(ids) and not result["failed"]
    replay = client.post("/api/orders/confirm", json={"tokens": tokens}).json()
    assert replay["executed"] == []  # one-time tokens cannot be reused


def test_advice_report_is_fingerprinted(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/report").status_code == 409
    _profile(client)
    client.post("/api/allocation", json={})
    client.post("/api/goal", json={"target": 300_000, "years": 8, "monthly": 1_000})
    page = client.get("/report")
    assert page.status_code == 200 and "Advice Report" in page.text and "Recommended portfolio" in page.text
    events = [r["event"] for r in client.get("/api/audit").json()["records"]]
    assert "advice_report_issued" in events


def test_profile_built_in_chat_appears_in_ui_state(tmp_path, monkeypatch):
    from wealth_advisor.ui import server

    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/state").json()["profile"] is None
    file = server._FILES[client.cookies["wa_sid"]]
    questions = client.get("/api/questionnaire").json()
    answers = {q["key"]: q["options"][len(q["options"]) // 2]["key"] for q in questions}
    # Same calls the agent makes through its tools during conversational KYC.
    file.session.dispatcher.dispatch("record_client_facts", {"amount": 80_000, "horizon_years": 6, "max_loss": 0.15, "age": 29})
    file.session.dispatcher.dispatch("profile_investor", {"answers": answers, "age": 29})
    file.session.dispatcher.dispatch("build_allocation", {"amount": 80_000})
    state = client.get("/api/state").json()
    assert state["profile"]["investor_class"] >= 1
    assert state["answers"] == answers
    assert state["client"]["amount"] == 80_000
    assert state["allocation"]["amount"] == 80_000
    assert state["allocation_provenance"]["source"] == "agent tool build_allocation"
