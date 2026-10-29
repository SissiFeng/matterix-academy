"""Local IPC/recovery tests, without importing Isaac or producing native evidence."""

import subprocess
import sys
import time
from copy import deepcopy
from uuid import uuid4

import pytest
from academy.gateway import GatewayUnavailable
from academy.native_files import FrameBuffer, alive_lease, read_json, write_json
from academy.native_media import relay_sdp
from academy.native_runner import NativeConfig, NativeFlexRunner
from academy.recipes import MixingPlan
from academy.remote_run import workflow_digest


def test_shared_frame_is_atomic_bounded_and_preserves_simulation_tick(tmp_path):
    writer = FrameBuffer(tmp_path / "frame.rgb", create=True)
    reader = FrameBuffer(tmp_path / "frame.rgb")
    assert reader.read() is None
    rgb = bytes([11, 22, 33]) * (960 * 540)
    writer.write(rgb, 55)
    pixels, tick, timestamp = reader.read()
    assert pixels == rgb and tick == 55
    assert abs(time.time() - timestamp) < 2
    with pytest.raises(ValueError):
        writer.write(rgb[:-1], 56)
    writer.memory[0:8] = (3).to_bytes(8, "little")
    assert reader.read() is None
    reader.close()
    writer.close()


def test_missing_or_expired_cloud_lease_stops_local_authority(tmp_path):
    assert not alive_lease(tmp_path)
    write_json(tmp_path / "lease.json", {"lease_expires": time.time() + 30})
    assert alive_lease(tmp_path)
    write_json(tmp_path / "lease.json", {"lease_expires": time.time() - 1})
    assert not alive_lease(tmp_path)


def test_relay_filter_never_advertises_host_or_server_reflexive_candidates():
    pytest.importorskip("aiortc")
    sdp = "v=0\r\na=candidate:1 1 UDP 123 192.168.1.2 5000 typ host generation 0\r\na=candidate:2 1 UDP 124 3.1.1.1 5000 typ srflx raddr 192.168.1.2\r\na=candidate:3 1 UDP 125 52.1.1.1 443 typ relay raddr 192.168.1.2\r\n"
    filtered = relay_sdp(sdp)
    assert " typ host " not in filtered and " typ srflx " not in filtered
    assert " typ relay " in filtered


def test_prepared_binding_recovers_read_only_and_never_reallocates(tmp_path, monkeypatch):
    cfg = NativeConfig(
        python="/prepared/python",
        matterix_root="/prepared/code",
        assets_root="/prepared/assets",
        assets_data_dir="/prepared/assets/data",
        engine_version="a" * 40,
        asset_version="b" * 40,
        run_root=str(tmp_path / "runs"),
        frame_root=str(tmp_path / "frames"),
    )
    config_path = tmp_path / "config.json"
    write_json(config_path, cfg.model_dump())
    runner = NativeFlexRunner(config_path, None)
    monkeypatch.setattr(NativeConfig, "verify", lambda _: None)
    plan = MixingPlan()
    local = {
        "allocation_id": str(uuid4()),
        "run": {
            "run_id": str(uuid4()),
            "plan": plan.model_dump(mode="json"),
            "plan_hash": workflow_digest(plan),
        },
    }
    binding = runner.prepare(local)
    assert runner.prepare(local, recovering=True) == binding
    changed = deepcopy(local)
    changed["allocation_id"] = str(uuid4())
    with pytest.raises(GatewayUnavailable):
        runner.prepare(changed, recovering=True)
    with pytest.raises(FileExistsError):
        runner.prepare(local)
    assert read_json(runner.folder(local) / "binding.json") == binding


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "100.119.227.39",
        "::1",
        "fe80::1",
        "224.0.0.1",
        "device.local",
    ],
)
def test_untrusted_relay_label_cannot_target_private_addresses(address):
    pytest.importorskip("aiortc")
    from academy.native_media import public_relay_candidate

    with pytest.raises(ValueError):
        public_relay_candidate(f"candidate:1 1 UDP 123 {address} 5000 typ relay generation 0")


def test_publisher_gatherer_never_receives_local_interfaces(monkeypatch):
    pytest.importorskip("aiortc")
    import asyncio

    from academy.native_media import enforce_publisher_relay
    from aioice import Connection
    from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, VideoStreamTrack

    calls = []

    async def gather(self, component, addresses, timeout=5):
        calls.append(addresses)
        return []

    monkeypatch.setattr(Connection, "get_component_candidates", gather)

    async def verify():
        peer = RTCPeerConnection(
            RTCConfiguration(
                iceServers=[
                    RTCIceServer(
                        urls="turn:example.org:443", username="fixture", credential="fixture"
                    )
                ]
            )
        )
        peer.addTrack(VideoStreamTrack())
        enforce_publisher_relay(peer)
        connection = peer.getTransceivers()[0].sender.transport.transport.iceGatherer._connection
        await connection.get_component_candidates(1, ["10.0.0.1", "127.0.0.1"])
        await peer.close()

    asyncio.run(verify())
    assert calls == [[]]


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\r"])
def test_sdp_line_endings_cannot_bypass_candidate_checks(separator):
    pytest.importorskip("aiortc")
    with pytest.raises(ValueError):
        relay_sdp(
            separator.join(
                ["v=0", "a=candidate:1 1 UDP 123 internal.local 5000 typ relay generation 0", ""]
            )
        )


def test_native_assets_reject_untracked_overrides_and_external_data(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    data = assets / "data"
    data.mkdir()
    (data / "fixture.usda").write_text("#usda 1.0\n")
    subprocess.run(["git", "init", "-q", str(assets)], check=True)
    subprocess.run(["git", "add", "data"], cwd=assets, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.org",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=assets,
        check=True,
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=assets, text=True).strip()
    config = NativeConfig(
        python=sys.executable,
        matterix_root=str(assets),
        assets_root=str(assets),
        assets_data_dir=str(data),
        engine_version=head,
        asset_version=head,
        run_root=str(tmp_path / "runs"),
        frame_root=str(tmp_path / "frames"),
    )
    config.verify()
    (data / "untracked.usda").write_text("#usda 1.0\n")
    with pytest.raises(GatewayUnavailable, match="pinned"):
        config.verify()
    (data / "untracked.usda").unlink()
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(GatewayUnavailable, match="belong to the pinned assets"):
        config.model_copy(update={"assets_data_dir": str(other)}).verify()
