"""Connector-owned Protocol Engine transport; startup performs only GET requests.

The exact firmware/HTTP interface must be operator-qualified. This client never
homes on startup, uploads arbitrary Python, retries a robot mutation, or resumes
a failed/uncertain run. SiLA is not presented as a whole-workflow API.
"""

import re
import time
from collections.abc import Callable

import httpx

from .compiler import CompiledProtocol
from .config import RobotProfile, digest, validate_url
from .identity import probe_sila


class ProtocolError(RuntimeError):
    pass


def resource_id(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ProtocolError("Robot returned an invalid resource ID")
    return value


class ProtocolEngine:
    def __init__(
        self,
        robot_url: str,
        profile: RobotProfile,
        *,
        transport=None,
        sila_probe=None,
        certificate=None,
    ):
        self.profile = profile
        self.sila_probe = sila_probe or (lambda: probe_sila(robot_url, profile, certificate))
        self.http = httpx.Client(
            base_url=validate_url(robot_url, robot=True),
            headers={"Opentrons-Version": "3"},
            timeout=15,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self):
        self.http.close()

    def _request(self, method, path, **kwargs):
        response = self.http.request(method, path, **kwargs)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ProtocolError("Malformed Protocol Engine response")
        return result

    def probe(self) -> dict:
        self.profile.assert_current()
        health = self._request("GET", "/health")
        expected_model = "OT-3 Standard" if self.profile.instrument == "flex" else "OT-2 Standard"
        expected = {
            "robot_serial": self.profile.serial,
            "robot_model": expected_model,
            "fw_version": self.profile.firmware,
            "api_version": self.profile.api_version,
        }
        if any(health.get(key) != value for key, value in expected.items()):
            raise ProtocolError(
                "Robot identity, firmware or API version differs from local qualification"
            )
        version = [int(part) for part in self.profile.protocol_api.split(".")]
        minimum, maximum = (
            health.get("minimum_protocol_api_version"),
            health.get("maximum_protocol_api_version"),
        )
        if not (
            isinstance(minimum, list)
            and isinstance(maximum, list)
            and minimum <= version <= maximum
        ):
            raise ProtocolError("Robot does not support the qualified Protocol API")
        pipettes = self._request("GET", "/pipettes")
        attached = pipettes.get(self.profile.pipette_mount, {})
        hardware_name = {
            "flex_1channel_1000": "p1000_single_flex",
            "flex_1channel_50": "p50_single_flex",
        }.get(self.profile.pipette_model, self.profile.pipette_model)
        if (
            not isinstance(attached, dict)
            or attached.get("name") not in {self.profile.pipette_model, hardware_name}
            or attached.get("id") != self.profile.pipette_serial
        ):
            raise ProtocolError("Mounted pipette differs from qualified model/serial/mount")
        runtime = self._request("GET", "/unitelabs/runtime")
        expected_runtime = {
            "runtimeContractId": self.profile.runtime_contract_id,
            "connectorVersion": self.profile.connector_version,
            "opentronsVersion": self.profile.api_version,
            "releaseIdentity": {
                "release_id": self.profile.runtime_release_id,
                "bundle_sha256": self.profile.runtime_bundle_sha256,
            },
        }
        if runtime != expected_runtime:
            raise ProtocolError(
                "Running connector release identity differs from approved installation"
            )
        calibration = self._request("GET", "/calibration/status")
        offsets = self._request("GET", "/labwareOffsets")
        pipette_offsets = self._request("GET", "/calibration/pipette_offset")
        tip_lengths = self._request("GET", "/calibration/tip_length")
        if calibration.get("deckCalibration", {}).get("status") != "OK":
            raise ProtocolError("Robot deck calibration is not valid")

        def marked_bad(value):
            if isinstance(value, dict):
                return value.get("markedBad") is True or any(
                    marked_bad(item) for item in value.values()
                )
            return isinstance(value, list) and any(marked_bad(item) for item in value)

        if any(marked_bad(value) for value in (calibration, pipette_offsets, tip_lengths)):
            raise ProtocolError("Robot calibration is marked invalid")
        if (
            digest(
                {
                    "calibration": calibration,
                    "labware_offsets": offsets,
                    "pipette_offsets": pipette_offsets,
                    "tip_lengths": tip_lengths,
                }
            )
            != self.profile.calibration_sha256
        ):
            raise ProtocolError("Calibration or labware offsets changed since local qualification")
        self.sila_probe()
        return health

    def _assert_idle(self):
        runs = self._request("GET", "/runs", params={"pageLength": 100})
        data = runs.get("data")
        if not isinstance(data, list):
            raise ProtocolError("Cannot establish current robot run")
        # Opentrons /runs has no cursor pagination. Its current link is global,
        # independent of the bounded latest-history slice (v8.5+ API contract).
        links = runs.get("links")
        if not isinstance(links, dict) or "current" not in links:
            raise ProtocolError("Robot omitted authoritative current-run ownership")
        if any(not isinstance(run, dict) for run in data):
            raise ProtocolError("Malformed bounded robot history")
        if links["current"] is not None or any(run.get("current") is True for run in data):
            raise ProtocolError("Robot already has a current run; companion will not take it over")
        if len(data) > 100 or any(
            not isinstance(run, dict) or run.get("current") is not False for run in data
        ):
            raise ProtocolError("Malformed bounded robot history")

    def get_run(self, run_id: str, protocol_id: str) -> dict:
        data = self._request("GET", f"/runs/{resource_id(run_id)}").get("data", {})
        if data.get("id") != run_id or data.get("protocolId") != protocol_id:
            raise ProtocolError("Robot run/protocol binding changed")
        return data

    def _commands(self, run_id: str) -> list:
        result, cursor = [], 0
        while cursor < 4096:
            page = self._request(
                "GET",
                f"/runs/{resource_id(run_id)}/commands",
                params={"cursor": cursor, "pageLength": 100},
            )
            data, meta = page.get("data"), page.get("meta", {})
            if not isinstance(data, list) or meta.get("cursor") != cursor:
                raise ProtocolError("Invalid command evidence page")
            result.extend(data)
            total = meta.get("totalLength")
            if not isinstance(total, int) or total > 4096 or total < len(result):
                raise ProtocolError("Invalid command evidence length")
            if len(result) == total:
                return result
            if not data:
                raise ProtocolError("Incomplete command evidence")
            cursor += len(data)
        raise ProtocolError("Too many robot commands")

    def execute(
        self,
        protocol: CompiledProtocol,
        *,
        approve: Callable[[], bool],
        phase: Callable,
        stop_requested: Callable[[], bool],
        timeout_seconds=1800,
        poll_seconds=1.0,
    ) -> dict:
        self.probe()
        self._assert_idle()
        if not approve():
            return {
                "outcome": "stopped",
                "protocol_id": None,
                "robot_run_id": None,
                "completed_actions": 0,
                "stop_confirmed": True,
                "detail": "Local operator cancelled before mutation; no robot mutation submitted",
            }
        # Recheck after an arbitrarily long operator prompt, before any robot mutation.
        self.probe()
        self._assert_idle()
        if stop_requested():
            return {
                "outcome": "stopped",
                "protocol_id": None,
                "robot_run_id": None,
                "completed_actions": 0,
                "stop_confirmed": True,
                "detail": "Cancelled before robot mutation",
            }
        phase("upload_attempted")
        uploaded = self._request(
            "POST",
            "/protocols",
            files={"files": ("academy_protocol.py", protocol.source, "text/x-python")},
        )
        protocol_id = resource_id(uploaded.get("data", {}).get("id"))
        phase("uploaded", protocol_id=protocol_id)
        deadline = time.monotonic() + timeout_seconds
        analysis_id = None
        while time.monotonic() < deadline:
            summaries = self._request("GET", f"/protocols/{protocol_id}/analyses").get("data", [])
            if not isinstance(summaries, list) or not summaries:
                raise ProtocolError("Uploaded protocol has no analysis")
            if analysis_id is None:
                analysis_id = resource_id(summaries[-1].get("id"))
            analysis = self._request("GET", f"/protocols/{protocol_id}/analyses/{analysis_id}").get(
                "data", {}
            )
            if analysis.get("status") == "completed":
                if analysis.get("result") != "ok" or analysis.get("errors") != []:
                    raise ProtocolError("Protocol analysis rejected the exact compiled workflow")
                break
            if analysis.get("status") != "pending":
                raise ProtocolError("Unknown protocol analysis status")
            time.sleep(poll_seconds)
        else:
            raise TimeoutError("Protocol analysis timed out")
        if stop_requested():
            return {
                "outcome": "stopped",
                "protocol_id": protocol_id,
                "robot_run_id": None,
                "completed_actions": 0,
                "stop_confirmed": True,
                "detail": "Cancelled before creating a robot run",
            }
        self.probe()
        self._assert_idle()
        phase("create_run_attempted", protocol_id=protocol_id)
        run = self._request("POST", "/runs", json={"data": {"protocolId": protocol_id}}).get(
            "data", {}
        )
        run_id = resource_id(run.get("id"))
        phase("run_created", robot_run_id=run_id)
        bound = self.get_run(run_id, protocol_id)
        if not bound.get("current") or bound.get("status") != "idle":
            raise ProtocolError("Created run is not current and idle")
        # Authority is checked immediately before actuation, not only before upload.
        self.profile.assert_current()
        stopping = stop_requested()
        phase("stop_attempted" if stopping else "play_attempted")
        self._request(
            "POST",
            f"/runs/{run_id}/actions",
            json={"data": {"actionType": "stop" if stopping else "play"}},
        )
        while time.monotonic() < deadline:
            run = self.get_run(run_id, protocol_id)
            status = run.get("status")
            if status in {"succeeded", "failed", "stopped"}:
                break
            if not run.get("current"):
                raise ProtocolError("Physical run lost current ownership")
            if stop_requested() and not stopping:
                # Bound current resource only. Never issue a global/home/other-run command.
                phase("stop_attempted")
                self._request(
                    "POST", f"/runs/{run_id}/actions", json={"data": {"actionType": "stop"}}
                )
                stopping = True
            time.sleep(poll_seconds)
        else:
            raise TimeoutError("Physical run exceeded local deadline; inspect robot, do not replay")
        commands = self._commands(run_id)
        completed = [
            c.get("commandType")
            for c in commands
            if c.get("status") == "succeeded"
            and c.get("commandType")
            in {"pickUpTip", "aspirate", "dispense", "dropTip", "dropTipInPlace"}
        ]
        completed = ["dropTip" if name == "dropTipInPlace" else name for name in completed]
        if status == "succeeded" and (
            tuple(completed) != protocol.expected_actions or run.get("errors") != []
        ):
            raise ProtocolError("Succeeded run lacks exact ordered action completion evidence")
        if tuple(completed) != protocol.expected_actions[: len(completed)]:
            raise ProtocolError("Robot action evidence differs from compiled plan")
        # Deactivation is separately journaled. A lost response remains unknown, no replay.
        if run.get("current"):
            phase("release_attempted")
            self._request("PATCH", f"/runs/{run_id}", json={"data": {"current": False}})
            if self.get_run(run_id, protocol_id).get("current"):
                raise ProtocolError("Robot run release was not confirmed")
        return {
            "outcome": {"succeeded": "completed", "failed": "failed", "stopped": "stopped"}[status],
            "protocol_id": protocol_id,
            "robot_run_id": run_id,
            "completed_actions": len(completed),
            "stop_confirmed": True,
            "detail": "Bound Protocol Engine terminal status and command evidence observed",
        }
