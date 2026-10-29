"""Guard the future paid Packer build with local inputs, explicit consent and pinned AWS identity."""

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# EC2 reports physical VRAM; installed-driver usable VRAM is checked separately.
BUILD_HARDWARE = {
    "g4dn.2xlarge": ("T4", 16384),
    "g5.2xlarge": ("A10G", 22000),
    "g6.2xlarge": ("L4", 22000),
    "g6.4xlarge": ("L4", 22000),
    "g6e.2xlarge": ("L40S", 22000),
}
BUILD_TYPES = set(BUILD_HARDWARE)


def validate_instance(instance):
    gpus = instance.get("GpuInfo", {}).get("Gpus", [])
    expected = BUILD_HARDWARE.get(instance.get("InstanceType"))
    if not (
        expected is not None
        and instance.get("VCpuInfo", {}).get("DefaultVCpus", 0) >= 8
        and instance.get("MemoryInfo", {}).get("SizeInMiB", 0) >= 32768
        and "x86_64" in instance.get("ProcessorInfo", {}).get("SupportedArchitectures", [])
        and len(gpus) == 1
        and gpus[0].get("Count") == 1
        and gpus[0].get("GpuPartitionSize", 1) == 1
        and gpus[0].get("Name") == expected[0]
        and gpus[0].get("MemoryInfo", {}).get("SizeInMiB", 0) >= expected[1]
    ):
        raise ValueError(
            "Build requires at least 8 vCPU, 32 GiB and the instance's full reviewed GPU: "
            "T4 with 16384 MiB, or A10G/L4/L40S with 22000 MiB"
        )


def capacity_preflight(session, env, config):
    """Read the selected account using the same frozen identity as the paid child."""
    region = config["region"]
    instance_type = config.get("build_instance_type", "g6.4xlarge")
    if instance_type not in BUILD_TYPES:
        raise ValueError("Unsupported GPU build instance type")
    credentials = {
        "region_name": region,
        "verify": True,
        "aws_access_key_id": env["AWS_ACCESS_KEY_ID"],
        "aws_secret_access_key": env["AWS_SECRET_ACCESS_KEY"],
        "aws_session_token": env["AWS_SESSION_TOKEN"],
    }
    ec2 = session.client("ec2", endpoint_url=f"https://ec2.{region}.amazonaws.com", **credentials)
    instance = ec2.describe_instance_types(InstanceTypes=[instance_type])["InstanceTypes"][0]
    validate_instance(instance)
    if instance["InstanceType"] != instance_type:
        raise ValueError("EC2 capacity response differs from the selected instance type")
    quotas = session.client(
        "service-quotas",
        endpoint_url=f"https://servicequotas.{region}.amazonaws.com",
        **credentials,
    )
    quota = quotas.get_service_quota(ServiceCode="ec2", QuotaCode="L-DB2E81BA")["Quota"]["Value"]
    if quota < instance["VCpuInfo"]["DefaultVCpus"]:
        raise ValueError("Applied G/VT On-Demand quota is insufficient for the selected build")
    pages = ec2.get_paginator("describe_instances").paginate(
        Filters=[
            {"Name": "instance-type", "Values": ["g*", "vt*"]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping"]},
        ]
    )
    if any(reservation["Instances"] for page in pages for reservation in page["Reservations"]):
        raise ValueError("An active G/VT instance exists; keep GPU build and acceptance sequential")
    return {
        "instance_type": instance_type,
        "applied_g_vcpu_quota": quota,
        "vcpus": instance["VCpuInfo"]["DefaultVCpus"],
        "physical_memory_mib": instance["MemoryInfo"]["SizeInMiB"],
        "gpu": instance["GpuInfo"]["Gpus"][0],
    }


def run_build(command, env, timeout_seconds, expires=None):
    # Packer receives SIGINT first so it can remove its own temporary AWS resources.
    # This limits the local operation, not AWS billing: reconcile resources after failure.
    if not 60 <= timeout_seconds <= 9000:
        raise ValueError("Build timeout must be 60–9000 seconds (default 7200)")
    # Preflight retries may consume the margin. Recheck the expiration captured with
    # this exact frozen token immediately before starting the paid child process.
    credential_lifetime(expires, env.get("AWS_SESSION_TOKEN"), timeout_seconds)
    process = subprocess.Popen(command, env=env, start_new_session=True)

    def interrupt(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass  # Packer can finish between wait's timeout and cleanup signalling.

    try:
        returncode = process.wait(timeout=timeout_seconds)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        interrupt(signal.SIGINT)
        try:
            process.wait(timeout=300)
        except subprocess.TimeoutExpired:
            interrupt(signal.SIGTERM)
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                interrupt(signal.SIGKILL)
                process.wait()
        raise RuntimeError(
            "Build interrupted; inspect the log and reconcile temporary AWS resources"
        ) from exc
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)


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


def credential_lifetime(expires, session_token, timeout_seconds, now=None):
    if expires is None:
        if session_token:
            raise ValueError(
                "Temporary AWS credentials need a known expiration before a paid build"
            )
        return  # Static credentials without a session token do not have an STS expiration.
    if expires.tzinfo is None:
        raise ValueError("AWS credential expiration must include its timezone")
    remaining = (expires - (now or datetime.now(UTC))).total_seconds()
    if remaining < timeout_seconds + 300 + 60 + 120:
        raise ValueError(
            "Refresh AWS credentials: lifetime must cover build timeout, cleanup and clock margin"
        )


def verified_environment(session, expected_account, region, timeout_seconds=7200):
    provider = session.get_credentials()
    credentials = (
        provider.get_frozen_credentials()
    )  # Refresh first, then inspect this token's expiry.
    expires = getattr(provider, "_expiry_time", None)
    credential_lifetime(expires, credentials.token, timeout_seconds)
    identity = session.client(
        "sts",
        region_name=region,
        endpoint_url=f"https://sts.{region}.amazonaws.com",
        verify=True,
        aws_access_key_id=credentials.access_key,
        aws_secret_access_key=credentials.secret_key,
        aws_session_token=credentials.token,
    ).get_caller_identity()
    return build_environment(identity, credentials, expected_account, region), expires


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "build"])
    parser.add_argument(
        "--config", type=Path, required=True, help="Protected JSON Packer variables"
    )
    parser.add_argument("--packer", default="packer")
    parser.add_argument("--confirm-paid-build", action="store_true")
    parser.add_argument("--accept-nvidia-eula", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    # Bind even the default into -var-file so PKR_VAR_* cannot change the checked type.
    config.setdefault("build_instance_type", "g6.4xlarge")
    if config["build_instance_type"] not in BUILD_TYPES:
        parser.error("Unsupported GPU build instance type")
    if not 60 <= args.timeout_seconds <= 9000:
        parser.error("Build timeout must be 60–9000 seconds")
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
    if config.get("region") not in {"ca-central-1", "us-east-1", "us-east-2"}:
        parser.error("Build only in the reviewed pilot regions")
    import boto3

    session = boto3.Session(region_name=config["region"])
    env, expires = verified_environment(
        session, config["expected_account_id"], config["region"], args.timeout_seconds
    )
    capacity = capacity_preflight(session, env, config)
    print(
        json.dumps({"capacity_preflight": capacity, "build_timeout_seconds": args.timeout_seconds}),
        flush=True,
    )
    # The temporary variables contain no credentials. Credentials stay in the child environment.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pkrvars.json") as file:
        json.dump(config, file)
        file.flush()
        command = [args.packer, "build", "-var-file=" + file.name, str(ROOT / "ops/ec2-gpu/image")]
        run_build(command, env, args.timeout_seconds, expires)


if __name__ == "__main__":
    main()
