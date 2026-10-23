import json
from importlib.metadata import version
from pathlib import Path

from academy._version import __version__


def test_runtime_and_frontend_release_versions_agree():
    root = Path(__file__).resolve().parents[3]
    package = json.loads((root / "app/frontend/package.json").read_text())
    lock = json.loads((root / "app/frontend/package-lock.json").read_text())
    assert version("matterix-academy") == __version__
    assert package["version"] == lock["version"] == lock["packages"][""]["version"] == __version__


def test_health_and_openapi_report_the_packaged_version(client):
    assert client.get("/api/health").json() == {"status": "ok", "version": __version__}
    assert client.get("/api/openapi.json").json()["info"]["version"] == __version__
