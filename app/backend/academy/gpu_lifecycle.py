"""One pinned GPU, durable demand and serialized power transitions.

This is power management, never native qualification or workflow authority.
Authenticated capacity requests and validated runs can create demand. EC2 state is reconciled before
every retry; neither native runs nor unknown SSM commands are replayed.
"""

import os
import time
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .store import Conflict, Write

PARTITION = "system#gpu"
KEY = "host"
IDLE_SECONDS = 3600
FRESH_SECONDS = 45
STARTUP_SECONDS = 600
# Exceeds both callers' hard Lambda lifetimes (API 15s, reaper 30s), including
# DynamoDB response delays after its conditional transaction has committed.
OPERATION_SECONDS = 90
MESSAGES = {
    "sleeping": "The digital twin is asleep. Request a GPU to connect.",
    "starting": "Starting the GPU for digital twin access.",
    "preparing": "GPU started. Preparing the Isaac worker.",
    "ready": "Digital twin worker connected. Queued workflows run in order.",
    "busy": "The digital twin is running or verifying cleanup. Your workflow stays queued.",
    "capacity_wait": "AWS GPU capacity is unavailable. Your request is retained; retrying shortly.",
    "stopping": "The digital twin is shutting down. New workflows wait for it to restart.",
    "error": "The digital twin needs operator attention. Your workflow has not been replayed.",
}


def configured(store, clock=time.time):
    instance = os.getenv("ACADEMY_GPU_INSTANCE_ID", "")
    worker = os.getenv("ACADEMY_GPU_WORKER_ID", "")
    document = os.getenv("ACADEMY_GPU_START_DOCUMENT", "")
    if not all((instance, worker, document)):
        return None
    return GpuLifecycle(
        store,
        instance,
        worker,
        document,
        region=os.getenv("ACADEMY_GPU_REGION") or None,
        clock=clock,
    )


class GpuLifecycle:
    def __init__(
        self, store, instance, worker, document, *, region=None, ec2=None, ssm=None, clock=time.time
    ):
        self.store, self.instance, self.worker, self.document = store, instance, worker, document
        self.clock, self._ec2, self._ssm = clock, ec2, ssm
        self.region = region

    def client(self, name):
        attr = "_" + name
        if getattr(self, attr) is None:
            setattr(
                self,
                attr,
                boto3.client(
                    name,
                    region_name=self.region,
                    config=Config(
                        connect_timeout=2, read_timeout=4, retries={"total_max_attempts": 1}
                    ),
                ),
            )
        return getattr(self, attr)

    def record(self):
        return self.store.get(PARTITION, KEY)

    def demand_write(self):
        old = self.record()
        now = self.clock()
        record = {
            **(old or {}),
            "version": (old or {}).get("version", 0) + 1,
            "desired_until": now + IDLE_SECONDS,
            "requested_at": now,
        }
        return Write(PARTITION, KEY, record, old["version"] if old else None)

    def status(self):
        record = self.record() or {}
        state = record.get("state", "sleeping")
        return {
            "state": state,
            "message": MESSAGES.get(state, MESSAGES["error"]),
            "idle_seconds": IDLE_SECONDS,
            "retry_at": record.get("retry_at"),
            "updated_at": record.get("updated_at"),
        }

    def claim_writes(self):
        old = self.record()
        if old and (
            old.get("operation_until", 0) > self.clock()
            or old.get("stop_requested")
            or old.get("state") in {"stopping", "sleeping", "capacity_wait", "error"}
        ):
            return None
        if old:
            return [
                Write(
                    PARTITION,
                    KEY,
                    {
                        **old,
                        "version": old["version"] + 1,
                        "desired_until": self.clock() + IDLE_SECONDS,
                    },
                    old["version"],
                )
            ]
        return []

    def reconcile(self):
        old = self.record()
        if not old or old.get("operation_until", 0) > self.clock():
            return self.status()
        worker = self.store.get("system#workers", self.worker)
        now = self.clock()
        queued = self.store.partition("system#queue", limit=1)
        # A busy/unknown run retains this guard even after its lease expires.
        busy = bool(worker and worker.get("active_run"))
        if busy:
            desired = max(old.get("desired_until", 0), now + IDLE_SECONDS)
        else:
            desired = old.get("desired_until", 0)
        if worker and worker.get("last_cleanup_at"):
            desired = max(desired, worker["last_cleanup_at"] + IDLE_SECONDS)
        if old.get("retry_at", 0) > now:
            return self.status()
        token = str(uuid4())
        record = {
            **old,
            "version": old["version"] + 1,
            "operation": token,
            "operation_until": now + OPERATION_SECONDS,
            "desired_until": desired,
        }
        # Serialize against worker claims/heartbeats as well as concurrent demand.
        writes = [Write(PARTITION, KEY, record, old["version"])]
        if worker:
            writes.append(
                Write(
                    "system#workers",
                    self.worker,
                    {**worker, "version": worker["version"] + 1},
                    worker["version"],
                )
            )
        try:
            self.store.transact(writes)
        except Conflict:
            return self.status()
        changes = {}
        try:
            response = self.client("ec2").describe_instances(InstanceIds=[self.instance])
            instance = response["Reservations"][0]["Instances"][0]
            power = instance["State"]["Name"]
            changes = self.advance(record, worker, power, bool(queued), busy, now)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in {"InvalidInstanceId", "InvocationDoesNotExist", "ThrottlingException"}:
                changes = {
                    "state": "preparing",
                    "retry_at": now + 30,
                    "service_requested": bool(record.get("command_id")),
                    "error_code": code,
                }
                return self.status()
            capacity = code in {
                "InsufficientInstanceCapacity",
                "InsufficientHostCapacity",
                "InstanceLimitExceeded",
                "VcpuLimitExceeded",
            }
            changes = {
                "state": "capacity_wait" if capacity else "error",
                "retry_at": now + (60 if capacity else 300),
                "error_code": code,
            }
        except (BotoCoreError, KeyError, IndexError):
            # Reconcile EC2 power next tick. SSM ambiguity is latched below.
            changes = {"state": "error", "retry_at": now + 60, "error_code": "control_unconfirmed"}
        except Conflict:
            changes = {"retry_at": now + 10}
        finally:
            latest = self.record()
            if latest and latest.get("operation") == token:
                # Preserve demand committed while this external operation was in flight.
                result = {
                    **latest,
                    **changes,
                    "version": latest["version"] + 1,
                    "operation_until": 0,
                    "updated_at": now,
                }
                try:
                    self.store.put(PARTITION, KEY, result, latest["version"])
                except Conflict:
                    pass
        return self.status()

    def advance(self, record, worker, power, queued, busy, now):
        wanted = record.get("desired_until", 0) > now
        if power == "stopped":
            if wanted:
                self.mutation_intent(
                    record,
                    state="starting",
                    stop_requested=False,
                    boot_after=now,
                    startup_deadline=now + STARTUP_SECONDS,
                    command_id=None,
                    service_requested=False,
                )
                self.client("ec2").start_instances(InstanceIds=[self.instance])
            return {
                "state": "starting" if wanted else "sleeping",
                "command_id": None,
                "service_requested": False,
                "stop_requested": False,
                "boot_after": now,
                "startup_deadline": now + STARTUP_SECONDS,
                "retry_at": now + 10,
            }
        if power == "pending":
            if record.get("startup_deadline", now + 1) <= now:
                return {"state": "error", "retry_at": now + 60}
            return {"state": "starting", "retry_at": now + 10}
        if power == "stopping":
            return {"state": "stopping", "retry_at": now + 10}
        if power != "running":
            return {"state": "error", "retry_at": now + 300}
        if record.get("stop_requested"):
            # EC2's running observation is not proof that an accepted stop won't
            # propagate. Keep claims fenced until stopped or operator recovery.
            return {"state": "error", "retry_at": now + 30, "error_code": "stop_not_confirmed"}
        fresh = bool(
            worker
            and worker.get("last_seen", 0) > max(now - FRESH_SECONDS, record.get("boot_after", 0))
        )
        if not wanted and not queued and not busy and fresh:
            # The operation lock blocks new native claims before this API call.
            self.mutation_intent(record, state="stopping", stop_requested=True)
            self.client("ec2").stop_instances(InstanceIds=[self.instance])
            return {
                "state": "stopping",
                "command_id": None,
                "service_requested": False,
                "retry_at": now + 10,
            }
        if busy:
            return {"state": "busy", "retry_at": now + 10}
        if fresh:
            return {"state": "ready", "retry_at": now + 10}
        if record.get("startup_deadline", now + 1) <= now:
            return {"state": "error", "retry_at": now + 60, "error_code": "worker_start_timeout"}
        if record.get("service_requested"):
            command_id = record.get("command_id")
            if not command_id:
                return {"state": "error", "retry_at": now + 300}
            result = self.client("ssm").get_command_invocation(
                CommandId=command_id, InstanceId=self.instance
            )
            if result["Status"] in {"Failed", "Cancelled", "TimedOut"}:
                return {"state": "error", "retry_at": now + 300}
            return {"state": "preparing", "retry_at": now + 10}
        # Persist intent before SendCommand. A lost response must not replay it.
        self.mutation_intent(
            record,
            service_requested=True,
            startup_deadline=record.get("startup_deadline") or now + STARTUP_SECONDS,
        )
        response = self.client("ssm").send_command(
            InstanceIds=[self.instance],
            DocumentName=self.document,
            TimeoutSeconds=120,
            Comment="Academy digital twin wakeup",
        )
        return {
            "state": "preparing",
            "command_id": response["Command"]["CommandId"],
            "service_requested": True,
            "startup_deadline": record.get("startup_deadline") or now + STARTUP_SECONDS,
            "retry_at": now + 10,
        }

    def mutation_intent(self, record, **changes):
        latest = self.record()
        if (
            not latest
            or latest.get("operation") != record["operation"]
            or latest.get("operation_until", 0) <= self.clock() + 5
        ):
            raise Conflict
        self.store.put(
            PARTITION,
            KEY,
            {**latest, **changes, "version": latest["version"] + 1},
            latest["version"],
        )
