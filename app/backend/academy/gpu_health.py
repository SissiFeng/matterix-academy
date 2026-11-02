"""Read-only GPU readiness check for the unprivileged native worker.

The worker cannot load kernel modules or create device nodes (NoNewPrivileges);
a root boot unit does that. This check only observes, so a host whose driver is
not ready never claims a run and never launches Isaac into a missing GPU.
"""

import os
import subprocess
from pathlib import Path

# Isaac needs NVML (nvidiactl), a device node and CUDA's unified memory node.
DEVICE_NODES = ("nvidiactl", "nvidia0", "nvidia-uvm")
QUERY = ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]


def gpu_issue(expected_driver=None, *, dev=Path("/dev"), run=subprocess.run):
    """Return None when the GPU is usable, otherwise a short operator-facing reason."""
    for name in DEVICE_NODES:
        node = dev / name
        if not node.exists():
            return f"GPU device /dev/{name} is missing; the NVIDIA driver is not loaded"
        if not os.access(node, os.R_OK | os.W_OK):
            return f"GPU device /dev/{name} is not accessible to the worker"
    try:
        result = run(QUERY, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "nvidia-smi could not be run within 15 seconds"
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or not lines:
        return "nvidia-smi cannot reach the NVIDIA driver"
    drivers = {line.rsplit(",", 1)[-1].strip() for line in lines}
    if expected_driver and drivers != {expected_driver}:
        return f"NVIDIA driver {', '.join(sorted(drivers))} differs from pinned {expected_driver}"
    return None
