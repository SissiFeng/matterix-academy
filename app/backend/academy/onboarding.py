"""Device onboarding records. Declarations never qualify a physical device."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, model_validator

from .learning import present
from .models import Experiment, StrictModel
from .store import Conflict, Write
from .teaching import new_session

Capability = Literal["pickup", "aspirate", "dispense", "drop", "mix", "move_labware", "image"]


class DeviceUpdate(StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    name: str = Field(min_length=1, max_length=80)
    workcell: str = Field(min_length=1, max_length=80)
    model: Literal["opentrons_flex", "opentrons_ot2"] = "opentrons_flex"
    connection: Literal["", "native_api", "pylabrobot", "sila2", "custom"] = ""
    capabilities: list[Capability] = Field(default_factory=list, max_length=7)
    stage: int = Field(ge=1, le=3, strict=True)

    @model_validator(mode="after")
    def validate_progress(self):
        self.name = self.name.strip()
        self.workcell = self.workcell.strip()
        if not self.name or not self.workcell:
            raise ValueError("Name the device and its workcell")
        if self.stage >= 2 and not self.connection:
            raise ValueError("Choose a planned connection before continuing")
        if self.stage >= 3 and not self.capabilities:
            raise ValueError("Declare at least one capability before creating a teaching twin")
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("Capabilities must be unique")
        return self


class TwinCreate(StrictModel):
    expected_version: int = Field(ge=1, strict=True)


class OnboardingService:
    def __init__(self, store, pairing=None):
        self.store = store
        self.pairing = pairing

    def get(self, owner: str, device_id: UUID):
        record = self.store.get(owner, f"device#{device_id}")
        if record is None:
            raise HTTPException(404, "Device not found")
        return record

    def save(self, owner: str, device_id: UUID, data: DeviceUpdate):
        previous = self.store.get(owner, f"device#{device_id}")
        if (previous["version"] if previous else 0) != data.expected_version:
            raise Conflict
        # The binding is server-owned; changing declarations cannot create evidence.
        record = {
            **data.model_dump(exclude={"expected_version"}),
            "id": str(device_id),
            "version": data.expected_version + 1,
            "updated_at": datetime.now(UTC).isoformat(),
            "twin_session_id": previous["twin_session_id"] if previous else None,
            # Server-owned: set only by an operator link to a registered instrument.
            "instrument_id": previous.get("instrument_id") if previous else None,
        }
        if record["instrument_id"] and previous and previous.get("model") != record["model"]:
            raise HTTPException(
                409, "This declaration is linked to an instrument; its model is fixed"
            )
        self.store.put(owner, f"device#{device_id}", record, data.expected_version or None)
        return self.describe(owner, record)

    def create_twin(self, owner: str, device_id: UUID, data: TwinCreate):
        record = self.get(owner, device_id)
        if record["version"] != data.expected_version:
            raise Conflict
        if record["twin_session_id"]:
            raise HTTPException(409, "A teaching twin is already paired with this device")
        if record["stage"] != 3:
            raise HTTPException(409, "Complete the device, connection and capability steps first")
        if record.get("model", "opentrons_flex") != "opentrons_flex":
            raise HTTPException(
                409,
                "Teaching twins exist for the Flex lessons only; OT-2 evidence comes from a linked instrument",
            )
        session = new_session(Experiment(title=f"{record['name'][:60]} · teaching trial"))
        record.update(
            version=record["version"] + 1,
            twin_session_id=session["id"],
            updated_at=datetime.now(UTC).isoformat(),
        )
        # Pairing and session creation commit together in SQLite and DynamoDB.
        self.store.transact(
            [
                Write(owner, f"device#{device_id}", record, data.expected_version),
                Write(owner, f"session#{session['id']}", session, None),
            ]
        )
        return self.describe(owner, record)

    def describe(self, owner: str, record: dict):
        session = (
            self.store.get(owner, f"session#{record['twin_session_id']}")
            if record["twin_session_id"]
            else None
        )
        required = {a["kind"] for a in session["experiment"]["actions"]} if session else set()
        missing = sorted(required - set(record["capabilities"]))
        result_passed = bool(
            session
            and session["status"] == "completed"
            and (session.get("assessment") or {}).get("passed")
        )
        checks = [
            {
                "id": "capabilities",
                "label": "Teaching capability coverage",
                "status": "missing" if not session else "failed" if missing else "passed",
                "detail": "Create a teaching twin to check its workflow."
                if not session
                else f"Not declared: {', '.join(missing)}."
                if missing
                else "Declared operations cover this teaching workflow; hardware is unverified.",
                "scope": "teaching",
            },
            {
                "id": "trial",
                "label": "Teaching trial",
                "status": "passed"
                if result_passed
                else "failed"
                if session and session["status"] in {"faulted", "completed"}
                else "missing",
                "detail": "Saved teaching goal passed. Synthetic evidence only."
                if result_passed
                else "Open the paired trial and complete its teaching goals.",
                "scope": "teaching",
            },
        ]
        instrument_id = record.get("instrument_id")
        physical = None
        if instrument_id and self.pairing is not None:
            from .sim2real_api import physical_checks

            try:
                physical = physical_checks(self.pairing, instrument_id)
            except HTTPException:
                physical = None
        if physical is not None:
            checks.extend(physical)
        for key, label, detail in (
            []
            if physical is not None
            else [
                (
                    "connection",
                    "Device connectivity",
                    "A planned adapter is not a verified connection.",
                ),
                (
                    "hardware",
                    "Physical capabilities",
                    "No capabilities observed from a real device.",
                ),
                (
                    "geometry",
                    "Geometry and reachability",
                    "The schematic has no collision or reachability checks.",
                ),
                (
                    "resources",
                    "Physical resources",
                    "Real liquid volumes and tip inventory have not been observed.",
                ),
                ("calibration", "Calibration", "No physical calibration record is available."),
                (
                    "sync",
                    "State consistency",
                    "Physical state is absent; a state difference cannot be calculated.",
                ),
                (
                    "authorization",
                    "Physical execution",
                    "Supervised hardware execution is not connected in this application.",
                ),
            ]
        ):
            checks.append(
                {
                    "id": key,
                    "label": label,
                    "status": "missing",
                    "detail": detail,
                    "scope": "physical",
                }
            )
        return {
            **record,
            "session": present(session) if session else None,
            "checks": checks,
            "physical_ready": bool(physical) and all(c["status"] == "passed" for c in physical),
            "physical_state": None,
            "instrument_id": instrument_id,
            "evidence": "physical"
            if physical and any(c["status"] == "passed" for c in physical)
            else "synthetic"
            if session
            else "declaration_only",
        }

    def list(self, owner: str):
        return [self.describe(owner, item) for item in self.store.partition(owner, "device#")]
