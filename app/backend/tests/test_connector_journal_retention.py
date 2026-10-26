"""Keeping historical receipts must not eventually prevent process restart."""

import pytest
from academy.companion.config import private_directory
from academy.companion.installer import InstallJournal
from academy.companion.journal import Journal


@pytest.mark.parametrize("factory", [Journal, InstallJournal])
def test_large_durable_history_reopens_without_loading_database_as_secret(tmp_path, factory):
    state = private_directory(tmp_path / "state")
    journal = factory(state)
    journal.db.execute("CREATE TABLE retained_history(payload BLOB)")
    journal.db.execute("INSERT INTO retained_history VALUES (zeroblob(4100000))")
    journal.db.commit()
    journal.close()
    reopened = factory(state)
    try:
        assert (
            reopened.db.execute("SELECT length(payload) FROM retained_history").fetchone()[0]
            == 4100000
        )
    finally:
        reopened.close()
