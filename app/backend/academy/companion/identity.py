"""Bounded, read-only SiLA property checks. Never instantiate a robot controller.

Uses the standard SiLA String/Boolean wire wrappers and grpcio's public client.
Only three fixed property RPCs are callable; there is no command dispatch path.
"""

import hashlib
import importlib.metadata
from urllib.parse import urlsplit

from .config import RobotProfile, digest

GRPC_VERSION = "1.81.1"
SERVICE = "/sila2.org.silastandard.core.silaservice.v1.SiLAService/"


def _fields(data: bytes) -> list[tuple[int, int, bytes | int]]:
    if len(data) > 65536:
        raise ValueError("SiLA property exceeds bounded response size")
    cursor = 0

    def varint():
        nonlocal cursor
        value = 0
        for shift in range(0, 70, 7):
            if cursor >= len(data):
                raise ValueError("Truncated SiLA property")
            byte = data[cursor]
            cursor += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError("Invalid SiLA varint")

    fields = []
    while cursor < len(data):
        tag = varint()
        number, wire = tag >> 3, tag & 7
        if number != 1 or wire not in {0, 2}:
            raise ValueError("Unexpected SiLA property schema")
        if wire == 0:
            value = varint()
        else:
            length = varint()
            if length > len(data) - cursor:
                raise ValueError("Truncated SiLA wrapper")
            value = data[cursor : cursor + length]
            cursor += length
        fields.append((number, wire, value))
    return fields


def strings(data: bytes) -> list[str]:
    result = []
    for _, wire, wrapper in _fields(data):
        if wire != 2 or not isinstance(wrapper, bytes):
            raise ValueError("SiLA String wrapper required")
        fields = _fields(wrapper)
        if len(fields) != 1 or fields[0][1] != 2 or not isinstance(fields[0][2], bytes):
            raise ValueError("SiLA String value required")
        result.append(fields[0][2].decode("utf-8"))
    if not result:
        raise ValueError("Empty SiLA identity property")
    return result


def boolean(data: bytes) -> bool:
    outer = _fields(data)
    if len(outer) != 1 or outer[0][1] != 2 or not isinstance(outer[0][2], bytes):
        raise ValueError("SiLA Boolean wrapper required")
    inner = _fields(outer[0][2])
    if not inner:  # Protobuf default false inside an explicitly present wrapper.
        return False
    if len(inner) != 1 or inner[0][1] != 0 or inner[0][2] not in {0, 1}:
        raise ValueError("SiLA Boolean value required")
    return bool(inner[0][2])


def probe_sila(robot_url: str, profile: RobotProfile, certificate: bytes | None = None):
    try:
        version = importlib.metadata.version("grpcio")
    except importlib.metadata.PackageNotFoundError:
        raise RuntimeError("Install the reviewed pinned SiLA identity client dependency") from None
    if version != GRPC_VERSION:
        raise RuntimeError("SiLA identity client grpcio version is not qualified")
    import grpc

    host = urlsplit(robot_url).hostname
    address = f"[{host}]:{profile.sila_port}" if ":" in host else f"{host}:{profile.sila_port}"
    if profile.sila_tls:
        if (
            certificate is None
            or hashlib.sha256(certificate).hexdigest() != profile.sila_certificate_sha256
        ):
            raise ValueError("Local SiLA certificate fingerprint mismatch")
        channel = grpc.secure_channel(
            address, grpc.ssl_channel_credentials(root_certificates=certificate)
        )
    else:
        channel = grpc.insecure_channel(address)
    with channel:
        grpc.channel_ready_future(channel).result(timeout=10)

        def read(path):
            return channel.unary_unary(path)(b"", timeout=10)

        server_uuid = strings(read(SERVICE + "Get_ServerUUID"))
        if server_uuid != [str(profile.sila_server_uuid)]:
            raise ValueError("SiLA server identity differs from qualification")
        features = strings(read(SERVICE + "Get_ImplementedFeatures"))
        if digest({"features": sorted(features)}) != profile.sila_features_sha256:
            raise ValueError("SiLA feature identity differs from qualification")
        version = "v2" if profile.instrument == "flex" else "v1"
        path = f"/sila2.ca.accelerationconsortium.robots.motioncontroller.{version}.MotionController/Get_IsSimulating"
        if boolean(read(path)):
            raise ValueError("A simulated SiLA connector cannot authorize physical execution")
