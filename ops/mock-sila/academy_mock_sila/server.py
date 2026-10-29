"""Loopback-only mock SiLA2 connector. Synthetic results; no hardware, GPU or cloud.

Runs a saved Studio workflow through the same offline model the browser uses
(`academy.mock_connector.run_mock`). Real Mode is refused by design.
"""

import argparse
import asyncio
import json

from academy.mock_connector import run_mock
from academy.models import Experiment
from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila
from unitelabs.cdk.features.core.simulation_controller import (
    SimulationControllerBase,
    StartRealModeFailed,
)

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class SimulationController(SimulationControllerBase):
    """Permanently in Simulation Mode."""

    # Overrides must repeat the SiLA decorators or the CDK skips the feature.
    @sila.UnobservableCommand()
    async def start_simulation_mode(self) -> None:
        """Already in Simulation Mode."""

    @sila.UnobservableCommand(errors=[StartRealModeFailed])
    async def start_real_mode(self) -> None:
        """
        Always refused: this connector has no hardware.

        Raises:
          StartRealModeFailed: Always.
        """
        raise StartRealModeFailed("The mock connector has no real mode")

    @sila.UnobservableProperty(name="SimulationMode")
    async def simulation_mode(self) -> bool:
        """Always true."""
        return True


class InvalidWorkflow(Exception):
    """The workflow JSON is not a saved Studio workflow with at least one action."""


class MockWorkflowRunner(sila.Feature):
    """Executes Academy Studio workflows against a synthetic deck model."""

    def __init__(self):
        super().__init__(
            originator="ca.matterix.academy",
            category="mock",
            version="1.0",
            maturity_level="Draft",
        )

    @sila.UnobservableCommand(errors=[InvalidWorkflow])
    async def run_workflow(self, workflow: str) -> str:
        """
        Run every step of a workflow offline and return the synthetic result.

        Args:
          workflow: The saved Studio experiment as JSON.

        Returns:
          Result: Synthetic simulation state and per-step trace as JSON.

        Raises:
          InvalidWorkflow: If the workflow is malformed or empty.
        """
        try:
            return json.dumps(run_mock(Experiment.model_validate_json(workflow)))
        except ValueError as error:
            raise InvalidWorkflow(str(error)) from error

    @sila.UnobservableProperty()
    async def physical_execution(self) -> bool:
        """Always false: no command reaches an instrument."""
        return False


def create(host="127.0.0.1", port=50052) -> Connector:
    if host not in LOOPBACK:
        raise ValueError("The mock SiLA2 connector binds to loopback only")
    config = ConnectorBaseConfig(
        sila_server=SiLAServerConfig(
            hostname=host,
            port=port,
            tls=False,
            name="Academy Mock SiLA2",
            type="AcademyMockConnector",
            description="Offline synthetic connector for learning; not a hardware qualification.",
            version="0.1.0",
        ),
        discovery=None,
    )
    connector = Connector(config)
    connector.register(SimulationController())
    connector.register(MockWorkflowRunner())
    return connector


async def serve(host, port):
    connector = create(host, port)
    await connector.start()
    print(json.dumps({"sila": f"{host}:{port}", "evidence": "synthetic"}), flush=True)
    try:
        await connector.wait_for_termination()
    finally:
        await connector.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50052)
    args = parser.parse_args(argv)
    asyncio.run(serve(args.host, args.port))


if __name__ == "__main__":
    main()
