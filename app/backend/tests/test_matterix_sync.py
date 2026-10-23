"""Static upstream intake must never grant runtime support or trust mutable names."""

import copy
import hashlib
import json

import pytest
from academy import matterix_sync
from academy.matterix_sync import (
    build_candidate,
    render_report,
    serialized_candidate,
    validate_candidate,
)

TASK = "source/matterix_tasks/tasks.py"
ACTION = "source/matterix_sm/primitive_actions/pour.py"
SEMANTIC = "source/matterix/managers/semantics/state.py"
DEVICE = "source/matterix_assets/devices/robot.py"


def blob(text):
    raw = text.encode("utf-8")
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False).hexdigest()


def entry(path, text, mode="100644", kind="blob"):
    return {"path": path, "mode": mode, "type": kind, "sha": blob(text)}


@pytest.fixture
def inputs():
    policy = {
        "schema_version": 1,
        "repositories": {
            "engine": {"repository": "ac-rad/Matterix-Internal", "ref": "main"},
            "assets": {"repository": "ac-rad/Matterix_assets_internal", "ref": "main"},
        },
        "limits": {
            "max_tree_entries": 20000,
            "max_source_files": 1000,
            "max_source_bytes": 20000000,
            "max_changed_files": 10000,
        },
        "required_paths": {"engine": [TASK, ACTION], "assets": ["robots/flex.usda"]},
        "surfaces": [
            {
                "id": "engine",
                "label": "Engine and recipes",
                "repository": "engine",
                "prefixes": ["source/"],
                "academy_paths": ["app/backend/academy/native_isaac.py"],
                "required_gates": ["native-workflow", "english-course-coverage"],
            },
            {
                "id": "assets",
                "label": "Independent asset payloads",
                "repository": "assets",
                "prefixes": [""],
                "academy_paths": ["app/backend/academy/runtime_inventory.py"],
                "required_gates": ["materialized-lfs-hashes"],
            },
        ],
    }
    profile = {
        "engine_repository": policy["repositories"]["engine"]["repository"],
        "asset_repository": policy["repositories"]["assets"]["repository"],
        "engine_commit": "a" * 40,
        "asset_commit": "b" * 40,
        "academy_adapter_sha256": "a" * 64,
    }
    sources = {
        TASK: "import gymnasium as gym\ngym.register(id='Mix-v1')\nclass Config:\n    workflows = {'mix': create_actions()}\n",
        ACTION: "class Pour:\n    volume = 10\n__all__ = ['Pour']\n",
        SEMANTIC: "class MixingCfg:\n    type = 'FlexMixing'\n",
        DEVICE: "class RobotCfg:\n    pass\n",
    }
    engine = {
        "repository": profile["engine_repository"],
        "ref": "main",
        "base_commit": profile["engine_commit"],
        "commit": profile["engine_commit"],
        "base_tree": [entry(path, text) for path, text in sources.items()],
        "tree": [entry(path, text) for path, text in sources.items()],
        "base_sources": dict(sources),
        "sources": dict(sources),
    }
    assets = {
        "repository": profile["asset_repository"],
        "ref": "main",
        "base_commit": profile["asset_commit"],
        "commit": profile["asset_commit"],
        "base_tree": [entry("robots/flex.usda", "old payload")],
        "tree": [entry("robots/flex.usda", "old payload")],
        "base_sources": {},
        "sources": {},
    }
    return policy, profile, engine, assets


def update(engine, path, text):
    engine["commit"] = "c" * 40
    engine["tree"] = [item for item in engine["tree"] if item["path"] != path]
    if text is None:
        engine["sources"].pop(path, None)
    else:
        engine["tree"].append(entry(path, text))
        if path.startswith("source/") and path.endswith(".py"):
            engine["sources"][path] = text


def resign(candidate):
    body = {key: value for key, value in candidate.items() if key != "candidate_id"}
    candidate["candidate_id"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def test_unchanged_intake_is_deterministic_read_only_and_never_qualified(inputs):
    before = copy.deepcopy(inputs)
    candidate = build_candidate(*inputs)
    assert inputs == before
    assert candidate == build_candidate(*inputs)
    assert candidate["has_changes"] is False
    assert candidate["changes"] == {"engine": [], "assets": []}
    assert candidate["activation_allowed"] is False
    assert candidate["worker_qualified"] is False
    validate_candidate(candidate, *inputs[:2])
    assert {item["kind"] for item in candidate["discoveries"]["engine"]["candidate"]} == {
        "task",
        "workflow",
        "action",
        "action-export",
        "semantic-type",
        "asset-config",
    }
    assert all(
        item["support_status"] == "detected-unreviewed"
        for item in candidate["discoveries"]["engine"]["candidate"]
    )
    inputs[2]["tree"].reverse()
    inputs[2]["base_tree"].reverse()
    assert build_candidate(*inputs) == candidate


def test_same_name_changed_blob_requires_adaptation_and_fresh_qualification(inputs):
    original = build_candidate(*inputs)
    update(inputs[2], ACTION, "class Pour:\n    volume = 100\n__all__ = ['Pour']\n")
    candidate = build_candidate(*inputs)
    assert candidate["candidate_id"] != original["candidate_id"]
    assert candidate["has_changes"] is True
    assert candidate["feature_changes"]["engine"] == {"added": [], "removed": []}
    (change,) = candidate["changes"]["engine"]
    assert change["path"] == ACTION and change["change"] == "changed"
    assert change["before"]["sha"] != change["after"]["sha"]
    assert {"candidate-review", "fresh-gpu-qualification", "fresh-browser-qualification"} <= set(
        candidate["required_gates"]
    )
    assert candidate["surface_reviews"][0]["status"] == "review-required"
    assert "unchanged task or class names" in render_report(candidate)
    validate_candidate(candidate, *inputs[:2])


def test_removed_files_and_removed_workflow_keys_are_reported(inputs):
    update(inputs[2], ACTION, None)
    update(
        inputs[2],
        TASK,
        "import gymnasium as gym\ngym.register(id='Mix-v2')\nclass Config:\n    def configure(self):\n        self.workflows = {'new-mix': make_actions()}\n",
    )
    candidate = build_candidate(*inputs)
    removed = {
        (item["kind"], item["name"]) for item in candidate["feature_changes"]["engine"]["removed"]
    }
    added = {
        (item["kind"], item["name"]) for item in candidate["feature_changes"]["engine"]["added"]
    }
    assert {
        ("action", "Pour"),
        ("action-export", "Pour"),
        ("task", "Mix-v1"),
        ("workflow", "mix"),
    } <= removed
    assert {("task", "Mix-v2"), ("workflow", "new-mix")} <= added
    assert any(
        item["path"] == ACTION and item["change"] == "removed"
        for item in candidate["changes"]["engine"]
    )
    validate_candidate(candidate, *inputs[:2])


def test_assets_advance_independently_and_even_same_tree_commit_requires_review(inputs):
    original = build_candidate(*inputs)
    inputs[3]["commit"] = "d" * 40
    candidate = build_candidate(*inputs)
    assert (
        candidate["has_changes"] is True and candidate["candidate_id"] != original["candidate_id"]
    )
    assert candidate["changes"]["engine"] == candidate["changes"]["assets"] == []
    inputs[3]["tree"][0]["sha"] = blob("updated independent asset")
    changed = build_candidate(*inputs)
    assert changed["candidate_id"] != candidate["candidate_id"]
    assert changed["surface_reviews"][1]["status"] == "review-required"
    assert changed["feature_changes"]["assets"] == {"added": [], "removed": []}
    validate_candidate(changed, *inputs[:2])


def test_gitlinks_and_unknown_paths_cannot_silently_disappear(inputs):
    engine = inputs[2]
    engine["base_tree"].append(
        entry("source/matterix_assets/data", "old gitlink", "160000", "commit")
    )
    engine["tree"].append(entry("source/matterix_assets/data", "new gitlink", "160000", "commit"))
    update(engine, "unexpected/installer.sh", "do_something\n")
    candidate = build_candidate(*inputs)
    assert any(
        item["gitlink"] and item["change"] == "changed" for item in candidate["changes"]["engine"]
    )
    assert [item["path"] for item in candidate["unmapped_changes"]] == ["unexpected/installer.sh"]
    assert "Unmapped changes require explicit review" in render_report(candidate)
    validate_candidate(candidate, *inputs[:2])


def test_dynamic_registry_and_parse_failures_remain_explicit_and_never_execute(inputs):
    update(
        inputs[2],
        TASK,
        "from gymnasium.envs.registration import register as add_task\nadd_task(id=build_id())\nclass Config:\n    workflows = {dynamic_key(): action()}\n    def configure(self):\n        self.workflows.update(build_workflows())\nexec('raise RuntimeError(\"must not execute\")')\n",
    )
    update(inputs[2], SEMANTIC, "class Broken(:\n")
    candidate = build_candidate(*inputs)
    codes = {item["code"] for item in candidate["diagnostics"] if item["revision"] == "candidate"}
    assert {
        "dynamic-task-id",
        "dynamic-workflow-key",
        "dynamic-workflow-registry",
        "syntax-error",
        "dynamic-code",
    } <= codes
    assert not any(
        item["kind"] == "task" for item in candidate["discoveries"]["engine"]["candidate"]
    )
    assert "incomplete" in render_report(candidate)
    validate_candidate(candidate, *inputs[:2])


def test_literal_aliases_annotated_semantics_and_workflow_keys(inputs):
    update(
        inputs[2],
        TASK,
        "from gymnasium.envs.registration import register as add_task\nadd_task('New-v1')\nclass Config:\n    workflows: dict = {1: factory(), '1': factory()}\n    def configure(self):\n        self.workflows['next'] = factory()\n        self.workflows.update({'last': factory()})\n",
    )
    update(
        inputs[2],
        SEMANTIC,
        "class Cfg:\n    type: str = 'LiteralSemantic'\n    dynamic: str = unknown\nvalue = {'type': 'DictSemantic'}\n",
    )
    catalog = build_candidate(*inputs)["discoveries"]["engine"]["candidate"]
    assert any(item["kind"] == "task" and item["name"] == "New-v1" for item in catalog)
    assert {(item["name"], item["key_type"]) for item in catalog if item["kind"] == "workflow"} == {
        ("1", "str"),
        ("1", "int"),
        ("next", "str"),
        ("last", "str"),
    }
    assert {item["name"] for item in catalog if item["kind"] == "semantic-type"} == {
        "LiteralSemantic",
        "DictSemantic",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", "someone/other"),
        ("ref", "feature"),
        ("commit", "main"),
        ("commit", "ABC" * 13 + "A"),
        ("base_commit", "f" * 40),
    ],
)
def test_invalid_repository_ref_or_pins_fail_closed(inputs, field, value):
    inputs[2][field] = value
    with pytest.raises(ValueError):
        build_candidate(*inputs)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong-hash", "bytes", "assets-source"])
def test_source_evidence_is_complete_and_matches_exact_git_blob(inputs, mutation):
    engine, assets = inputs[2:]
    if mutation == "missing":
        engine["sources"].pop(TASK)
    elif mutation == "extra":
        engine["sources"]["outside.py"] = "pass\n"
    elif mutation == "wrong-hash":
        engine["sources"][TASK] += "# not the blob\n"
    elif mutation == "bytes":
        engine["sources"][TASK] = b"pass"
    else:
        assets["sources"]["payload.py"] = "pass\n"
    with pytest.raises(ValueError):
        build_candidate(*inputs)


@pytest.mark.parametrize(
    "path",
    [
        "../escape.py",
        "/absolute.py",
        "source//double.py",
        "source/./dot.py",
        "source/a\\b.py",
        "source/line\nbreak.py",
        ".git/config",
    ],
)
def test_invalid_tree_paths_are_rejected(inputs, path):
    inputs[2]["tree"].append(entry(path, "not relevant"))
    with pytest.raises(ValueError, match="path"):
        build_candidate(*inputs)


@pytest.mark.parametrize(
    "mutation", ["duplicate", "bad-mode", "bad-object", "ancestor", "same-commit"]
)
def test_invalid_or_conflicting_tree_evidence_is_rejected(inputs, mutation):
    engine = inputs[2]
    if mutation == "duplicate":
        engine["tree"].append(dict(engine["tree"][0]))
    elif mutation == "bad-mode":
        engine["tree"][0]["mode"] = "040000"
        engine["tree"][0]["type"] = "tree"
    elif mutation == "bad-object":
        engine["tree"][0]["sha"] = "z" * 40
    elif mutation == "ancestor":
        engine["tree"].append(entry("source", "ancestor", "160000", "commit"))
    else:
        engine["tree"].append(entry("README", "different tree same commit"))
    with pytest.raises(ValueError):
        build_candidate(*inputs)


@pytest.mark.parametrize(
    "limit", ["max_tree_entries", "max_source_files", "max_source_bytes", "max_changed_files"]
)
def test_input_limits_fail_instead_of_truncating_evidence(inputs, limit):
    inputs[0]["limits"][limit] = 1
    update(inputs[2], "README", "new")
    update(inputs[2], "other", "new")
    with pytest.raises(ValueError, match="limit"):
        build_candidate(*inputs)


@pytest.mark.parametrize("field", ["policy", "profile", "adapter"])
def test_full_context_is_bound_to_candidate_identity(inputs, field):
    candidate = build_candidate(*inputs)
    if field == "policy":
        inputs[0]["surfaces"][0]["label"] = "Revised review context"
    elif field == "profile":
        inputs[1]["isaacsim_version"] = "a different runtime"
    else:
        inputs[1]["academy_adapter_sha256"] = "b" * 64
    assert build_candidate(*inputs)["candidate_id"] != candidate["candidate_id"]
    with pytest.raises(ValueError, match="binding"):
        validate_candidate(candidate, *inputs[:2])


@pytest.mark.parametrize(
    "mutation", ["flag", "hash", "tree", "gates", "diff", "source", "qualification", "source-text"]
)
def test_candidate_tampering_fails_even_when_self_hash_is_recomputed(inputs, mutation):
    candidate = build_candidate(*inputs)
    if mutation == "flag":
        candidate["activation_allowed"] = True
    elif mutation == "qualification":
        candidate["worker_qualified"] = True
    elif mutation == "hash":
        candidate["candidate_id"] = "f" * 64
    elif mutation == "tree":
        candidate["repositories"]["engine"]["tree"][0]["sha"] = "f" * 40
    elif mutation == "gates":
        candidate["required_gates"] = []
    elif mutation == "diff":
        candidate["changes"]["engine"] = [{"path": "invented"}]
    elif mutation == "source-text":
        candidate["repositories"]["engine"]["sources"][TASK]["text"] = "secret source"
    else:
        candidate["discoveries"]["engine"]["candidate"][0]["source_blob_sha"] = "f" * 40
    if mutation != "hash":
        resign(candidate)
    with pytest.raises(ValueError):
        validate_candidate(candidate, *inputs[:2])


def test_candidate_contains_fingerprints_but_not_upstream_source_or_runtime(inputs):
    candidate = build_candidate(*inputs)
    serialized = json.dumps(candidate)
    assert all(text not in serialized for text in inputs[2]["sources"].values())
    record = candidate["repositories"]["engine"]["sources"][TASK]
    assert record == {
        "git_blob_sha": blob(inputs[2]["sources"][TASK]),
        "sha256": hashlib.sha256(inputs[2]["sources"][TASK].encode()).hexdigest(),
        "bytes": len(inputs[2]["sources"][TASK].encode()),
    }
    assert "not authenticity" in render_report(candidate)


def test_candidate_does_not_retain_mutable_policy_references(inputs):
    candidate = build_candidate(*inputs)
    candidate["surface_reviews"][0]["academy_paths"].append("unexpected")
    assert inputs[0]["surfaces"][0]["academy_paths"] == ["app/backend/academy/native_isaac.py"]


def test_main_can_diverge_and_assets_can_regress_removing_required_workflow_files(inputs):
    update(inputs[2], ACTION, None)
    inputs[2]["ancestry"] = "diverged"
    inputs[3]["commit"] = "d" * 40
    inputs[3]["ancestry"] = "behind"
    inputs[3]["tree"] = []
    candidate = build_candidate(*inputs)
    assert candidate["compatibility_status"] == "blocked"
    assert {
        (item["repository"], item["code"], item.get("path")) for item in candidate["blockers"]
    } == {
        ("engine", "upstream-diverged", None),
        ("engine", "missing-required-path", ACTION),
        ("assets", "upstream-behind", None),
        ("assets", "missing-required-path", "robots/flex.usda"),
    }
    assert "Compatibility: **blocked**" in render_report(candidate)
    assert candidate["activation_allowed"] is False
    validate_candidate(candidate, *inputs[:2])


def test_unknown_history_is_not_reported_as_newer_and_ahead_still_requires_review(inputs):
    inputs[3]["commit"] = "d" * 40
    candidate = build_candidate(*inputs)
    assert candidate["compatibility_status"] == "review-required"
    assert candidate["review_risks"][0]["code"] == "unknown-ancestry"
    inputs[3]["ancestry"] = "ahead"
    ahead = build_candidate(*inputs)
    assert ahead["compatibility_status"] == "review-required" and ahead["review_risks"] == []
    assert ahead["candidate_id"] != candidate["candidate_id"]
    validate_candidate(ahead, *inputs[:2])


@pytest.mark.parametrize("ancestry", ["newer", "ahead", "behind", "diverged", "unknown"])
def test_ancestry_evidence_cannot_conflict_with_identical_commit_ids(inputs, ancestry):
    inputs[2]["ancestry"] = ancestry
    with pytest.raises(ValueError, match="ancestry|Ancestry"):
        build_candidate(*inputs)


def test_resigned_blocker_removal_is_rejected(inputs):
    update(inputs[2], ACTION, None)
    candidate = build_candidate(*inputs)
    candidate["blockers"] = []
    candidate["compatibility_status"] = "review-required"
    resign(candidate)
    with pytest.raises(ValueError, match="derived evidence"):
        validate_candidate(candidate, *inputs[:2])


@pytest.mark.parametrize("field", ["kind", "source_path"])
def test_malformed_discovery_types_are_validation_errors(inputs, field):
    candidate = build_candidate(*inputs)
    candidate["discoveries"]["engine"]["candidate"][0][field] = []
    candidate["discoveries"]["engine"]["candidate"].sort(
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
    )
    resign(candidate)
    with pytest.raises(ValueError):
        validate_candidate(candidate, *inputs[:2])


def test_report_never_hides_an_activation_flag(inputs):
    candidate = build_candidate(*inputs)
    candidate["activation_allowed"] = True
    resign(candidate)
    with pytest.raises(ValueError, match="cannot activate"):
        render_report(candidate)


@pytest.mark.parametrize("character", ["x", "π"])
def test_oversized_source_is_rejected_before_ast_parse(inputs, monkeypatch, character):
    text = "#" + character * (matterix_sync.MAX_SOURCE_FILE_BYTES // len(character.encode()) + 1)
    inputs[2]["base_sources"][ACTION] = text
    inputs[2]["base_tree"] = [item for item in inputs[2]["base_tree"] if item["path"] != ACTION]
    inputs[2]["base_tree"].append(entry(ACTION, text))

    def forbidden_parse(*args, **kwargs):
        pytest.fail("Source size must be checked before parsing any oversized snapshot")

    monkeypatch.setattr(matterix_sync.ast, "parse", forbidden_parse)
    with pytest.raises(ValueError, match="Source file byte limit exceeded"):
        build_candidate(*inputs)


def test_ast_walk_stops_at_the_node_limit_instead_of_collecting_every_node(inputs, monkeypatch):
    consumed = 0

    def excessive_walk(module):
        nonlocal consumed
        while True:
            consumed += 1
            if consumed > 100_001:
                pytest.fail("AST walk consumed beyond its bounded sentinel")
            yield matterix_sync.ast.Pass()

    monkeypatch.setattr(matterix_sync.ast, "walk", excessive_walk)
    with pytest.raises(ValueError, match="AST node limit exceeded"):
        build_candidate(*inputs)
    assert consumed == 100_001


@pytest.mark.parametrize("operation", ["build", "serialize", "validate"])
def test_candidate_size_limit_matches_the_exact_pretty_utf8_artifact(
    inputs, monkeypatch, operation
):
    candidate = build_candidate(*inputs)
    serialized = serialized_candidate(candidate)
    assert json.loads(serialized) == candidate
    assert serialized.endswith("\n")
    monkeypatch.setattr(matterix_sync, "MAX_METADATA_BYTES", len(serialized.encode("utf-8")) - 1)
    with pytest.raises(ValueError, match="Candidate metadata byte limit exceeded"):
        if operation == "build":
            build_candidate(*inputs)
        elif operation == "serialize":
            serialized_candidate(candidate)
        else:
            validate_candidate(candidate, *inputs[:2])


def test_report_enforces_utf8_byte_limit_and_accepts_exact_boundary(inputs, monkeypatch):
    inputs[0]["surfaces"][0]["label"] = "Engine αβγ"
    update(inputs[2], ACTION, "class Pour:\n    volume = 100\n")
    candidate = build_candidate(*inputs)
    report = render_report(candidate)
    size = len(report.encode("utf-8"))
    monkeypatch.setattr(matterix_sync, "MAX_METADATA_BYTES", size)
    assert render_report(candidate) == report
    monkeypatch.setattr(matterix_sync, "MAX_METADATA_BYTES", size - 1)
    with pytest.raises(ValueError, match="Report metadata byte limit exceeded"):
        render_report(candidate)
