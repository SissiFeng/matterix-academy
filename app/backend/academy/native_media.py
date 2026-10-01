"""Read-only Isaac RGB publisher using KVS signaling and its TURN relay.

Runs outside the Isaac Python environment. The short cloud allowlist is checked
throughout each connection, including after signaling URLs have expired.
"""

import argparse
import asyncio
import base64
import ipaddress
import json
import time
import types
from pathlib import Path

from .native_files import FrameBuffer, alive_lease, read_json, write_json


def encode(payload):
    return base64.b64encode(json.dumps(payload).encode()).decode()


def public_relay_candidate(value):
    from aiortc.sdp import candidate_from_sdp

    candidate = candidate_from_sdp(value.removeprefix("candidate:"))
    address = ipaddress.ip_address(candidate.ip)
    if (
        candidate.type != "relay"
        or candidate.protocol.lower() != "udp"
        or candidate.component != 1
        or not 0 < candidate.port < 65536
        or not address.is_global
        or address.is_multicast
    ):
        raise ValueError("Only public relay candidates are allowed")
    return candidate


def relay_sdp(sdp):
    lines = []
    for line in sdp.splitlines():
        if line.startswith("a=candidate:"):
            if " typ relay " not in line:
                continue
            public_relay_candidate(line.removeprefix("a="))
        lines.append(line)
    return "\r\n".join(lines) + "\r\n"


def enforce_publisher_relay(peer):
    """Version-pinned aiortc adapter: create no host ICE socket/protocol.

    aiortc 1.14 has no public iceTransportPolicy argument. Merely filtering SDP
    leaves aioice's host protocols able to send private-network probes. The
    pinned candidate hook passes no local interfaces to aioice's gatherer, so
    only its AWS TURN transport is constructed. Tests assert this boundary.
    """
    from importlib.metadata import version

    from aioice.ice import TransportPolicy

    if version("aiortc") != "1.14.0" or version("aioice") != "0.10.2":
        raise RuntimeError("Requalify the relay adapter after upgrading aiortc/aioice")
    for transceiver in peer.getTransceivers():
        connection = transceiver.sender.transport.transport.iceGatherer._connection
        if connection._local_candidates_start or not connection.turn_server:
            raise RuntimeError("A fresh TURN-configured ICE transport is required")
        connection._transport_policy = TransportPolicy.RELAY
        connection.stun_server = None
        original = connection.get_component_candidates

        async def gather(_self, component, addresses, timeout=5, _original=original):
            return await _original(component=component, addresses=[], timeout=timeout)

        connection.get_component_candidates = types.MethodType(gather, connection)


async def publish(folder):
    import av
    import numpy as np
    import websockets
    from aiortc import (
        RTCConfiguration,
        RTCIceServer,
        RTCPeerConnection,
        RTCSessionDescription,
        VideoStreamTrack,
    )

    manifest = read_json(folder / "manifest.json")
    binding = manifest["binding"]
    frame_path = Path(manifest["config"]["frame_root"]) / (binding["native_session_id"] + ".rgb")
    peers = {}
    frame_buffer = None

    def allowed(client_id):
        if not alive_lease(folder):
            return False
        lease = read_json(folder / "lease.json")
        return lease["native_session_id"] == binding["native_session_id"] and any(
            viewer["client_id"] == client_id and viewer["expires"] > time.time()
            for viewer in lease["viewers"]
        )

    class ViewportTrack(VideoStreamTrack):
        async def recv(self):
            nonlocal frame_buffer
            pts, time_base = await self.next_timestamp()
            while alive_lease(folder):
                if frame_buffer is None and frame_path.exists():
                    frame_buffer = FrameBuffer(frame_path)
                sample = frame_buffer.read() if frame_buffer else None
                if sample and time.time() - sample[2] < 5:
                    pixels, _, _ = sample
                    frame = av.VideoFrame.from_ndarray(
                        np.frombuffer(pixels, dtype=np.uint8).reshape(540, 960, 3), format="rgb24"
                    )
                    frame.pts, frame.time_base = pts, time_base
                    return frame
                await asyncio.sleep(0.03)
            from aiortc.mediastreams import MediaStreamError

            raise MediaStreamError

    grant = read_json(folder / "publisher.json")
    if (
        grant["native_session_id"] != binding["native_session_id"]
        or grant["run_id"] != manifest["request"]["run_id"]
    ):
        raise ValueError("Publisher identity mismatch")
    config = RTCConfiguration(
        iceServers=[RTCIceServer(**server) for server in grant["ice_servers"]]
    )
    async with websockets.connect(
        grant["signaling_url"], max_size=32768, ping_interval=20
    ) as socket:

        async def monitor():
            while alive_lease(folder) and not (folder / "stop-media.json").exists():
                for client_id, peer in list(peers.items()):
                    if not allowed(client_id):
                        await peer.close()
                        peers.pop(client_id, None)
                write_json(
                    folder / "viewer-ready.json",
                    {
                        "native_session_id": binding["native_session_id"],
                        "observed_at": time.time(),
                        "connected": any(
                            peer.connectionState == "connected"
                            and any(
                                v["client_id"] == client_id and v.get("frame_received")
                                for v in read_json(folder / "lease.json")["viewers"]
                            )
                            for client_id, peer in peers.items()
                        ),
                    },
                )
                await asyncio.sleep(0.5)
            await socket.close()

        watchdog = asyncio.create_task(monitor())
        try:
            async for raw in socket:
                pending_peer = None
                client_id = None
                try:
                    message = json.loads(raw)
                    client_id = str(message.get("senderClientId", ""))
                    kind = message.get("messageType")
                    if not client_id:
                        continue
                    # The cloud grant can precede the next worker allowlist copy.
                    # Bound the wait without accepting an unauthorized SDP.
                    deadline = time.monotonic() + 8
                    while (
                        kind == "SDP_OFFER"
                        and not allowed(client_id)
                        and alive_lease(folder)
                        and time.monotonic() < deadline
                    ):
                        await asyncio.sleep(0.1)
                    if not allowed(client_id):
                        continue
                    payload = json.loads(base64.b64decode(message["messagePayload"], validate=True))
                    if kind == "SDP_OFFER":
                        sdp = payload.get("sdp", "")
                        if (
                            payload.get("type") != "offer"
                            or sdp.count("m=video") != 1
                            or "m=audio" in sdp
                            or "m=application" in sdp
                            or "a=recvonly" not in sdp
                            or "a=rtcp-mux" not in sdp
                        ):
                            continue
                        pending_peer = RTCPeerConnection(configuration=config)
                        pending_peer.addTrack(ViewportTrack())
                        enforce_publisher_relay(pending_peer)
                        await pending_peer.setRemoteDescription(
                            RTCSessionDescription(sdp=relay_sdp(sdp), type="offer")
                        )
                        await pending_peer.setLocalDescription(await pending_peer.createAnswer())
                        if not allowed(client_id):
                            await pending_peer.close()
                            continue
                        # Replace only after complete validation/negotiation.
                        for old in list(peers.values()):
                            await old.close()
                        peers.clear()
                        peers[client_id] = pending_peer
                        peer = pending_peer
                        pending_peer = None
                        await socket.send(
                            json.dumps(
                                {
                                    "action": "SDP_ANSWER",
                                    "recipientClientId": client_id,
                                    "messagePayload": encode(
                                        {
                                            "type": "answer",
                                            "sdp": relay_sdp(peer.localDescription.sdp),
                                        }
                                    ),
                                }
                            )
                        )
                    elif kind == "ICE_CANDIDATE" and client_id in peers:
                        candidate = public_relay_candidate(payload.get("candidate", ""))
                        candidate.sdpMid = payload.get("sdpMid")
                        candidate.sdpMLineIndex = payload.get("sdpMLineIndex")
                        await peers[client_id].addIceCandidate(candidate)
                except Exception:
                    # Malformed viewer input must not kill the shared simulator.
                    # Do not log signaling payloads, addresses or credentials.
                    if pending_peer is not None:
                        await pending_peer.close()
                    else:
                        bad_peer = peers.pop(client_id, None)
                        if bad_peer is not None:
                            await bad_peer.close()

        finally:
            watchdog.cancel()
            await asyncio.gather(watchdog, return_exceptions=True)
            for peer in peers.values():
                await peer.close()
            if frame_buffer:
                frame_buffer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True)
    args = parser.parse_args()
    # Avoid logging exceptions that may include signed signaling URLs.
    try:
        asyncio.run(publish(Path(args.folder)))
    except Exception:
        raise SystemExit("Native media stopped; inspect connectivity and grant validity") from None


if __name__ == "__main__":
    main()
