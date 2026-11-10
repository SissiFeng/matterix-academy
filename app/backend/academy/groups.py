"""Study groups: learners share snapshots of their experiments and discuss them.

A group lives in its own partition. Members are known to each other only by a
random member id and their profile name, never by their sign-in subject.
"""

import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request
from pydantic import Field

from .auth import identify, in_cognito_group
from .learning import present
from .models import Experiment, StrictModel
from .recipes import MIXING
from .store import Conflict, Write
from .teaching import new_session
from .workcell_layout import corners

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MAX_MEMBERS = 40
MAX_GROUPS = 20
MAX_SHARES = 100
MAX_COMMENTS = 100


class CreateGroup(StrictModel):
    name: str = Field(min_length=1, max_length=60)


class JoinGroup(StrictModel):
    code: str = Field(min_length=8, max_length=8, pattern=r"^[A-Za-z0-9]+$")


class ShareExperiment(StrictModel):
    session_id: UUID


class Comment(StrictModel):
    version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=500)


class Removal(StrictModel):
    version: int = Field(ge=1)


def now():
    return datetime.now(UTC).isoformat()


def install(app, *, store):
    def learner_name(owner):
        profile = store.get(owner, "profile")
        return profile["name"] if profile else "Learner"

    def membership(owner, group_id):
        found = store.get(owner, f"membership#{group_id}")
        if found is None:
            raise HTTPException(404, "Study group not found")
        group = store.get(f"group#{group_id}", "group")
        member = next((m for m in group["members"] if m["id"] == found["member_id"]), None)
        if member is None:
            raise HTTPException(404, "Study group not found")
        return group, member

    def shares(group_id):
        return sorted(
            store.partition(f"group#{group_id}", "share#", MAX_SHARES),
            key=lambda share: share["shared_at"],
            reverse=True,
        )

    def view(group, member):
        return {
            **{k: group[k] for k in ("id", "name", "version", "created_at")},
            # Only facilitators hand out the code; members invite through them.
            "code": group["code"] if member["role"] == "facilitator" else None,
            "you": member,
            "members": [{"name": m["name"], "role": m["role"]} for m in group["members"]],
            "shares": shares(group["id"]),
        }

    def get_share(group_id, share_id):
        share = store.get(f"group#{group_id}", f"share#{share_id}")
        if share is None:
            raise HTTPException(404, "Shared experiment not found")
        return share

    @app.get("/api/groups")
    def groups(request: Request, owner: str = Depends(identify)):
        listed = []
        for found in store.partition(owner, "membership#", MAX_GROUPS):
            group = store.get(f"group#{found['group_id']}", "group")
            if group:
                listed.append(
                    {
                        "id": group["id"],
                        "name": group["name"],
                        "members": len(group["members"]),
                        "shares": len(shares(group["id"])),
                    }
                )
        return {"groups": listed, "can_create": can_create(request)}

    def can_create(request):
        group = request.app.state.settings.instructor_group
        return not group or in_cognito_group(request, group)

    @app.post("/api/groups", status_code=201)
    def create_group(data: CreateGroup, request: Request, owner: str = Depends(identify)):
        if not can_create(request):
            raise HTTPException(403, "Ask your instructor to create the group and share its code")
        if len(store.partition(owner, "membership#", MAX_GROUPS)) >= MAX_GROUPS:
            raise HTTPException(409, f"You can belong to at most {MAX_GROUPS} study groups")
        member = {"id": str(uuid4()), "name": learner_name(owner), "role": "facilitator"}
        group_id = str(uuid4())
        for _ in range(3):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            group = {
                "id": group_id,
                "name": data.name.strip(),
                "code": code,
                "version": 1,
                "created_at": now(),
                "members": [member],
            }
            try:
                store.transact(
                    [
                        Write(
                            f"groupcode#{code}", "group", {"group_id": group_id, "version": 1}, None
                        ),
                        Write(f"group#{group_id}", "group", group, None),
                        Write(
                            owner,
                            f"membership#{group_id}",
                            {"group_id": group_id, "member_id": member["id"], "version": 1},
                            None,
                        ),
                    ]
                )
            except Conflict:
                continue  # a join code collision; draw another
            return view(group, member)
        raise HTTPException(503, "Could not allocate a join code. Try again.")

    @app.post("/api/groups/join")
    def join_group(data: JoinGroup, owner: str = Depends(identify)):
        pointer = store.get(f"groupcode#{data.code.upper()}", "group")
        if pointer is None:
            raise HTTPException(404, "No study group uses that code")
        group_id = pointer["group_id"]
        found = store.get(owner, f"membership#{group_id}")
        if found:
            return view(*membership(owner, group_id))
        if len(store.partition(owner, "membership#", MAX_GROUPS)) >= MAX_GROUPS:
            raise HTTPException(409, f"You can belong to at most {MAX_GROUPS} study groups")
        group = store.get(f"group#{group_id}", "group")
        if len(group["members"]) >= MAX_MEMBERS:
            raise HTTPException(409, "This study group is full")
        member = {"id": str(uuid4()), "name": learner_name(owner), "role": "member"}
        updated = {**group, "version": group["version"] + 1, "members": [*group["members"], member]}
        store.transact(
            [
                Write(f"group#{group_id}", "group", updated, group["version"]),
                Write(
                    owner,
                    f"membership#{group_id}",
                    {"group_id": group_id, "member_id": member["id"], "version": 1},
                    None,
                ),
            ]
        )
        return view(updated, member)

    @app.get("/api/groups/{group_id}")
    def group_detail(group_id: UUID, owner: str = Depends(identify)):
        return view(*membership(owner, group_id))

    @app.post("/api/groups/{group_id}/shares", status_code=201)
    def share_experiment(group_id: UUID, data: ShareExperiment, owner: str = Depends(identify)):
        group, member = membership(owner, group_id)
        session = store.get(owner, f"session#{data.session_id}")
        if session is None:
            raise HTTPException(404, "Experiment not found")
        if session["experiment"]["course_id"] == MIXING:
            raise HTTPException(409, "Native simulation recipes cannot be shared yet")
        experiment = Experiment.model_validate(present(session)["experiment"]).model_dump()
        share_id = f"{member['id']}_{data.session_id}"
        key = f"share#{share_id}"
        existing = store.get(f"group#{group_id}", key)
        if existing is None and len(shares(group_id)) >= MAX_SHARES:
            raise HTTPException(409, "This study group has reached its shared experiment limit")
        assessment = session.get("assessment") or {}
        share = {
            "id": share_id,
            "version": (existing["version"] if existing else 0) + 1,
            "member_id": member["id"],
            "author": member["name"],
            "shared_at": now(),
            "kind": "experiment",
            "experiment": experiment,
            # Teaching outcomes stay synthetic; nothing here claims physical validation.
            "evidence": "synthetic",
            "status": session["status"],
            "passed": assessment.get("passed") if assessment else None,
            "comments": existing["comments"] if existing else [],
        }
        store.put(f"group#{group_id}", key, share, existing["version"] if existing else None)
        return share

    @app.post("/api/groups/{group_id}/layout", status_code=201)
    def share_layout(group_id: UUID, request: Request, owner: str = Depends(identify)):
        """One bench layout per member, for the group to discuss rather than copy."""
        _, member = membership(owner, group_id)
        record = request.app.state.twins.get(owner)
        if not record.get("layout"):
            raise HTTPException(409, "Save a bench layout in Plan a layout first")
        twins = {t["id"]: t for t in record["twins"]}
        arms = {s["device_id"] for s in record["steps"] if s["operation"] == "transfer"}
        share_id = f"{member['id']}_layout"
        key = f"share#{share_id}"
        existing = store.get(f"group#{group_id}", key)
        if existing is None and len(shares(group_id)) >= MAX_SHARES:
            raise HTTPException(409, "This study group has reached its shared experiment limit")
        share = {
            "id": share_id,
            "version": (existing["version"] if existing else 0) + 1,
            "member_id": member["id"],
            "author": member["name"],
            "shared_at": now(),
            "kind": "layout",
            # A planning sketch: nothing here claims a measured or validated cell.
            "evidence": "synthetic",
            "layout": {
                "bench": record["layout"]["bench"],
                "instruments": [
                    {
                        "name": twins[p["twin_id"]]["spec"]["name"],
                        "arm": p["twin_id"] in arms,
                        "corners": [
                            [round(x, 3), round(z, 3)]
                            for x, z in corners(twins[p["twin_id"]]["spec"], p)
                        ],
                    }
                    for p in record["layout"]["placements"]
                ],
                "transfers": [
                    {
                        "from": twins[s["source_id"]]["spec"]["name"],
                        "to": twins[s["target_id"]]["spec"]["name"],
                    }
                    for s in record["steps"]
                    if s["operation"] == "transfer"
                ],
            },
            "comments": existing["comments"] if existing else [],
        }
        store.put(f"group#{group_id}", key, share, existing["version"] if existing else None)
        return share

    @app.post("/api/groups/{group_id}/shares/{share_id}/comments")
    def comment(group_id: UUID, share_id: str, data: Comment, owner: str = Depends(identify)):
        _, member = membership(owner, group_id)
        share = get_share(group_id, share_id)
        if share["version"] != data.version:
            raise Conflict
        if len(share["comments"]) >= MAX_COMMENTS:
            raise HTTPException(409, "This discussion is full")
        share = {
            **share,
            "version": share["version"] + 1,
            "comments": [
                *share["comments"],
                {"author": member["name"], "text": data.text.strip(), "at": now()},
            ],
        }
        store.put(f"group#{group_id}", f"share#{share_id}", share, data.version)
        return share

    @app.post("/api/groups/{group_id}/shares/{share_id}/remove")
    def unshare(group_id: UUID, share_id: str, data: Removal, owner: str = Depends(identify)):
        _, member = membership(owner, group_id)
        share = get_share(group_id, share_id)
        if share["member_id"] != member["id"] and member["role"] != "facilitator":
            raise HTTPException(403, "Only the author or a facilitator can remove this")
        store.transact([Write(f"group#{group_id}", f"share#{share_id}", None, data.version)])
        return {"removed": share_id}

    @app.post("/api/groups/{group_id}/shares/{share_id}/copy", status_code=201)
    def copy_share(group_id: UUID, share_id: str, owner: str = Depends(identify)):
        membership(owner, group_id)
        share = get_share(group_id, share_id)
        if "experiment" not in share:
            raise HTTPException(409, "A shared layout is discussed here, not copied")
        title = f"{share['experiment']['title']} · {share['author']}"[:80]
        experiment = Experiment.model_validate({**share["experiment"], "title": title})
        session = new_session(experiment)
        store.put(owner, f"session#{session['id']}", session, None)
        return present(session)
