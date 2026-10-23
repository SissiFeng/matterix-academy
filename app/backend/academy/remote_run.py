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
from .native_studio import STUDIO, studio_scene
from .recipes import ExecutionPlan, MixingPlan

TERMINAL_SNAPSHOT_STATUSES = frozenset({"completed", "failed", "unknown"})


def workflow_digest(experiment: ExecutionPlan) -> str:
    """Bind the complete normalized plan, including layout and starting volumes."""
    encoded = json.dumps(
        experiment.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class RemoteRunRequest(StrictModel):
    run_id: UUID
    expected_revision: int = Field(ge=1)
    experiment: ExecutionPlan
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


class MixingObservation(StrictModel):
    """Observed semantic state for the single-environment Flex mixing recipe."""

    source_volumes_ul: list[float] = Field(min_length=8, max_length=8)
    mixture_components_ul: list[float] = Field(min_length=8, max_length=8)
    source_order: list[int] = Field(min_length=4, max_length=4)
    lid_parked: bool
    lid_attached: bool
    active_tip: str | None
    tips_used: list[str] = Field(max_length=4)
    tips_discarded: list[str] = Field(max_length=4)
    joint_positions: list[float] = Field(min_length=7, max_length=7)
    native_action_index: int = Field(ge=0, le=256)
    native_action_count: int = Field(ge=1, le=256)
    native_action: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def valid_observation(self):
        if any(v < 0 for v in self.source_volumes_ul + self.mixture_components_ul):
            raise ValueError("Observed amounts cannot be negative")
        if len(set(self.source_order)) != 4 or any(not 0 <= i < 8 for i in self.source_order):
            raise ValueError("Report four distinct source indices")
        allowed = {f"Tips__A{i}" for i in range(1, 5)}
        if self.active_tip is not None and self.active_tip not in allowed:
            raise ValueError("Unknown mixing tip")
        if any(
            len(ids) != len(set(ids)) or not set(ids) <= allowed
            for ids in (self.tips_used, self.tips_discarded)
        ) or not set(self.tips_discarded) <= set(self.tips_used):
            raise ValueError("Inconsistent tip observations")
        if self.native_action_index > self.native_action_count:
            raise ValueError("Action index exceeds native workflow")
        return self


class StudioObservation(StrictModel):
    """Native motion and semantic liquid accounting; not fluid/chemical validation."""

    instrument: Literal["flex", "ot2"]
    scene: Literal["workflow-studio-flex", "workflow-studio-ot2"]
    observation_model: Literal["native-semantic"]
    waste_volume_ul: float = Field(ge=0)
    labware_slots: dict[Literal["tips", "stock", "plate", "waste"], str]
    native_action_index: int = Field(ge=0, le=1024)
    native_action_count: int = Field(ge=1, le=1024)
    native_action: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def bound_scene(self):
        if self.scene != f"workflow-studio-{self.instrument}":
            raise ValueError("Native scene and instrument differ")
        if set(self.labware_slots) != {"tips", "stock", "plate", "waste"}:
            raise ValueError("Report every native labware placement")
        if self.native_action_index > self.native_action_count:
            raise ValueError("Action index exceeds native workflow")
        return self


class RemoteNativeState(StrictModel):
    """Null means unobserved, never zero or a value filled by the teaching model."""

    revision: int = Field(ge=1)
    observed_at: AwareDatetime
    simulation_tick: int = Field(ge=0)
    pipette_volume_ul: float | None = Field(default=None, ge=0)
    tip_attached: bool | None = None
    well_volumes_ul: dict[Literal["stock", "A1", "A2", "A3"], float | None]
    mixing: MixingObservation | None = None
    studio: StudioObservation | None = None

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
    if isinstance(request.experiment, MixingPlan):
        check_mixing_observation(snapshot, request.experiment)
    elif request.experiment.course_id == STUDIO:
        check_studio_observation(snapshot, request.experiment)
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
    if previous.native_state is not None and previous.native_state.studio is not None:
        old_studio = previous.native_state.studio
        new_studio = snapshot.native_state.studio
        if new_studio is None or new_studio.native_action_count != old_studio.native_action_count:
            raise ValueError("Native Studio workflow identity cannot change within a run")
        if new_studio.native_action_index < old_studio.native_action_index:
            raise ValueError("Native Studio action progress cannot move backward within a run")


def check_studio_observation(snapshot: RemoteRunSnapshot, plan: Experiment) -> None:
    state = snapshot.native_state
    studio = state.studio if state else None
    if studio is None:
        if snapshot.completed_steps or snapshot.status in {"running", "paused", "completed"}:
            raise ValueError("Studio progress requires native scene observations")
        return
    if studio.scene != studio_scene(plan) or studio.labware_slots != plan.layout:
        raise ValueError("Native scene placements differ from the saved Studio plan")
    if (
        state.tip_attached is None
        or state.pipette_volume_ul is None
        or any(v is None for v in state.well_volumes_ul.values())
    ):
        raise ValueError("Studio execution requires native tip and liquid observations")
    total = sum(state.well_volumes_ul.values()) + state.pipette_volume_ul + studio.waste_volume_ul
    if abs(total - (plan.source_volume + 3 * plan.diluent_volume)) > 0.01:
        raise ValueError("Native Studio liquid accounting does not conserve the initial volume")
    completed = snapshot.completed_steps
    if studio.native_action_index < completed or (
        snapshot.status in {"loading", "queued"} and studio.native_action_index != 0
    ):
        raise ValueError("Native motion cannot precede its confirmed Studio steps")
    if snapshot.status == "completed" and studio.native_action_index != studio.native_action_count:
        raise ValueError("Native Studio completion requires finished motion")
    expected = {
        "stock": plan.source_volume,
        **dict.fromkeys(("A1", "A2", "A3"), plan.diluent_volume),
    }
    tip, waste, attached = 0.0, 0.0, False
    for action in plan.actions[:completed]:
        if action.kind == "pickup":
            attached = True
        elif action.kind == "drop":
            attached = False
            waste += tip
            tip = 0.0
        else:
            delta = action.volume * (1 if action.kind == "aspirate" else -1)
            expected[action.well] -= delta
            tip += delta
    # A report may arrive midway through the single next action. Permit only
    # that action's bounded native effects, never effects from a later step.
    if completed < len(plan.actions) and snapshot.status not in {"loading", "queued"}:
        action = plan.actions[completed]
        if action.kind == "pickup":
            attached = state.tip_attached
        elif action.kind == "drop":
            if not state.tip_attached:
                attached = False
                waste += tip
                tip = 0.0
        else:
            delta = state.pipette_volume_ul - tip
            moved = delta if action.kind == "aspirate" else -delta
            if not -0.01 <= moved <= action.volume + 0.01:
                raise ValueError("Observed Studio flow exceeds the next saved action")
            expected[action.well] -= delta
            tip += delta
    if (
        state.tip_attached != attached
        or abs(state.pipette_volume_ul - tip) > 0.01
        or abs(studio.waste_volume_ul - waste) > 0.01
        or any(
            abs(state.well_volumes_ul[well] - amount) > 0.01 for well, amount in expected.items()
        )
    ):
        raise ValueError("Native Studio observations contradict the confirmed workflow prefix")


def check_mixing_observation(snapshot: RemoteRunSnapshot, plan: MixingPlan) -> None:
    state = snapshot.native_state
    mixing = state.mixing if state else None
    if mixing is None:
        if snapshot.completed_steps or snapshot.status in {"running", "paused", "completed"}:
            raise ValueError("Mixing progress requires the native mixing observation")
        return
    sources = [step.source_index for step in plan.actions[1:]]
    if mixing.source_order != sources:
        raise ValueError("Observed source order differs from the saved mixing plan")
    if snapshot.completed_steps and (not mixing.lid_parked or mixing.lid_attached):
        raise ValueError("Confirmed uncover step requires the parked lid observation")
    transfers = max(0, snapshot.completed_steps - 1)
    tips = [step.tip_id for step in plan.actions[1 : transfers + 1]]
    if mixing.tips_discarded[:transfers] != tips or mixing.tips_used[:transfers] != tips:
        raise ValueError("Confirmed transfers require the planned fresh-tip disposal order")
    for source in sources[:transfers]:
        if abs(mixing.mixture_components_ul[source] - 10) > 0.01:
            raise ValueError("Confirmed transfer requires 10 uL observed in its mixture component")
    if snapshot.status == "completed":
        expected = [10 if i in sources else 0 for i in range(8)]
        if (
            any(
                abs(a - b) > 0.01
                for a, b in zip(mixing.mixture_components_ul, expected, strict=True)
            )
            or any(
                abs(v - (1500 - expected[i])) > 0.01 for i, v in enumerate(mixing.source_volumes_ul)
            )
            or mixing.active_tip is not None
            or state.tip_attached is not False
            or state.pipette_volume_ul is None
            or abs(state.pipette_volume_ul) > 0.01
            or state.well_volumes_ul["A1"] is None
            or abs(state.well_volumes_ul["A1"] - 40) > 0.01
            or mixing.native_action_index != mixing.native_action_count
        ):
            raise ValueError(
                "Mixing completion requires the observed 40 uL result, empty tool and completed workflow"
            )
