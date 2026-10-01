"""Package committed agent code with an enrolled worker credential for private delivery.

Writes the presigned URL only into a protected operator handoff file, never stdout.
The bootstrap bucket must be private, independent of the learner website bucket.
"""

import argparse
import hashlib
import io
import os
import pathlib
import shlex
import subprocess
import tarfile
import tempfile

import boto3
from academy.worker_admin import operator_identity, read_credential


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    session = boto3.Session(region_name="ca-central-1")
    operator_identity(session.client("sts").get_caller_identity(), args.expected_account_id)
    expected_bucket = f"matterix-academy-dev-{args.expected_account_id}-bootstrap"
    if args.bucket != expected_bucket:
        parser.error("Only the separate private development bootstrap bucket is supported")
    s3 = session.client("s3")
    if not all(
        s3.get_public_access_block(Bucket=args.bucket)["PublicAccessBlockConfiguration"].values()
    ):
        parser.error("Bootstrap bucket public access must be fully blocked")
    credential = read_credential(args.credential_file, args.worker_id)
    source = pathlib.Path(__file__).resolve().parent.parent
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=source).returncode:
        parser.error("Commit and verify the agent before packaging it")
    output = pathlib.Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = subprocess.check_output(
        [
            "git",
            "archive",
            revision,
            "app/backend/academy",
            "scripts/install-native.sh",
            "pyproject.toml",
            "uv.lock",
        ],
        cwd=source,
    )
    bundle = output / f"lab-onboarding-{revision[:12]}.tar.gz"
    with (
        tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as committed,
        tarfile.open(bundle, "w:gz") as target,
    ):
        for member in committed.getmembers():
            target.addfile(member, committed.extractfile(member) if member.isfile() else None)
        body = (credential + "\n").encode()
        member = tarfile.TarInfo("worker-credential")
        member.size, member.mode = len(body), 0o600
        target.addfile(member, io.BytesIO(body))
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    key = f"enrollment/{args.worker_id}/{digest}.tar.gz"
    s3.upload_file(
        str(bundle),
        args.bucket,
        key,
        ExtraArgs={
            "ServerSideEncryption": "AES256",
            "ContentType": "application/gzip",
            "CacheControl": "no-store",
        },
    )
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": args.bucket, "Key": key}, ExpiresIn=3600
    )
    # Verify the uploaded bytes privately; no token or URL enters diagnostics.
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as response:
        if hashlib.sha256(response.read()).hexdigest() != digest:
            raise RuntimeError("Uploaded installer checksum differs")
    command = "\n".join(
        [
            "bash <<'LAB_ONBOARDING_INSTALL'",
            "set -euo pipefail",
            "umask 077",
            'release_base="${XDG_DATA_HOME:-$HOME/.local/share}/lab-onboarding/releases"',
            'mkdir -p "$release_base"',
            f'release_dir="$(mktemp -d "$release_base/{revision[:12]}.XXXXXX")"',
            f'curl --fail --silent --show-error --location {shlex.quote(url)} --output "$release_dir/agent.tar.gz"',
            f"printf '%s  %s\\n' '{digest}' \"$release_dir/agent.tar.gz\" | sha256sum --check --status",
            'tar -xzf "$release_dir/agent.tar.gz" -C "$release_dir"',
            'bash "$release_dir/scripts/install-native.sh"',
            'rm "$release_dir/agent.tar.gz"',
            "LAB_ONBOARDING_INSTALL",
            "",
        ]
    )
    # Atomic private publication also prevents a partially written handoff.
    with tempfile.NamedTemporaryFile(mode="w", dir=output, delete=False) as file:
        file.write(command)
    handoff = output / "ubuntu-install-command.sh"
    os.replace(file.name, handoff)
    print(f"Private installer uploaded and checksum verified for commit {revision}.")
    print(f"Protected pasteable command: {handoff}")
    print("Download authorization lasts at most one hour, bounded by the operator session expiry.")


if __name__ == "__main__":
    main()
