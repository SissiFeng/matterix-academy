#!/usr/bin/env bash
# Fail the AMI build if the installed image cannot enter bounded commissioning.
set -euo pipefail
umask 077
[[ "$EUID" == 0 && "$(uname -m)" == x86_64 ]]
root=/opt/academy-agent
install -d -m 755 /etc/academy-native/evidence
# /run was cleared by the build reboot; the disabled worker service has not
# recreated its RuntimeDirectory. Native probes run as the worker without starting it.
install -d -o academy-native -g academy-native -m 700 /run/academy-native
export OMNI_KIT_ACCEPT_EULA=YES
# Git safe.directory is per invoking user: checkouts are root-owned and read-only for the worker.
runuser -u academy-native -- env HOME=/var/cache/academy-native git config --global --add safe.directory /srv/matterix
runuser -u academy-native -- env HOME=/var/cache/academy-native git config --global --add safe.directory /srv/matterix-assets
# Preserve the inventory even when its fail-closed CLI rejects this host. The
# local Packer log must retain the reason after automatic instance cleanup.
runtime_status=0
runuser -u academy-native -- env HOME=/var/cache/academy-native OMNI_KIT_ACCEPT_EULA=YES \
  "$root/.venv/bin/python" -m academy.runtime_inventory \
  --engine-root /srv/matterix --assets-root /srv/matterix-assets \
  --isaac-python /opt/matterix-isaac/bin/python --output /var/lib/academy-native/runtime.json \
  || runtime_status=$?
if [[ -s /var/lib/academy-native/runtime.json ]]; then
  install -m 644 /var/lib/academy-native/runtime.json /etc/academy-native/evidence/runtime.json
  printf 'ACADEMY_RUNTIME_JSON='
  cat /etc/academy-native/evidence/runtime.json
fi
if [[ "$runtime_status" != 0 ]]; then
  printf 'Runtime inventory failed with exit status %s; native probes were not started.\n' "$runtime_status" >&2
  exit "$runtime_status"
fi
[[ -s /etc/academy-native/evidence/runtime.json ]]
# Keep measurements outside the native process so timeout/OOM still yields evidence.
evidence=/etc/academy-native/evidence
probe_started=$(date +%s)
date -u +%Y-%m-%dT%H:%M:%SZ > "$evidence/probe-started-at.txt"
nvidia-smi --query-gpu=timestamp,name,memory.total,memory.used \
  --format=csv,noheader,nounits --loop=1 > "$evidence/gpu-memory.csv" &
gpu_sampler=$!
trap 'kill "$gpu_sampler" 2>/dev/null || true' EXIT
probe_status=0
LC_ALL=C /usr/bin/time -v -o "$evidence/probe-time.txt" \
  timeout --signal=TERM --kill-after=30s 1800s \
  runuser -u academy-native -- env HOME=/var/cache/academy-native OMNI_KIT_ACCEPT_EULA=YES \
  PYTHONPATH="$root/app/backend" /bin/bash -c '
    /opt/matterix-isaac/bin/python -m academy.native_image_probe \
      --confirm-native-probe --config /etc/academy-native/native-config.json \
      --output /var/lib/academy-native/scene-render.json &&
    /opt/matterix-isaac/bin/python -m academy.native_studio_isaac \
      --probe --config /etc/academy-native/native-config.json \
      --output /var/lib/academy-native/studio-probe.json
  ' || probe_status=$?
gpu_sampler_complete=0
if kill -0 "$gpu_sampler" 2>/dev/null; then gpu_sampler_complete=1; fi
printf '%s\n' "$gpu_sampler_complete" > "$evidence/gpu-sampler-complete.txt"
kill "$gpu_sampler" 2>/dev/null || true
wait "$gpu_sampler" 2>/dev/null || true
trap - EXIT
journal_status=0
journalctl --sync || journal_status=$?
journalctl -k --since "@$probe_started" --no-pager -o cat \
  > "$evidence/probe-kernel.log" || journal_status=$?
printf '%s\n' "$journal_status" > "$evidence/kernel-read-status.txt"
probe_elapsed=$(( $(date +%s) - probe_started ))
# Preserve available native diagnostics even when the capacity gate rejects the build.
if [[ -f /var/lib/academy-native/scene-render.json ]]; then
  install -m 644 /var/lib/academy-native/scene-render.json "$evidence/scene-render.json"
  printf 'ACADEMY_SCENE_RENDER_JSON='
  cat "$evidence/scene-render.json"
fi
if [[ -f /var/lib/academy-native/studio-probe.json ]]; then
  install -m 644 /var/lib/academy-native/studio-probe.json "$evidence/studio-probe.json"
  printf 'ACADEMY_STUDIO_PROBE_JSON='
  cat "$evidence/studio-probe.json"
fi
# Emit a compact copy before any failure; Packer's local log survives instance cleanup.
"$root/.venv/bin/python" - "$evidence" "$probe_status" "$probe_elapsed" <<'PY'
import json,sys
from pathlib import Path
from academy.native_image_probe import capacity_report
report=capacity_report(Path(sys.argv[1]),int(sys.argv[2]),int(sys.argv[3]))
print('ACADEMY_CAPACITY_JSON='+json.dumps(report,sort_keys=True),flush=True)
raise SystemExit(0 if report['capacity_probe_passed'] else 1)
PY
[[ -s "$evidence/scene-render.json" && -s "$evidence/studio-probe.json" ]]

"$root/.venv/bin/python" - <<'PY'
from academy.native_runner import NativeConfig
from pathlib import Path
cfg=NativeConfig.model_validate_json(Path('/etc/academy-native/native-config.json').read_text())
cfg.verify()
assert not Path('/etc/academy-native/worker.token').exists()
PY
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader > /etc/academy-native/evidence/nvidia-smi.txt
dpkg-query -W -f='${Package}\t${Version}\n' > /etc/academy-native/evidence/dpkg.tsv
/opt/matterix-isaac/bin/python -m pip freeze --all > /etc/academy-native/evidence/runtime-freeze.txt
/opt/academy-agent/.venv/bin/python - <<'PY' > /etc/academy-native/evidence/agent-freeze.txt
from importlib.metadata import distributions
for item in sorted(distributions(),key=lambda d:d.metadata['Name'].lower()):print(item.metadata['Name']+'=='+item.version)
PY
systemctl is-enabled academy-imds.service
systemctl is-active academy-imds.service
if systemctl is-enabled academy-native.service >/dev/null 2>&1; then exit 1; fi
# Root must reach IMDSv2; the unprivileged worker must fail at the network layer.
curl --noproxy '*' --max-time 5 -fsS -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
  -o /dev/null http://169.254.169.254/latest/api/token
worker_metadata_status=0
runuser -u academy-native -- curl --noproxy '*' --max-time 3 -sS -X PUT \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' -o /dev/null \
  http://169.254.169.254/latest/api/token 2>/dev/null || worker_metadata_status=$?
[[ "$worker_metadata_status" == 7 || "$worker_metadata_status" == 28 ]]
systemd-analyze verify /etc/systemd/system/academy-native.service
# All installed code and evidence remain readable, but never writable by the worker.
chmod -R go-w /opt/academy-agent /opt/matterix-isaac /srv/matterix /srv/matterix-assets
rm -f /home/ubuntu/.ssh/authorized_keys /root/.ssh/authorized_keys
cloud-init clean --logs
sync
printf '%s\n' 'Image and local Studio probe passed. Browser acceptance remains pending; worker remains unqualified.'
