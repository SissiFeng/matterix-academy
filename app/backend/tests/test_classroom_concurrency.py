"""Five local learners share SQLite; this is not an AWS capacity measurement."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier

from academy.main import create_app
from academy.settings import Settings
from fastapi.testclient import TestClient


def concurrent_posts(clients, requests, *, competing=False):
    """Release all requests together, including duplicate versions from each learner."""
    copies = 2 if competing else 1
    barrier = Barrier(len(clients) * copies, timeout=10)

    def post(index):
        path, payload = requests[index]
        barrier.wait()
        return index, clients[index].post(path, json=payload)

    grouped = [[] for _ in clients]
    with ThreadPoolExecutor(max_workers=len(clients) * copies) as pool:
        pending = [pool.submit(post, index) for index in range(len(clients)) for _ in range(copies)]
        for future in pending:
            index, response = future.result(timeout=20)
            grouped[index].append(response)
    saved = []
    for responses in grouped:
        assert sorted(response.status_code for response in responses) == (
            [200, 409] if competing else [200]
        ), [response.text for response in responses]
        saved.append(next(response.json() for response in responses if response.status_code == 200))
    return saved


def course_round(clients, states, action, *, competing=False, **answers):
    return concurrent_posts(
        clients,
        [
            (
                "/api/workflow-course",
                {"expected_version": state["version"], "action": action, **answers},
            )
            for state in states
        ],
        competing=competing,
    )


def session_round(clients, sessions, action, *, competing=False):
    return concurrent_posts(
        clients,
        [
            (f"/api/sessions/{session['id']}/{action}", {"version": session["version"]})
            for session in sessions
        ],
        competing=competing,
    )


def test_five_learners_complete_reset_and_repeat_without_cross_owner_or_replayed_progress(tmp_path):
    app = create_app(
        Settings(
            allow_demo=True,
            secret="classroom-test-secret-at-least-32-characters",
            data_path=str(tmp_path / "classroom.sqlite"),
        )
    )
    with ExitStack() as stack:
        clients = [stack.enter_context(TestClient(app)) for _ in range(5)]
        sessions = []
        for index, client in enumerate(clients):
            assert (
                client.post("/api/auth/guest", json={"name": f"Learner {index}"}).status_code == 200
            )
            response = client.post("/api/sessions", json={"title": f"Learner {index} dilution"})
            assert response.status_code == 201
            sessions.append(response.json())
        assert len({client.cookies.get("academy_local") for client in clients}) == 5
        assert len({session["id"] for session in sessions}) == 5
        initial_states = [session["state"] for session in sessions]
        courses = [client.get("/api/workflow-course").json() for client in clients]
        courses = course_round(
            clients, courses, "inspect", findings=["source", "mixing", "physical"]
        )

        # Different plans reveal owner mix-ups even when every learner is at the same stage.
        courses = concurrent_posts(
            clients,
            [
                (
                    "/api/workflow-course",
                    {
                        "expected_version": course["version"],
                        "action": "repair",
                        "source_volume": 100 + index * 10,
                        "mixing": "ideal",
                    },
                )
                for index, course in enumerate(courses)
            ],
        )

        for attempt in range(2):
            sessions = session_round(clients, sessions, "start")
            sessions = session_round(clients, sessions, "advance", competing=True)
            for session in sessions:
                assert (
                    session["cursor"]
                    == session["state"]["tips_used"]
                    == len(session["events"])
                    == 1
                )
            if attempt == 0:
                courses = course_round(clients, courses, "practice", competing=True)
                for course in courses:
                    assert course["version"] == 3
                    assert course["trial"]["steps"] == len(course["trial"]["events"]) == 12
                    assert course["evidence"] == course["trial"]["evidence"] == "synthetic"
            for _ in range(11):
                sessions = session_round(clients, sessions, "advance")
            for session in sessions:
                assert session["status"] == "completed"
                assert session["assessment"]["passed"]
                assert session["cursor"] == len(session["events"]) == 12
                assert session["state"]["tips_used"] == session["state"]["tips_discarded"] == 3
            if attempt == 0:
                courses = course_round(clients, courses, "reconcile", recovery="read")
                courses = course_round(
                    clients,
                    courses,
                    "assess",
                    decision="synthetic",
                    rationale="Only synthetic teaching evidence was checked; hardware remains unknown.",
                )
            # A repeated reset with the original version may create only one history entry.
            sessions = session_round(clients, sessions, "reset", competing=True)
            for index, session in enumerate(sessions):
                assert session["status"] == "draft" and session["cursor"] == 0
                assert session["state"] == initial_states[index] and session["events"] == []
                assert len(session["attempts"]) == attempt + 1
                assert all(summary["steps"] == 12 for summary in session["attempts"])

        for index, client in enumerate(clients):
            # Fresh browser sessions recover the exact saved records with their own cookie.
            with TestClient(app) as reconnect:
                reconnect.cookies.update(client.cookies)
                assert reconnect.get("/api/me").json()["name"] == f"Learner {index}"
                assert reconnect.get("/api/sessions").json() == [sessions[index]]
                recovered = reconnect.get("/api/workflow-course").json()
                assert recovered == courses[index] and recovered["completed"]
                assert recovered["plan"]["source_volume"] == 100 + index * 10
                for other in sessions:
                    if other["id"] != sessions[index]["id"]:
                        assert reconnect.get(f"/api/sessions/{other['id']}").status_code == 404
                foreign = sessions[(index + 1) % len(sessions)]
                assert (
                    reconnect.post(
                        f"/api/sessions/{foreign['id']}/start", json={"version": foreign["version"]}
                    ).status_code
                    == 404
                )
        # Rejected foreign writes did not alter the owner's saved session.
        assert [client.get("/api/sessions").json() for client in clients] == [
            [session] for session in sessions
        ]
