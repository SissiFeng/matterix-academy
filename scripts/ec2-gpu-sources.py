"""Export independent clean private checkouts to a protected external image input directory.

No cloud calls, runtime download, mutation of source repos or credential export.
"""

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app/backend"))
from academy.runtime_inventory import PROFILE, source_inventory  # noqa: E402

spec = importlib.util.spec_from_file_location("release_inputs", ROOT / "scripts/ec2-gpu-release.py")
release_inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_inputs)


def snapshot(source, revision, target):
    """Shallow Git history plus materialized tracked files; excludes local config/hooks/secrets."""
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"}
    with tempfile.TemporaryDirectory() as temp:
        checkout = Path(temp) / "checkout"
        checkout.mkdir()

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(checkout), *args], env=env, stderr=subprocess.DEVNULL
            )

        git("init", "--quiet")
        git("lfs", "install", "--local", "--skip-smudge", "--skip-repo")
        git("-c", "core.hooksPath=/dev/null", "fetch", "--depth=1", str(source), revision)
        git("-c", "core.hooksPath=/dev/null", "checkout", "--detach", "FETCH_HEAD")
        for record in git("ls-files", "--stage", "-z").split(b"\0"):
            if not record:
                continue
            header, raw = record.split(b"\t", 1)
            mode = header.split()[0]
            relative = Path(os.fsdecode(raw))
            original = source / relative
            if relative.as_posix() == "source/matterix_assets/data":
                if git("ls-files", "--stage", "--", str(relative)).startswith(b"160000 "):
                    # The adapter explicitly binds the separately pinned internal asset checkout.
                    continue
            if original.is_symlink() or not original.is_file():
                raise ValueError("Image exports require ordinary tracked files")
            destination = checkout / relative
            shutil.copy2(original, destination)
            destination.chmod(0o755 if mode == b"100755" else 0o644)
        git("add", "--renormalize", ".")
        if (
            git("diff", "--cached", "--name-only", "HEAD").strip()
            or git("status", "--porcelain").strip()
        ):
            raise ValueError(
                "Materialized source export differs from its Git pin: "
                + git("status", "--porcelain").decode()
            )
        # No fetch origin or credential helper survives in the image source archive.
        (checkout / ".git/config").write_text(
            '[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tlogallrefupdates = false\n\thooksPath = /dev/null\n[filter "lfs"]\n\tclean = git-lfs clean -- %f\n\tsmudge = git-lfs smudge --skip -- %f\n\tprocess = git-lfs filter-process --skip\n\trequired = true\n'
        )
        shutil.rmtree(checkout / ".git/hooks", ignore_errors=True)
        for name in ("FETCH_HEAD", "logs"):
            item = checkout / ".git" / name
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink(missing_ok=True)
        with target.open("wb") as file, gzip.GzipFile(fileobj=file, mode="wb", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|") as archive:
                archive.add(checkout, arcname=".")
    target.chmod(0o600)
    sha = hashlib.sha256()
    with target.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", required=True, type=Path)
    parser.add_argument("--assets-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    engine, assets = args.engine_root.resolve(), args.assets_root.resolve()
    report = source_inventory(engine, assets)
    if not all(report["checks"].values()):
        parser.error("Clean internal source pins and materialized assets are required")
    output = args.output_dir.resolve()
    if any(output.is_relative_to(root) for root in (engine, assets)):
        parser.error("Never export into a source checkout")
    output = release_inputs.external_output(ROOT, output)
    record = {}
    for name, source, revision in (
        ("engine", engine, PROFILE["engine_commit"]),
        ("assets", assets, PROFILE["asset_commit"]),
    ):
        record[name] = {
            "commit": revision,
            "sha256": snapshot(source, revision, output / f"{name}.tar.gz"),
        }
    (output / "sources.json").write_text(json.dumps(record, indent=2) + "\n")
    (output / "sources.json").chmod(0o600)
    print("Private source archives written outside Academy. No credentials or runtime were copied.")


if __name__ == "__main__":
    main()
