"""Exercises the mock connector over real loopback SiLA2/gRPC. No network beyond 127.0.0.1."""

import asyncio
import json
import socket

import pytest
from academy.models import Action, Experiment
from academy_mock_sila.server import create
from sila.client import Client, ClientConfig, DefinedExecutionError

RUNNER = "ca.matterix.academy/mock/MockWorkflowRunner/v1"
SIMULATION = "org.silastandard/core/SimulationController/v1"


def workflow(actions):
    return Experiment(
        course_id="workflow-sandbox",
        instrument="flex",
        layout={"tips": "B1", "stock": "D1", "plate": "D2", "waste": "D3"},
        diluent_volume=0,
        actions=actions,
    ).model_dump_json()


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def session(check):
    port = free_port()
    connector = create(port=port)
    await connector.start()
    client = Client(ClientConfig(hostname="127.0.0.1", port=port, tls=False))
    try:
        await client.open()
        await check(client)
    finally:
        await client.close()
        await connector.stop()


def test_runs_workflow_offline_and_refuses_real_mode():
    async def check(client):
        assert await client.get_server_name() == "Academy Mock SiLA2"
        features = await client.get_implemented_features()
        assert {RUNNER, SIMULATION} <= set(features)
        runner = client.get_feature(RUNNER)
        assert await runner.properties["PhysicalExecution"].read() is False
        actions = [
            Action(kind="pickup"),
            Action(kind="aspirate"),
            Action(kind="dispense", well="A1"),
            Action(kind="drop"),
        ]
        response = await runner.commands["RunWorkflow"].execute({"Workflow": workflow(actions)})
        result = json.loads(response["Result"])
        assert result["simulation"]["status"] == "completed"
        assert result["simulation"]["state"]["wells"]["A1"]["volume"] == 100
        assert result["evidence"] == "synthetic" and result["physical_execution"] is False

        simulation = client.get_feature(SIMULATION)
        assert await simulation.properties["SimulationMode"].read() is True
        with pytest.raises(DefinedExecutionError):
            await simulation.commands["StartRealMode"].execute({})

    asyncio.run(session(check))


def test_rejects_empty_workflow_as_defined_error():
    async def check(client):
        runner = client.get_feature(RUNNER)
        with pytest.raises(DefinedExecutionError):
            await runner.commands["RunWorkflow"].execute({"Workflow": workflow([])})

    asyncio.run(session(check))


def test_refuses_non_loopback_bind():
    with pytest.raises(ValueError):
        create(host="0.0.0.0")
