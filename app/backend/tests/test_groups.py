from dataclasses import replace

from fastapi.testclient import TestClient


def learner(app, name):
    client = TestClient(app)
    assert client.post("/api/auth/guest", json={"name": name}).status_code == 200
    profile = {"name": name, "experience": "new", "onboarded": True}
    assert client.put("/api/me", json=profile).status_code == 200
    return client


def experiment(client, title):
    created = client.post("/api/sessions", json={"title": title})
    assert created.status_code == 201
    return created.json()


def test_two_learners_share_compare_and_discuss(app):
    ada, grace = learner(app, "Ada"), learner(app, "Grace")
    group = ada.post("/api/groups", json={"name": "Dilution pair"}).json()
    assert group["you"]["role"] == "facilitator" and len(group["code"]) == 8

    joined = grace.post("/api/groups/join", json={"code": group["code"].lower()}).json()
    assert joined["you"]["role"] == "member"
    assert joined["code"] is None  # only facilitators hand out the code
    assert [m["name"] for m in joined["members"]] == ["Ada", "Grace"]
    # Joining twice keeps one membership.
    again = grace.post("/api/groups/join", json={"code": group["code"]}).json()
    assert len(again["members"]) == 2

    ada_run = experiment(ada, "Ada's dilution")
    grace_run = experiment(grace, "Grace's dilution")
    path = f"/api/groups/{group['id']}/shares"
    shared = ada.post(path, json={"session_id": ada_run["id"]}).json()
    grace.post(path, json={"session_id": grace_run["id"]})
    assert shared["author"] == "Ada" and shared["evidence"] == "synthetic"
    assert "owner" not in shared and "sub" not in str(shared)

    seen = grace.get(f"/api/groups/{group['id']}").json()
    assert {s["experiment"]["title"] for s in seen["shares"]} == {
        "Ada's dilution",
        "Grace's dilution",
    }

    # Re-sharing replaces the snapshot and keeps the discussion.
    discussed = grace.post(
        f"{path}/{shared['id']}/comments",
        json={"version": shared["version"], "text": "Why 100 µL?"},
    ).json()
    assert discussed["comments"][0]["author"] == "Grace"
    stale = ada.post(
        f"{path}/{shared['id']}/comments", json={"version": shared["version"], "text": "x"}
    )
    assert stale.status_code == 409
    reshared = ada.post(path, json={"session_id": ada_run["id"]}).json()
    assert reshared["id"] == shared["id"] and len(reshared["comments"]) == 1

    copied = grace.post(f"{path}/{shared['id']}/copy")
    assert copied.status_code == 201
    assert copied.json()["experiment"]["title"] == "Ada's dilution · Ada"
    assert copied.json()["experiment"]["actions"] == ada_run["experiment"]["actions"]

    # Members remove only their own shares; the facilitator may remove any.
    current = grace.get(f"/api/groups/{group['id']}").json()["shares"]
    ada_share = next(s for s in current if s["author"] == "Ada")
    grace_share = next(s for s in current if s["author"] == "Grace")
    denied = grace.post(f"{path}/{ada_share['id']}/remove", json={"version": ada_share["version"]})
    assert denied.status_code == 403
    removed = ada.post(
        f"{path}/{grace_share['id']}/remove", json={"version": grace_share["version"]}
    )
    assert removed.status_code == 200

    listed = grace.get("/api/groups").json()
    assert listed["groups"] == [
        {"id": group["id"], "name": "Dilution pair", "members": 2, "shares": 1}
    ]


def test_outsiders_cannot_read_or_share(app):
    ada, eve = learner(app, "Ada"), learner(app, "Eve")
    group = ada.post("/api/groups", json={"name": "Private"}).json()
    assert eve.get(f"/api/groups/{group['id']}").status_code == 404
    run = experiment(eve, "Eve's")
    assert (
        eve.post(f"/api/groups/{group['id']}/shares", json={"session_id": run["id"]}).status_code
        == 404
    )
    assert eve.post("/api/groups/join", json={"code": "ZZZZZZZZ"}).status_code == 404
    # A member cannot share somebody else's experiment.
    eve.post("/api/groups/join", json={"code": group["code"]})
    ada_run = experiment(ada, "Ada's")
    shared = eve.post(f"/api/groups/{group['id']}/shares", json={"session_id": ada_run["id"]})
    assert shared.status_code == 404


def test_instructor_group_limits_who_creates(app):
    app.state.settings = replace(app.state.settings, instructor_group="instructors")
    ada = learner(app, "Ada")
    assert ada.get("/api/groups").json()["can_create"] is False
    assert ada.post("/api/groups", json={"name": "x"}).status_code == 403


def test_a_bench_layout_is_shared_for_discussion_not_copied(app):
    from tests.test_layout import placed_cell, placements, save_layout

    ada, grace = learner(app, "Ada"), learner(app, "Grace")
    group = ada.post("/api/groups", json={"name": "Cell"}).json()
    grace.post("/api/groups/join", json={"code": group["code"]})
    path = f"/api/groups/{group['id']}"
    assert ada.post(f"{path}/layout").status_code == 409  # nothing saved yet

    reader, heater, arm, _, catalog = placed_cell(ada)
    rows = placements(reader, heater, arm)
    assert save_layout(ada, catalog["version"], rows).status_code == 200
    shared = ada.post(f"{path}/layout")
    assert shared.status_code == 201
    share = shared.json()
    assert share["kind"] == "layout" and share["evidence"] == "synthetic"
    assert len(share["layout"]["instruments"]) == 3
    assert sum(i["arm"] for i in share["layout"]["instruments"]) == 1
    assert len(share["layout"]["transfers"]) == 1
    assert str(arm) not in str(share)  # twin ids stay with their owner

    # Everyone discusses the same layout; sharing again keeps the thread.
    talked = grace.post(
        f"{path}/shares/{share['id']}/comments",
        json={"version": share["version"], "text": "Reader is far from the arm"},
    ).json()
    assert grace.post(f"{path}/shares/{share['id']}/copy").status_code == 409
    again = ada.post(f"{path}/layout").json()
    assert again["id"] == share["id"] and again["comments"] == talked["comments"]
    assert len(grace.get(path).json()["shares"]) == 1


def test_researcher_group_limits_layout_planning(app):
    ada = learner(app, "Ada")
    assert ada.get("/api/access").json() == {"plan_layouts": True}
    app.state.settings = replace(app.state.settings, researcher_group="researchers")
    assert ada.get("/api/access").json() == {"plan_layouts": False}
    search = ada.post("/api/twins/layout/search", json={"bench": {"width": 2, "depth": 1}})
    assert search.status_code == 403
    saved = ada.put("/api/twins/layout/constraints", json={"expected_version": 0})
    assert saved.status_code == 403
