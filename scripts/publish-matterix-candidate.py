"""Publish metadata-only candidate PRs; never update approved pins or deployed workers."""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "SissiFeng/matterix-academy"
API = f"repos/{REPOSITORY}"
CANDIDATE_PATH = "ops/matterix-sync/candidate.json"
REPORT_PATH = "docs/evidence/matterix-sync/latest.md"
SHA = re.compile(r"[0-9a-f]{40}")
MAX_FILE_BYTES = 4_000_000


class PublishError(RuntimeError):
    pass


class APIError(PublishError):
    def __init__(self, status=None):
        self.status = status
        super().__init__(
            f"GitHub request failed (HTTP {status or 'unknown'}); reconcile before retry"
        )


class GitHub:
    def __init__(self):
        if not os.environ.get("GH_TOKEN"):
            raise PublishError("GH_TOKEN must contain a scoped GitHub App installation token")
        if os.environ.get("GH_HOST", "github.com") != "github.com":
            raise PublishError("Only github.com is permitted")
        self.env = {**os.environ, "GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1"}

    def run(self, args, *, payload=None):
        try:
            result = subprocess.run(
                ["gh", *args],
                input=json.dumps(payload) if payload is not None else None,
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
                env=self.env,
            )
        except subprocess.TimeoutExpired as exc:
            raise APIError() from exc
        if result.returncode:
            status = re.search(r"\bHTTP (\d{3})\b", result.stderr)
            raise APIError(int(status[1]) if status else None)
        if len(result.stdout.encode()) > 12_000_000:
            raise PublishError("GitHub response exceeded the metadata size limit")
        return result.stdout

    def api(self, endpoint, *, method="GET", payload=None, missing_ok=False):
        args = ["api", "--hostname", "github.com", "--method", method, endpoint]
        if payload is not None:
            args += ["--input", "-"]
        try:
            return json.loads(self.run(args, payload=payload))
        except APIError as exc:
            if missing_ok and exc.status == 404:
                return None
            raise

    def create_pr(self, branch, candidate_id, report, compatibility_status):
        body = (
            "This is an unqualified Matterix main candidate. Merging this metadata does not "
            "change runtime pins, build a GPU image, or qualify a worker. Merging it can "
            "trigger the existing deployment of approved Academy application code.\n\n"
            "Required before promotion:\n\n"
            "- Review the independent engine/assets pairing and runtime dependency locks.\n"
            "- Implement the adapter, versioned recipe, English course and UI coverage for "
            "each supported new feature; mark unsupported discoveries explicitly.\n"
            "- Run Academy contract tests and build an immutable GPU image.\n"
            "- Collect native workflow, session isolation, real browser video, refresh "
            "recovery, reset and second-run evidence against the new image/worker identity.\n"
            "- Drain the old worker before an explicit release; retain the prior image "
            "and exact pins for rollback.\n\n"
            f"Candidate: `{candidate_id}`\n\nCompatibility: **{compatibility_status}**.\n\n"
            f"Full report: `{REPORT_PATH}`.\n\n{report[:12000]}"
        )
        with tempfile.TemporaryDirectory(prefix="academy-candidate-pr-") as directory:
            body_file = Path(directory) / "body.md"
            body_file.write_text(body)
            return self.run(
                [
                    "pr",
                    "create",
                    "--repo",
                    REPOSITORY,
                    "--base",
                    "main",
                    "--head",
                    branch,
                    "--draft",
                    "--title",
                    f"Review {compatibility_status} Matterix candidate {candidate_id[:16]}",
                    "--body-file",
                    str(body_file),
                ]
            ).strip()


def validate_sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise PublishError("Expected a full Git SHA")
    return value


def read_file(path):
    if path.stat().st_size > MAX_FILE_BYTES:
        raise PublishError("Candidate metadata exceeds the size limit")
    return path.read_bytes()


def check_main(github, expected):
    ref = github.api(f"{API}/git/ref/heads/main")
    if ref.get("ref") != "refs/heads/main" or ref.get("object", {}).get("sha") != expected:
        raise PublishError("Academy main changed; rescan from the current trusted main")


def find_pr(github, branch):
    owner = REPOSITORY.split("/")[0]
    rows = github.api(f"{API}/pulls?state=all&head={owner}:{branch}&base=main&per_page=100")
    if not isinstance(rows, list) or len(rows) > 1:
        raise PublishError("Ambiguous existing candidate PRs; operator review required")
    if not rows:
        return None
    row = rows[0]
    if (
        row.get("head", {}).get("ref") != branch
        or row.get("head", {}).get("repo", {}).get("full_name") != REPOSITORY
        or row.get("base", {}).get("ref") != "main"
        or row.get("base", {}).get("repo", {}).get("full_name") != REPOSITORY
    ):
        raise PublishError("Existing PR repository/ref differs from the candidate")
    validate_sha(row["head"].get("sha"))
    return row


def verify_existing(github, commit_sha, files, candidate_id, expected_main):
    commit = github.api(f"{API}/git/commits/{validate_sha(commit_sha)}")
    parents = commit.get("parents", [])
    if len(parents) != 1 or commit.get("message") != f"Record Matterix candidate {candidate_id}":
        raise PublishError("Candidate branch has unexpected history; refusing to overwrite")
    parent = validate_sha(parents[0].get("sha"))
    if parent != expected_main:
        lineage = github.api(f"{API}/compare/{parent}...{expected_main}")
        if lineage.get("status") not in {"ahead", "identical"} or lineage.get("behind_by") != 0:
            raise PublishError(
                "Candidate parent is outside trusted main history; refusing to overwrite"
            )
    # Validate the entire generated commit, including after it has been merged.
    comparison = github.api(f"{API}/compare/{parent}...{commit_sha}")
    changed = comparison.get("files", [])
    if (
        comparison.get("ahead_by") != 1
        or comparison.get("total_commits") != 1
        or {entry.get("filename") for entry in changed} != set(files)
        or len(changed) != len(files)
        or any(entry.get("status") not in {"added", "modified"} for entry in changed)
    ):
        raise PublishError("Candidate branch contains unexpected changes; refusing to overwrite")
    if parent != expected_main:
        # GitHub compares from the merge base. A candidate already merged into
        # main contributes zero commits; an unmerged candidate contributes one.
        difference = github.api(f"{API}/compare/{expected_main}...{commit_sha}")
        entries = difference.get("files", [])
        unmerged = (
            difference.get("ahead_by") == 1
            and difference.get("total_commits") == 1
            and len(entries) == len(files)
            and {entry.get("filename") for entry in entries} == set(files)
            and all(entry.get("status") in {"added", "modified"} for entry in entries)
        )
        merged = (
            difference.get("ahead_by") == 0
            and difference.get("total_commits") == 0
            and difference.get("status") in {"behind", "identical"}
            and entries == []
        )
        if not (unmerged or merged):
            raise PublishError(
                "Candidate contains untrusted commits outside main; refusing to overwrite"
            )
    for path, expected in files.items():
        blob = github.api(f"{API}/contents/{path}?ref={commit_sha}")
        if blob.get("type") != "file" or blob.get("size") != len(expected):
            raise PublishError("Existing candidate evidence conflicts; refusing to overwrite")
        if blob.get("encoding") == "none":
            blob = github.api(f"{API}/git/blobs/{validate_sha(blob.get('sha'))}")
        if (
            blob.get("encoding") != "base64"
            or blob.get("size") != len(expected)
            or base64.b64decode(blob.get("content", "")) != expected
        ):
            raise PublishError("Existing candidate evidence conflicts; refusing to overwrite")


def publish(github, candidate, files, expected_main):
    validate_sha(expected_main)
    candidate_id = candidate.get("candidate_id", "")
    if (
        not re.fullmatch(r"[0-9a-f]{64}", candidate_id)
        or candidate.get("status") != "candidate-unqualified"
        or candidate.get("activation_allowed") is not False
        or candidate.get("worker_qualified") is not False
        or candidate.get("compatibility_status") not in {"blocked", "review-required"}
        or type(candidate.get("has_changes")) is not bool
        or set(files) != {CANDIDATE_PATH, REPORT_PATH}
    ):
        raise PublishError("Invalid unqualified candidate metadata")
    for key, repository in {
        "engine": "ac-rad/Matterix-Internal",
        "assets": "ac-rad/Matterix_assets_internal",
    }.items():
        source = candidate.get("repositories", {}).get(key, {})
        if source.get("repository") != repository or source.get("ref") != "main":
            raise PublishError("Only the fixed internal repositories' main refs are permitted")
    # This endpoint rejects personal tokens. Each write token is restricted to this one repo.
    installation = github.api("installation/repositories?per_page=100")
    if installation.get("total_count") != 1 or [
        row.get("full_name") for row in installation.get("repositories", [])
    ] != [REPOSITORY]:
        raise PublishError("Use a GitHub App installation token restricted to Academy")
    repo = github.api(API)
    if repo.get("full_name") != REPOSITORY or repo.get("default_branch") != "main":
        raise PublishError("Academy repository/default branch changed")
    check_main(github, expected_main)
    if not candidate["has_changes"]:
        return {"status": "no-upstream-changes", "published": False, "activation_allowed": False}
    branch = f"automation/matterix-{candidate_id[:16]}"
    existing_pr = find_pr(github, branch)
    ref = github.api(f"{API}/git/ref/heads/{branch}", missing_ok=True)
    if ref is not None and ref.get("ref") != f"refs/heads/{branch}":
        raise PublishError("Unexpected candidate branch ref")
    if existing_pr or ref:
        commit_sha = existing_pr["head"]["sha"] if existing_pr else ref["object"]["sha"]
        if ref and ref.get("object", {}).get("sha") != commit_sha:
            raise PublishError("Existing PR and branch disagree; operator review required")
        verify_existing(github, commit_sha, files, candidate_id, expected_main)
        if existing_pr:
            return {
                "status": "existing-candidate-pr",
                "published": False,
                "pull_request": existing_pr["html_url"],
                "state": existing_pr["state"],
                "activation_allowed": False,
            }
    else:
        parent = github.api(f"{API}/git/commits/{expected_main}")
        tree = []
        for path, content in files.items():
            blob = github.api(
                f"{API}/git/blobs",
                method="POST",
                payload={"content": base64.b64encode(content).decode(), "encoding": "base64"},
            )
            tree.append(
                {
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": validate_sha(blob.get("sha")),
                }
            )
        new_tree = github.api(
            f"{API}/git/trees",
            method="POST",
            payload={"base_tree": validate_sha(parent.get("tree", {}).get("sha")), "tree": tree},
        )
        commit = github.api(
            f"{API}/git/commits",
            method="POST",
            payload={
                "message": f"Record Matterix candidate {candidate_id}",
                "tree": validate_sha(new_tree.get("sha")),
                "parents": [expected_main],
            },
        )
        commit_sha = validate_sha(commit.get("sha"))
        check_main(github, expected_main)
        try:
            github.api(
                f"{API}/git/refs",
                method="POST",
                payload={"ref": f"refs/heads/{branch}", "sha": commit_sha},
            )
        except APIError as exc:
            if exc.status != 422:
                raise
            # Another run may have created this immutable branch. Reconcile, never force-push.
            raced = github.api(f"{API}/git/ref/heads/{branch}")
            if raced.get("ref") != f"refs/heads/{branch}":
                raise PublishError("Concurrent branch ref mismatch") from exc
            verify_existing(github, raced["object"]["sha"], files, candidate_id, expected_main)
    check_main(github, expected_main)
    # Reconcile the PR immediately before creation, including closed PRs.
    existing_pr = find_pr(github, branch)
    if existing_pr:
        verify_existing(github, existing_pr["head"]["sha"], files, candidate_id, expected_main)
        return {
            "status": "existing-candidate-pr",
            "published": False,
            "pull_request": existing_pr["html_url"],
            "state": existing_pr["state"],
            "activation_allowed": False,
        }
    github.create_pr(
        branch, candidate_id, files[REPORT_PATH].decode(), candidate["compatibility_status"]
    )
    created = find_pr(github, branch)
    if not created or created.get("draft") is not True or created.get("state") != "open":
        raise PublishError("Candidate PR creation could not be confirmed; reconcile before retry")
    verify_existing(github, created["head"]["sha"], files, candidate_id, expected_main)
    return {
        "status": "draft-candidate-created",
        "published": True,
        "pull_request": created["html_url"],
        "activation_allowed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-main", required=True)
    args = parser.parse_args()
    try:
        # Validation loads only trusted Academy code; upstream source is never executed.
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/matterix-sync.py"),
                "check",
                "--candidate",
                str(args.candidate),
                "--report",
                str(args.report),
            ],
            check=True,
            timeout=60,
        )
        files = {CANDIDATE_PATH: read_file(args.candidate), REPORT_PATH: read_file(args.report)}
        result = publish(GitHub(), json.loads(files[CANDIDATE_PATH]), files, args.expected_main)
    except (PublishError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Candidate publication failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
