"""Bounded, synthetic workflow review exercise. Never dispatches device commands."""

from copy import deepcopy
from typing import Literal

from pydantic import Field

from .models import Experiment, StrictModel
from .teaching import InvalidTransition, control, execute_step, new_session

KEY = "course#workflow-readiness"
GAPS = {"source", "mixing", "physical"}


class CourseCommand(StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    action: Literal["inspect", "repair", "practice", "reconcile", "assess", "restart"]
    findings: list[Literal["source", "mixing", "physical", "tips", "capacity"]] = Field(
        default_factory=list, max_length=5
    )
    source_volume: float = Field(default=50, ge=0, le=1500)
    mixing: Literal["command", "ideal"] = "command"
    recovery: Literal["", "retry", "assume", "read"] = ""
    decision: Literal["", "hardware", "synthetic", "failed"] = ""
    rationale: str = Field(default="", max_length=600)


def initial() -> dict:
    return {
        "version": 0,
        "course_id": "workflow-readiness",
        "evidence": "synthetic",
        "phase": "review",
        "findings": [],
        "plan": {"source_volume": 50, "mixing": "command"},
        "trial": None,
        "recovery": "",
        "reconciled": False,
        "decision": "",
        "rationale": "",
        "completed": False,
        "feedback": "Review the proposed workflow and select every unsupported claim.",
    }


def transition(saved: dict, data: CourseCommand) -> dict:
    result = deepcopy(saved)
    phase = saved["phase"]
    if data.action == "restart":
        result = initial()
        result["feedback"] = "A fresh synthetic exercise is ready. Previous answers were cleared."
    elif data.action == "inspect" and phase == "review":
        result["findings"] = list(dict.fromkeys(data.findings))
        if set(data.findings) == GAPS:
            result.update(
                phase="repair", feedback="Three gaps identified. Repair the teaching plan."
            )
        else:
            result["feedback"] = (
                "Compare the 50 µL source with the 100 µL first transfer. "
                "Check explicit mixing support and whether teaching success authorizes hardware. "
                "The supplied tips and 300 µL capacity are sufficient."
            )
    elif data.action == "repair" and phase == "repair":
        result["plan"] = {"source_volume": data.source_volume, "mixing": data.mixing}
        if data.source_volume >= 100 and data.mixing == "ideal":
            result.update(
                phase="practice",
                feedback="Plan saved. Ideal instantaneous mixing is an assumption, not a device skill.",
            )
        else:
            result["feedback"] = (
                "Provide at least 100 µL of stock and replace the unsupported mixing command "
                "with the teaching model's ideal-mixing assumption."
            )
    elif data.action == "practice" and phase == "practice":
        # Reuse the established dilution calculator, with no native or physical execution path.
        trial = control(
            new_session(Experiment(source_volume=saved["plan"]["source_volume"])), "start"
        )
        while trial["status"] == "running":
            trial = execute_step(trial)
        if trial["status"] != "completed" or not trial["assessment"]["passed"]:
            raise InvalidTransition(
                "The synthetic trial did not pass. Restart and review the plan."
            )
        result.update(
            phase="incident",
            trial={
                "evidence": "synthetic",
                "status": trial["status"],
                "steps": trial["cursor"],
                "assessment": trial["assessment"],
                "state": trial["state"],
                "events": trial["events"],
            },
            feedback="The synthetic dilution passed. Next, evaluate a separate scripted timeout.",
        )
    elif data.action == "reconcile" and phase == "incident":
        result["recovery"] = data.recovery
        if data.recovery == "read":
            result.update(
                phase="reflect",
                reconciled=True,
                feedback="Scripted record retrieved: command demo-dispense-03 completed once. "
                "No command was replayed. This is scenario evidence only.",
            )
        else:
            result["feedback"] = (
                "A missing response leaves the outcome unknown. Read the original command record "
                "before choosing a next action; replay could dispense twice."
            )
    elif data.action == "assess" and phase == "reflect":
        rationale = data.rationale.strip()
        result.update(decision=data.decision, rationale=rationale)
        if data.decision == "synthetic" and len(rationale) >= 20:
            result.update(
                phase="complete",
                completed=True,
                feedback="Course complete: the evidence supports synthetic practice only. "
                "Your explanation is saved for reflection; its scientific correctness is not "
                "automatically graded. No physical-device authorization is granted.",
            )
        else:
            result["feedback"] = (
                "Choose the conclusion supported by the evidence and explain it in at least "
                "20 characters. Teaching results cannot establish physical readiness."
            )
    else:
        raise InvalidTransition("Complete the current course stage before this action")
    result["version"] = saved["version"] + 1
    return result
