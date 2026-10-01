"""Verify AWS signaling/TURN credentials, not Isaac or native run acceptance.

Creates one short-lived channel in the existing account/region and deletes it
in finally. Never prints signed URLs, TURN credentials or AWS session tokens.
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

import boto3
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/backend"))
from academy.media import KinesisTransport


async def main():
    session = boto3.Session(profile_name=os.environ["AWS_PROFILE"], region_name="ca-central-1")
    if session.client("sts").get_caller_identity()["Account"] != "247893369214":
        raise RuntimeError("Wrong AWS account")
    backend = KinesisTransport("matterix-academy-dev-sim-", session)
    arn = backend.ensure(str(uuid4()))
    try:
        for role in ("MASTER", "VIEWER"):
            grant = backend.grant(arn, role, str(uuid4()) if role == "VIEWER" else None)
            assert grant["ice_servers"]
            async with websockets.connect(grant["signaling_url"], open_timeout=15):
                print(role + " signaling authenticated; TURN credentials issued", flush=True)
    finally:
        backend.delete(arn)
        print("Temporary signaling channel deleted", flush=True)


try:
    asyncio.run(main())
except Exception as exc:
    print("AWS signaling probe failed: " + type(exc).__name__, file=sys.stderr)
    raise SystemExit(1) from None
