"""Outbound-only worker. Run with a qualified, operator-installed gateway.

The local intent journal precedes every simulator mutation. Restart recovery
only reads original IDs. Cloud start permission alone never authorizes a replay.
"""

import argparse
import fcntl
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx

from .gateway import (
    GatewayUnavailable,
    MatterixGateway,
    RemoteOperationPending,
    RemoteOutcomeUnknown,
)
from .models import StrictModel
from .remote_run import (
    TERMINAL_SNAPSHOT_STATUSES,
    RemoteRunRequest,
    RemoteRunSnapshot,
    check_run_snapshot,
)
from .runs import TERMINAL

logger = logging.getLogger("academy.worker")


class Journal:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self.lock = open(str(path) + ".lock", "a+")
        os.chmod(str(path) + ".lock", 0o600)
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS active (id INTEGER PRIMARY KEY, body TEXT NOT NULL)"
        )

    def read(self):
        row = self.db.execute("SELECT body FROM active WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None

    def save(self, record):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO active VALUES (1,?)", (json.dumps(record),))

    def clear(self):
        with self.db:
            self.db.execute("DELETE FROM active WHERE id=1")

    def close(self):
        self.db.close()
        self.lock.close()


class WorkerClient:
    def __init__(self, url, token, transport=None):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Worker API must be an operator-configured HTTPS endpoint")
        self.http = httpx.Client(
            base_url=url.rstrip("/") + "/",
            headers={"Authorization": "Bearer " + token.strip()},
            timeout=10,
            follow_redirects=False,
            transport=transport,
        )

    def request(self, method, path, body=None):
        response = self.http.request(method, path, json=body)
        response.raise_for_status()
        return None if response.status_code == 204 else response.json()

    def post(self, run, action, **body):
        return self.request(
            "POST",
            f"internal/runs/{run['run_id']}/{action}",
            {"claim_token": run["claim_token"], **body},
        )


class ResetVerification(StrictModel):
    command_id: UUID
    native_session_id: UUID
    engine_version: str
    asset_version: str
    reset_verified: bool
    checks: dict[str, bool]


class GatewayRunner:
    """Protocol client; actual gateway server remains separately qualified.

    cleanup verification is a required native endpoint, not inferred from reset's
    HTTP status. No synthetic volume or reset result is produced by this client.
    """

    def __init__(self, gateway):
        self.gateway = gateway

    def require_actions(self, local):
        capabilities = self.gateway.capabilities()
        needed = {action["kind"] for action in local["run"]["plan"]["actions"]}
        if not needed <= set(capabilities.actions):
            raise GatewayUnavailable("Gateway does not support every saved workflow action")

    def prepare(self, local, recovering=False):
        self.require_actions(local)
        allocation_id = UUID(local["allocation_id"])
        if recovering:
            allocation = self.gateway.allocation(allocation_id)
            if allocation.status == "pending":
                raise RemoteOperationPending("Allocation is still pending")
            if allocation.status != "allocated" or allocation.session_id is None:
                raise GatewayUnavailable("Allocation intent cannot be safely recovered")
            native = self.gateway.snapshot(allocation.session_id)
        else:
            native = self.gateway.allocate(allocation_id)
        return {
            "native_session_id": str(native.id),
            "expected_revision": native.revision,
            "engine_version": native.engine_version,
            "asset_version": native.asset_version,
        }

    def request_for(self, local):
        run = local["run"]
        return RemoteRunRequest(
            run_id=run["run_id"],
            expected_revision=local["binding"]["expected_revision"],
            experiment=run["plan"],
            plan_hash=run["plan_hash"],
        )

    def start(self, local):
        self.require_actions(local)
        return self.gateway.start_run(
            UUID(local["binding"]["native_session_id"]), self.request_for(local)
        )

    def poll(self, local):
        previous = (
            RemoteRunSnapshot.model_validate(local["last_snapshot"])
            if local.get("last_snapshot")
            else None
        )
        return self.gateway.run_snapshot(
            UUID(local["binding"]["native_session_id"]), self.request_for(local), previous
        )

    def control(self, local, command, recovering=False):
        session_id = UUID(local["binding"]["native_session_id"])
        run_id = UUID(local["run"]["run_id"])
        path = f"v1/sessions/{session_id}/runs/{run_id}/controls/{UUID(command['command_id'])}"
        payload = (
            {
                "action": command["action"],
                "expected_revision": local["last_snapshot"]["session_revision"],
            }
            if not recovering
            else None
        )
        snapshot = self.gateway._exchange(
            "GET" if recovering else "POST", path, RemoteRunSnapshot, payload
        )
        check_run_snapshot(
            snapshot,
            session_id,
            self.request_for(local),
            RemoteRunSnapshot.model_validate(local["last_snapshot"]),
        )
        return snapshot

    def require_completed_operation(self, session_id, command_id, operation):
        if operation.status in {"accepted", "running"}:
            operation = self.gateway.operation(session_id, operation.operation_id)
        if operation.command_id != command_id:
            raise GatewayUnavailable("Native operation belongs to a different command")
        if operation.status in {"accepted", "running"}:
            raise RemoteOperationPending("Native operation is still pending")
        if operation.status != "completed":
            raise GatewayUnavailable("Native operation requires operator reconciliation")

    def cleanup(self, local, recovering=False):
        session_id = UUID(local["binding"]["native_session_id"])
        command_id = UUID(local["cleanup_id"])
        if recovering:
            operation = self.gateway.command_result(session_id, command_id)
        else:
            revision = local["last_snapshot"]["session_revision"]
            operation = self.gateway.reset(session_id, command_id, revision)
        self.require_completed_operation(session_id, command_id, operation)
        proof = self.gateway._exchange(
            "GET", f"v1/sessions/{session_id}/reset-verification/{command_id}", ResetVerification
        )
        if proof.command_id != command_id or proof.native_session_id != session_id:
            raise GatewayUnavailable("Reset proof identity mismatch")
        return proof.model_dump(mode="json")

    def release(self, local, recovering=False):
        session_id = UUID(local["binding"]["native_session_id"])
        command_id = UUID(local["release_id"])
        if recovering:
            operation = self.gateway.command_result(session_id, command_id)
        else:
            revision = self.gateway.snapshot(session_id).revision
            operation = self.gateway.release(session_id, command_id, revision)
        self.require_completed_operation(session_id, command_id, operation)


class Worker:
    def __init__(self, client, runner, journal, clock=time.time):
        self.client, self.runner, self.journal, self.clock = client, runner, journal, clock

    def valid_lease(self, run):
        if min(run["lease_expires"], run["deadline"]) <= self.clock() + 2:
            raise GatewayUnavailable("Lease cannot authorize another simulator operation")

    def step(self):
        local = self.journal.read()
        if not local:
            run = self.client.request("POST", "internal/runs/claim")
            if not run:
                return False  # Idle polling has a separate bounded backoff.
            if run["status"] != "claimed":
                # A journal lost after an execution cannot be reconstructed as
                # permission to start. Keep its runtime quarantined for recovery.
                self.client.post(
                    run,
                    "unknown",
                    reason="Local intent journal is missing; operator reconciliation required",
                )
                return
            local = dict(
                run=run, phase="claimed", start_id=str(uuid4()), allocation_id=str(uuid4())
            )
            self.journal.save(local)
        run = self.client.request("GET", f"internal/runs/{local['run']['run_id']}")
        local["run"] = run
        if (run.get("cleanup") or {}).get("reset_verified"):
            self.journal.clear()
            return
        if run["status"] == "outcome_unknown":
            return
        if (
            run["status"] in {"completed", "failed", "cancelled"}
            and run.get("snapshot")
            and local["phase"] in {"start_intent", "polling", "control_intent", "control_ack"}
        ):
            # The final cloud ACK can be lost. Recover its exact confirmed
            # snapshot and continue cleanup instead of polling a newer terminal
            # report that the immutable run correctly rejects.
            local.update(last_snapshot=run["snapshot"], phase="polling")
            self.journal.save(local)
        if run["status"] not in TERMINAL:
            run = self.client.post(run, "heartbeat")
            local["run"] = run
            self.valid_lease(run)
        if local["phase"] == "claimed":
            run = self.client.post(run, "start", command_id=local["start_id"])
            local.update(run=run, phase="granted")
            self.journal.save(local)
        try:
            if local["phase"] in {"granted", "allocation_intent"}:
                self.valid_lease(run)
                recovering = local["phase"] == "allocation_intent"
                local["phase"] = "allocation_intent"
                self.journal.save(local)
                binding = self.runner.prepare(local, recovering)
                if any(
                    binding[k] != run["runtime_manifest"][k]
                    for k in ("engine_version", "asset_version")
                ):
                    raise GatewayUnavailable("Installed runtime no longer matches qualification")
                local.update(binding=binding, phase="allocated")
                self.journal.save(local)
            if local["phase"] == "allocated":
                run = self.client.post(
                    run,
                    "binding",
                    native_session_id=local["binding"]["native_session_id"],
                    expected_revision=local["binding"]["expected_revision"],
                    engine_version=local["binding"]["engine_version"],
                    asset_version=local["binding"]["asset_version"],
                )
                local.update(run=run, phase="start_intent")
                self.journal.save(local)
                self.valid_lease(run)
                result = self.runner.start(local)
                local.update(phase="polling", last_snapshot=result.model_dump(mode="json"))
                self.journal.save(local)
            elif (
                local["phase"] in {"start_intent", "polling"}
                and run["status"] not in TERMINAL
                and local.get("last_snapshot", {}).get("status") not in TERMINAL_SNAPSHOT_STATUSES
            ):
                result = self.runner.poll(local)
                local.update(phase="polling", last_snapshot=result.model_dump(mode="json"))
                self.journal.save(local)
            if local["phase"] == "polling":
                run = self.client.post(run, "snapshots", snapshot=local["last_snapshot"])
                local["run"] = run
                if (
                    run.get("control")
                    and not run["control"]["acknowledged"]
                    and run["status"] not in TERMINAL
                ):
                    self.valid_lease(run)
                    local["control"] = run["control"]
                    local["phase"] = "control_intent"
                    self.journal.save(local)
                    result = self.runner.control(local, local["control"])
                    local.update(last_snapshot=result.model_dump(mode="json"), phase="control_ack")
                    self.journal.save(local)
            elif local["phase"] == "control_intent":
                # Lost command response: GET original command, never POST again.
                result = self.runner.control(local, local["control"], recovering=True)
                local.update(last_snapshot=result.model_dump(mode="json"), phase="control_ack")
                self.journal.save(local)
            if local["phase"] == "control_ack":
                run = self.client.post(
                    run,
                    "snapshots",
                    snapshot=local["last_snapshot"],
                    control_id=local["control"]["command_id"],
                )
                local.update(run=run, phase="polling")
                self.journal.save(local)
            if (
                run["status"] in {"completed", "failed", "cancelled"}
                and local["phase"] == "polling"
            ):
                local.update(phase="cleanup_intent", cleanup_id=str(uuid4()))
                self.journal.save(local)
                local["cleanup"] = self.runner.cleanup(local)
                local["phase"] = "reset_verified"
                self.journal.save(local)
            elif local["phase"] == "cleanup_intent":
                local["cleanup"] = self.runner.cleanup(local, recovering=True)
                local["phase"] = "reset_verified"
                self.journal.save(local)
            if local["phase"] == "reset_verified":
                proof = local["cleanup"]
                if (
                    not proof["reset_verified"]
                    or set(proof["checks"])
                    != {"objects", "liquids", "tips", "controllers", "stopped"}
                    or not all(proof["checks"].values())
                ):
                    raise GatewayUnavailable("Native reset verification failed")
                local.update(phase="release_intent", release_id=str(uuid4()))
                self.journal.save(local)
                self.runner.release(local)
                local["phase"] = "cleanup_ack"
                self.journal.save(local)
            elif local["phase"] == "release_intent":
                self.runner.release(local, recovering=True)
                local["phase"] = "cleanup_ack"
                self.journal.save(local)
            if local["phase"] == "cleanup_ack":
                result = self.client.post(run, "cleanup", **local["cleanup"])
                if result["cleanup"]["reset_verified"]:
                    self.journal.clear()
        except RemoteOperationPending:
            logger.info("Native operation is pending; preserving its intent for read-only polling")
        except RemoteOutcomeUnknown:
            logger.warning(
                "Native acknowledgement lost; next attempt only reads the original operation"
            )
        except (GatewayUnavailable, ValueError):
            # No native command is retried here. Cloud outages leave the intent
            # journal in place; a later step can only perform read-only recovery.
            self.client.post(
                run,
                "unknown",
                reason="Native operation or recovery could not be verified; operator reconciliation required",
            )
            logger.warning("Run quarantined; native outcome requires reconciliation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("ACADEMY_WORKER_API_URL"))
    parser.add_argument("--credential-file", default=os.getenv("ACADEMY_WORKER_CREDENTIAL_FILE"))
    parser.add_argument("--gateway-url", default=os.getenv("ACADEMY_GATEWAY_URL"))
    parser.add_argument(
        "--gateway-credential-file", default=os.getenv("ACADEMY_GATEWAY_CREDENTIAL_FILE")
    )
    parser.add_argument("--journal", default="/var/lib/matterix-worker/journal.sqlite")
    args = parser.parse_args()
    if not all(
        [args.api_url, args.credential_file, args.gateway_url, args.gateway_credential_file]
    ):
        parser.error("API URL, gateway URL and protected credential files are required")
    logging.basicConfig(level=logging.INFO)
    journal = Journal(args.journal)
    client = WorkerClient(args.api_url, Path(args.credential_file).read_text().strip())
    gateway = MatterixGateway(
        args.gateway_url, Path(args.gateway_credential_file).read_text().strip()
    )
    worker = Worker(client, GatewayRunner(gateway), journal)
    delay = 2
    try:
        while True:
            try:
                idle = worker.step() is False
                delay = min(delay * 2, 20) if idle else 2
            except (httpx.HTTPError, GatewayUnavailable):
                # Do not log headers, full URL, tokens, plans or learner records.
                logger.warning(
                    "Worker connection unavailable; preserving journal for read-only recovery"
                )
                delay = min(delay * 2, 20)
            time.sleep(delay)
    finally:
        gateway.close()
        client.http.close()
        journal.close()


if __name__ == "__main__":
    main()
