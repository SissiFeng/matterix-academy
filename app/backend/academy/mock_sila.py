"""Loopback-only SiLA 2 transport for exported teaching workcells.

Run the exported bundle with: python mock_sila.py workspace.json --run
No SDK is imported by the web application or Lambda.
"""

import argparse
import json
import threading
from contextlib import contextmanager
from pathlib import Path

if __package__:
    from .mock_contract import PlanError, execute_mock
else:
    from mock_contract import PlanError, execute_mock

PARAMETERS = {
    "load": ("VolumeMicroliters",),
    "transfer": ("SourceStation", "TargetStation"),
    "mix": ("DurationSeconds",),
    "heat": ("TargetTemperature",),
    "read": (),
    "wait": ("DurationSeconds",),
}


class MockWorkcell:
    """One sample and one serialized command history shared by all device servers."""

    def __init__(self, twins):
        self.twins = {t["id"]: t for t in twins}
        self.steps = []
        self.trace = []
        self.lock = threading.RLock()

    def command(self, device_id, operation, *args):
        params = dict(zip(PARAMETERS[operation], args, strict=True))
        step = {
            "device_id": device_id,
            "operation": operation,
            "source_id": None,
            "target_id": None,
            "value": 1,
        }
        if operation == "transfer":
            step.update(source_id=params["SourceStation"], target_id=params["TargetStation"])
            if step["source_id"] == step["target_id"]:
                raise PlanError("state", "A transfer requires different stations")
        elif params:
            import math

            value = next(iter(params.values()))
            if not math.isfinite(value) or not 0.001 <= value <= 1_000_000:
                raise PlanError(
                    "constraint", "Command value must be finite and within 0.001–1000000"
                )
            step["value"] = value
        with self.lock:
            if len(self.steps) >= 48:
                raise PlanError("state", "This teaching run supports at most 48 commands")
            steps = [*self.steps, step]
            trace = execute_mock(self.twins, steps)
            # Failed commands never consume resources or alter the command history.
            self.steps, self.trace = steps, trace

    def property(self, device_id, name, consumables):
        with self.lock:
            state = self.trace[-1] if self.trace else {}
            # The first sample on this device, in load order.
            here = next(
                (s for s in state.get("samples", {}).values() if s["location"] == device_id),
                None,
            )
            if name == "SampleLoaded":
                return here is not None
            if name == "TemperatureC":
                return here["temperature_c"] if here else 20.0
            if name == "VolumeMicroliters":
                return here["volume_ul"] if here else 0.0
            item = consumables[name]
            return state.get("consumables", {}).get(device_id, {}).get(item["name"], item["stock"])


@contextmanager
def serve(manifest, port=50520):
    """Start real SiLA gRPC servers, backed exclusively by synthetic state."""
    from sila2.framework import Feature
    from sila2.framework.errors.undefined_execution_error import UndefinedExecutionError
    from sila2.server import FeatureImplementationBase, SilaServer

    twins = manifest["twins"]
    if not 1 <= len(twins) <= 12 or not 1024 <= port <= 65535 - len(twins):
        raise ValueError("Choose 1–12 devices and an unprivileged port range")
    runtime = MockWorkcell(twins)
    servers = []
    endpoints = {}
    try:
        for index, twin in enumerate(twins):
            server = SilaServer(
                server_name=twin["spec"]["name"],
                server_type="AcademySyntheticTwin",
                server_description="Loopback teaching mock. No physical hardware.",
                server_version="1.0",
                server_vendor_url="https://github.com/SissiFeng/matterix-academy",
                server_uuid=twin["id"],
                max_grpc_workers=2,
                max_child_task_workers=2,
            )
            implementation = FeatureImplementationBase(server)
            feature = manifest["features"][twin["id"]]

            def command(operation, twin_id):
                def call(*args, metadata=None):
                    try:
                        runtime.command(twin_id, operation, *args)
                    except (PlanError, ValueError, TypeError) as exc:
                        raise UndefinedExecutionError(str(exc)) from exc
                    return None

                return call

            for operation in twin["spec"]["operations"]:
                setattr(implementation, operation.capitalize(), command(operation, twin["id"]))
            items = {
                f"Consumable{i + 1}Remaining": c for i, c in enumerate(twin["spec"]["consumables"])
            }

            def getter(name, twin_id, consumables):
                return lambda metadata=None: runtime.property(twin_id, name, consumables)

            for name in ("SampleLoaded", "TemperatureC", "VolumeMicroliters", *items):
                setattr(implementation, f"get_{name}", getter(name, twin["id"], items))
            server.set_feature_implementation(Feature(feature["xml"]), implementation)
            server.start_insecure("127.0.0.1", port + index, enable_discovery=False)
            servers.append(server)
            endpoints[twin["id"]] = {"port": port + index, "feature": feature["identifier"]}
        yield runtime, endpoints
    finally:
        for server in reversed(servers):
            server.stop(grace_period=1)


def run_workflow(manifest, endpoints):
    from sila2.client import SilaClient

    clients = {}
    try:
        for device_id, endpoint in endpoints.items():
            clients[device_id] = SilaClient("127.0.0.1", endpoint["port"], insecure=True)
        for step in manifest["steps"]:
            feature = getattr(clients[step["device_id"]], endpoints[step["device_id"]]["feature"])
            operation = step["operation"]
            values = {
                "VolumeMicroliters": step["value"],
                "DurationSeconds": step["value"],
                "TargetTemperature": step["value"],
                "SourceStation": step["source_id"],
                "TargetStation": step["target_id"],
            }
            getattr(feature, operation.capitalize())(
                **{k: values[k] for k in PARAMETERS[operation]}
            )
    finally:
        for client in clients.values():
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--port", type=int, default=50520)
    parser.add_argument(
        "--run", action="store_true", help="Run the saved workflow through SiLA gRPC, then stop"
    )
    args = parser.parse_args()
    manifest = json.loads(args.workspace.read_text())
    with serve(manifest, args.port) as (runtime, endpoints):
        if args.run:
            if not manifest["steps"]:
                raise ValueError("Save a workflow before exporting a runnable workcell")
            run_workflow(manifest, endpoints)
            print(
                json.dumps(
                    {"evidence": "synthetic", "transport": "sila2_grpc", "trace": runtime.trace},
                    indent=2,
                )
            )
        else:
            print(json.dumps({"evidence": "synthetic", "endpoints": endpoints}), flush=True)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
