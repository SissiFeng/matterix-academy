"""Offline release/image contracts. No Packer build, cloud or GPU execution."""

import gzip
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from academy.runtime_inventory import PROFILE

ROOT = Path(__file__).resolve().parents[3]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


def repository(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Synthetic release fixture")
    for name, body in (
        ("ops/ec2-gpu/image-manifest.example.json", json.dumps({**PROFILE, "academy_commit": ""})),
        ("uv.lock", "agent dependencies"),
        ("app/frontend/package-lock.json", "frontend dependencies"),
        ("ops/ec2-gpu/runtime-linux-x86_64.lock", "runtime dependencies"),
        ("ops/ec2-gpu/agent-requirements.lock", "agent lock"),
    ):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "Synthetic fixture")
    return root, git(root, "rev-parse", "HEAD")


def test_release_is_committed_deterministic_and_hash_bound(tmp_path):
    module = script("ec2-gpu-release")
    root, commit = repository(tmp_path)
    for name in ("first", "second"):
        private_inputs(tmp_path / name)
    first = module.package(root, commit, tmp_path / "first")
    second = module.package(root, commit, tmp_path / "second")
    assert first == second
    archive = (tmp_path / "first/academy.tar.gz").read_bytes()
    assert hashlib.sha256(archive).hexdigest() == first["archive_sha256"]
    manifest = json.loads((tmp_path / "first/image-manifest.json").read_text())
    assert manifest["academy_commit"] == commit
    assert first["status"] == "source-release-not-gpu-qualified"
    assert gzip.decompress(archive)
    assert archive[9] == 255  # Platform-independent gzip OS header.
    assert (
        manifest["sources_manifest_sha256"]
        == hashlib.sha256((tmp_path / "first/sources.json").read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "case", ["dirty", "untracked", "abbreviated", "older_commit", "in_checkout"]
)
def test_release_rejects_unreviewable_inputs(tmp_path, case):
    module = script("ec2-gpu-release")
    root, commit = repository(tmp_path)
    output = tmp_path / "output"
    if case == "dirty":
        (root / "uv.lock").write_text("changed")
    elif case == "untracked":
        (root / "credential").write_text("synthetic private file")
    elif case == "abbreviated":
        commit = commit[:12]
    elif case == "older_commit":
        git(root, "commit", "--allow-empty", "-qm", "New reviewed revision")
    else:
        output = root / "output"
    with pytest.raises(ValueError):
        module.package(root, commit, output)


def test_source_export_keeps_commit_without_local_credentials_or_untracked_files(
    tmp_path, monkeypatch
):
    module = script("ec2-gpu-sources")
    root, commit = repository(tmp_path)
    git(root, "config", "credential.helper", "synthetic-local-helper")
    copy = module.shutil.copy2

    def inject_checkout_credential(source, destination):
        copy(source, destination)
        checkout = next(p for p in destination.parents if (p / ".git/config").is_file())
        with (checkout / ".git/config").open("a") as file:
            file.write("\n[credential]\n\thelper = checkout-secret-sentinel\n")

    monkeypatch.setattr(module.shutil, "copy2", inject_checkout_credential)
    (root / "private-untracked").write_text("do not export")
    target = tmp_path / "source.tar.gz"
    sha = module.snapshot(root, commit, target)
    assert sha == hashlib.sha256(target.read_bytes()).hexdigest()
    with tarfile.open(target) as archive:
        assert not any("private-untracked" in name for name in archive.getnames())
        config = archive.extractfile("./.git/config").read().decode()
        assert "credential" not in config and "remote" not in config
        assert "checkout-secret-sentinel" not in config
        assert archive.extractfile("./.git/HEAD").read().decode().strip() == commit


def test_source_export_rejects_materialized_content_drift(tmp_path):
    module = script("ec2-gpu-sources")
    root, commit = repository(tmp_path)
    (root / "uv.lock").write_text("changed source content")
    with pytest.raises(ValueError, match="differs"):
        module.snapshot(root, commit, tmp_path / "drift.tar.gz")


def test_runtime_lock_closes_internal_and_sim_dependencies():
    lock = (ROOT / "ops/ec2-gpu/runtime-linux-x86_64.lock").read_text()
    versions = dict(re.findall(r"^([a-zA-Z0-9_-]+)==([^\s\\]+)", lock, re.M))
    assert versions["torch"] == PROFILE["torch_version"] == "2.11.0+cu128"
    assert versions["torchvision"] == PROFILE["torchvision_version"] == "0.26.0+cu128"
    assert versions["isaaclab"] == PROFILE["isaaclab_version"]
    assert versions["isaacsim-core"] == PROFILE["isaacsim_version"]
    assert versions["pydantic"] == "2.11.10"
    assert all(
        name in versions
        for name in ["psutil", "toml", "protobuf", "scikit-learn", "tensorboard", "flatdict"]
    )
    assert PROFILE["isaaclab_wheel_sha256"] in lock
    for block in re.split(r"\n(?=[a-zA-Z0-9_-]+==)", lock)[1:]:
        assert "--hash=sha256:" in block


def test_native_entrypoint_imports_use_only_runtime_locked_packages():
    """The agent venv must not hide a missing dependency in the isolated Isaac venv."""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            r"""
import importlib.abc
import importlib.metadata
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
normalize = lambda name: name.lower().replace('_', '-').replace('.', '-')
locked = {
    normalize(name)
    for name in re.findall(
        r'^([a-zA-Z0-9_-]+)==',
        (root / 'ops/ec2-gpu/runtime-linux-x86_64.lock').read_text(), re.M,
    )
}
distributions = importlib.metadata.packages_distributions()

class RuntimeLockOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        package = fullname.partition('.')[0]
        if package == 'academy' or package in sys.stdlib_module_names:
            return None
        owners = {normalize(name) for name in distributions.get(package, [])}
        if owners and not owners.intersection(locked):
            raise ModuleNotFoundError(
                f'{fullname} is unavailable in the isolated native runtime: {sorted(owners)}'
            )
        return None

sys.meta_path.insert(0, RuntimeLockOnly())
sys.path.insert(0, str(root / 'app/backend'))
from academy import native_image_probe, native_studio_isaac
from academy.native_runner import NativeConfig
assert callable(native_image_probe.main)
assert callable(native_studio_isaac.run)
assert callable(NativeConfig.model_validate)
""",
            str(ROOT),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_image_build_is_explicit_and_service_remains_uncredentialed():
    config = (ROOT / "ops/ec2-gpu/image/gpu.pkr.hcl").read_text()
    assert 'variable "confirm_paid_build"' in config and "default = false" in config
    assert 'variable "accept_nvidia_eula"' in config
    assert "expected_account_id" in config and "source_ami_filter" not in config
    assert "AcademyManifestSHA256" in config
    assert 'source      = "${var.input_dir}/"' not in config
    provision = (ROOT / "ops/ec2-gpu/image/provision.sh").read_text()
    assert "--require-hashes" in provision and "--no-build-isolation" in provision
    assert "systemctl disable academy-native.service" in provision
    assert "systemctl enable academy-native.service" not in provision
    assert "worker.token" not in provision
    for name in ("provision.sh", "finalize.sh"):
        subprocess.run(["bash", "-n", str(ROOT / "ops/ec2-gpu/image" / name)], check=True)


def test_native_image_probe_requires_confirmation_before_runtime_import(tmp_path):
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "academy.native_image_probe",
            "--config",
            str(tmp_path / "missing"),
            "--output",
            str(tmp_path / "report"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Explicit native scene/render probe authorization" in result.stderr
    assert not (tmp_path / "report").exists()


def test_bootstrap_extracts_complete_hashed_logical_requirements():
    module = script("ec2-gpu-bootstrap")
    selected = module.extract((ROOT / "ops/ec2-gpu/runtime-linux-x86_64.lock").read_text())
    assert set(re.findall(r"^([a-z]+)==", selected, re.M)) == module.TOOLS
    for block in re.split(r"\n(?=[a-z]+==)", selected):
        assert "--hash=sha256:" in block
        assert not block.rstrip().endswith("\\")
    with pytest.raises(ValueError):
        module.extract("uv==0.11.18\n")


def test_image_installed_permissions_and_metadata_probe_contract():
    provision = (ROOT / "ops/ec2-gpu/image/provision.sh").read_text()
    assert "chmod -R a+rX,go-w /opt/academy-agent /opt/matterix-isaac" in provision
    assert "chmod 644 /etc/academy-native/native-config.json" in provision
    finalize = (ROOT / "ops/ec2-gpu/image/finalize.sh").read_text()
    assert "latest/api/token" in finalize and "-X PUT" in finalize
    assert '"$worker_metadata_status" == 7' in finalize


def private_inputs(root):
    root.mkdir(parents=True, exist_ok=True)
    record = {}
    for name, key in (("engine", "engine_commit"), ("assets", "asset_commit")):
        payload = b"synthetic archive " + name.encode()
        (root / f"{name}.tar.gz").write_bytes(payload)
        record[name] = {"commit": PROFILE[key], "sha256": hashlib.sha256(payload).hexdigest()}
    (root / "sources.json").write_text(json.dumps(record))


def image_inputs(tmp_path, monkeypatch):
    module = script("ec2-gpu-inputs")
    manifest = json.loads((ROOT / "ops/ec2-gpu/image-manifest.example.json").read_text())
    manifest["academy_commit"] = "a" * 40
    private_inputs(tmp_path)
    manifest["sources_manifest_sha256"] = module.sha256(tmp_path / "sources.json")
    monkeypatch.setattr(module, "reviewed_commit", lambda: manifest["academy_commit"])
    (tmp_path / "image-manifest.json").write_text(json.dumps(manifest))
    for name in ("academy", "engine", "assets"):
        (tmp_path / f"{name}.tar.gz").write_bytes(b"synthetic archive " + name.encode())
    release = {
        "academy_commit": manifest["academy_commit"],
        "archive_sha256": module.sha256(tmp_path / "academy.tar.gz"),
        "manifest_sha256": module.sha256(tmp_path / "image-manifest.json"),
    }
    (tmp_path / "release.json").write_text(json.dumps(release))
    driver = json.loads((ROOT / "ops/ec2-gpu/image/driver.json").read_text())
    (tmp_path / "driver.json").write_text(json.dumps(driver))
    real_hash = module.sha256
    # The 403 MB proprietary installer is not a test fixture. Other digests are real.
    monkeypatch.setattr(
        module,
        "sha256",
        lambda path: driver["sha256"] if path.name == "nvidia-driver.run" else real_hash(path),
    )
    return module


def test_complete_input_binding_is_only_ready_for_authorized_build(tmp_path, monkeypatch):
    module = image_inputs(tmp_path, monkeypatch)
    result = module.validate(tmp_path)
    assert result["inputs_ready_for_authorized_build"]
    assert not result["image_built"] and not result["browser_dt_accepted"]


@pytest.mark.parametrize(
    "change",
    ["archive", "manifest", "source", "driver", "release", "source_and_archive", "checkout"],
)
def test_image_input_binding_blocks_drift(tmp_path, monkeypatch, change):
    module = image_inputs(tmp_path, monkeypatch)
    if change == "archive":
        (tmp_path / "engine.tar.gz").write_bytes(b"changed archive")
    elif change == "checkout":
        monkeypatch.setattr(module, "reviewed_commit", lambda: "b" * 40)
    elif change == "source_and_archive":
        archive = tmp_path / "engine.tar.gz"
        archive.write_bytes(b"different payload claiming the same commit")
        source = tmp_path / "sources.json"
        value = json.loads(source.read_text())
        value["engine"]["sha256"] = module.sha256(archive)
        source.write_text(json.dumps(value))
    else:
        name = {
            "manifest": "image-manifest.json",
            "source": "sources.json",
            "driver": "driver.json",
            "release": "release.json",
        }[change]
        value = json.loads((tmp_path / name).read_text())
        if change == "manifest":
            value["torch_version"] = "2.10.0+cu128"
        elif change == "source":
            value["engine"]["commit"] = "b" * 40
        elif change == "driver":
            value["sha256"] = "b" * 64
        else:
            value["academy_commit"] = "b" * 40
        (tmp_path / name).write_text(json.dumps(value))
    with pytest.raises(ValueError):
        module.validate(tmp_path)


def test_build_identity_uses_exact_frozen_credentials_and_pinned_sts_endpoint(monkeypatch):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    module = script("ec2-gpu-build")
    monkeypatch.setenv("AWS_ENDPOINT_URL_STS", "https://example.invalid/spoofed-sts")
    monkeypatch.setenv("AWS_PROFILE", "unrelated-profile")
    frozen = SimpleNamespace(
        access_key="synthetic-key", secret_key="synthetic-secret", token="synthetic-token"
    )
    calls = []

    def client(name, **kwargs):
        calls.append((name, kwargs))
        return SimpleNamespace(get_caller_identity=lambda: {"Account": "123456789012"})

    session = SimpleNamespace(
        get_credentials=lambda: SimpleNamespace(
            get_frozen_credentials=lambda: frozen,
            _expiry_time=datetime.now(UTC) + timedelta(hours=4),
        ),
        client=client,
    )
    env, expires = module.verified_environment(session, "123456789012", "ca-central-1")
    assert expires > datetime.now(UTC) + timedelta(hours=3)
    assert calls[0][1]["endpoint_url"] == "https://sts.ca-central-1.amazonaws.com"
    assert calls[0][1]["verify"] is True
    assert calls[0][1]["aws_access_key_id"] == env["AWS_ACCESS_KEY_ID"] == frozen.access_key
    assert "AWS_PROFILE" not in env and "AWS_ENDPOINT_URL_STS" not in env
    with pytest.raises(ValueError, match="account"):
        module.build_environment(
            {"Account": "999999999999"}, frozen, "123456789012", "ca-central-1"
        )
