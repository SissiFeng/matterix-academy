"""A deploy job must reject changed artifacts before obtaining cloud credentials."""

import importlib.util
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from academy._version import __version__


@pytest.fixture
def release(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[3] / "scripts" / "release.py"
    spec = importlib.util.spec_from_file_location("academy_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.MANIFEST = tmp_path / "release.json"
    module.LAMBDA = tmp_path / "lambda.zip"
    module.WEB = tmp_path / "web"
    module.WEB.mkdir()
    with zipfile.ZipFile(module.LAMBDA, "w") as archive:
        archive.writestr("academy/_version.py", f"__version__ = {__version__!r}\n")
    (module.WEB / "index.html").write_text("<p>Fixture</p>")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    module.manifest()
    return module


def test_release_accepts_exact_tested_files(release):
    assert release.verify()["commit"] == "a" * 40
    assert release.verify()["version"] == __version__


def test_manifest_rejects_a_stale_lambda_package(release):
    with zipfile.ZipFile(release.LAMBDA, "w") as archive:
        archive.writestr("academy/_version.py", '__version__ = "0.1.0"\n')
    with pytest.raises(ValueError, match="package version"):
        release.manifest()


def test_release_rejects_a_manifest_with_another_version(release):
    manifest = json.loads(release.MANIFEST.read_text())
    manifest["version"] = "0.1.0"
    release.MANIFEST.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Release version"):
        release.verify()


@pytest.mark.parametrize("api_version", [__version__, "0.1.0"])
def test_live_api_and_frontend_must_report_the_same_release(release, api_version):
    manifest = release.verify()

    def respond(request):
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "version": api_version})
        if request.url.path == "/version.json":
            return httpx.Response(200, json=manifest)
        return httpx.Response(401 if request.url.path == "/api/me" else 200)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        if api_version == __version__:
            release.verify_live_release(http, "https://example.cloudfront.net", manifest)
        else:
            with pytest.raises(RuntimeError, match="Live API version"):
                release.verify_live_release(http, "https://example.cloudfront.net", manifest)


@pytest.mark.parametrize("change", ["lambda", "frontend", "missing", "extra", "commit"])
def test_release_rejects_changed_files_and_revision(release, monkeypatch, change):
    if change == "lambda":
        release.LAMBDA.write_bytes(b"other code")
    elif change == "frontend":
        (release.WEB / "index.html").write_text("other page")
    elif change == "missing":
        (release.WEB / "index.html").unlink()
    elif change == "extra":
        (release.WEB / "unexpected.js").write_text("other script")
    else:
        monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    with pytest.raises(ValueError):
        release.verify()


@pytest.mark.parametrize("workers", ['"abc"', '{"a":1,"b":2,"c":3}', '[{},"b","c"]'])
def test_malformed_function_configuration_is_rejected_before_aws(release, monkeypatch, workers):
    monkeypatch.setenv("LAMBDA_FUNCTION", "academy")
    monkeypatch.setenv("WORKER_LAMBDA_FUNCTIONS", workers)
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: pytest.fail("AWS was accessed"))
    with pytest.raises(ValueError):
        release.publish()


def configure(monkeypatch):
    monkeypatch.setenv("LAMBDA_FUNCTION", "academy")
    monkeypatch.setenv("WORKER_LAMBDA_FUNCTIONS", '["w", "a", "r"]')
    monkeypatch.setenv("AWS_ACCOUNT_ID", "123456789012")
    monkeypatch.setenv("AWS_REGION", "ca-central-1")
    monkeypatch.setenv("WEB_BUCKET", "bucket")
    monkeypatch.setenv("DISTRIBUTION_ID", "E1")
    monkeypatch.setenv("APP_URL", "https://abc123.cloudfront.net")


class FakeLambda:
    def __init__(self, gate):
        self.gate, self.updated = gate, []

    def get_function_configuration(self, FunctionName):
        return {"Environment": {"Variables": {"ACADEMY_REMOTE_ENABLED": self.gate}}}

    def update_function_code(self, **kwargs):
        self.updated.append(kwargs["FunctionName"])
        raise RuntimeError("stop after the preflight")


class FakeSession:
    def __init__(self, gate):
        self.functions = FakeLambda(gate)

    def client(self, name):
        if name == "sts":
            return type("STS", (), {"get_caller_identity": lambda s: {"Account": "123456789012"}})()
        return self.functions


@pytest.mark.parametrize("value", ["yes", "1", "TRUE"])
def test_native_gate_declaration_is_validated_before_aws(release, monkeypatch, value):
    configure(monkeypatch)
    monkeypatch.setenv("NATIVE_EXECUTION_EXPECTED", value)
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: pytest.fail("AWS was accessed"))
    with pytest.raises(ValueError):
        release.publish()


@pytest.mark.parametrize(
    "declared,actual,proceeds",
    [
        (None, "false", True),
        (None, "true", False),
        ("true", "true", True),
        ("true", "false", False),
    ],
)
def test_native_gate_must_match_declared_state(release, monkeypatch, declared, actual, proceeds):
    configure(monkeypatch)
    if declared:
        monkeypatch.setenv("NATIVE_EXECUTION_EXPECTED", declared)
    session = FakeSession(actual)
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: session)
    if proceeds:
        with pytest.raises(RuntimeError, match="preflight"):
            release.publish()
        assert session.functions.updated == ["academy"]
    else:
        with pytest.raises(ValueError, match="NATIVE_EXECUTION_EXPECTED"):
            release.publish()
        assert session.functions.updated == []
