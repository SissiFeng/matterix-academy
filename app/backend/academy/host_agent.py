"""Outbound installer agent: report environment, await operator-reviewed config.

No arbitrary remote command execution. Configuration selects only the fixed
NativeFlexRunner; cloud data cannot supply shell commands or Python source.
"""

import argparse
import json
import logging
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .native_files import write_json
from .native_runner import NativeConfig, NativeFlexRunner
from .worker import Journal, Worker, WorkerClient

PROBE = """
import importlib.util, importlib.metadata, json, sys
result = {"python": sys.executable, "version": sys.version.split()[0], "packages": {}}
for name in ("isaaclab", "isaacsim", "matterix", "matterix_assets"):
    try:
        spec = importlib.util.find_spec(name)
        result["packages"][name] = spec.origin if spec else None
    except Exception:
        result["packages"][name] = None
print(json.dumps(result))
"""


def environment_report(isaac_python):
    home = Path.home()
    pythons = [Path(isaac_python)]
    for base in (home / ".conda/envs", home / "miniconda3/envs", home / "anaconda3/envs"):
        pythons += sorted(base.glob("*/bin/python"))[:12]
    environments = []
    for python in dict.fromkeys(pythons):
        try:
            result = subprocess.run(
                [str(python), "-c", PROBE], capture_output=True, text=True, timeout=20, check=True
            )
            environments.append(json.loads(result.stdout.strip().splitlines()[-1]))
        except (OSError, ValueError, subprocess.SubprocessError):
            environments.append({"python": str(python), "error": "Environment probe unavailable"})
    roots = [home / "IsaacLab/Matterix/Matterix"]
    roots += sorted(home.glob("[Mm]atterix*"))[:25]
    repositories = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in (root, root / "assets"):
            if not path.is_dir():
                continue
            result = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--show-toplevel", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            repositories.append(
                {
                    "path": str(path),
                    "git": result.stdout.strip()
                    if result.returncode == 0
                    else "Not a trusted readable Git checkout",
                }
            )
    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        gpu = "Unavailable"
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "hostname": os.uname().nodename,
        "display": os.getenv("DISPLAY"),
        "environments": environments,
        "repositories": repositories,
        "gpu": gpu,
    }


def configured_runner(folder, client, journal, settings, runner):
    path = folder / "native-config.json"
    if journal.read():
        # A restart recovers the original binding; an operator's newer config
        # cannot redirect an active journal to a different process directory.
        if runner is not None:
            return runner
        if not path.is_file():
            raise RuntimeError("Active journal has no saved native configuration")
        return NativeFlexRunner(path, client)
    config = NativeConfig.model_validate(settings["configuration"])
    if runner is not None and runner.config == config:
        return runner
    config.verify()
    write_json(path, config.model_dump())
    return NativeFlexRunner(path, client)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--isaac-python", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    folder = Path(args.state_dir)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    client = WorkerClient(args.api_url, Path(args.credential_file).read_text())
    report = environment_report(args.isaac_python)
    write_json(folder / "environment.json", report)
    journal = Journal(folder / "journal.sqlite")
    published = False
    runner = None
    try:
        while True:
            try:
                if not published:
                    client.request("POST", "internal/workers/probe", report)
                    published = True
                    logging.info(
                        "Environment report uploaded; waiting for native configuration and qualification"
                    )
                settings = client.request("GET", "internal/workers/configuration")
                if (
                    not settings["qualified"]
                    or not settings["enabled"]
                    or not settings["configuration"]
                ):
                    time.sleep(15)
                    continue
                runner = configured_runner(folder, client, journal, settings, runner)
                Worker(client, runner, journal).step()
                time.sleep(2)
            except (httpx.HTTPError, OSError, ValueError, RuntimeError):
                logging.warning(
                    "Agent awaiting a reachable API or verified configuration; no native command retried"
                )
                time.sleep(10)
    finally:
        journal.close()
        client.http.close()


if __name__ == "__main__":
    main()
