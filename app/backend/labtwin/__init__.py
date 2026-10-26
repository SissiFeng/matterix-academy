"""Shared sim-to-real contracts: operations, evidence, workflows, gates and datasets.

Pure standard library. The control plane (Lab Onboarding), simulation workers
and device gateways must run the same ``CONTRACT_VERSION``.
"""

from .compare import Comparison, compare
from .models import Evidence, Fact, Observation, Operation, Outcome, Status
from .wire import (
    dumps,
    fingerprint,
    observation_from_dict,
    operation_from_dict,
    outcome_from_dict,
    plain,
)

CONTRACT_VERSION = "1.0.0"

__all__ = [
    "CONTRACT_VERSION",
    "Comparison",
    "Evidence",
    "Fact",
    "Observation",
    "Operation",
    "Outcome",
    "Status",
    "compare",
    "dumps",
    "fingerprint",
    "observation_from_dict",
    "operation_from_dict",
    "outcome_from_dict",
    "plain",
]
