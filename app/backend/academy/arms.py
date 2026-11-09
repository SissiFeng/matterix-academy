"""Arm profiles the bench planner can mount on a transfer twin.

Kinematics are Universal Robots' published DH parameters. Joint limits are the margins
the Academy UR SiLA connector accepts (elbow under 155°, other joints under 355°), so a
planned path stays exportable; a twin may narrow them further when its connector does.
Link radii are capsule envelopes sized to each arm, not CAD. Teaching geometry only.
"""

import math
from dataclasses import dataclass

CONNECTOR_LIMITS_DEG = (354, 354, 154, 354, 354, 354)
# The elbow is kept at least this bent: near straight the arm cannot lift vertically
# and small pose errors need large joint moves (the shoulder-elbow-wrist singularity).
ELBOW_MIN_DEG = 12


@dataclass(frozen=True)
class Arm:
    key: str
    name: str
    d: tuple
    a: tuple
    reach: float
    links: tuple
    limits: tuple = tuple(math.radians(v) for v in CONNECTOR_LIMITS_DEG)
    alpha: tuple = (math.pi / 2, 0.0, 0.0, math.pi / 2, -math.pi / 2, 0.0)

    @property
    def scale(self):
        """Size relative to the UR5e the search rings were tuned on."""
        return self.reach / 0.85

    def narrowed(self, limits_deg):
        if not limits_deg:
            return self
        limits = tuple(
            min(own, math.radians(v)) for own, v in zip(self.limits, limits_deg, strict=True)
        )
        return Arm(self.key, self.name, self.d, self.a, self.reach, self.links, limits)


def _links(base, upper, fore, wrist):
    return (
        ("base", base),
        ("upper arm", upper),
        ("forearm", fore),
        ("wrist 1", wrist),
        ("wrist 2", wrist),
        ("wrist 3", wrist),
        ("gripper", 0.06),
    )


ARMS = {
    "ur3e": Arm(
        "ur3e",
        "UR3e",
        (0.15185, 0.0, 0.0, 0.13105, 0.08535, 0.0921),
        (0.0, -0.24355, -0.2132, 0.0, 0.0, 0.0),
        0.5,
        _links(0.06, 0.05, 0.045, 0.04),
    ),
    "ur5e": Arm(
        "ur5e",
        "UR5e",
        (0.1625, 0.0, 0.0, 0.1333, 0.0997, 0.0996),
        (0.0, -0.425, -0.3922, 0.0, 0.0, 0.0),
        0.85,
        _links(0.075, 0.065, 0.055, 0.048),
    ),
    "ur10e": Arm(
        "ur10e",
        "UR10e",
        (0.1807, 0.0, 0.0, 0.17415, 0.11985, 0.11655),
        (0.0, -0.6127, -0.57155, 0.0, 0.0, 0.0),
        1.3,
        _links(0.09, 0.075, 0.065, 0.055),
    ),
}
DEFAULT = "ur5e"


def arm_for(spec):
    """The profile a transfer twin carries, narrowed by its connector's joint limits."""
    arm = ARMS[spec.get("arm") or DEFAULT]
    return arm.narrowed(spec.get("joint_limits_deg") or ())
