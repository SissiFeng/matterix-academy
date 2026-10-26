"""Vendor the shared labtwin contracts from the connector repository.

The canonical package is ``packages/labtwin`` in the OT-2/Flex connector
repository. Lambda packaging cannot reach another repository, so a byte copy is
kept here and pinned by ``app/backend/labtwin/CONTRACT.sha256``. Never edit the
vendored files directly; change the canonical package and re-run:

    uv run python scripts/sync-labtwin.py --source ../opentrons-ot2-digital-twin-connector/packages/labtwin
"""

import argparse
import hashlib
import shutil
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "app/backend/labtwin"


def digest(directory: Path) -> str:
    h = hashlib.sha256()
    for file in sorted(directory.glob("*.py")):
        h.update(file.name.encode() + b"\0" + file.read_bytes() + b"\0")
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="Path to packages/labtwin")
    parser.add_argument("--check", action="store_true", help="Only verify the pinned digest")
    args = parser.parse_args()
    source = Path(args.source).resolve() / "src/labtwin"
    if not args.check:
        for old in TARGET.glob("*.py"):
            old.unlink()
        for file in sorted(source.glob("*.py")):
            shutil.copy2(file, TARGET / file.name)
        (TARGET / "CONTRACT.sha256").write_text(digest(TARGET) + "\n")
    if digest(source) != digest(TARGET):
        raise SystemExit("Vendored labtwin differs from the canonical source")
    print(f"labtwin {digest(TARGET)}")


if __name__ == "__main__":
    main()
