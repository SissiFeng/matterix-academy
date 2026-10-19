"""Guard the future paid Packer build with local inputs, explicit consent and pinned AWS identity."""

import argparse
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_environment(identity, credentials, expected_account, region):
    if identity.get("Account") != expected_account:
        raise ValueError("AWS caller account differs from the approved build account")
    # Freeze the exact verified credentials for Packer rather than re-resolving profiles.
    env = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
    env.update(
        AWS_ACCESS_KEY_ID=credentials.access_key,
        AWS_SECRET_ACCESS_KEY=credentials.secret_key,
        AWS_SESSION_TOKEN=credentials.token or "",
        AWS_REGION=region,
        AWS_DEFAULT_REGION=region,
        AWS_EC2_METADATA_DISABLED="true",
    )
    return env


def verified_environment(session, expected_account, region):
    credentials = session.get_credentials().get_frozen_credentials()
    identity = session.client(
        "sts",
        region_name=region,
        endpoint_url=f"https://sts.{region}.amazonaws.com",
        verify=True,
        aws_access_key_id=credentials.access_key,
        aws_secret_access_key=credentials.secret_key,
        aws_session_token=credentials.token,
    ).get_caller_identity()
    return build_environment(identity, credentials, expected_account, region)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "build"])
    parser.add_argument(
        "--config", type=Path, required=True, help="Protected JSON Packer variables"
    )
    parser.add_argument("--packer", default="packer")
    parser.add_argument("--confirm-paid-build", action="store_true")
    parser.add_argument("--accept-nvidia-eula", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    spec = importlib.util.spec_from_file_location(
        "image_inputs", ROOT / "scripts/ec2-gpu-inputs.py"
    )
    inputs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inputs)
    report = inputs.validate(Path(config["input_dir"]).resolve())
    for key, report_key in (
        ("release_sha256", "archive_sha256"),
        ("manifest_sha256", "manifest_sha256"),
    ):
        if config.get(key) != report[report_key]:
            parser.error("Build config must match the reviewed input " + key)
    if args.action == "check":
        print(json.dumps(report, indent=2))
        return
    if not args.confirm_paid_build or not args.accept_nvidia_eula:
        parser.error("Paid build and NVIDIA license acceptance must both be explicitly authorized")
    if config.get("confirm_paid_build") is not True or config.get("accept_nvidia_eula") is not True:
        parser.error("Protected build config must also explicitly enable both opt-ins")
    if config.get("region") not in {"ca-central-1", "us-east-1"}:
        parser.error("Build only in the reviewed pilot regions")
    import boto3

    session = boto3.Session(region_name=config["region"])
    env = verified_environment(session, config["expected_account_id"], config["region"])
    # The temporary variables contain no credentials. Credentials stay in the child environment.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pkrvars.json") as file:
        json.dump(config, file)
        file.flush()
        command = [args.packer, "build", "-var-file=" + file.name, str(ROOT / "ops/ec2-gpu/image")]
        subprocess.run(command, env=env, check=True)


if __name__ == "__main__":
    main()
