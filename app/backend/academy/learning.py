"""First-transfer lesson checks. All numerical evidence remains synthetic."""

import re

from .models import LearningProgress


def readiness(session: dict) -> dict:
    progress = LearningProgress.model_validate(session.get("learning", {}))
    experiment = session["experiment"]
    prediction = progress.prediction
    volume = experiment.get("transfer_volume", 100)
    checks = [
        {
            "id": "orientation",
            "label": "Explore all five objects and distinguish deck slots from wells",
            "passed": set(progress.visited) == {"pipette", "tips", "stock", "plate", "waste"}
            and progress.location_answer == "well",
        },
        {
            "id": "preparation",
            "label": "Check the instrument, labware, liquids and teaching model limits",
            "passed": set(progress.checks) == {"instrument", "labware", "liquids", "simulation"},
        },
        {
            "id": "prediction",
            "label": "Correctly predict the source, tip and target volumes after aspiration",
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


def _english_assessment(result: dict | None) -> dict | None:
    """Translate legacy system labels without changing recorded outcomes."""
    if result is None:
        return None
    labels = {
        "源容器减少了对应体积": "The source volume decreased by the transferred amount",
        "未向其他孔转移": "No liquid was transferred to other wells",
    }
    return {
        **result,
        "checks": [
            {
                **check,
                "label": labels.get(
                    check["label"],
                    re.sub(
                        r"^目标 A1 孔收到 ([0-9.]+) µL$",
                        r"Target well A1 received \1 µL",
                        check["label"],
                    ),
                ),
            }
            for check in result["checks"]
        ],
    }


def present(session: dict) -> dict:
    """Derived values are never writable learner claims or stored physics state."""
    if session["experiment"]["course_id"] != "flex-first-transfer":
        return session
    return {
        **session,
        "experiment": {
            **session["experiment"],
            # Only the old generated title is translated; learner titles stay intact.
            "title": re.sub(
                r"^第一次转移 · ([0-9.]+) µL$",
                r"First transfer · \1 µL",
                session["experiment"]["title"],
            ),
        },
        "assessment": _english_assessment(session.get("assessment")),
        "attempts": [
            {**attempt, "assessment": _english_assessment(attempt.get("assessment"))}
            for attempt in session["attempts"]
        ],
        "learning": session.get("learning", LearningProgress().model_dump()),
        "readiness": readiness(session),
        "lesson_outcome": lesson_outcome(session),
    }
