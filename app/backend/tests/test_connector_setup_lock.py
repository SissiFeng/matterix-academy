"""The real setup CLI cannot race the normal companion's workflow process."""

from pathlib import Path
from uuid import uuid4

import pytest
from academy.companion import installer
from academy.companion.config import private_directory
from academy.companion.journal import Journal


def arguments():
    return [
        "reconcile",
        "--operation-id",
        str(uuid4()),
        "--recovery-id",
        str(uuid4()),
        "--resolution-id",
        str(uuid4()),
    ]


def setup_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(installer.sys.stdin, "isatty", lambda: True)
    return private_directory(tmp_path / ".local/share/academy-companion")


def test_live_workflow_process_blocks_robot_setup(monkeypatch, tmp_path):
    state = setup_home(monkeypatch, tmp_path)
    monkeypatch.setattr(installer, "Installer", lambda _: pytest.fail("setup must not start"))
    with Journal(state):
        with pytest.raises(RuntimeError, match="Another companion"):
            installer.main(arguments())


def test_unresolved_workflow_blocks_robot_software_changes(monkeypatch, tmp_path):
    state = setup_home(monkeypatch, tmp_path)
    with Journal(state) as journal:
        journal.begin({"run_id": str(uuid4())})
    monkeypatch.setattr(installer, "Installer", lambda _: pytest.fail("setup must not start"))
    with pytest.raises(RuntimeError, match="prior physical workflow"):
        installer.main(arguments())


def test_setup_holds_shared_lock_until_complete(monkeypatch, tmp_path):
    state = setup_home(monkeypatch, tmp_path)
    closed = []

    class FixtureInstaller:
        def __init__(self, directory):
            assert directory == state / "installer"

        def reconcile(self, *args, **kwargs):
            with pytest.raises(RuntimeError, match="Another companion"):
                Journal(state)
            return {"evidence": "software-only fixture"}

        def close(self):
            closed.append(True)

    monkeypatch.setattr(installer, "Installer", FixtureInstaller)
    installer.main(arguments())
    assert closed == [True]
    with Journal(state):
        pass
