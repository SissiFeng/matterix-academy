"""Create a secret-free, deterministic local Academy image input. Never calls AWS."""

import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def external_output(root, output):
    output = output.resolve()
    roots = [root.resolve()]
    for line in git(root, "worktree", "list", "--porcelain").decode().splitlines():
        if line.startswith("worktree "):
            roots.append(Path(line[9:]).resolve())
    if any(output.is_relative_to(item) for item in roots):
        raise ValueError("Keep image inputs outside every Academy checkout")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    return output


def package(root, revision, output):
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Pin the full Academy commit")
    if git(root, "status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError("Commit and verify Academy before packaging a release")
    if git(root, "rev-parse", f"{revision}^{{commit}}").decode().strip() != revision:
        raise ValueError("Academy revision is not a commit")
    if git(root, "rev-parse", "HEAD").decode().strip() != revision:
        raise ValueError("Check out the exact reviewed Academy revision before packaging")
    output = external_output(root, output)
    sources_bytes = (output / "sources.json").read_bytes()
    sources = json.loads(sources_bytes)
    if set(sources) != {"engine", "assets"}:
        raise ValueError("Export exactly the two reviewed private sources before packaging")
    raw = git(root, "archive", "--format=tar", revision)
    # GzipFile fixes the OS header byte across Python 3.12/3.14; gzip.compress does not.
    compressed = io.BytesIO()
    with gzip.GzipFile(
        filename="", fileobj=compressed, mode="wb", compresslevel=9, mtime=0
    ) as zipped:
        zipped.write(raw)
    archive = compressed.getvalue()
    with tarfile.open(fileobj=io.BytesIO(raw)) as files:
        manifest = json.load(files.extractfile("ops/ec2-gpu/image-manifest.example.json"))
        hashes = {
            name: digest(files.extractfile(name).read())
            for name in (
                "uv.lock",
                "app/frontend/package-lock.json",
                "ops/ec2-gpu/runtime-linux-x86_64.lock",
                "ops/ec2-gpu/agent-requirements.lock",
            )
        }
    manifest["academy_commit"] = revision
    for name, key in (("engine", "engine_commit"), ("assets", "asset_commit")):
        if sources[name]["commit"] != manifest[key]:
            raise ValueError("Private source commit differs from the reviewed image profile")
        with (output / f"{name}.tar.gz").open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != sources[name]["sha256"]:
                raise ValueError("Private source archive differs from its export manifest")
    manifest["sources_manifest_sha256"] = digest(sources_bytes)
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode()
    release = {
        "schema_version": 1,
        "academy_commit": revision,
        "archive_sha256": digest(archive),
        "manifest_sha256": digest(manifest_bytes),
        "dependency_hashes": hashes,
        "status": "source-release-not-gpu-qualified",
    }
    for name, body in (
        ("academy.tar.gz", archive),
        ("image-manifest.json", manifest_bytes),
        ("release.json", (json.dumps(release, indent=2) + "\n").encode()),
    ):
        (output / name).write_bytes(body)
        (output / name).chmod(0o600)
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        release = package(ROOT, args.revision, args.output_dir)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"Release blocked: {exc}\n")
    print(json.dumps(release, indent=2))


if __name__ == "__main__":
    main()
