"""Durable no-replay journal and immutable receipt outbox, protected by a process lock."""

import fcntl
import json
import os
import sqlite3
from pathlib import Path

from .config import canonical, check_private_database, private_directory


class Journal:
    def __init__(self, directory: Path):
        self.directory = private_directory(directory)
        self.lock_fd = os.open(
            directory / "companion.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.lock_fd)
            raise RuntimeError("Another companion owns this installation") from None
        path = directory / "journal.sqlite3"
        try:
            if path.exists() or path.is_symlink():
                check_private_database(path)
            else:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            self.db = sqlite3.connect(path)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=DELETE")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, command TEXT NOT NULL, phase TEXT NOT NULL, protocol_id TEXT, robot_run_id TEXT, receipt TEXT, sent INTEGER NOT NULL DEFAULT 0)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS resolutions (command_id TEXT PRIMARY KEY REFERENCES commands(id), evidence TEXT NOT NULL)"
            )
            self.db.execute(
                "CREATE TRIGGER IF NOT EXISTS immutable_resolution_update BEFORE UPDATE ON resolutions BEGIN SELECT RAISE(ABORT, 'Resolution evidence is append-only'); END"
            )
            self.db.execute(
                "CREATE TRIGGER IF NOT EXISTS immutable_resolution_delete BEFORE DELETE ON resolutions BEGIN SELECT RAISE(ABORT, 'Resolution evidence is append-only'); END"
            )
            self.db.commit()
        except BaseException:
            os.close(self.lock_fd)
            raise

    def close(self):
        self.db.close()
        os.close(self.lock_fd)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def begin(self, command: dict) -> bool:
        encoded = canonical(command).decode()
        old = self.db.execute(
            "SELECT command FROM commands WHERE id=?", (command["run_id"],)
        ).fetchone()
        if old:
            if old["command"] != encoded:
                raise ValueError("A previously seen command changed; refusing execution")
            return False
        if self.db.execute(
            "SELECT 1 FROM commands c WHERE receipt IS NULL OR (json_extract(receipt,'$.outcome')='unknown' AND NOT EXISTS (SELECT 1 FROM resolutions r WHERE r.command_id=c.id))"
        ).fetchone():
            raise RuntimeError(
                "Unresolved prior execution: physical inspection and reconciliation required"
            )
        with self.db:
            self.db.execute(
                "INSERT INTO commands(id,command,phase) VALUES(?,?,'claimed')",
                (command["run_id"], encoded),
            )
        return True

    def phase(self, run_id: str, phase: str, *, protocol_id=None, robot_run_id=None):
        # Commit before every uncertain mutation. No resumed process dispatches mutations.
        with self.db:
            self.db.execute(
                "UPDATE commands SET phase=?, protocol_id=COALESCE(?,protocol_id), robot_run_id=COALESCE(?,robot_run_id) WHERE id=? AND receipt IS NULL",
                (phase, protocol_id, robot_run_id, run_id),
            )

    def finish(self, run_id: str, receipt: dict):
        encoded = canonical(receipt).decode()
        old = self.db.execute("SELECT receipt FROM commands WHERE id=?", (run_id,)).fetchone()
        if old is None:
            raise ValueError("Receipt has no attempted command")
        if old["receipt"] is not None and old["receipt"] != encoded:
            raise ValueError("Terminal receipts are immutable")
        with self.db:
            self.db.execute(
                "UPDATE commands SET receipt=?,phase='terminal' WHERE id=?", (encoded, run_id)
            )

    def unfinished(self):
        return [
            dict(row) for row in self.db.execute("SELECT * FROM commands WHERE receipt IS NULL")
        ]

    def outbox(self):
        return [
            (row["id"], json.loads(row["receipt"]))
            for row in self.db.execute(
                "SELECT id,receipt FROM commands WHERE receipt IS NOT NULL AND sent=0"
            )
        ]

    def acknowledged(self, run_id):
        with self.db:
            self.db.execute(
                "UPDATE commands SET sent=1 WHERE id=? AND receipt IS NOT NULL", (run_id,)
            )

    def unresolved(self):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT c.* FROM commands c WHERE json_extract(receipt,'$.outcome')='unknown' AND NOT EXISTS (SELECT 1 FROM resolutions r WHERE r.command_id=c.id)"
            )
        ]

    def record_resolution(self, run_id: str, verified_audit: dict):
        """Append a validated authoritative audit; never rewrite the old command/receipt."""
        row = self.db.execute("SELECT receipt,sent FROM commands WHERE id=?", (run_id,)).fetchone()
        if (
            row is None
            or not row["sent"]
            or not row["receipt"]
            or json.loads(row["receipt"]).get("outcome") != "unknown"
        ):
            raise ValueError("Resolution requires an acknowledged unknown command")
        encoded = canonical(verified_audit).decode()
        old = self.db.execute(
            "SELECT evidence FROM resolutions WHERE command_id=?", (run_id,)
        ).fetchone()
        if old:
            if old["evidence"] != encoded:
                raise ValueError("Resolution evidence is append-only")
            return
        with self.db:
            self.db.execute(
                "INSERT INTO resolutions(command_id,evidence) VALUES(?,?)", (run_id, encoded)
            )
