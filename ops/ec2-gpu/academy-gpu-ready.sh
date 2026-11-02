#!/bin/sh
# Root boot step: load the pinned NVIDIA driver and its device nodes before the
# unprivileged worker starts. The worker runs with NoNewPrivileges, so the setuid
# nvidia-modprobe cannot load modules on its behalf; without this unit a cold
# boot leaves Isaac with no GPU.
set -eu
manifest=/etc/academy-native/image-manifest.json
expected=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["driver_version"])' "$manifest")
# -u loads nvidia-uvm (CUDA); -c=0 creates /dev/nvidiactl and /dev/nvidia0.
nvidia-modprobe -u -c=0
# Persistence keeps the driver initialised between runs; it is not required.
nvidia-smi -pm 1 >/dev/null || printf '%s\n' 'NVIDIA persistence mode unavailable; continuing' >&2
attempt=0
while :; do
  observed=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | sort -u || true)
  if [ "$observed" = "$expected" ] && [ -c /dev/nvidia-uvm ] && [ -c /dev/nvidia0 ]; then
    printf 'NVIDIA driver %s ready\n' "$observed"
    exit 0
  fi
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    printf 'NVIDIA driver not ready: observed "%s", pinned %s\n' "$observed" "$expected" >&2
    exit 1
  fi
  sleep 2
done
