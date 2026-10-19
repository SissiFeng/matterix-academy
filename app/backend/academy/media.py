"""Run-scoped, view-only WebRTC grants. AWS credentials never leave the API.

The publisher must enforce the short viewer allowlist even on an established
peer connection. A signaling URL expiry alone does not revoke WebRTC media.
"""

import os
from urllib.parse import urlencode
from uuid import UUID

import boto3
from botocore.auth import SigV4QueryAuth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from pydantic import Field

from .models import StrictModel
from .runs import TERMINAL, RunService, revised
from .store import Conflict, Write

MEDIA = "system#media"
VIEWERS = "system#viewers"
VIEWER_SECONDS = 35


class ViewerRequest(StrictModel):
    client_id: UUID
    frame_received: bool = False
    frames_decoded: int = Field(default=0, ge=0, le=10000000)


class KinesisTransport:
    def __init__(self, prefix, session=None):
        self.prefix = prefix
        self.session = session or boto3.Session()
        self.region = self.session.region_name
        self.client = self.session.client("kinesisvideo")

    def ensure(self, native_id):
        name = self.prefix + str(UUID(native_id))
        try:
            return self.client.describe_signaling_channel(ChannelName=name)["ChannelInfo"][
                "ChannelARN"
            ]
        except self.client.exceptions.ResourceNotFoundException:
            try:
                return self.client.create_signaling_channel(
                    ChannelName=name,
                    SingleMasterConfiguration={"MessageTtlSeconds": 60},
                )["ChannelARN"]
            except self.client.exceptions.ResourceInUseException:
                return self.client.describe_signaling_channel(ChannelName=name)["ChannelInfo"][
                    "ChannelARN"
                ]

    def grant(self, arn, role, client_id=None):
        endpoints = {
            item["Protocol"]: item["ResourceEndpoint"]
            for item in self.client.get_signaling_channel_endpoint(
                ChannelARN=arn,
                SingleMasterChannelEndpointConfiguration={
                    "Protocols": ["WSS", "HTTPS"],
                    "Role": role,
                },
            )["ResourceEndpointList"]
        }
        signaling = self.session.client("kinesis-video-signaling", endpoint_url=endpoints["HTTPS"])
        args = {"ChannelARN": arn, "Service": "TURN"}
        if client_id:
            args["ClientId"] = client_id
        turn = signaling.get_ice_server_config(**args)["IceServerList"]
        params = {"X-Amz-ChannelARN": arn}
        if client_id:
            params["X-Amz-ClientId"] = client_id
        request = AWSRequest(
            method="GET",
            url=endpoints["WSS"].replace("wss://", "https://", 1) + "?" + urlencode(params),
        )
        SigV4QueryAuth(
            self.session.get_credentials().get_frozen_credentials(),
            "kinesisvideo",
            self.region,
            expires=299,
        ).add_auth(request)
        return {
            "signaling_url": request.url.replace("https://", "wss://", 1),
            "ice_servers": [
                {
                    "urls": server["Uris"],
                    "username": server["Username"],
                    "credential": server["Password"],
                }
                for server in turn
            ],
            "region": self.region,
        }

    def delete(self, arn):
        try:
            self.client.delete_signaling_channel(ChannelARN=arn)
        except self.client.exceptions.ResourceNotFoundException:
            pass


class MediaService:
    def __init__(self, runs: RunService, transport=None):
        self.runs, self.store = runs, runs.store
        self.transport = transport

    def backend(self):
        if self.transport is None:
            prefix = os.getenv("ACADEMY_MEDIA_PREFIX", "")
            if not prefix:
                raise HTTPException(503, "Live viewport is not qualified for this deployment")
            self.transport = KinesisTransport(prefix)
        return self.transport

    def active(self, run):
        worker = self.store.get("system#workers", run.get("worker_id", ""))
        if (
            not worker
            or not self.runs.execution_allowed(worker, run)
            or not run.get("binding")
            or run["status"] in TERMINAL
        ):
            raise HTTPException(409, "This run has no active viewport")
        self.runs.owned(run["worker_id"], run["run_id"], run["claim_token"])
        if run["plan"]["course_id"] != "flex-mixing":
            raise HTTPException(409, "This scene has no qualified viewport")

    def publisher(self, worker_id, run_id, claim_token):
        _, run = self.runs.owned(worker_id, run_id, claim_token)
        self.active(run)
        key = run["run_id"]
        native_id = run["binding"]["native_session_id"]
        record = self.store.get(MEDIA, key)
        if record is None:
            # Persist provisioning intent before any AWS mutation. Reaper can
            # resolve the deterministic name after a lost create response.
            record = dict(
                version=1,
                run_id=key,
                native_session_id=native_id,
                channel_arn=None,
                deadline=run["deadline"],
            )
            try:
                self.store.put(MEDIA, key, record, None)
            except Conflict:
                record = self.store.get(MEDIA, key)
        if record["native_session_id"] != native_id:
            raise HTTPException(409, "Viewport allocation changed")
        if not record["channel_arn"]:
            arn = self.backend().ensure(native_id)
            updated = revised(record, channel_arn=arn)
            self.store.put(MEDIA, key, updated, record["version"])
            record = updated
        # Creation can take time: recheck the lease before issuing credentials.
        self.active(self.runs.raw(run_id))
        return self.backend().grant(record["channel_arn"], "MASTER") | {
            "run_id": key,
            "native_session_id": native_id,
            "plan_hash": run["plan_hash"],
        }

    def viewer(
        self, owner, run_id, client_id, *, connect=True, frame_received=False, frames_decoded=0
    ):
        self.runs.get(owner, run_id)  # 404 before any media information is returned.
        run = self.runs.raw(run_id)
        self.active(run)
        record = self.store.get(MEDIA, run["run_id"])
        if (
            not record
            or not record["channel_arn"]
            or record["native_session_id"] != run["binding"]["native_session_id"]
        ):
            raise HTTPException(409, "Isaac is preparing the live viewport")
        key = run["run_id"]
        old = self.store.get(VIEWERS, key)
        if not connect and (not old or old["client_id"] != str(client_id)):
            raise HTTPException(409, "This viewer was replaced; reconnect to take over viewing")
        next_viewer = dict(
            version=(old["version"] if old else 0) + 1,
            client_id=str(client_id),
            frame_received=bool(not connect and (frame_received or old.get("frame_received"))),
            expires=min(self.runs.clock() + VIEWER_SECONDS, run["lease_expires"], run["deadline"]),
        )
        self.store.put(VIEWERS, key, next_viewer, old["version"] if old else None)
        if run.get("commissioning_id") and frame_received and frames_decoded > 0:
            # Persist separately: the ordinary media reaper may remove viewer grants.
            proof = self.store.get("system#browser-evidence", key)
            proof_record = {
                "version": (proof["version"] if proof else 0) + 1,
                "run_id": key,
                "native_session_id": run["binding"]["native_session_id"],
                "plan_hash": run["plan_hash"],
                "source": "browser-report",
                "frames_decoded": max(frames_decoded, (proof or {}).get("frames_decoded", 0)),
                "observed_at": self.runs.clock(),
            }
            self.store.put(
                "system#browser-evidence", key, proof_record, proof["version"] if proof else None
            )
        binding = dict(
            run_id=key,
            session_id=run["session_id"],
            native_session_id=record["native_session_id"],
            plan_hash=run["plan_hash"],
            client_id=str(client_id),
            expires=next_viewer["expires"],
        )
        return binding | (
            self.backend().grant(record["channel_arn"], "VIEWER", str(client_id)) if connect else {}
        )

    def viewers(self, worker_id, run_id, claim_token):
        _, run = self.runs.owned(worker_id, run_id, claim_token)
        self.active(run)
        viewer = self.store.get(VIEWERS, run["run_id"])
        return {
            "run_id": run["run_id"],
            "native_session_id": run["binding"]["native_session_id"],
            "lease_expires": min(run["lease_expires"], run["deadline"]),
            "viewers": [viewer] if viewer and viewer["expires"] > self.runs.clock() else [],
        }

    def reap(self):
        count = 0
        for record in self.store.partition(MEDIA):
            run = self.runs.raw(record["run_id"])
            worker = self.store.get("system#workers", run["worker_id"])
            if (
                run["status"] not in TERMINAL
                and worker
                and not worker.get("revoked")
                and min(run["lease_expires"], record["deadline"]) > self.runs.clock()
            ):
                continue
            try:
                # A provisioning intent may have survived a lost AWS response.
                arn = record["channel_arn"] or self.backend().ensure(record["native_session_id"])
                self.backend().delete(arn)
                viewer = self.store.get(VIEWERS, record["run_id"])
                writes = [Write(MEDIA, record["run_id"], None, record["version"])]
                if viewer:
                    writes.append(Write(VIEWERS, record["run_id"], None, viewer["version"]))
                self.store.transact(writes)
                count += 1
            except (Conflict, ClientError):
                continue  # Durable intent remains for the next reaper invocation.
        return count
