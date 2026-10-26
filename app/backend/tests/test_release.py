"""A deploy job must reject changed artifacts before obtaining cloud credentials."""

import importlib.util
from pathlib import Path

import pytest


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
    module.LAMBDA.write_bytes(b"fixture-only-package")
    (module.WEB / "index.html").write_text("<p>Fixture</p>")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    module.manifest()
    return module


def test_release_accepts_exact_tested_files(release):
    assert release.verify()["commit"] == "a" * 40


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


def test_physical_gate_must_match_its_declared_state(release, monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("SIM2REAL_LAMBDA_FUNCTIONS", '["gateway-authorizer"]')

    class RealGateLambda(FakeLambda):
        def get_function_configuration(self, FunctionName):
            return {
                "Environment": {
                    "Variables": {"ACADEMY_REMOTE_ENABLED": "false", "ACADEMY_REAL_ENABLED": "true"}
                }
            }

    session = FakeSession("false")
    session.functions = RealGateLambda("false")
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: session)
    with pytest.raises(ValueError, match="Physical execution gate"):
        release.publish()
    assert session.functions.updated == []


def test_sim2real_functions_must_be_distinct(release, monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("SIM2REAL_LAMBDA_FUNCTIONS", '["academy"]')
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: pytest.fail("AWS was accessed"))
    with pytest.raises(ValueError):
        release.publish()
