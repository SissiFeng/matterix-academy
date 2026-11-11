"""One pinned GPU, durable demand and serialized power transitions.

This is power management, never native qualification or workflow authority.
Authenticated capacity requests and validated runs can create demand. EC2 state is reconciled before
every retry; neither native runs nor unknown SSM commands are replayed.

A host whose worker never connects after boot is recovered in bounded steps: one restart of the
worker service (only when the previous SSM command is known to have finished), one stop/start of
the host, then a stop and hold for operator attention. A worker that has not polled since boot
cannot hold a claimed run, so stopping it never interrupts native work.
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
# A worker that reports an unusable GPU after boot gets this long before the host is restarted.
UNREADY_GRACE_SECONDS = 120
# An accepted stop that EC2 still reports as running is re-issued after this long.
STOP_RETRY_SECONDS = 300
CAPACITY_RETRY_MAX = 300
# Cost guard: with no demand, queue or cloud-side run, a host whose worker has been
# silent this long is stopped instead of billing until an operator notices.
SILENT_STOP_SECONDS = 900
METRIC_NAMESPACE = "Academy/GPU"
SSM_FINISHED = {"Success", "Failed", "Cancelled", "TimedOut"}
READINESS = "system#worker-readiness"
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
# Recovery notes refine the message of the current state.
NOTES = {
    "restarting_service": "The GPU started but its worker did not connect. Restarting the worker.",
    "power_cycle": "The GPU worker did not connect. Restarting the GPU host.",
    "gpu_unready": "The GPU host is up but its GPU is not ready yet.",
    "halted": "The GPU host could not prepare its worker after automatic restarts and was stopped. "
    "An operator needs to check it; your workflow has not been replayed.",
    "unresolved_run": "An earlier run needs operator review before the digital twin can start "
    "again. Your workflow has not been replayed.",
}


def startup_seconds():
    try:
        value = int(os.getenv("ACADEMY_GPU_STARTUP_SECONDS", STARTUP_SECONDS))
    except ValueError:
        return STARTUP_SECONDS
    return min(1800, max(300, value))


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
        startup=startup_seconds(),
    )


class GpuLifecycle:
    def __init__(
        self,
        store,
        instance,
        worker,
        document,
        *,
        region=None,
        ec2=None,
        ssm=None,
        clock=time.time,
        startup=STARTUP_SECONDS,
    ):
        self.store, self.instance, self.worker, self.document = store, instance, worker, document
        self.clock, self._ec2, self._ssm = clock, ec2, ssm
        self.region = region
        self.startup = startup

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

    def readiness(self):
        return self.store.get(READINESS, self.worker)

    def status(self):
        record = self.record() or {}
        state = record.get("state", "sleeping")
        note = record.get("note")
        result = {
            "state": state,
            "message": NOTES.get(note) or MESSAGES.get(state, MESSAGES["error"]),
            "idle_seconds": IDLE_SECONDS,
            "retry_at": record.get("retry_at"),
            "updated_at": record.get("updated_at"),
        }
        if state == "capacity_wait":
            result["attempts"] = record.get("capacity_attempts", 1)
        if note == "gpu_unready":
            result["detail"] = (self.readiness() or {}).get("issue")
        return result

    def metrics(self):
        """One CloudWatch embedded-metric line for the reaper's log; alarms read these."""
        record = self.record() or {}
        now = self.clock()
        running = record.get("power") == "running"
        since = max(record.get("desired_until", 0), record.get("boot_after", 0))
        values = {
            "HostRunning": int(running),
            "RunningSeconds": int(now - record.get("boot_after", now)) if running else 0,
            # Demand lapsed and the host is still up: what the cost guard should end.
            "UnwantedRunningSeconds": int(max(0, now - since)) if running else 0,
            "NeedsOperator": int(record.get("state") == "error"),
            "CapacityWait": int(record.get("state") == "capacity_wait"),
        }
        return {
            "_aws": {
                "Timestamp": int(now * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": METRIC_NAMESPACE,
                        "Dimensions": [["Instance"]],
                        "Metrics": [
                            {"Name": k, "Unit": "Seconds" if k.endswith("Seconds") else "Count"}
                            for k in values
                        ],
                    }
                ],
            },
            "Instance": self.instance,
            "state": record.get("state"),
            "error_code": record.get("error_code"),
            **values,
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
        # A live run retains this guard even after its lease expires. An unknown
        # outcome holds the host for one inspection window, not indefinitely: the
        # run is terminal, never replayed, and its evidence stays on the volume.
        busy = bool(worker and worker.get("active_run"))
        parked = unresolved = False
        if busy:
            run = self.store.get("system#runs", worker["active_run"])
            if run and run.get("status") == "outcome_unknown":
                unresolved = True
                desired = max(old.get("desired_until", 0), run["updated_at"] + IDLE_SECONDS)
                parked = desired <= now
                busy = not parked
            else:
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
            changes = {"power": power}
            changes |= self.advance(
                record, worker, power, bool(queued), busy, now, parked, unresolved
            )
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            # AWS asking the controller to slow down is not a fault in the host.
            if code in {
                "InvalidInstanceId",
                "InvocationDoesNotExist",
                "ThrottlingException",
                "Throttling",
                "RequestLimitExceeded",
            }:
                changes = {
                    "state": "preparing",
                    "retry_at": now + 30,
                    "service_requested": bool(record.get("command_id")),
                    "error_code": code,
                }
            else:
                capacity = code in {
                    "InsufficientInstanceCapacity",
                    "InsufficientHostCapacity",
                    "InstanceLimitExceeded",
                    "VcpuLimitExceeded",
                }
                attempts = record.get("capacity_attempts", 0) + 1 if capacity else 0
                changes = {
                    "state": "capacity_wait" if capacity else "error",
                    # Capacity often returns within minutes; back off 60, 120, 240, then 300 s.
                    "retry_at": now
                    + (min(CAPACITY_RETRY_MAX, 60 * 2 ** (attempts - 1)) if capacity else 300),
                    "error_code": code,
                    "capacity_attempts": attempts,
                    "note": None,
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

    def advance(self, record, worker, power, queued, busy, now, parked=False, unresolved=False):
        wanted = record.get("desired_until", 0) > now
        if power == "stopped":
            if wanted and unresolved:
                # Its worker is quarantined with that run, so a boot could serve nobody.
                return {
                    "state": "error",
                    "note": "unresolved_run",
                    "stop_requested": False,
                    "error_code": "unresolved_run",
                    "retry_at": now + 60,
                }
            halted = record.get("halted_until", 0) > now
            if wanted and halted:
                # Repeated failed preparation: stay stopped instead of paying for more boots.
                return {
                    "state": "error",
                    "note": "halted",
                    "stop_requested": False,
                    "error_code": "worker_start_failed",
                    "retry_at": now + 60,
                }
            if wanted:
                self.mutation_intent(
                    record,
                    state="starting",
                    stop_requested=False,
                    boot_after=now,
                    startup_deadline=now + self.startup,
                    command_id=None,
                    service_requested=False,
                )
                self.client("ec2").start_instances(InstanceIds=[self.instance])
            reset = {} if wanted else {"recovery": 0, "halted_until": 0}
            return {
                "state": "starting" if wanted else "sleeping",
                "command_id": None,
                "service_requested": False,
                "stop_requested": False,
                "boot_after": now,
                "startup_deadline": now + self.startup,
                "retry_at": now + 10,
                "capacity_attempts": 0,
                "note": "power_cycle" if wanted and record.get("recovery", 0) >= 2 else None,
                **reset,
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
            asked = record.get("stop_requested_at") or now
            if not busy and asked + STOP_RETRY_SECONDS <= now:
                # The fence still blocks claims, so asking again cannot stop a new run.
                self.mutation_intent(record, stop_requested_at=now)
                self.client("ec2").stop_instances(InstanceIds=[self.instance])
                return {
                    "state": "stopping",
                    "stop_requested_at": now,
                    "retry_at": now + 10,
                    "error_code": "stop_reissued",
                }
            return {
                "state": "error",
                "retry_at": now + 30,
                "error_code": "stop_not_confirmed",
                "stop_requested_at": asked,
            }
        fresh = bool(
            worker
            and worker.get("last_seen", 0) > max(now - FRESH_SECONDS, record.get("boot_after", 0))
        )
        # A parked worker cannot serve its queue until an operator reconciles it.
        if not wanted and not busy and ((not queued and fresh) or parked):
            # The operation lock blocks new native claims before this API call.
            self.mutation_intent(
                record, state="stopping", stop_requested=True, stop_requested_at=now
            )
            self.client("ec2").stop_instances(InstanceIds=[self.instance])
            return {
                "state": "stopping",
                "command_id": None,
                "service_requested": False,
                "stop_requested_at": now,
                "retry_at": now + 10,
            }
        if (
            not wanted
            and not busy
            and not queued
            and max(
                record.get("desired_until", 0),
                record.get("boot_after", 0),
                worker.get("last_seen", 0) if worker else 0,
            )
            + SILENT_STOP_SECONDS
            <= now
        ):
            # Claims set active_run in the same transaction, so this worker holds no
            # run the cloud knows of; whatever is on its volume survives a stop.
            self.mutation_intent(
                record, state="stopping", stop_requested=True, stop_requested_at=now
            )
            self.client("ec2").stop_instances(InstanceIds=[self.instance])
            return {
                "state": "stopping",
                "command_id": None,
                "service_requested": False,
                "stop_requested_at": now,
                "retry_at": now + 10,
                "error_code": "silent_host_stopped",
            }
        if busy:
            return {"state": "busy", "retry_at": now + 10}
        if fresh:
            return {
                "state": "ready",
                "retry_at": now + 10,
                # A worker that was just ready gets the same grace if it goes quiet.
                "startup_deadline": now + self.startup,
                "recovery": 0,
                "halted_until": 0,
                "note": None,
                "capacity_attempts": 0,
            }
        boot = record.get("boot_after", 0)
        connected = bool(worker and worker.get("last_seen", 0) > boot)
        report = self.readiness() or {}
        unready = bool(report.get("issue")) and report.get("at", 0) > boot
        deadline_passed = record.get("startup_deadline", now + 1) <= now
        if not connected and (
            deadline_passed
            or (unready and max(report.get("since", 0), boot) + UNREADY_GRACE_SECONDS <= now)
        ):
            # Never connected since boot, so no run can be claimed on this host.
            return self.recover(record, now, unready)
        if deadline_passed:
            # The worker connected once and went quiet; its journal may hold work.
            return {"state": "error", "retry_at": now + 60, "error_code": "worker_start_timeout"}
        if unready and not connected:
            return {"state": "preparing", "note": "gpu_unready", "retry_at": now + 10}
        if record.get("service_requested"):
            command_id = record.get("command_id")
            if not command_id:
                return {"state": "error", "retry_at": now + 300}
            result = self.client("ssm").get_command_invocation(
                CommandId=command_id, InstanceId=self.instance
            )
            if result["Status"] in {"Failed", "Cancelled", "TimedOut"}:
                return {"state": "error", "retry_at": now + 300}
            # An unready report that has since cleared no longer explains the wait.
            note = None if record.get("note") == "gpu_unready" else record.get("note")
            return {"state": "preparing", "retry_at": now + 10, "note": note}
        # Persist intent before SendCommand. A lost response must not replay it.
        self.mutation_intent(
            record,
            service_requested=True,
            startup_deadline=record.get("startup_deadline") or now + self.startup,
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
            "startup_deadline": record.get("startup_deadline") or now + self.startup,
            "retry_at": now + 10,
            "note": None,
        }

    def recover(self, record, now, unready):
        """Bounded recovery for a worker that never connected since this boot."""
        step = record.get("recovery", 0)
        if step == 0 and not unready:
            status = None
            if record.get("command_id"):
                try:
                    status = self.client("ssm").get_command_invocation(
                        CommandId=record["command_id"], InstanceId=self.instance
                    )["Status"]
                except (ClientError, BotoCoreError, KeyError):
                    status = None
            if status in SSM_FINISHED:
                # The previous command is finished, so sending the fixed document again
                # cannot double-start it; the service start itself is idempotent.
                deadline = now + self.startup // 2
                self.mutation_intent(
                    record,
                    recovery=1,
                    note="restarting_service",
                    service_requested=True,
                    command_id=None,
                    startup_deadline=deadline,
                )
                response = self.client("ssm").send_command(
                    InstanceIds=[self.instance],
                    DocumentName=self.document,
                    TimeoutSeconds=120,
                    Comment="Academy digital twin worker restart",
                )
                return {
                    "state": "preparing",
                    "recovery": 1,
                    "note": "restarting_service",
                    "command_id": response["Command"]["CommandId"],
                    "service_requested": True,
                    "startup_deadline": deadline,
                    "retry_at": now + 10,
                }
            # The command's outcome is unknown: never replay it. Restart the host instead.
        if step <= 1:
            self.mutation_intent(
                record,
                recovery=2,
                note="power_cycle",
                stop_requested=True,
                stop_requested_at=now,
                state="stopping",
            )
            self.client("ec2").stop_instances(InstanceIds=[self.instance])
            return {
                "state": "stopping",
                "recovery": 2,
                "note": "power_cycle",
                "command_id": None,
                "service_requested": False,
                "stop_requested_at": now,
                "retry_at": now + 10,
            }
        self.mutation_intent(
            record,
            note="halted",
            halted_until=now + IDLE_SECONDS,
            stop_requested=True,
            stop_requested_at=now,
        )
        self.client("ec2").stop_instances(InstanceIds=[self.instance])
        return {
            "state": "error",
            "note": "halted",
            "halted_until": now + IDLE_SECONDS,
            "error_code": "worker_start_failed",
            "command_id": None,
            "service_requested": False,
            "stop_requested_at": now,
            "retry_at": now + 60,
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
