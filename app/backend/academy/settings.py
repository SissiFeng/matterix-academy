import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    runtime: str = "local"
    allow_demo: bool = False
    data_path: str = ".data/academy.sqlite"
    secret: str = ""
    table: str = ""
    issuer: str = ""
    client_id: str = ""
    cognito_domain: str = ""
    app_url: str = "http://127.0.0.1:5173"
    gateway_url: str = ""
    gateway_token: str = ""
    remote_enabled: bool = False
    connector_real_enabled: bool = False
    self_signup_email_domains: tuple[str, ...] = ()
    # Sim-to-real coordination and physical execution are separate, default-off switches.
    pairing_enabled: bool = False
    real_enabled: bool = False
    operator_group: str = "lab-operators"
    local_operator: bool = False
    twin_region: str = ""
    twin_api_key: str = ""
    twin_api_key_secret: str = ""

    def __post_init__(self):
        if self.runtime not in {"local", "aws"}:
            raise ValueError("ACADEMY_RUNTIME must be local or aws")
        if self.twin_region not in {"", "us-east-1", "us-west-2"}:
            raise ValueError(
                "ACADEMY_TWIN_REGION must be a Bedrock Mantle region serving GPT-6 Astra"
            )
        if self.twin_api_key_secret and not re.fullmatch(
            r"arn:aws:secretsmanager:[a-z0-9-]+:\d{12}:secret:[A-Za-z0-9/_+=.@-]+",
            self.twin_api_key_secret,
        ):
            raise ValueError("ACADEMY_TWIN_API_KEY_SECRET must be a Secrets Manager secret ARN")
        if (self.twin_api_key or self.twin_api_key_secret) and not self.twin_region:
            raise ValueError("A Bedrock twin key requires ACADEMY_TWIN_REGION")
        if self.runtime == "aws" and self.twin_api_key:
            raise ValueError("AWS reads the Bedrock twin key from Secrets Manager, not plaintext")
        if self.runtime == "aws" and (
            self.allow_demo
            or not all([self.table, self.issuer, self.client_id, self.cognito_domain])
            or not self.app_url.startswith("https://")
        ):
            raise ValueError(
                "AWS requires Cognito, DynamoDB, an HTTPS application URL, and demo login disabled"
            )
        if self.real_enabled and not self.pairing_enabled:
            raise ValueError("Physical execution requires sim-to-real coordination to be enabled")
        if self.local_operator and (self.runtime != "local" or not self.allow_demo):
            raise ValueError("Local operator access exists only for the loopback demo")
        if self.runtime == "local" and self.allow_demo and len(self.secret) < 32:
            raise ValueError("Local demo requires a secret of at least 32 characters")

    @classmethod
    def from_env(cls):
        runtime = os.getenv("ACADEMY_RUNTIME", "local")
        allow_demo = os.getenv("ACADEMY_ALLOW_DEMO", "false").lower() == "true"
        data_path = os.getenv("ACADEMY_DATA_PATH", ".data/academy.sqlite")
        secret = ""
        if runtime == "local" and allow_demo:
            key_path = Path(data_path).parent / "dev-session.key"
            key_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as handle:
                    handle.write(secrets.token_urlsafe(48))
            except FileExistsError:
                pass
            secret = key_path.read_text()
        return cls(
            runtime=runtime,
            allow_demo=allow_demo,
            data_path=data_path,
            secret=secret,
            table=os.getenv("ACADEMY_TABLE", ""),
            issuer=os.getenv("ACADEMY_ISSUER", ""),
            client_id=os.getenv("ACADEMY_CLIENT_ID", ""),
            cognito_domain=os.getenv("ACADEMY_COGNITO_DOMAIN", ""),
            app_url=os.getenv("ACADEMY_APP_URL", "http://127.0.0.1:5173"),
            gateway_url=os.getenv("ACADEMY_GATEWAY_URL", ""),
            gateway_token=os.getenv("ACADEMY_GATEWAY_TOKEN", ""),
            remote_enabled=os.getenv("ACADEMY_REMOTE_ENABLED", "false").lower() == "true",
            connector_real_enabled=os.getenv("ACADEMY_CONNECTOR_REAL_ENABLED", "false").lower()
            == "true",
            self_signup_email_domains=tuple(
                json.loads(os.getenv("ACADEMY_SELF_SIGNUP_EMAIL_DOMAINS", "[]"))
            ),
            pairing_enabled=os.getenv("ACADEMY_PAIRING_ENABLED", "false").lower() == "true",
            real_enabled=os.getenv("ACADEMY_REAL_ENABLED", "false").lower() == "true",
            operator_group=os.getenv("ACADEMY_OPERATOR_GROUP", "lab-operators"),
            local_operator=os.getenv("ACADEMY_LOCAL_OPERATOR", "false").lower() == "true",
            twin_region=os.getenv("ACADEMY_TWIN_REGION", ""),
            twin_api_key=os.getenv("ACADEMY_TWIN_API_KEY", ""),
            twin_api_key_secret=os.getenv("ACADEMY_TWIN_API_KEY_SECRET", ""),
        )
