"""Protocol-2 worker routes for both worker classes on the machine API.

Simulation workers use ``/internal/sim/*`` with their worker credential.
Device gateways use ``/internal/gateway/*`` with a ``gw.`` gateway credential.
The two credential types are verified against different registries, carry a
different ``worker_class`` in the Lambda authorizer context and can never be
used on each other's routes. Error bodies use the bridge gateway format
(``{"code", "error"}``) so the existing gateway agent recovers correctly.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .broker import BrokerError, ConflictError, SessionError
from .instruments import device_target, gateway_credential
from .runs import worker_credential


def error(status, code, message):
    return JSONResponse({"code": code, "error": message, "detail": message}, status_code=status)


def body_fields(data, required, optional=()):
    if (
        not isinstance(data, dict)
        or not set(required) <= set(data)
        or set(data) - set(required) - set(optional)
    ):
        raise BrokerError("Invalid request fields")
    return data


def install(app, *, store, runs, pairing, runtime, poll_wait):
    broker = pairing.broker
    instruments = pairing.instruments

    def lambda_claims(request):
        return (
            request.scope.get("aws.event", {})
            .get("requestContext", {})
            .get("authorizer", {})
            .get("lambda", {})
        )

    def sim_worker(request: Request):
        if runtime == "aws":
            claims = lambda_claims(request)
            if claims.get("worker_class", "simulation") != "simulation" or not claims.get(
                "worker_id"
            ):
                raise HTTPException(403, "Simulation worker credential required")
            worker = runs.worker(claims["worker_id"])
            if str(worker["credential_version"]) != claims.get("credential_version"):
                raise HTTPException(403, "Machine credential was rotated")
        else:
            worker = worker_credential(
                store, request.headers.get("authorization", ""), runs.clock()
            )
            if not worker:
                raise HTTPException(403, "Simulation worker credential required")
        if worker.get("worker_class", "simulation") != "simulation":
            raise HTTPException(403, "Simulation worker credential required")
        return worker

    def device_gateway(request: Request):
        if runtime == "aws":
            claims = lambda_claims(request)
            if claims.get("worker_class") != "device" or not claims.get("gateway_id"):
                raise HTTPException(403, "Device gateway credential required")
            gateway = instruments.gateway(claims["gateway_id"])
            if str(gateway["credential_version"]) != claims.get("credential_version"):
                raise HTTPException(403, "Gateway credential was rotated")
        else:
            gateway = gateway_credential(
                store, request.headers.get("authorization", ""), runs.clock()
            )
            if not gateway:
                raise HTTPException(403, "Device gateway credential required")
        header = request.headers.get("x-device-id")
        if header is not None and header != gateway["instrument_id"]:
            raise HTTPException(403, "Credential belongs to another instrument")
        return gateway

    def guarded(fn):
        try:
            return fn()
        except SessionError as exc:
            return error(409, "session", str(exc))
        except ConflictError as exc:
            return error(409, "conflict", str(exc))
        except BrokerError as exc:
            return error(400, exc.code, str(exc))

    def poll(target, credential, data):
        body_fields(data, {"session", "seq"}, {"acks", "results"})
        return broker.exchange(
            target,
            data["session"],
            seq=data["seq"],
            acks=data.get("acks", []),
            results=data.get("results", []),
            wait=poll_wait,
            credential=credential,
        )

    def result(target, credential, data):
        body_fields(data, {"session", "result"})
        broker.result(target, data["session"], data["result"], credential=credential)
        return {"received": True}

    # ------------------------------------------------------------- simulation class

    @app.post("/internal/sim/register")
    async def sim_register(request: Request, worker=Depends(sim_worker)):
        data = await request.json()

        def run():
            body_fields(data, {"instance", "protocol", "runtime"}, {"results"})
            if data["protocol"] != 2:
                raise BrokerError("Protocol 2 is required")
            if not pairing.pairing_enabled or not worker.get("qualified"):
                return error(
                    403,
                    "credential",
                    "Qualified simulation worker and sim-to-real coordination required",
                )
            runtime_info = data["runtime"]
            if (
                not isinstance(runtime_info, dict)
                or runtime_info.get("simulation_only") is not True
                or runtime_info.get("engine_version") != worker["engine_version"]
                or runtime_info.get("asset_version") != worker["asset_version"]
            ):
                raise BrokerError("Worker runtime differs from its qualified manifest")
            return broker.register(
                f"sim:{worker['worker_id']}",
                credential=[worker["worker_id"], worker["credential_version"]],
                instance=data["instance"],
                results=data.get("results", []),
            )

        return guarded(run)

    @app.post("/internal/sim/poll")
    async def sim_poll(request: Request, worker=Depends(sim_worker)):
        data = await request.json()
        credential = [worker["worker_id"], worker["credential_version"]]
        return guarded(lambda: poll(f"sim:{worker['worker_id']}", credential, data))

    @app.post("/internal/sim/result")
    async def sim_result(request: Request, worker=Depends(sim_worker)):
        data = await request.json()
        credential = [worker["worker_id"], worker["credential_version"]]
        return guarded(lambda: result(f"sim:{worker['worker_id']}", credential, data))

    # ------------------------------------------------------------- device class

    @app.post("/internal/gateway/register")
    async def gateway_register(request: Request, gateway=Depends(device_gateway)):
        data = await request.json()

        def run():
            body_fields(data, {"profile", "instance", "protocol"}, {"results"})
            if data["protocol"] != 2:
                raise BrokerError("Protocol 2 is required; upgrade the gateway")
            problem = instruments.check_registration(gateway["instrument_id"], data["profile"])
            if problem:
                raise BrokerError(problem)
            return broker.register(
                device_target(gateway["instrument_id"]),
                credential=[gateway["gateway_id"], gateway["credential_version"]],
                instance=data["instance"],
                results=data.get("results", []),
            )

        return guarded(run)

    @app.post("/internal/gateway/poll")
    async def gateway_poll(request: Request, gateway=Depends(device_gateway)):
        data = await request.json()
        credential = [gateway["gateway_id"], gateway["credential_version"]]
        return guarded(lambda: poll(device_target(gateway["instrument_id"]), credential, data))

    @app.post("/internal/gateway/result")
    async def gateway_result(request: Request, gateway=Depends(device_gateway)):
        data = await request.json()
        credential = [gateway["gateway_id"], gateway["credential_version"]]
        return guarded(lambda: result(device_target(gateway["instrument_id"]), credential, data))
