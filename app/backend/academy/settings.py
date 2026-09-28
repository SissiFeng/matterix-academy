import os
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

    def __post_init__(self):
        if self.runtime not in {"local", "aws"}:
            raise ValueError("ACADEMY_RUNTIME must be local or aws")
        if self.runtime == "aws" and (
            self.allow_demo
            or not all([self.table, self.issuer, self.client_id, self.cognito_domain])
            or not self.app_url.startswith("https://")
        ):
            raise ValueError(
                "AWS requires Cognito, DynamoDB, an HTTPS application URL, and demo login disabled"
            )
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
        )
