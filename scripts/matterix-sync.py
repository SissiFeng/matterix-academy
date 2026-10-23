#!/usr/bin/env python3
"""Inspect independent upstream Git objects; never import, install or execute them."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app/backend"))

from academy.matterix_sync import build_candidate, render_report, validate_candidate  # noqa: E402
from academy.runtime_inventory import PROFILE  # noqa: E402

POLICY_PATH = ROOT / "ops/matterix-sync/policy.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")
ADAPTER_PATHS = (
    "app/backend/academy/worker_admin.py",
    "app/backend/academy/runs.py",
    "app/backend/academy/commissioning_evidence.py",
    "app/backend/academy/models.py",
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def load_policy(root=ROOT):
    policy = json.loads((root / "ops/matterix-sync/policy.json").read_text())
    if policy.get("schema_version") != 1:
        raise ValueError("Unsupported synchronization policy")
    expected = {
        "engine": {"repository": PROFILE["engine_repository"], "ref": "main"},
        "assets": {"repository": PROFILE["asset_repository"], "ref": "main"},
    }
    if policy.get("repositories") != expected:
        raise ValueError(
            "Synchronization must track the approved independent internal repositories"
        )
    paths = set(ADAPTER_PATHS)
    for surface in policy["surfaces"]:
        paths.update(surface["academy_paths"])
    hashes = {}
    for name in sorted(paths):
        path = root / name
        if (
            not name
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            or path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())
        ):
            raise ValueError(f"Invalid or missing Academy integration path: {name!r}")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return policy, {
        **PROFILE,
        "academy_adapter_sha256": hashlib.sha256(canonical(hashes)).hexdigest(),
    }


def git(root, *args, limit=32_000_000):
    """Bound output and avoid hooks, filters, external diff tools or working-tree reads."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    command = [
        "git",
        "--no-pager",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.pager=cat",
        "-C",
        str(root),
        *args,
    ]
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, env=env, timeout=60)
        if result.returncode:
            # Git diagnostics can include authenticated remotes or credential helpers.
            raise ValueError(
                "Cannot read required upstream Git object; refresh the independent checkout"
            )
        if output.tell() > limit:
            raise ValueError("Upstream Git output exceeds the intake limit")
        output.seek(0)
        return output.read()


def origin_repository(value):
    """Allow GitHub SSH/HTTPS origins without embedding credentials or arbitrary hosts."""
    value = value.strip()
    if value.startswith("git@github.com:"):
        path = value.removeprefix("git@github.com:")
    else:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "ssh"} or parsed.hostname != "github.com":
            raise ValueError("Upstream origin must be GitHub")
        if parsed.password or parsed.port or parsed.query or parsed.fragment:
            raise ValueError("Upstream origin must not contain credentials, ports or query data")
        if parsed.username and not (parsed.scheme == "ssh" and parsed.username == "git"):
            raise ValueError("Upstream origin must not contain credentials")
        path = parsed.path.removeprefix("/")
    path = path.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        raise ValueError("Invalid upstream repository name")
    return path


def tree(root, commit, max_entries):
    entries = []
    raw = git(root, "ls-tree", "-r", "-z", "--full-tree", commit)
    for record in raw.split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        mode, kind, sha = header.decode("ascii").split(" ")
        entries.append({"path": path.decode("utf-8"), "mode": mode, "type": kind, "sha": sha})
        if len(entries) > max_entries:
            raise ValueError("Upstream tree exceeds the configured entry limit")
    return entries


def sources(root, entries, limits):
    selected = [
        item
        for item in entries
        if item["path"].startswith("source/")
        and item["path"].endswith(".py")
        and item["mode"] in {"100644", "100755"}
        and item["type"] == "blob"
    ]
    if len(selected) > limits["max_source_files"]:
        raise ValueError("Upstream source count exceeds the configured limit")
    result = {}
    remaining = limits["max_source_bytes"]
    for item in selected:
        data = git(root, "cat-file", "blob", item["sha"], limit=remaining)
        remaining -= len(data)
        result[item["path"]] = data.decode("utf-8")
    return result


def snapshot(root, kind, policy, profile, expected=None):
    repository = policy["repositories"][kind]["repository"]
    actual = origin_repository(git(root, "remote", "get-url", "origin", limit=4096).decode())
    if actual.lower() != repository.lower():
        raise ValueError(f"Wrong {kind} origin; expected {repository}")
    commit = (
        git(root, "rev-parse", "--verify", "refs/remotes/origin/main^{commit}", limit=128)
        .decode()
        .strip()
    )
    if not SHA.fullmatch(commit) or (expected is not None and commit != expected):
        raise ValueError(f"{kind} main differs from the expected observed revision")
    base = profile["engine_commit" if kind == "engine" else "asset_commit"]
    # Both commits must already exist. Discovery never resolves moving dependencies or submodules.
    if git(root, "rev-parse", "--verify", base + "^{commit}", limit=128).decode().strip() != base:
        raise ValueError(f"Missing approved {kind} revision")
    base_tree = tree(root, base, policy["limits"]["max_tree_entries"])
    target_tree = tree(root, commit, policy["limits"]["max_tree_entries"])
    ancestry = "same" if commit == base else "unknown"
    if (
        commit != base
        and git(root, "rev-parse", "--is-shallow-repository", limit=32).strip() == b"false"
    ):
        # rev-list on a complete local history gives a read-only ancestry observation.
        counts = (
            git(root, "rev-list", "--left-right", "--count", base + "..." + commit, limit=128)
            .decode()
            .split()
        )
        old_only, main_only = (int(value) for value in counts)
        ancestry = "ahead" if old_only == 0 else "behind" if main_only == 0 else "diverged"
    return {
        "repository": repository,
        "ref": "main",
        "commit": commit,
        "base_commit": base,
        "ancestry": ancestry,
        "base_tree": base_tree,
        "tree": target_tree,
        "base_sources": sources(root, base_tree, policy["limits"]) if kind == "engine" else {},
        "sources": sources(root, target_tree, policy["limits"]) if kind == "engine" else {},
    }


def write_output(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Refusing to replace a symlink output")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(content.encode("utf-8"))
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser(
        "scan", help="Inspect local origin/main Git objects without executing upstream code"
    )
    scan.add_argument("--engine-root", type=Path, required=True)
    scan.add_argument("--assets-root", type=Path, required=True)
    scan.add_argument("--expected-engine-commit")
    scan.add_argument("--expected-assets-commit")
    scan.add_argument("--output-dir", type=Path, default=ROOT / "build/matterix-sync")
    check = subparsers.add_parser(
        "check", help="Validate candidate integrity against the current reviewed Academy adapter"
    )
    check.add_argument("--candidate", type=Path, required=True)
    check.add_argument("--report", type=Path, help="Also require the exact deterministic report")
    subparsers.add_parser("check-policy", help="Verify repository and Academy integration mapping")
    args = parser.parse_args()
    policy, profile = load_policy()
    if args.command == "scan":
        engine = snapshot(args.engine_root, "engine", policy, profile, args.expected_engine_commit)
        assets = snapshot(args.assets_root, "assets", policy, profile, args.expected_assets_commit)
        candidate = build_candidate(policy, profile, engine, assets)
        validate_candidate(candidate, policy, profile)
        write_output(
            args.output_dir / "candidate.json",
            json.dumps(candidate, indent=2, sort_keys=True) + "\n",
        )
        write_output(args.output_dir / "report.md", render_report(candidate))
        print(
            json.dumps(
                {
                    "candidate_id": candidate["candidate_id"],
                    "has_changes": candidate["has_changes"],
                    "activation_allowed": False,
                    "output_dir": str(args.output_dir),
                }
            )
        )
    elif args.command == "check":
        if args.candidate.stat().st_size > 40_000_000:
            raise ValueError("Candidate exceeds the intake limit")
        candidate = json.loads(args.candidate.read_text())
        validate_candidate(candidate, policy, profile)
        if args.report is not None and args.report.read_text() != render_report(candidate):
            raise ValueError("Report does not match the validated candidate")
        print("Candidate integrity and policy binding passed; runtime remains unqualified.")
    else:
        print("Internal repository policy and Academy integration paths are valid.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"Matterix intake failed: {error}") from None
