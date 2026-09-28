"""Contract client for a future Ubuntu gateway; not a native Matterix API.

Kept outside the teaching runner. No fallback from remote failure to synthetic state.
The platform does not expose this until a deployed gateway passes qualification.
"""

from urllib.parse import urlparse

import httpx
from pydantic import Field

from .models import StrictModel


class GatewayCapabilities(StrictModel):
    contract_version: str
    engine: str
    simulation_only: bool
    supports_isolated_sessions: bool
    actions: list[str] = Field(default_factory=list)


class GatewayUnavailable(RuntimeError):
    pass


class MatterixGateway:
    def __init__(self, base_url: str, token: str, transport=None):
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("An operator-configured HTTPS gateway URL is required")
        if not token:
            raise ValueError("A gateway service credential is required")
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
            follow_redirects=False,
            transport=transport,
        )

    def capabilities(self):
        try:
            response = self.client.get("v1/capabilities")
            response.raise_for_status()
            capabilities = GatewayCapabilities.model_validate(response.json())
            if (
                capabilities.contract_version != "1"
                or capabilities.engine != "matterix"
                or not capabilities.simulation_only
                or not capabilities.supports_isolated_sessions
            ):
                raise ValueError("Gateway does not meet the Academy simulation contract")
            return capabilities
        except (httpx.HTTPError, ValueError) as exc:
            raise GatewayUnavailable("Matterix gateway qualification failed") from exc

    def close(self):
        self.client.close()
