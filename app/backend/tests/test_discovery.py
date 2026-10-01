from copy import deepcopy
from uuid import uuid4

from fastapi.testclient import TestClient


def brief():
    return {
        "id": str(uuid4()),
        "title": "A controlled blend study",
        "source_id": "clio",
        "objective": "Compare repeatability across blend ratios",
        "variables": "Ratio changes, total volume stays fixed",
        "measurement": "Measure an optical response in arbitrary teaching units",
        "decision": "Repeat the most variable recipe before choosing the next region",
        "controls": "Two repeats per ratio and a blank",
        "methods": ["blend", "mix"],
        "gantry": "liquid",
        "status": "design_only",
    }


def test_notebook_is_versioned_persistent_and_separate_from_runs(client):
    assert client.get("/api/discovery").json() == {"version": 0, "briefs": []}
    item = brief()
    first = client.put("/api/discovery", json={"expected_version": 0, "briefs": [item]})
    assert first.status_code == 200
    assert first.json() == {"version": 1, "briefs": [item]}
    assert client.get("/api/discovery").json() == first.json()
    assert client.get("/api/sessions").json() == []
    # A second initial create and a stale edit must not overwrite the saved record.
    assert (
        client.put("/api/discovery", json={"expected_version": 0, "briefs": []}).status_code == 409
    )
    revised = deepcopy(item)
    revised["measurement"] = "Add a replicate measurement"
    assert (
        client.put("/api/discovery", json={"expected_version": 1, "briefs": [revised]}).status_code
        == 200
    )
    assert (
        client.put("/api/discovery", json={"expected_version": 1, "briefs": []}).status_code == 409
    )
    assert client.get("/api/discovery").json()["briefs"] == [revised]


def test_notebook_owner_cannot_be_supplied_by_client(client, app):
    item = brief()
    client.put("/api/discovery", json={"expected_version": 0, "briefs": [item]})
    with TestClient(app) as other:
        assert other.get("/api/discovery").status_code == 401
        assert (
            other.put("/api/discovery", json={"expected_version": 0, "briefs": []}).status_code
            == 401
        )
        other.post("/api/auth/guest", json={"name": "Grace"})
        assert other.get("/api/discovery").json()["briefs"] == []
        assert (
            other.put(
                "/api/discovery", json={"expected_version": 0, "briefs": [], "owner": "Ada"}
            ).status_code
            == 422
        )
        assert (
            other.put("/api/discovery", json={"expected_version": 0, "briefs": []}).status_code
            == 200
        )
    assert client.get("/api/discovery").json()["briefs"] == [item]


def test_notebook_rejects_unbounded_unknown_or_executable_content(client):
    cases = []
    for key, value in [
        ("objective", " " * 5),
        ("objective", "x" * 601),
        ("source_id", "unreviewed-paper"),
        ("methods", []),
        ("methods", ["blend", "blend"]),
        ("methods", ["arbitrary-tool"]),
        ("status", "ready_to_run"),
        ("gantry", "live"),
        ("title", "x" * 101),
        ("id", "not-an-id"),
    ]:
        item = brief()
        item[key] = value
        cases.append({"expected_version": 0, "briefs": [item]})
    same = brief()
    cases.extend(
        [
            {"expected_version": 0, "briefs": [same, same]},
            {"expected_version": 0, "briefs": [brief() for _ in range(21)]},
            {"expected_version": -1, "briefs": []},
            {"expected_version": True, "briefs": []},
        ]
    )
    for payload in cases:
        assert client.put("/api/discovery", json=payload).status_code == 422
    assert client.get("/api/discovery").json()["version"] == 0


def test_notebook_origin_boundary(client):
    assert (
        client.put(
            "/api/discovery",
            json={"expected_version": 0, "briefs": [brief()]},
            headers={"Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    assert client.get("/api/discovery").json()["briefs"] == []


def test_notebook_bounds_serialized_storage_size(client):
    items = [brief() for _ in range(20)]
    for item in items:
        for field in ("objective", "variables", "measurement", "decision", "controls"):
            item[field] = "🧪" * 600
    response = client.put("/api/discovery", json={"expected_version": 0, "briefs": items})
    assert response.status_code == 422
    assert "storage limit" in response.text
