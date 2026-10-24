"""Local-only trust configuration and robot qualification; no cloud-selected endpoints."""

import hashlib
import ipaddress
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from academy.models import StrictModel

DIGEST = r"^[a-f0-9]{64}$"
COMMIT = r"^[a-f0-9]{40}$"
IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
PIPETTES = {
    "flex_1channel_1000": ("flex", 5, 1000),
    "flex_1channel_50": ("flex", 1, 50),
    "p20_single_gen2": ("ot2", 1, 20),
    "p300_single_gen2": ("ot2", 20, 300),
    "p1000_single_gen2": ("ot2", 100, 1000),
}


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def private_directory(path: Path) -> Path:
    path = path.absolute()
    # Refuse symlink ancestors as well as a redirected final state directory.
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Private state path must not contain symlinks")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Private state directory must be owned by this user with mode 0700")
    return path


def read_private(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Local credentials/configuration must be user-owned mode 0600")
        if info.st_size > 4_000_000:
            raise ValueError("Local file exceeds size limit")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read(4_000_001)
    finally:
        os.close(fd)


def check_private_database(path: Path) -> None:
    """Check protected durable state without reading it or imposing a secret-file size limit."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Local database must be user-owned mode 0600")
    finally:
        os.close(fd)


def write_private(path: Path, value: dict) -> None:
    private_directory(path.parent)
    # No overwrite avoids credential replacement after an uncertain pairing response.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def validate_url(value: str, *, robot: bool, dev: bool = False) -> str:
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Endpoint must not contain credentials, query or fragment")
    if parsed.path not in {"", "/"} or not parsed.hostname:
        raise ValueError("Endpoint must be an origin, without a path")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        ip = None
    if robot:
        # Literal addresses avoid DNS rebinding; allow only local/private attached networks.
        allowed = ip and (
            ip.is_loopback
            or ip.is_link_local
            or any(
                ip in ipaddress.ip_network(net)
                for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
                if ip.version == ipaddress.ip_network(net).version
            )
        )
        if not allowed or parsed.scheme not in {"http", "https"}:
            raise ValueError("Robot endpoint requires a local/private literal IP address")
    elif parsed.scheme != "https":
        if not (dev and parsed.scheme == "http" and ip and ip.is_loopback):
            raise ValueError("Academy requires HTTPS; loopback HTTP needs explicit dev opt-in")
    elif ip and not ip.is_global:
        raise ValueError("Production Academy endpoint must be public HTTPS")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid endpoint port")
    return value.rstrip("/")


class Labware(StrictModel):
    load_name: str = Field(pattern=IDENTIFIER)
    namespace: str = Field(pattern=IDENTIFIER)
    version: int = Field(ge=1)
    sha256: str = Field(pattern=DIGEST)
    definition: dict
    slot: str

    @model_validator(mode="after")
    def exact_definition(self):
        d = self.definition
        if digest(d) != self.sha256:
            raise ValueError("Labware definition checksum mismatch")
        if (d.get("parameters", {}).get("loadName"), d.get("namespace"), d.get("version")) != (
            self.load_name,
            self.namespace,
            self.version,
        ):
            raise ValueError("Labware load name/namespace/version mismatch")
        if not isinstance(d.get("wells"), dict) or not d["wells"]:
            raise ValueError("Labware must define wells")
        return self


class RobotProfile(StrictModel):
    schema_version: Literal[1] = 1
    qualification_id: str = Field(min_length=1, max_length=128)
    qualified_by: str = Field(min_length=1, max_length=128)
    qualified_until: AwareDatetime
    instrument: Literal["flex", "ot2"]
    serial: str = Field(pattern=IDENTIFIER)
    source_commit: str = Field(pattern=COMMIT)
    release_id: str = Field(pattern=IDENTIFIER)
    artifact_sha256: str = Field(pattern=DIGEST)
    firmware: str = Field(min_length=1, max_length=128)
    api_version: str = Field(min_length=1, max_length=128)
    runtime_contract_id: str = Field(min_length=1, max_length=256)
    runtime_release_id: str = Field(pattern=IDENTIFIER)
    runtime_bundle_sha256: str = Field(pattern=DIGEST)
    connector_version: str = Field(min_length=1, max_length=64)
    calibration_sha256: str = Field(pattern=DIGEST)
    sila_port: int = Field(default=50051, ge=1, le=65535)
    sila_tls: bool = True
    sila_certificate_sha256: str | None = Field(default=None, pattern=DIGEST)
    sila_server_uuid: UUID
    sila_features_sha256: str = Field(pattern=DIGEST)
    protocol_api: Literal["2.20"] = "2.20"
    pipette_model: str
    pipette_mount: Literal["left", "right"]
    pipette_serial: str = Field(pattern=IDENTIFIER)
    min_volume_ul: float = Field(gt=0)
    max_volume_ul: float = Field(gt=0)
    labware: dict[str, Labware]
    tip_wells: list[str] = Field(min_length=1, max_length=96)
    stock_well: str
    capacity_ul: dict[str, float]
    calibration_confirmed: Literal[True]
    deck_confirmed: Literal[True]

    @model_validator(mode="after")
    def valid_profile(self):
        if self.pipette_model not in PIPETTES:
            raise ValueError("Pipette model is not supported by this constrained compiler")
        instrument, low, high = PIPETTES[self.pipette_model]
        if (
            instrument != self.instrument
            or not low <= self.min_volume_ul <= self.max_volume_ul <= high
        ):
            raise ValueError("Pipette model or volume limits do not match instrument")
        if set(self.labware) != {"tips", "stock", "plate"}:
            raise ValueError("Explicit qualified tips, stock and plate definitions are required")
        if set(self.capacity_ul) != {"stock", "A1", "A2", "A3"}:
            raise ValueError("Qualify every source/destination capacity")
        if len(set(self.tip_wells)) != len(self.tip_wells):
            raise ValueError("Fresh tip positions must be unique")
        if not self.labware["tips"].definition.get("parameters", {}).get("isTiprack"):
            raise ValueError("Qualified tips must be a tip rack")
        for name in self.tip_wells:
            if name not in self.labware["tips"].definition["wells"]:
                raise ValueError("Tip position absent from definition")
        for logical, cap in self.capacity_ul.items():
            definition = self.labware["stock" if logical == "stock" else "plate"].definition
            name = self.stock_well if logical == "stock" else logical
            well = definition["wells"].get(name, {})
            actual = well.get("totalLiquidVolume", 0)
            if not isinstance(actual, (int, float)) or not 0 < cap <= actual:
                raise ValueError("Qualified capacity exceeds labware well definition")
        return self

    def assert_current(self):
        if self.qualified_until <= datetime.now(UTC):
            raise ValueError("Local hardware qualification has expired")

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class LocalConfig(StrictModel):
    academy_url: str
    allowed_academy_origins: list[str] = Field(min_length=1, max_length=4)
    robot_url: str
    loopback_development: bool = False
    profile: RobotProfile
    sila_certificate_file: str | None = None

    @model_validator(mode="after")
    def endpoints(self):
        self.academy_url = validate_url(
            self.academy_url, robot=False, dev=self.loopback_development
        )
        allowed = [
            validate_url(v, robot=False, dev=self.loopback_development)
            for v in self.allowed_academy_origins
        ]
        if self.academy_url not in allowed:
            raise ValueError("Academy origin is not locally allowlisted")
        self.robot_url = validate_url(self.robot_url, robot=True)
        return self
