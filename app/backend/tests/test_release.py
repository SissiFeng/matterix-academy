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
