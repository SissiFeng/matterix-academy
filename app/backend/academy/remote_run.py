"""Proposed whole-workflow contract, independent of synthetic teaching execution.

These types validate gateway reports; they do not produce native observations or
implement a runner. No student execution route is enabled by this module.
"""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .models import Experiment, StrictModel

TERMINAL_SNAPSHOT_STATUSES = frozenset({"completed", "failed", "unknown"})


def workflow_digest(experiment: Experiment) -> str:
    """Bind the complete normalized plan, including layout and starting volumes."""
    encoded = json.dumps(
        experiment.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class RemoteRunRequest(StrictModel):
    run_id: UUID
    expected_revision: int = Field(ge=1)
    experiment: Experiment
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def plan_matches_hash(self):
        if workflow_digest(self.experiment) != self.plan_hash:
            raise ValueError("The workflow does not match its saved plan hash")
        return self


class RemoteStepProgress(StrictModel):
    index: int = Field(ge=0, lt=64)
    status: Literal["pending", "running", "completed", "failed", "unknown"]
    completed_at: AwareDatetime | None = None
    observation_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def completed_requires_observation(self):
        confirmed = self.completed_at is not None and self.observation_revision is not None
        if self.status == "completed" and not confirmed:
            raise ValueError(
                "Completed steps require a native confirmation and observation revision"
            )
        if self.status != "completed" and (
            self.completed_at is not None or self.observation_revision is not None
        ):
            raise ValueError("Unfinished steps cannot report completion evidence")
        return self


class RemoteNativeState(StrictModel):
    """Null means unobserved, never zero or a value filled by the teaching model."""

    revision: int = Field(ge=1)
    observed_at: AwareDatetime
    simulation_tick: int = Field(ge=0)
    pipette_volume_ul: float | None = Field(default=None, ge=0)
    tip_attached: bool | None = None
    well_volumes_ul: dict[Literal["stock", "A1", "A2", "A3"], float | None]

    @model_validator(mode="after")
    def volumes_are_nonnegative(self):
        if set(self.well_volumes_ul) != {"stock", "A1", "A2", "A3"}:
            raise ValueError("Report each well explicitly, using null for unavailable observations")
        if any(value is not None and value < 0 for value in self.well_volumes_ul.values()):
            raise ValueError("Native liquid volumes cannot be negative")
        return self


class RemoteRunSnapshot(StrictModel):
    session_id: UUID
    run_id: UUID
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    sequence: int = Field(ge=0)
    session_revision: int = Field(ge=1)
    engine: Literal["matterix"]
    evidence: Literal["native"]
    simulation_only: Literal[True]
    engine_version: str = Field(min_length=1, max_length=100)
    asset_version: str = Field(min_length=1, max_length=100)
    status: Literal[
        "queued",
        "loading",
        "running",
        "pause_requested",
        "paused",
        "completed",
        "failed",
        "unknown",
    ]
    observed_at: AwareDatetime
    steps: list[RemoteStepProgress] = Field(min_length=1, max_length=64)
    native_state: RemoteNativeState | None
    error: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def progress_is_consistent(self):
        prefix = True
        active_seen = False
        previous_confirmation = None
        for index, step in enumerate(self.steps):
            if step.index != index:
                raise ValueError("Progress must cover the full workflow in order")
            if step.status == "completed":
                if not prefix:
                    raise ValueError("A later step cannot complete before an earlier step")
                if step.completed_at > self.observed_at:
                    raise ValueError("Completion cannot be later than the snapshot")
                if step.observation_revision > self.session_revision:
                    raise ValueError("Completion refers to an unavailable session revision")
                if previous_confirmation is not None and (
                    step.completed_at < previous_confirmation.completed_at
                    or step.observation_revision < previous_confirmation.observation_revision
                ):
                    raise ValueError("Sequential step confirmations cannot move backward")
                previous_confirmation = step
            else:
                prefix = False
                if step.status != "pending":
                    if active_seen or index != self.completed_steps:
                        raise ValueError("Only the next unfinished step can be active")
                    active_seen = True
        if self.status == "completed" and self.completed_steps != len(self.steps):
            raise ValueError("Run completion requires every step to be confirmed")
        if self.status in {"queued", "loading"} and any(s.status != "pending" for s in self.steps):
            raise ValueError("A queued or loading run cannot report executed steps")
        if self.status == "failed" and self.error is None:
            raise ValueError("Failed runs require an explanation")
        if any(s.status == "failed" for s in self.steps) and self.status not in {
            "failed",
            "unknown",
        }:
            raise ValueError("A failed step cannot be presented as an active or paused run")
        if any(s.status == "unknown" for s in self.steps) and self.status != "unknown":
            raise ValueError("An uncertain step requires an uncertain run status")
        if self.status == "paused" and any(s.status == "running" for s in self.steps):
            raise ValueError("Pause is confirmed only after the active action has stopped")
        if self.native_state is not None and (
            self.native_state.revision > self.session_revision
            or self.native_state.observed_at > self.observed_at
        ):
            raise ValueError("Native observations cannot be newer than the snapshot")
        confirmed_revisions = [
            s.observation_revision for s in self.steps if s.status == "completed"
        ]
        if confirmed_revisions and (
            self.native_state is None
            or self.native_state.revision < max(confirmed_revisions)
            or any(
                s.completed_at > self.native_state.observed_at
                for s in self.steps
                if s.status == "completed"
            )
        ):
            raise ValueError("Confirmed progress requires a matching or newer native observation")
        return self

    @property
    def completed_steps(self) -> int:
        return sum(step.status == "completed" for step in self.steps)

    @property
    def progress_percent(self) -> float:
        return 100 * self.completed_steps / len(self.steps)


def check_run_snapshot(
    snapshot: RemoteRunSnapshot,
    session_id: UUID,
    request: RemoteRunRequest,
    previous: RemoteRunSnapshot | None = None,
) -> None:
    """Reject cross-run responses, replayed state and retracted confirmations."""
    if (
        snapshot.session_id != session_id
        or snapshot.run_id != request.run_id
        or snapshot.plan_hash != request.plan_hash
        or len(snapshot.steps) != len(request.experiment.actions)
        or snapshot.session_revision < request.expected_revision
        or any(
            s.status == "completed" and s.observation_revision <= request.expected_revision
            for s in snapshot.steps
        )
    ):
        raise ValueError("Progress does not belong to the submitted workflow and session")
    if previous is None:
        return
    check_run_snapshot(previous, session_id, request)
    if previous.status in TERMINAL_SNAPSHOT_STATUSES and snapshot != previous:
        raise ValueError("Terminal evidence is immutable; reconcile before creating another run")
    if snapshot.sequence < previous.sequence:
        raise ValueError("Progress snapshot is out of order")
    if snapshot.sequence == previous.sequence and snapshot != previous:
        raise ValueError("The same sequence cannot describe different progress")
    if (
        snapshot.session_revision < previous.session_revision
        or snapshot.observed_at < previous.observed_at
        or snapshot.engine_version != previous.engine_version
        or snapshot.asset_version != previous.asset_version
    ):
        raise ValueError("Session observations or runtime identity changed unexpectedly")
    for old, new in zip(previous.steps, snapshot.steps, strict=True):
        if old.status == "completed" and old != new:
            raise ValueError("Confirmed steps cannot be revised or uncompleted")
    if previous.native_state is not None and (
        snapshot.native_state is None
        or snapshot.native_state.revision < previous.native_state.revision
        or snapshot.native_state.observed_at < previous.native_state.observed_at
        or snapshot.native_state.simulation_tick < previous.native_state.simulation_tick
    ):
        raise ValueError("Native observations cannot disappear or move backward within a run")
    if (
        previous.native_state is not None
        and snapshot.native_state.revision == previous.native_state.revision
        and snapshot.native_state != previous.native_state
    ):
        raise ValueError("The same native observation revision cannot describe different state")
