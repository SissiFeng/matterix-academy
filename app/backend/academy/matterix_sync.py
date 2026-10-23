"""Deterministic, read-only upstream intake. Never imports or executes upstream code.

Candidates are review evidence, not runtime profiles. Their self-hash detects drift;
it is neither a signature nor proof of origin, completeness, or GPU qualification.
The Git collector is responsible for obtaining complete trees from trusted origins.
"""

import ast
import hashlib
import json
import re
from itertools import islice
from pathlib import PurePosixPath

MAX_METADATA_BYTES = 4_000_000
MAX_SOURCE_FILE_BYTES = 512_000
_MAX_AST_NODES = 100_000
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_LIMITS = {
    "max_tree_entries": 20000,
    "max_source_files": 1000,
    "max_source_bytes": 20000000,
    "max_changed_files": 10000,
}
_MODES = {"100644": "blob", "100755": "blob", "120000": "blob", "160000": "commit"}
_KINDS = {"task", "action", "action-export", "workflow", "semantic-type", "asset-config"}
_GATES = ["candidate-review", "fresh-gpu-qualification", "fresh-browser-qualification"]
_BOUNDARY = (
    "Static detections are unreviewed. No upstream code ran, no Academy support was added, "
    "and no profile or worker qualification changed. Self-hashes establish internal integrity, "
    "not authenticity. Runtime activation requires separately reviewed qualification."
)


def _json(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("Evidence must be bounded UTF-8 JSON") from error


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def serialized_candidate(candidate: dict) -> str:
    """Use the same bounded UTF-8 JSON representation for generation and publishing."""
    _require(isinstance(candidate, dict), "Candidate must be an object")
    try:
        text = (
            json.dumps(candidate, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n"
        )
        size = len(text.encode("utf-8"))
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("Candidate must be bounded UTF-8 JSON") from error
    _require(size <= MAX_METADATA_BYTES, "Candidate metadata byte limit exceeded")
    return text


def _path(value, *, prefix=False):
    _require(isinstance(value, str) and len(value.encode("utf-8")) <= 4096, "Invalid path")
    if prefix and value == "":
        return value
    path = value.removesuffix("/") if prefix else value
    _require(
        path
        and not path.startswith("/")
        and "\\" not in path
        and all(part not in {"", ".", "..", ".git"} for part in path.split("/"))
        and not any(ord(char) < 32 or ord(char) == 127 for char in path),
        f"Invalid path: {value!r}",
    )
    return value


def _context(policy, approved_profile):
    _require(
        isinstance(policy, dict) and isinstance(approved_profile, dict),
        "Policy and profile must be objects",
    )
    _require(
        len(_json(policy)) <= 1000000 and len(_json(approved_profile)) <= 1000000,
        "Policy/profile too large",
    )
    _require(
        policy.get("schema_version") == 1 and type(policy.get("schema_version")) is int,
        "Unsupported policy schema",
    )
    _require(
        isinstance(policy.get("repositories"), dict)
        and set(policy["repositories"]) == {"engine", "assets"},
        "Policy repositories must be engine and assets",
    )
    for key, profile_key in (("engine", "engine"), ("assets", "asset")):
        repo = policy["repositories"][key]
        _require(
            isinstance(repo, dict) and set(repo) == {"repository", "ref"},
            "Invalid policy repository",
        )
        _require(
            isinstance(repo["repository"], str) and _REPOSITORY.fullmatch(repo["repository"]),
            "Invalid repository",
        )
        _require(repo["ref"] == "main", "Only main intake is supported")
        _require(
            approved_profile.get(f"{profile_key}_repository") == repo["repository"],
            "Approved profile repository differs",
        )
        _require(
            isinstance(approved_profile.get(f"{profile_key}_commit"), str)
            and _SHA.fullmatch(approved_profile[f"{profile_key}_commit"]),
            "Approved profile commit must be a full SHA",
        )
    if "academy_adapter_sha256" in approved_profile:
        _require(
            isinstance(approved_profile["academy_adapter_sha256"], str)
            and _SHA256.fullmatch(approved_profile["academy_adapter_sha256"]),
            "Invalid Academy adapter hash",
        )
    limits = policy.get("limits")
    _require(isinstance(limits, dict) and set(limits) == set(_LIMITS), "Invalid limits")
    for key, maximum in _LIMITS.items():
        _require(
            type(limits[key]) is int and 0 < limits[key] <= maximum, f"Invalid bounded limit: {key}"
        )
    required = policy.get("required_paths")
    _require(
        isinstance(required, dict) and set(required) == {"engine", "assets"},
        "Invalid required paths",
    )
    for paths in required.values():
        _require(
            isinstance(paths, list)
            and len(paths) <= 1000
            and all(isinstance(path, str) for path in paths),
            "Invalid required paths",
        )
        _require(len(paths) == len(set(paths)), "Duplicate required path")
        for path in paths:
            _path(path)
    surfaces = policy.get("surfaces")
    _require(isinstance(surfaces, list) and 0 < len(surfaces) <= 100, "Invalid surfaces")
    ids = set()
    for surface in surfaces:
        _require(
            isinstance(surface, dict)
            and set(surface)
            == {"id", "label", "repository", "prefixes", "academy_paths", "required_gates"},
            "Invalid surface",
        )
        _require(
            isinstance(surface["id"], str)
            and re.fullmatch(r"[a-z0-9-]{1,100}", surface["id"])
            and surface["id"] not in ids,
            "Invalid or duplicate surface ID",
        )
        ids.add(surface["id"])
        _require(
            isinstance(surface["label"], str) and 0 < len(surface["label"]) <= 200,
            "Invalid surface label",
        )
        _require(
            isinstance(surface["repository"], str)
            and surface["repository"] in {"engine", "assets"},
            "Invalid surface repository",
        )
        for field in ("prefixes", "academy_paths", "required_gates"):
            values = surface[field]
            _require(
                isinstance(values, list)
                and 0 < len(values) <= 100
                and all(isinstance(value, str) for value in values),
                f"Invalid surface {field}",
            )
            _require(len(set(values)) == len(values), f"Duplicate surface {field}")
            for value in values:
                if field == "required_gates":
                    _require(re.fullmatch(r"[a-z0-9-]{1,100}", value), "Invalid gate")
                else:
                    _path(value, prefix=field == "prefixes")
    return limits


def _tree(entries, limit):
    _require(
        isinstance(entries, list) and len(entries) <= limit,
        "Tree entry limit exceeded or invalid tree",
    )
    paths = set()
    result = []
    for entry in entries:
        _require(
            isinstance(entry, dict) and set(entry) == {"path", "mode", "type", "sha"},
            "Invalid tree entry",
        )
        path = _path(entry["path"])
        _require(path not in paths, f"Duplicate tree path: {path}")
        paths.add(path)
        _require(
            isinstance(entry["mode"], str)
            and entry["mode"] in _MODES
            and _MODES[entry["mode"]] == entry["type"],
            "Expected recursive tree leaves, regular files, symlinks or gitlinks",
        )
        _require(
            isinstance(entry["sha"], str) and _SHA.fullmatch(entry["sha"]),
            "Invalid tree object SHA",
        )
        result.append(dict(entry))
    for path in paths:
        _require(
            not any(
                str(parent) in paths for parent in PurePosixPath(path).parents if str(parent) != "."
            ),
            "Tree contains a file/gitlink ancestor and its descendant",
        )
    return sorted(result, key=lambda entry: entry["path"])


def _source_paths(tree, repository):
    return {
        entry["path"]: entry
        for entry in tree
        if repository == "engine"
        and entry["mode"] in {"100644", "100755"}
        and entry["path"].startswith("source/")
        and entry["path"].endswith(".py")
    }


def _source_evidence(sources, tree, key, limits, *, metadata=False):
    expected = _source_paths(tree, key)
    _require(
        isinstance(sources, dict) and len(sources) <= limits["max_source_files"],
        "Source file limit exceeded or invalid sources",
    )
    _require(set(sources) == set(expected), "Missing relevant source or unexpected source path")
    result, total = {}, 0
    for path in sorted(sources):
        if metadata:
            record = sources[path]
            _require(
                isinstance(record, dict) and set(record) == {"git_blob_sha", "sha256", "bytes"},
                "Invalid source metadata; source text must not be retained",
            )
            _require(
                record["git_blob_sha"] == expected[path]["sha"],
                "Source blob evidence differs from tree",
            )
            _require(
                isinstance(record["sha256"], str) and _SHA256.fullmatch(record["sha256"]),
                "Invalid source SHA256",
            )
            _require(
                type(record["bytes"]) is int and record["bytes"] >= 0, "Invalid source byte count"
            )
            result[path] = dict(record)
        else:
            _require(isinstance(sources[path], str), "Sources must be UTF-8 text")
            try:
                raw = sources[path].encode("utf-8")
            except UnicodeError as error:
                raise ValueError("Sources must be UTF-8 text") from error
            blob = hashlib.sha1(
                f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False
            ).hexdigest()
            _require(blob == expected[path]["sha"], f"Source Git blob hash mismatch: {path}")
            result[path] = {
                "git_blob_sha": blob,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        total += result[path]["bytes"]
        _require(
            result[path]["bytes"] <= MAX_SOURCE_FILE_BYTES,
            f"Source file byte limit exceeded: {path}",
        )
        _require(total <= limits["max_source_bytes"], "Source byte limit exceeded")
    return result


def _qualified_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_qualified_name(node.value)}.{node.attr}"
    return ""


def _discover(sources, evidence, key, revision):
    features, diagnostics = [], []
    for path, text in sorted(sources.items()):

        def diagnostic(node, code, message, source_path=path):
            diagnostics.append(
                {
                    "repository": key,
                    "revision": revision,
                    "source_path": source_path,
                    "line": getattr(node, "lineno", 1) or 1,
                    "code": code,
                    "message": message,
                }
            )

        def feature(node, kind, value, source_path=path, **extra):
            features.append(
                {
                    "kind": kind,
                    "name": str(value),
                    "source_path": source_path,
                    "source_blob_sha": evidence[source_path]["git_blob_sha"],
                    "line": node.lineno,
                    "discovery": "static",
                    "support_status": "detected-unreviewed",
                    **extra,
                }
            )

        def workflow_keys(node):
            if not isinstance(node, ast.Dict):
                diagnostic(
                    node,
                    "dynamic-workflow-registry",
                    "Workflow keys cannot be resolved statically.",
                )
                return
            for item in node.keys:
                if isinstance(item, ast.Constant) and type(item.value) in {str, int}:
                    feature(item, "workflow", item.value, key_type=type(item.value).__name__)
                else:
                    diagnostic(
                        item or node,
                        "dynamic-workflow-key",
                        "Computed or unpacked workflow keys require review.",
                    )

        _require(
            evidence[path]["bytes"] <= MAX_SOURCE_FILE_BYTES,
            f"Source file byte limit exceeded before parsing: {path}",
        )
        try:
            module = ast.parse(text, filename=path)
        except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
            diagnostic(
                error,
                "syntax-error",
                "Python source could not be parsed; feature discovery is incomplete.",
            )
            continue
        nodes = list(islice(ast.walk(module), _MAX_AST_NODES + 1))
        _require(len(nodes) <= _MAX_AST_NODES, f"AST node limit exceeded: {path}")
        aliases = {"gym": "gym", "gymnasium": "gymnasium"}
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("gymnasium", "gym")):
                        aliases[alias.asname or alias.name.split(".")[0]] = (
                            alias.name if alias.asname else alias.name.split(".")[0]
                        )
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        diagnostic(
                            node,
                            "wildcard-import",
                            "Wildcard imports may expose declarations not resolved by this static catalog.",
                        )
                    elif node.module and node.module.split(".")[0] in {"gym", "gymnasium"}:
                        aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        action_path = any(
            part.endswith("_actions") for part in PurePosixPath(path).parts
        ) or PurePosixPath(path).stem.endswith("_actions")
        asset_path = "matterix_assets" in PurePosixPath(path).parts or any(
            part in {"assets", "devices", "robots", "labware", "equipment"}
            for part in PurePosixPath(path).parts
        )
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                if action_path:
                    feature(node, "action", node.name)
                if asset_path and (
                    node.name.endswith(("Cfg", "Config"))
                    or any(
                        _qualified_name(item).endswith("configclass")
                        for item in node.decorator_list
                    )
                ):
                    feature(node, "asset-config", node.name)
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    name = _qualified_name(target)
                    if name in {"workflows", "self.workflows"}:
                        workflow_keys(node.value)
                    elif isinstance(target, ast.Subscript) and _qualified_name(target.value) in {
                        "workflows",
                        "self.workflows",
                    }:
                        if isinstance(target.slice, ast.Constant) and type(target.slice.value) in {
                            str,
                            int,
                        }:
                            feature(
                                target,
                                "workflow",
                                target.slice.value,
                                key_type=type(target.slice.value).__name__,
                            )
                        else:
                            diagnostic(
                                target,
                                "dynamic-workflow-key",
                                "Computed workflow key requires review.",
                            )
                    if name in {"type", "self.type"} and node.value is not None:
                        if isinstance(node.value, ast.Constant) and isinstance(
                            node.value.value, str
                        ):
                            feature(node, "semantic-type", node.value.value)
                        else:
                            diagnostic(
                                node,
                                "dynamic-semantic-type",
                                "Nonliteral type declaration requires semantic review.",
                            )
                    if name == "__all__" and action_path:
                        if isinstance(node.value, (ast.List, ast.Tuple)) and all(
                            isinstance(item, ast.Constant) and isinstance(item.value, str)
                            for item in node.value.elts
                        ):
                            for item in node.value.elts:
                                feature(item, "action-export", item.value)
                        else:
                            diagnostic(
                                node, "dynamic-exports", "Computed action exports require review."
                            )
            if isinstance(node, ast.Dict):
                for field, value in zip(node.keys, node.values, strict=True):
                    if isinstance(field, ast.Constant) and field.value == "type":
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            feature(field, "semantic-type", value.value)
                        else:
                            diagnostic(
                                field,
                                "dynamic-semantic-type",
                                "Nonliteral dictionary type requires review.",
                            )
            if not isinstance(node, ast.Call):
                continue
            called = _qualified_name(node.func)
            head, *tail = called.split(".")
            resolved = ".".join([aliases.get(head, head), *tail])
            if resolved in {
                "gym.register",
                "gymnasium.register",
                "gym.envs.registration.register",
                "gymnasium.envs.registration.register",
            }:
                value = next(
                    (item.value for item in node.keywords if item.arg == "id"),
                    node.args[0] if node.args else None,
                )
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    feature(node, "task", value.value)
                else:
                    diagnostic(
                        node, "dynamic-task-id", "Computed or unpacked Gym task IDs require review."
                    )
            elif called.endswith(".register") and "matterix_tasks" in PurePosixPath(path).parts:
                diagnostic(
                    node, "dynamic-task-registry", "Unresolved registry call may add task IDs."
                )
            if called in {"self.workflows.update", "workflows.update"}:
                if len(node.args) == 1 and not node.keywords:
                    workflow_keys(node.args[0])
                else:
                    diagnostic(
                        node, "dynamic-workflow-registry", "Workflow update requires review."
                    )
            if called in {"eval", "exec", "globals", "locals", "setattr"}:
                diagnostic(
                    node, "dynamic-code", "Dynamic declarations are not executed or resolved."
                )
            if called.endswith(".update") and "semantics" in path:
                diagnostic(
                    node,
                    "dynamic-semantic-registry",
                    "Composed semantic registries require review of their literal definitions and imports.",
                )
    return sorted(features, key=_json), sorted(diagnostics, key=_json)


def _snapshot(snapshot, key, policy, profile, *, metadata=False):
    limits = policy["limits"]
    fields = {
        "repository",
        "ref",
        "commit",
        "base_commit",
        "base_tree",
        "tree",
        "base_sources",
        "sources",
    }
    if metadata:
        fields |= {"base_tree_sha256", "tree_sha256", "ancestry"}
    _require(
        isinstance(snapshot, dict)
        and (set(snapshot) == fields or (not metadata and set(snapshot) == fields | {"ancestry"})),
        "Invalid snapshot fields",
    )
    _require(
        snapshot["repository"] == policy["repositories"][key]["repository"],
        "Unexpected upstream repository",
    )
    _require(
        snapshot["ref"] == policy["repositories"][key]["ref"] == "main", "Unexpected upstream ref"
    )
    for field in ("commit", "base_commit"):
        _require(
            isinstance(snapshot[field], str) and _SHA.fullmatch(snapshot[field]),
            "Upstream commit must be a full SHA",
        )
    _require(
        snapshot["base_commit"] == profile[f"{'engine' if key == 'engine' else 'asset'}_commit"],
        "Base commit differs from approved profile",
    )
    result = {field: snapshot[field] for field in ("repository", "ref", "commit", "base_commit")}
    ancestry = snapshot.get(
        "ancestry", "same" if result["commit"] == result["base_commit"] else "unknown"
    )
    _require(
        isinstance(ancestry, str)
        and ancestry in {"same", "ahead", "behind", "diverged", "unknown"},
        "Invalid ancestry",
    )
    _require(
        (ancestry == "same") == (result["commit"] == result["base_commit"]),
        "Ancestry conflicts with commit identity",
    )
    result["ancestry"] = ancestry
    catalogs, diagnostics = {}, []
    for tree_field, sources_field, revision in (
        ("base_tree", "base_sources", "base"),
        ("tree", "sources", "candidate"),
    ):
        tree = _tree(snapshot[tree_field], limits["max_tree_entries"])
        source_evidence = _source_evidence(
            snapshot[sources_field], tree, key, limits, metadata=metadata
        )
        result[tree_field], result[f"{tree_field}_sha256"] = tree, _hash(tree)
        result[sources_field] = source_evidence
        if metadata:
            _require(snapshot[f"{tree_field}_sha256"] == _hash(tree), "Full tree hash differs")
        else:
            catalogs[revision], found = _discover(
                snapshot[sources_field], source_evidence, key, revision
            )
            diagnostics.extend(found)
    if result["commit"] == result["base_commit"]:
        _require(
            result["tree"] == result["base_tree"] and result["sources"] == result["base_sources"],
            "Same commit has inconsistent tree/source evidence",
        )
    return result, catalogs, diagnostics


def _changes(repository):
    base, current = (
        {entry["path"]: entry for entry in repository[field]} for field in ("base_tree", "tree")
    )
    return [
        {
            "path": path,
            "change": "added"
            if path not in base
            else "removed"
            if path not in current
            else "changed",
            "before": base.get(path),
            "after": current.get(path),
            "gitlink": any(
                entry and entry["mode"] == "160000" for entry in (base.get(path), current.get(path))
            ),
        }
        for path in sorted(base.keys() | current.keys())
        if base.get(path) != current.get(path)
    ]


def _feature_key(item):
    return item["kind"], item["source_path"], item["name"], item.get("key_type", "")


def _compose(policy, profile, repositories, discoveries, diagnostics):
    changes = {key: _changes(repositories[key]) for key in ("engine", "assets")}
    _require(
        sum(map(len, changes.values())) <= policy["limits"]["max_changed_files"],
        "Changed file limit exceeded",
    )
    _require(
        all(
            len(items) <= 100000 for catalogs in discoveries.values() for items in catalogs.values()
        )
        and len(diagnostics) <= 100000,
        "Discovery/diagnostic limit exceeded",
    )
    surface_reviews, covered = [], set()
    for surface in policy["surfaces"]:
        paths = [
            item["path"]
            for item in changes[surface["repository"]]
            if any(item["path"].startswith(prefix) for prefix in surface["prefixes"])
        ]
        covered.update((surface["repository"], path) for path in paths)
        surface_reviews.append(
            {
                **surface,
                "changed_paths": paths,
                "status": "review-required" if paths else "no-path-changes",
                "adaptation_checklist": [
                    "Review changed implementations and removals, even when feature names are unchanged.",
                    "Review the listed Academy adapters, versioned recipes, English lessons and UI coverage.",
                    "Keep teaching results synthetic; add no runnable controls from static discovery.",
                    "Run the listed gates against these exact engine/assets revisions before qualification.",
                ],
            }
        )
    feature_changes = {}
    for key, catalogs in discoveries.items():
        base = {_feature_key(item): item for item in catalogs["base"]}
        current = {_feature_key(item): item for item in catalogs["candidate"]}
        feature_changes[key] = {
            "added": [current[item] for item in sorted(current.keys() - base.keys())],
            "removed": [base[item] for item in sorted(base.keys() - current.keys())],
        }
    blockers, review_risks = [], []
    for key in ("engine", "assets"):
        repository = repositories[key]
        regular_paths = {
            item["path"] for item in repository["tree"] if item["mode"] in {"100644", "100755"}
        }
        for path in policy["required_paths"][key]:
            if path not in regular_paths:
                blockers.append(
                    {
                        "repository": key,
                        "code": "missing-required-path",
                        "path": path,
                        "message": "A required approved-workflow file is absent or is not a regular file.",
                    }
                )
        if repository["ancestry"] in {"behind", "diverged"}:
            blockers.append(
                {
                    "repository": key,
                    "code": f"upstream-{repository['ancestry']}",
                    "message": "Main is not an advance of the approved revision; reconcile the history and missing behavior before adaptation.",
                }
            )
        elif repository["ancestry"] == "unknown":
            review_risks.append(
                {
                    "repository": key,
                    "code": "unknown-ancestry",
                    "message": "History coverage is insufficient to classify main relative to the approved revision; main is not assumed newer.",
                }
            )
    result = {
        "schema_version": 1,
        "status": "candidate-unqualified",
        "activation_allowed": False,
        "worker_qualified": False,
        "has_changes": any(repo["commit"] != repo["base_commit"] for repo in repositories.values()),
        "policy_sha256": _hash(policy),
        "approved_profile_sha256": _hash(profile),
        "repositories": repositories,
        "changes": changes,
        "discoveries": discoveries,
        "feature_changes": feature_changes,
        "diagnostics": sorted(diagnostics, key=_json),
        "compatibility_status": "blocked" if blockers else "review-required",
        "blockers": blockers,
        "review_risks": review_risks,
        "surface_reviews": surface_reviews,
        "unmapped_changes": [
            {"repository": key, **item}
            for key, items in changes.items()
            for item in items
            if (key, item["path"]) not in covered
        ],
        "required_gates": sorted(
            set(_GATES)
            | {
                gate
                for surface in surface_reviews
                if surface["changed_paths"]
                for gate in surface["required_gates"]
            }
        ),
        "evidence_boundary": _BOUNDARY,
    }
    result["candidate_id"] = _hash(result)
    return result


def build_candidate(policy: dict, approved_profile: dict, engine: dict, assets: dict) -> dict:
    """Analyze bounded Git evidence without executing code or mutating any input."""
    _context(policy, approved_profile)
    repositories, discoveries, diagnostics = {}, {}, []
    for key, snapshot in (("engine", engine), ("assets", assets)):
        repositories[key], discoveries[key], found = _snapshot(
            snapshot, key, policy, approved_profile
        )
        diagnostics.extend(found)
    # A JSON round trip owns all nested values instead of leaking mutable policy aliases.
    return json.loads(
        serialized_candidate(
            _compose(policy, approved_profile, repositories, discoveries, diagnostics)
        )
    )


def validate_candidate(candidate: dict, policy: dict, approved_profile: dict) -> None:
    """Check schema, identity and internal evidence consistency, not authenticity."""
    _context(policy, approved_profile)
    _require(isinstance(candidate, dict), "Candidate must be an object")
    serialized_candidate(candidate)
    _require(
        candidate.get("status") == "candidate-unqualified"
        and candidate.get("activation_allowed") is False
        and candidate.get("worker_qualified") is False,
        "Candidate cannot activate or qualify a worker",
    )
    _require(
        candidate.get("policy_sha256") == _hash(policy)
        and candidate.get("approved_profile_sha256") == _hash(approved_profile),
        "Candidate policy/profile binding differs",
    )
    _require(
        candidate.get("candidate_id")
        == _hash({key: value for key, value in candidate.items() if key != "candidate_id"}),
        "Candidate identity hash differs",
    )
    _require(
        isinstance(candidate.get("repositories"), dict)
        and set(candidate["repositories"]) == {"engine", "assets"},
        "Invalid candidate repositories",
    )
    repositories = {
        key: _snapshot(value, key, policy, approved_profile, metadata=True)[0]
        for key, value in candidate["repositories"].items()
    }
    discoveries = candidate.get("discoveries")
    _require(
        isinstance(discoveries, dict) and set(discoveries) == {"engine", "assets"},
        "Invalid discoveries",
    )
    for key, catalogs in discoveries.items():
        _require(
            isinstance(catalogs, dict) and set(catalogs) == {"base", "candidate"},
            "Invalid discovery revisions",
        )
        for revision, items in catalogs.items():
            sources = repositories[key]["base_sources" if revision == "base" else "sources"]
            _require(
                isinstance(items, list) and len(items) <= 100000, "Invalid or excessive discoveries"
            )
            _require(items == sorted(items, key=_json), "Discoveries are not canonical")
            for item in items:
                _require(
                    isinstance(item, dict)
                    and set(item)
                    in (
                        {
                            "kind",
                            "name",
                            "source_path",
                            "source_blob_sha",
                            "line",
                            "discovery",
                            "support_status",
                        },
                        {
                            "kind",
                            "name",
                            "source_path",
                            "source_blob_sha",
                            "line",
                            "discovery",
                            "support_status",
                            "key_type",
                        },
                    ),
                    "Invalid discovery record",
                )
                _require(
                    isinstance(item["kind"], str)
                    and item["kind"] in _KINDS
                    and isinstance(item["name"], str),
                    "Invalid discovery kind/name",
                )
                _require(
                    isinstance(item["source_path"], str)
                    and item["source_path"] in sources
                    and item["source_blob_sha"] == sources[item["source_path"]]["git_blob_sha"],
                    "Discovery source differs",
                )
                _require(
                    type(item["line"]) is int
                    and item["line"] > 0
                    and item["discovery"] == "static"
                    and item["support_status"] == "detected-unreviewed",
                    "Invalid discovery status/line",
                )
                _require(
                    (isinstance(item.get("key_type"), str) and item["key_type"] in {"str", "int"})
                    if item["kind"] == "workflow"
                    else "key_type" not in item,
                    "Invalid workflow key type",
                )
    diagnostics = candidate.get("diagnostics")
    _require(isinstance(diagnostics, list) and len(diagnostics) <= 100000, "Invalid diagnostics")
    for item in diagnostics:
        _require(
            isinstance(item, dict)
            and set(item) == {"repository", "revision", "source_path", "line", "code", "message"},
            "Invalid diagnostic",
        )
        _require(
            isinstance(item["repository"], str)
            and item["repository"] in repositories
            and isinstance(item["revision"], str)
            and item["revision"] in {"base", "candidate"},
            "Invalid diagnostic origin",
        )
        sources = repositories[item["repository"]][
            "base_sources" if item["revision"] == "base" else "sources"
        ]
        _require(
            isinstance(item["source_path"], str)
            and item["source_path"] in sources
            and type(item["line"]) is int
            and item["line"] > 0
            and all(isinstance(item[field], str) for field in ("code", "message")),
            "Invalid diagnostic evidence",
        )
    _require(
        candidate == _compose(policy, approved_profile, repositories, discoveries, diagnostics),
        "Candidate derived evidence differs",
    )


def _markdown(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("|", "\\|")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def render_report(candidate: dict) -> str:
    """Render English review guidance. Validate against trusted context before publishing."""
    _require(
        isinstance(candidate, dict)
        and candidate.get("status") == "candidate-unqualified"
        and candidate.get("activation_allowed") is False
        and candidate.get("worker_qualified") is False,
        "Report cannot activate or qualify a candidate",
    )
    _require(
        candidate.get("candidate_id")
        == _hash({key: value for key, value in candidate.items() if key != "candidate_id"}),
        "Candidate identity hash differs",
    )
    lines = [
        "# Internal Matterix candidate review",
        "",
        f"Candidate: `{candidate['candidate_id']}`",
        "",
        "Status: **candidate-unqualified**. Activation allowed: **false**. Worker qualified: **false**.",
        "",
        f"Compatibility: **{candidate['compatibility_status']}**.",
        "",
        candidate["evidence_boundary"],
        "",
        "## Compatibility blockers and history review",
        "",
    ]
    lines.extend(
        f"- **{_markdown(item['repository'])}: {_markdown(item['code'])}** {_markdown(item.get('path', ''))} — {_markdown(item['message'])}"
        for item in candidate["blockers"] + candidate["review_risks"]
    )
    if not candidate["blockers"] and not candidate["review_risks"]:
        lines.append(
            "No required-path/history blocker detected. Compatibility and new features still require review."
        )
    lines += ["", "## Pinned upstream evidence", ""]
    for key, repository in candidate["repositories"].items():
        lines.append(
            f"- {_markdown(key)}: `{_markdown(repository['repository'])}` main `{repository['base_commit']}` → `{repository['commit']}`; ancestry **{repository['ancestry']}**; {len(candidate['changes'][key])} changed paths."
        )
    lines += [
        "",
        "## Feature adaptation checklist",
        "",
        "Every changed blob needs review, including behavior changes under unchanged task or class names. Detected feature removals describe static declarations only; dynamic registries and imports can make the catalog incomplete.",
    ]
    for surface in candidate["surface_reviews"]:
        if not surface["changed_paths"]:
            continue
        lines += [
            "",
            f"### {_markdown(surface['label'])}",
            "",
            "Academy files: "
            + ", ".join(f"`{_markdown(path)}`" for path in surface["academy_paths"]),
            "",
        ]
        lines.extend(f"- [ ] {_markdown(item)}" for item in surface["adaptation_checklist"])
        lines.extend(
            f"- [ ] Required gate: `{_markdown(gate)}`" for gate in surface["required_gates"]
        )
        lines += ["", "Changed upstream paths:", ""]
        lines.extend(f"- `{_markdown(path)}`" for path in surface["changed_paths"])
    if candidate["unmapped_changes"]:
        lines += ["", "### Unmapped changes require explicit review", ""]
        lines.extend(
            f"- `{item['repository']}:{_markdown(item['path'])}` ({item['change']})"
            for item in candidate["unmapped_changes"]
        )
    lines += ["", "## Detected features — unreviewed", ""]
    for key, changes in candidate["feature_changes"].items():
        for change in ("added", "removed"):
            lines.append(f"{key}: {len(changes[change])} static declarations {change}.")
            lines.extend(
                f"- {change}: {_markdown(item['kind'])} `{_markdown(item['name'])}` at `{_markdown(item['source_path'])}:{item['line']}`"
                for item in changes[change]
            )
    lines += ["", "## Unresolved extraction diagnostics", ""]
    if not candidate["diagnostics"]:
        lines.append(
            "No recognized extraction diagnostics; this is not proof of complete feature discovery."
        )
    lines.extend(
        f"- {item['repository']}/{item['revision']} `{_markdown(item['source_path'])}:{item['line']}` — {_markdown(item['code'])}: {_markdown(item['message'])}"
        for item in candidate["diagnostics"]
    )
    lines += ["", "## Required before any runtime adoption", ""]
    lines.extend(f"- [ ] `{_markdown(gate)}`" for gate in candidate["required_gates"])
    lines += [
        "",
        "Fresh native evidence must cover the exact candidate engine/assets pair, real decoded browser video, refresh recovery of the same run, verified reset/release and a second complete run. Candidate generation provides none of that evidence.",
        "",
    ]
    report = "\n".join(lines)
    _require(
        len(report.encode("utf-8")) <= MAX_METADATA_BYTES, "Report metadata byte limit exceeded"
    )
    return report
