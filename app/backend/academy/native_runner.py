"""Pinned local process adapter for explicitly supported native Flex scenes."""

import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

from pydantic import Field

from .gateway import GatewayUnavailable, RemoteOperationPending
from .models import StrictModel
from .native_files import read_json, write_json
from .recipes import MixingPlan, parse_plan
from .remote_run import RemoteRunSnapshot, check_run_snapshot, workflow_digest
from .runtime_inventory import source_tree_clean
from .worker import GatewayRunner


class NativeConfig(StrictModel):
    python: str
    matterix_root: str
    assets_root: str
    assets_data_dir: str
    engine_version: str = Field(pattern=r"^[a-f0-9]{40}$")
    asset_version: str = Field(pattern=r"^[a-f0-9]{40}$")
    run_root: str = "/var/lib/matterix-worker/runs"
    frame_root: str = "/dev/shm/lab-onboarding"
    headless: bool = True
    display: str = ":0"

    def verify(self):
        for name in (
            "python",
            "matterix_root",
            "assets_root",
            "assets_data_dir",
            "run_root",
            "frame_root",
        ):
            if not Path(getattr(self, name)).is_absolute():
                raise ValueError("Native configuration paths must be absolute")
        for name, revision in (
            ("matterix_root", self.engine_version),
            ("assets_root", self.asset_version),
        ):
            root = getattr(self, name)
            if not source_tree_clean(root, revision):
                raise GatewayUnavailable(
                    "Prepared native checkout differs from its pinned qualification"
                )
        if not Path(self.python).is_file() or not Path(self.assets_data_dir).is_dir():
            raise GatewayUnavailable("Prepared Python or USD assets are missing")
        assets = Path(self.assets_root).resolve()
        data = Path(self.assets_data_dir).resolve()
        if not data.is_relative_to(assets):
            raise GatewayUnavailable("USD data must belong to the pinned assets checkout")
        tracked = {
            assets / name
            for name in subprocess.check_output(
                ["git", "ls-files", "-z"], cwd=assets, text=True
            ).split("\0")
            if name
        }
        for path in data.rglob("*"):
            if ".git" in path.relative_to(assets).parts:
                continue
            if path.is_file() and path not in tracked:
                raise GatewayUnavailable("USD data contains files outside the pinned Git revision")
            if path.is_symlink() and not path.resolve().is_relative_to(assets):
                raise GatewayUnavailable("USD assets cannot link outside the pinned checkout")


class NativeFlexRunner(GatewayRunner):
    def __init__(self, config, client):
        self.config = NativeConfig.model_validate_json(Path(config).read_text())
        self.client = client

    def folder(self, local):
        return Path(self.config.run_root) / str(UUID(local["run"]["run_id"]))

    def prepare(self, local, recovering=False):
        self.validate_plan(local)
        folder = self.folder(local)
        binding = {
            "native_session_id": str(UUID(local["allocation_id"])),
            "expected_revision": 1,
            "engine_version": self.config.engine_version,
            "asset_version": self.config.asset_version,
        }
        path = folder / "binding.json"
        if recovering:
            if not path.exists() or read_json(path) != binding:
                raise GatewayUnavailable(
                    "Allocation intent cannot be recovered without native identity"
                )
            return binding
        self.config.verify()
        folder.mkdir(parents=True, mode=0o700, exist_ok=False)
        write_json(path, binding)
        return binding

    def validate_plan(self, local):
        plan = parse_plan(local["run"]["plan"])
        if workflow_digest(plan) != local["run"]["plan_hash"]:
            raise GatewayUnavailable("Native allocation plan differs from its saved workflow hash")
        if plan.course_id == "workflow-sandbox":
            from .native_studio_runtime import compile_plan, validate_assets

            try:
                compile_plan(plan)
                validate_assets(plan, self.config)
            except ValueError as exc:
                raise GatewayUnavailable(str(exc)) from exc
        else:
            MixingPlan.model_validate(local["run"]["plan"])

    def renew(self, local):
        if not local.get("binding"):
            return
        run = local["run"]
        lease = self.client.post(run, "viewers")
        write_json(self.folder(local) / "lease.json", lease)

    def provision(self, local):
        folder = self.folder(local)
        self.renew(local)
        grant = self.client.post(local["run"], "publisher")
        write_json(folder / "publisher.json", grant)
        manifest = {
            "config": self.config.model_dump(),
            "binding": local["binding"],
            "request": self.request_for(local).model_dump(mode="json"),
        }
        write_json(folder / "manifest.json", manifest)

    def start(self, local):
        self.config.verify()
        self.validate_plan(local)
        folder = self.folder(local)
        # Never replay a launch whose response was lost; Worker polls this ID.
        fd = os.open(folder / "launch-intent", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with open(folder / "supervisor.log", "ab", buffering=0) as log:
            subprocess.Popen(
                [sys.executable, "-m", "academy.native_supervisor", "--folder", str(folder)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        raise RemoteOperationPending("Isaac is starting")

    def poll(self, local):
        folder = self.folder(local)
        if not (folder / "launch-intent").exists():
            raise GatewayUnavailable("Native launch intent has no durable local receipt")
        if (folder / "fault.json").exists():
            raise GatewayUnavailable("Native supervisor stopped; inspect the bound run artifacts")
        path = folder / "snapshot.json"
        if not path.exists():
            raise RemoteOperationPending("Waiting for the first native report")
        snapshot = RemoteRunSnapshot.model_validate(read_json(path))
        previous = (
            RemoteRunSnapshot.model_validate(local["last_snapshot"])
            if local.get("last_snapshot")
            else None
        )
        check_run_snapshot(
            snapshot, UUID(local["binding"]["native_session_id"]), self.request_for(local), previous
        )
        return snapshot

    def control(self, local, command, recovering=False):
        raise GatewayUnavailable("Controls are not qualified for this native recipe")

    def cleanup(self, local, recovering=False):
        folder = self.folder(local)
        if not recovering:
            write_json(folder / "cleanup-request.json", {"command_id": local["cleanup_id"]})
        elif not (folder / "cleanup-request.json").exists():
            raise GatewayUnavailable("Cleanup intent did not reach the native process")
        if (folder / "fault.json").exists():
            raise GatewayUnavailable("Native cleanup requires operator reconciliation")
        if not (folder / "released.json").exists():
            raise RemoteOperationPending("Waiting for native reset and process exit")
        receipt = read_json(folder / "released.json")
        if (
            receipt["command_id"] != local["cleanup_id"]
            or receipt["native_session_id"] != local["binding"]["native_session_id"]
        ):
            raise GatewayUnavailable("Native cleanup identity mismatch")
        return receipt

    def release(self, local, recovering=False):
        receipt = self.cleanup(local, recovering=True)
        if not receipt["checks"]["stopped"]:
            raise GatewayUnavailable("Native runtime has not stopped")
        path = self.folder(local) / "release-command.json"
        expected = {
            "command_id": local["release_id"],
            "native_session_id": receipt["native_session_id"],
        }
        if recovering:
            if not path.exists() or read_json(path) != expected:
                raise GatewayUnavailable("Release acknowledgement requires reconciliation")
        else:
            write_json(path, expected)


def main():
    import argparse
    import logging

    import httpx

    from .worker import Journal, Worker, WorkerClient

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--journal", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    journal = Journal(args.journal)
    client = WorkerClient(args.api_url, Path(args.credential_file).read_text())
    worker = Worker(client, NativeFlexRunner(args.config, client), journal)
    try:
        while True:
            try:
                idle = worker.step() is False
                delay = 10 if idle else 2
            except (httpx.HTTPError, GatewayUnavailable, OSError):
                logging.warning(
                    "Worker unavailable; preserving native intent and allowing its lease to expire"
                )
                delay = 5
            time.sleep(delay)
    finally:
        journal.close()
        client.http.close()


if __name__ == "__main__":
    main()
