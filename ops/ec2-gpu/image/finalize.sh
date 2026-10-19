#!/usr/bin/env bash
# Fail the AMI build if the installed image cannot enter bounded commissioning.
set -euo pipefail
umask 077
[[ "$EUID" == 0 && "$(uname -m)" == x86_64 ]]
root=/opt/academy-agent
install -d -m 755 /etc/academy-native/evidence
export OMNI_KIT_ACCEPT_EULA=YES
# Git safe.directory is per invoking user: checkouts are root-owned and read-only for the worker.
runuser -u academy-native -- env HOME=/var/cache/academy-native git config --global --add safe.directory /srv/matterix
runuser -u academy-native -- env HOME=/var/cache/academy-native git config --global --add safe.directory /srv/matterix-assets
runuser -u academy-native -- env HOME=/var/cache/academy-native OMNI_KIT_ACCEPT_EULA=YES \
  "$root/.venv/bin/python" -m academy.runtime_inventory \
  --engine-root /srv/matterix --assets-root /srv/matterix-assets \
  --isaac-python /opt/matterix-isaac/bin/python --output /var/lib/academy-native/runtime.json
install -m 644 /var/lib/academy-native/runtime.json /etc/academy-native/evidence/runtime.json
runuser -u academy-native -- env HOME=/var/cache/academy-native OMNI_KIT_ACCEPT_EULA=YES \
  PYTHONPATH="$root/app/backend" /opt/matterix-isaac/bin/python -m academy.native_image_probe \
  --confirm-native-probe --config /etc/academy-native/native-config.json \
  --output /var/lib/academy-native/scene-render.json
install -m 644 /var/lib/academy-native/scene-render.json /etc/academy-native/evidence/scene-render.json

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
printf '%s\n' 'Image fingerprint passed. No native workflow ran and worker remains unqualified.'
