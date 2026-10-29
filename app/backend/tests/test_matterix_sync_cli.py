"""Read upstream objects without trusting or executing the independent worktree."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def script():
    spec = importlib.util.spec_from_file_location(
        "matterix_sync_cli", ROOT / "scripts/matterix-sync.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


def fixture_repo(tmp_path):
    root = tmp_path / "upstream"
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.name", "Synthetic intake fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "remote", "add", "origin", "https://github.com/ac-rad/Matterix-Internal.git")
    source = root / "source/tasks.py"
    source.parent.mkdir()
    source.write_text("raise RuntimeError('Never import upstream')\n")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "commit.gpgSign=false",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "--quiet",
        "-m",
        "Synthetic intake fixture",
    )
    sha = git(root, "rev-parse", "HEAD")
    git(root, "update-ref", "refs/remotes/origin/main", sha)
    return root, source, sha


def test_snapshot_reads_pinned_objects_ignores_dirty_files_and_never_imports(tmp_path):
    module = script()
    root, source, sha = fixture_repo(tmp_path)
    source.write_text("malformed dirty file !!!")
    policy, profile = module.load_policy()
    profile["engine_commit"] = sha
    result = module.snapshot(root, "engine", policy, profile, sha)
    assert result["commit"] == sha
    assert result["sources"]["source/tasks.py"] == "raise RuntimeError('Never import upstream')\n"
    assert result["base_sources"] == result["sources"]
    assert source.read_text() == "malformed dirty file !!!"


def test_snapshot_rejects_wrong_origin_stale_resolution_and_missing_baseline(tmp_path):
    module = script()
    root, _, sha = fixture_repo(tmp_path)
    policy, profile = module.load_policy()
    profile["engine_commit"] = sha
    with pytest.raises(ValueError, match="expected observed revision"):
        module.snapshot(root, "engine", policy, profile, "f" * 40)
    profile["engine_commit"] = "e" * 40
    with pytest.raises(ValueError, match="Git object"):
        module.snapshot(root, "engine", policy, profile)
    git(root, "remote", "set-url", "origin", "https://github.com/ac-rad/Matterix.git")
    with pytest.raises(ValueError, match="Wrong engine origin"):
        module.snapshot(root, "engine", policy, profile)


@pytest.mark.parametrize(
    "origin",
    [
        "https://token@github.com/ac-rad/Matterix-Internal.git",
        "https://github.com.evil.invalid/ac-rad/Matterix-Internal.git",
        "https://github.com:443/ac-rad/Matterix-Internal.git",
        "https://github.com/ac-rad/Matterix-Internal.git?token=secret",
        "file:///tmp/upstream",
        "git@github.com:ac-rad/Matterix-Internal/../../evil",
    ],
)
def test_origin_rejects_credentials_and_unexpected_locations(origin):
    with pytest.raises(ValueError):
        script().origin_repository(origin)


def test_source_and_tree_limits_fail_closed(tmp_path):
    module = script()
    root, _, sha = fixture_repo(tmp_path)
    with pytest.raises(ValueError, match="entry limit"):
        module.tree(root, sha, 0)
    entries = module.tree(root, sha, 10)
    with pytest.raises(ValueError, match="source count"):
        module.sources(root, entries, {"max_source_files": 0, "max_source_bytes": 1024})
    with pytest.raises(ValueError, match="intake limit"):
        module.sources(root, entries, {"max_source_files": 10, "max_source_bytes": 1})


def test_output_cannot_replace_symlink(tmp_path):
    target = tmp_path / "keep.txt"
    target.write_text("preserve")
    output = tmp_path / "report.md"
    output.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        script().write_output(output, "replacement")
    assert target.read_text() == "preserve"


def test_policy_binds_real_adapter_paths():
    policy, profile = script().load_policy()
    assert policy["repositories"]["assets"]["repository"] == "ac-rad/Matterix_assets_internal"
    assert len(profile["academy_adapter_sha256"]) == 64


def test_policy_requires_payloads_loaded_by_the_approved_mixing_scene():
    policy, _ = script().load_policy()
    # Approved internal Flex labware config directly loads these USD payloads.
    payloads = {
        "trash_collision",
        "mix_plate",
        "vial_rack",
        "vial_lid",
        "lid_staging",
        "reservoir",
        "rack_50",
        "rack_1000",
        "tip_50",
        "tip_1000",
    }
    assert {f"labware/flex_mixing/{name}.usda" for name in payloads} <= set(
        policy["required_paths"]["assets"]
    )
    assert (
        "source/matterix_assets/matterix_assets/labware/flex_mixing.py"
        in policy["required_paths"]["engine"]
    )
