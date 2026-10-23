"""Candidate publication tests use an in-memory GitHub; no upstream or paid resources."""

import base64
import importlib.util
import json
import os
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
MAIN = "a" * 40
COMMIT = "b" * 40
TREE = "c" * 40
CANDIDATE_ID = "d" * 64


def publisher():
    spec = importlib.util.spec_from_file_location(
        "matterix_sync_publish", ROOT / "scripts/publish-matterix-candidate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence(module, **overrides):
    candidate = {
        "candidate_id": CANDIDATE_ID,
        "status": "candidate-unqualified",
        "activation_allowed": False,
        "worker_qualified": False,
        "compatibility_status": "blocked",
        "has_changes": True,
        "repositories": {
            "engine": {"repository": "ac-rad/Matterix-Internal", "ref": "main"},
            "assets": {"repository": "ac-rad/Matterix_assets_internal", "ref": "main"},
        },
        **overrides,
    }
    files = {
        module.CANDIDATE_PATH: json.dumps(candidate).encode(),
        module.REPORT_PATH: b"# Synthetic candidate metadata fixture\n",
    }
    return candidate, files


class FakeGitHub:
    def __init__(self, module, files):
        self.module = module
        self.files = files
        self.calls = []
        self.pr = None
        self.ref = None
        self.main = MAIN
        self.main_reads = 0
        self.advance_on = None
        self.concurrent_branch = False
        self.fail_endpoint = None
        self.extra_change = False
        self.changed_evidence = False
        self.installation_count = 1
        self.poisoned_parent = False
        self.merged = False

    def api(self, endpoint, *, method="GET", payload=None, missing_ok=False):
        self.calls.append((method, endpoint, payload))
        module = self.module
        if endpoint == self.fail_endpoint:
            raise module.APIError(403)
        if endpoint == "installation/repositories?per_page=100":
            return {
                "total_count": self.installation_count,
                "repositories": [{"full_name": module.REPOSITORY}],
            }
        if endpoint == module.API:
            return {"full_name": module.REPOSITORY, "default_branch": "main"}
        if endpoint == f"{module.API}/git/ref/heads/main":
            self.main_reads += 1
            if self.main_reads == self.advance_on:
                self.main = "f" * 40
            return {"ref": "refs/heads/main", "object": {"sha": self.main}}
        if "/pulls?" in endpoint:
            return [self.pr] if self.pr else []
        if "/git/ref/heads/automation/" in endpoint:
            return self.ref
        if endpoint == f"{module.API}/git/commits/{MAIN}":
            return {"tree": {"sha": TREE}}
        if endpoint == f"{module.API}/git/commits/{COMMIT}":
            return {
                "parents": [{"sha": "1" * 40 if self.poisoned_parent else MAIN}],
                "message": f"Record Matterix candidate {CANDIDATE_ID}",
            }
        if method == "POST" and endpoint.endswith("/git/blobs"):
            return {"sha": "e" * 40}
        if method == "POST" and endpoint.endswith("/git/trees"):
            assert {row["path"] for row in payload["tree"]} == set(self.files)
            return {"sha": TREE}
        if method == "POST" and endpoint.endswith("/git/commits"):
            assert payload["parents"] == [MAIN]
            return {"sha": COMMIT}
        if method == "POST" and endpoint.endswith("/git/refs"):
            assert set(payload) == {"ref", "sha"}  # No force update is ever available.
            self.ref = {"ref": payload["ref"], "object": {"sha": COMMIT}}
            if self.concurrent_branch:
                raise module.APIError(422)
            return self.ref
        if "/compare/" in endpoint:
            if self.merged and endpoint.endswith(f"{self.main}...{COMMIT}"):
                return {"status": "behind", "ahead_by": 0, "total_commits": 0, "files": []}
            if endpoint.endswith("..." + self.main):
                return {
                    "status": "diverged" if self.poisoned_parent else "ahead",
                    "behind_by": 1 if self.poisoned_parent else 0,
                }
            files = [{"filename": path, "status": "added"} for path in self.files]
            if self.extra_change:
                files.append(
                    {"filename": "app/backend/academy/runtime_inventory.py", "status": "modified"}
                )
            return {"ahead_by": 1, "total_commits": 1, "files": files}
        if "/contents/" in endpoint:
            path = endpoint.split("/contents/", 1)[1].split("?ref=")[0]
            content = b"changed" if self.changed_evidence else self.files[path]
            return {
                "type": "file",
                "encoding": "base64",
                "size": len(content),
                "content": base64.b64encode(content).decode(),
            }
        raise AssertionError((method, endpoint, payload, missing_ok))

    def create_pr(self, branch, candidate_id, report, compatibility_status):
        assert candidate_id == CANDIDATE_ID
        assert report == self.files[self.module.REPORT_PATH].decode()
        assert compatibility_status == "blocked"
        assert not self.pr
        self.pr = {
            "head": {"ref": branch, "sha": COMMIT, "repo": {"full_name": self.module.REPOSITORY}},
            "base": {"ref": "main", "repo": {"full_name": self.module.REPOSITORY}},
            "html_url": "https://github.com/SissiFeng/matterix-academy/pull/123",
            "state": "open",
            "draft": True,
        }
        return self.pr["html_url"]

    def mutations(self):
        return [call for call in self.calls if call[0] != "GET"]


def setup_candidate(**overrides):
    module = publisher()
    candidate, files = evidence(module, **overrides)
    return module, candidate, files, FakeGitHub(module, files)


def test_new_candidate_is_metadata_only_draft_and_same_candidate_is_idempotent():
    module, candidate, files, github = setup_candidate()
    result = module.publish(github, candidate, files, MAIN)
    assert result["status"] == "draft-candidate-created"
    assert result["activation_allowed"] is False
    assert github.pr["draft"] is True
    assert len(github.mutations()) == 5
    mutation_count = len(github.mutations())
    again = module.publish(github, candidate, files, MAIN)
    assert again["status"] == "existing-candidate-pr"
    assert again["published"] is False
    assert len(github.mutations()) == mutation_count


def test_closed_candidate_is_not_reopened_or_duplicated_even_after_branch_deleted():
    module, candidate, files, github = setup_candidate()
    module.publish(github, candidate, files, MAIN)
    github.pr["state"] = "closed"
    github.ref = None
    mutation_count = len(github.mutations())
    result = module.publish(github, candidate, files, MAIN)
    assert result["state"] == "closed"
    assert not result["published"]
    assert len(github.mutations()) == mutation_count


def test_no_upstream_changes_does_not_create_a_branch_or_claim_synchronization():
    module, candidate, files, github = setup_candidate(has_changes=False)
    result = module.publish(github, candidate, files, MAIN)
    assert result == {
        "status": "no-upstream-changes",
        "published": False,
        "activation_allowed": False,
    }
    assert not github.mutations()
    assert not github.pr


@pytest.mark.parametrize("advance_on", [1, 2])
def test_stale_academy_main_cannot_publish_a_branch_or_pr(advance_on):
    module, candidate, files, github = setup_candidate()
    github.advance_on = advance_on
    with pytest.raises(module.PublishError, match="main changed"):
        module.publish(github, candidate, files, MAIN)
    assert github.ref is None
    assert github.pr is None


def test_concurrent_identical_branch_is_reconciled_without_force_push():
    module, candidate, files, github = setup_candidate()
    github.concurrent_branch = True
    result = module.publish(github, candidate, files, MAIN)
    assert result["status"] == "draft-candidate-created"
    assert not any(method in {"PATCH", "PUT", "DELETE"} for method, *_ in github.calls)


@pytest.mark.parametrize("conflict", ["extra_change", "changed_evidence"])
def test_existing_human_changes_or_evidence_conflict_are_never_overwritten(conflict):
    module, candidate, files, github = setup_candidate()
    module.publish(github, candidate, files, MAIN)
    setattr(github, conflict, True)
    mutations = len(github.mutations())
    with pytest.raises(module.PublishError, match="refusing to overwrite"):
        module.publish(github, candidate, files, MAIN)
    assert len(github.mutations()) == mutations


@pytest.mark.parametrize(
    "field,value", [("repository", "attacker/Matterix"), ("ref", "pull/4/head")]
)
def test_wrong_upstream_repository_or_ref_is_rejected_before_network(field, value):
    module, candidate, files, github = setup_candidate()
    candidate["repositories"]["engine"][field] = value
    with pytest.raises(module.PublishError, match="fixed internal repositories"):
        module.publish(github, candidate, files, MAIN)
    assert github.calls == []


def test_wrong_pr_repository_ref_or_disagreeing_branch_is_rejected():
    module, candidate, files, github = setup_candidate()
    module.publish(github, candidate, files, MAIN)
    github.pr["head"]["repo"]["full_name"] = "attacker/matterix-academy"
    with pytest.raises(module.PublishError, match="repository/ref differs"):
        module.publish(github, candidate, files, MAIN)
    github.pr["head"]["repo"]["full_name"] = module.REPOSITORY
    github.ref["object"]["sha"] = "f" * 40
    with pytest.raises(module.PublishError, match="PR and branch disagree"):
        module.publish(github, candidate, files, MAIN)


def test_denied_access_or_overbroad_token_never_reports_success():
    module, candidate, files, github = setup_candidate()
    github.fail_endpoint = f"{module.API}/git/refs"
    with pytest.raises(module.APIError, match="403"):
        module.publish(github, candidate, files, MAIN)
    assert github.pr is None
    github.fail_endpoint = None
    github.installation_count = 2
    with pytest.raises(module.PublishError, match="restricted to Academy"):
        module.publish(github, candidate, files, MAIN)


def test_metadata_tip_on_poisoned_parent_is_rejected_even_when_tip_diff_is_exact():
    module, candidate, files, github = setup_candidate()
    module.publish(github, candidate, files, MAIN)
    github.poisoned_parent = True
    mutations = len(github.mutations())
    with pytest.raises(module.PublishError, match="outside trusted main history"):
        module.publish(github, candidate, files, MAIN)
    assert len(github.mutations()) == mutations


def test_existing_candidate_remains_idempotent_after_trusted_main_advances():
    module, candidate, files, github = setup_candidate()
    module.publish(github, candidate, files, MAIN)
    github.main = "f" * 40
    mutations = len(github.mutations())
    result = module.publish(github, candidate, files, github.main)
    assert result["status"] == "existing-candidate-pr"
    assert len(github.mutations()) == mutations


def test_merged_candidate_is_not_reopened_or_duplicated():
    module, candidate, files, github = setup_candidate()
    module.publish(github, candidate, files, MAIN)
    github.main = "f" * 40
    github.merged = True
    github.pr["state"] = "closed"
    github.ref = None
    mutations = len(github.mutations())
    result = module.publish(github, candidate, files, github.main)
    assert result["status"] == "existing-candidate-pr"
    assert result["state"] == "closed"
    assert len(github.mutations()) == mutations


def test_http_403_is_not_treated_as_a_missing_branch(monkeypatch):
    module = publisher()
    monkeypatch.setenv("GH_TOKEN", "synthetic-app-token")
    monkeypatch.delenv("GH_HOST", raising=False)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1, stderr="gh: Forbidden (HTTP 403)", stdout="")

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(module.APIError) as failure:
        module.GitHub().api("repos/fixture/git/ref/heads/fixture", missing_ok=True)
    assert failure.value.status == 403
    assert "synthetic-app-token" not in str(calls[0][0])
    assert calls[0][1]["env"]["GH_TOKEN"] == "synthetic-app-token"


def test_pr_uses_body_file_and_never_embeds_report_in_shell(monkeypatch):
    module = publisher()
    monkeypatch.setenv("GH_TOKEN", "synthetic-app-token")
    monkeypatch.delenv("GH_HOST", raising=False)
    seen = []

    def run(args, **kwargs):
        seen.append(args)
        body = Path(args[args.index("--body-file") + 1]).read_text()
        assert "$(do-not-run) `literal`" in body
        assert "--draft" in args
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout="https://github.com/SissiFeng/matterix-academy/pull/123\n",
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    module.GitHub().create_pr(
        "automation/matterix-" + CANDIDATE_ID[:16],
        CANDIDATE_ID,
        "$(do-not-run) `literal`",
        "blocked",
    )
    assert len(seen) == 1
    assert "$(do-not-run)" not in str(seen[0])


def test_workflow_uses_fixed_main_sources_scoped_tokens_and_no_aws_permissions():
    workflow = (ROOT / ".github/workflows/matterix-sync.yml").read_text()
    assert "cron: '23 */6 * * *'" in workflow
    assert "matterix-main-updated" in workflow
    assert '"$ACADEMY_REF" != refs/heads/main' in workflow
    assert "client_payload" not in workflow
    assert "pull_request_target" not in workflow
    assert "id-token:" not in workflow
    assert "configure-aws-credentials" not in workflow
    assert "MATTERIX_SYNC_ENABLED" in workflow and '"status": "setup-required"' in workflow
    assert "--depth=1 --no-tags --no-recurse-submodules" in workflow
    assert "refs/remotes/origin/main" in workflow
    assert "--report build/matterix-sync/report.md" in workflow
    assert "persist-credentials: false" in workflow
    assert "if: always()" in workflow
    upstream = workflow.split("id: upstream-token", 1)[1].split("      - name:", 1)[0]
    writer = workflow.split("id: academy-token", 1)[1].split("      - name:", 1)[0]
    assert "vars.MATTERIX_READ_APP_ID" in upstream
    assert "secrets.MATTERIX_READ_APP_PRIVATE_KEY" in upstream
    assert "permission-contents: read" in upstream
    assert ": write" not in upstream
    assert "vars.ACADEMY_SYNC_APP_ID" in writer
    assert "secrets.ACADEMY_SYNC_APP_PRIVATE_KEY" in writer
    assert "permission-contents: write" in writer
    assert "permission-pull-requests: write" in writer
    assert "MATTERIX_SYNC_APP_ID" not in workflow


@pytest.mark.parametrize(
    "missing",
    [
        "READ_APP_ID",
        "READ_APP_PRIVATE_KEY",
        "WRITE_APP_ID",
        "WRITE_APP_PRIVATE_KEY",
        "disabled",
        "complete",
    ],
)
def test_actual_workflow_configuration_requires_both_separate_apps(tmp_path, missing):
    workflow = (ROOT / ".github/workflows/matterix-sync.yml").read_text()
    step = workflow.split("id: configuration\n", 1)[1].split("      - name:", 1)[0]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    env = {
        **os.environ,
        "SYNC_ENABLED": "true",
        "READ_APP_ID": "synthetic-read-id",
        "READ_APP_PRIVATE_KEY": "synthetic-read-key",
        "WRITE_APP_ID": "synthetic-write-id",
        "WRITE_APP_PRIVATE_KEY": "synthetic-write-key",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    if missing == "disabled":
        env["SYNC_ENABLED"] = "false"
        for key in ("READ_APP_ID", "READ_APP_PRIVATE_KEY", "WRITE_APP_ID", "WRITE_APP_PRIVATE_KEY"):
            env[key] = ""
    elif missing != "complete":
        env[missing] = ""
    result = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, env=env, text=True, capture_output=True, timeout=10
    )
    assert result.returncode == (0 if missing in {"disabled", "complete"} else 1)
    output = (tmp_path / "output").read_text()
    if missing == "complete":
        assert output == "ready=true\n"
        assert not (tmp_path / "build/matterix-sync/status.json").exists()
    else:
        assert output == "ready=false\n"
        status = json.loads((tmp_path / "build/matterix-sync/status.json").read_text())
        assert status["status"] == "setup-required"
        assert status["upstream_checked"] is False
        assert status["published"] is False
        assert status["activation_allowed"] is False
