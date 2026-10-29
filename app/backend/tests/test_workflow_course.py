"""Course acceptance with SQLite and mocked DynamoDB (not hardware evidence)."""

from fastapi.testclient import TestClient


def command(client, action, **answers):
    saved = client.get("/api/workflow-course").json()
    return client.post(
        "/api/workflow-course",
        json={"expected_version": saved["version"], "action": action, **answers},
    )


def to_practice(client):
    assert (
        command(client, "inspect", findings=["source", "mixing", "physical"]).json()["phase"]
        == "repair"
    )
    assert (
        command(client, "repair", source_volume=100, mixing="ideal").json()["phase"] == "practice"
    )


def test_complete_course_persists_bounded_synthetic_evidence(client):
    assert client.get("/api/workflow-course").json()["version"] == 0
    to_practice(client)
    trial = command(client, "practice").json()
    assert trial["phase"] == "incident"
    assert trial["trial"]["assessment"]["passed"]
    assert trial["trial"]["assessment"]["concentrations"] == {
        "A1": 50,
        "A2": 25,
        "A3": 12.5,
    }
    assert trial["trial"]["steps"] == len(trial["trial"]["events"]) == 12
    assert trial["trial"]["state"]["tips_discarded"] == 3
    assert trial["evidence"] == trial["trial"]["evidence"] == "synthetic"
    reconciled = command(client, "reconcile", recovery="read").json()
    assert reconciled["reconciled"] and reconciled["phase"] == "reflect"
    result = command(
        client,
        "assess",
        decision="synthetic",
        rationale="Only synthetic volumes were checked; hardware readiness is unknown.",
    ).json()
    assert result["completed"] and result["phase"] == "complete"
    assert client.get("/api/workflow-course").json() == result
    assert client.get("/api/sessions").json() == []
    assert "workflow-readiness" in [c["id"] for c in client.get("/api/courses").json()]
    restarted = command(client, "restart").json()
    assert restarted["version"] == result["version"] + 1
    assert not restarted["completed"] and restarted["trial"] is None
    assert restarted["phase"] == "review" and restarted["rationale"] == ""


def test_wrong_answers_and_skip_attempts_cannot_complete_course(client):
    for action in ["repair", "practice", "reconcile", "assess"]:
        assert command(client, action).status_code == 409
    for gaps in [[], ["source", "mixing"], ["source", "mixing", "physical", "tips"]]:
        result = command(client, "inspect", findings=gaps).json()
        assert result["phase"] == "review" and not result["completed"]
    command(client, "inspect", findings=["source", "mixing", "physical"])
    for volume, mixing in [(50, "ideal"), (100, "command")]:
        result = command(client, "repair", source_volume=volume, mixing=mixing).json()
        assert result["phase"] == "repair" and result["trial"] is None
    command(client, "repair", source_volume=100, mixing="ideal")
    assert command(client, "assess", decision="synthetic", rationale="x" * 30).status_code == 409
    command(client, "practice")
    for choice in ["retry", "assume"]:
        result = command(client, "reconcile", recovery=choice).json()
        assert result["phase"] == "incident" and not result["reconciled"]
    command(client, "reconcile", recovery="read")
    for decision, rationale in [
        ("hardware", "x" * 30),
        ("failed", "x" * 30),
        ("synthetic", " " * 30),
    ]:
        result = command(client, "assess", decision=decision, rationale=rationale).json()
        assert result["phase"] == "reflect" and not result["completed"]


def test_course_rejects_stale_initial_and_later_mutations(client):
    payload = {"expected_version": 0, "action": "inspect", "findings": ["source"]}
    assert client.post("/api/workflow-course", json=payload).status_code == 200
    assert client.post("/api/workflow-course", json=payload).status_code == 409
    before = client.get("/api/workflow-course").json()
    assert command(client, "restart").status_code == 200
    payload["expected_version"] = before["version"]
    assert client.post("/api/workflow-course", json=payload).status_code == 409


def test_course_rejects_forged_results_and_invalid_input(client):
    for extra in [
        {"owner": "victim"},
        {"completed": True},
        {"evidence": "physical"},
        {"trial": {}},
        {"phase": "complete"},
        {"expected_version": True},
        {"source_volume": -1},
        {"source_volume": 1501},
        {"rationale": "x" * 601},
        {"findings": ["unreviewed"]},
    ]:
        response = client.post(
            "/api/workflow-course", json={"expected_version": 0, "action": "inspect", **extra}
        )
        assert response.status_code == 422
    assert client.get("/api/workflow-course").json()["version"] == 0


def test_course_identity_isolation_and_origin(client, app):
    to_practice(client)
    with TestClient(app) as other:
        assert other.get("/api/workflow-course").status_code == 401
        assert (
            other.post(
                "/api/workflow-course", json={"expected_version": 0, "action": "restart"}
            ).status_code
            == 401
        )
        other.post("/api/auth/guest", json={"name": "Grace"})
        assert other.get("/api/workflow-course").json()["version"] == 0
        assert command(other, "restart").status_code == 200
    assert client.get("/api/workflow-course").json()["phase"] == "practice"
    assert (
        client.post(
            "/api/workflow-course",
            json={"expected_version": 2, "action": "restart"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
