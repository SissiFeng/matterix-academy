"""First-transfer lesson checks. All numerical evidence remains synthetic."""

from .models import LearningProgress


def readiness(session: dict) -> dict:
    progress = LearningProgress.model_validate(session.get("learning", {}))
    experiment = session["experiment"]
    prediction = progress.prediction
    volume = experiment.get("transfer_volume", 100)
    checks = [
        {
            "id": "orientation",
            "label": "认识五个设备与耗材，并区分台面槽位和孔位",
            "passed": set(progress.visited) == {"pipette", "tips", "stock", "plate", "waste"}
            and progress.location_answer == "well",
        },
        {
            "id": "preparation",
            "label": "确认仪器、耗材、液体与教学模型范围",
            "passed": set(progress.checks) == {"instrument", "labware", "liquids", "simulation"},
        },
        {
            "id": "prediction",
            "label": "正确预测吸液后源容器、吸头和目标孔的液量",
            "passed": prediction is not None
            and abs(prediction.source - (experiment["source_volume"] - volume)) < 1e-6
            and abs(prediction.tip - volume) < 1e-6
            and prediction.target == 0,
        },
    ]
    return {"ready": all(check["passed"] for check in checks), "checks": checks}


def lesson_outcome(session: dict) -> dict:
    progress = LearningProgress.model_validate(session.get("learning", {}))
    return {
        "practice_completed": session["status"] == "completed"
        and bool((session.get("assessment") or {}).get("passed")),
        "understanding_demonstrated": progress.reflection == "source_to_tip",
        "evidence": "synthetic",
    }


def present(session: dict) -> dict:
    """Derived values are never writable learner claims or stored physics state."""
    if session["experiment"]["course_id"] != "flex-first-transfer":
        return session
    return {
        **session,
        "learning": session.get("learning", LearningProgress().model_dump()),
        "readiness": readiness(session),
        "lesson_outcome": lesson_outcome(session),
    }
