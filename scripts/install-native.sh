#!/usr/bin/env bash
# Install the outbound host agent. Native execution stays off until qualified.
set -euo pipefail
umask 077
release_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != Linux ]]; then
  printf '%s\n' 'This installer is for the Ubuntu simulator host.' >&2
  exit 1
fi
isaac_python="${LAB_ISAAC_PYTHON:-$(command -v python || command -v python3)}"
agent_root="${XDG_DATA_HOME:-$HOME/.local/share}/lab-onboarding"
state_dir="$agent_root/state"
mkdir -p "$state_dir" "$agent_root/tools" "$HOME/.config/systemd/user"
chmod 700 "$agent_root" "$state_dir"
if [[ ! -f "$release_dir/worker-credential" ]]; then
  printf '%s\n' 'The protected worker enrollment file is missing. Request a fresh installer.' >&2
  exit 1
fi
install -m 600 "$release_dir/worker-credential" "$state_dir/worker-credential"
printf '%s\n' 'Installing an isolated Python 3.12 agent; the current Isaac environment is unchanged.'
"$isaac_python" -m pip install --disable-pip-version-check --no-warn-script-location --target "$agent_root/tools" 'uv==0.11.18'
PYTHONPATH="$agent_root/tools" "$isaac_python" -m uv sync --project "$release_dir" --python 3.12 --frozen --no-dev --extra native-worker
"$release_dir/.venv/bin/python" - "$release_dir" "$state_dir" "$isaac_python" <<'PY'
import json
import pathlib
import sys
release, state, isaac = map(pathlib.Path, sys.argv[1:])
# systemd parses quoting itself and expands percent specifiers, never a shell.
def quote(value):
    return json.dumps(str(value).replace('%', '%%'))
command = [release / '.venv/bin/python', '-m', 'academy.host_agent',
           '--api-url', 'https://1cpkmq930k.execute-api.ca-central-1.amazonaws.com',
           '--credential-file', state / 'worker-credential', '--state-dir', state,
           '--isaac-python', isaac]
unit = '\n'.join([
    '[Unit]', 'Description=Lab Onboarding outbound simulator agent', 'After=network-online.target',
    '[Service]', 'Type=simple', 'UMask=0077', 'NoNewPrivileges=true',
    'Environment=' + quote('DISPLAY=' + __import__('os').environ.get('DISPLAY', '')),
    'WorkingDirectory=' + quote(release),
    'ExecStart=' + ' '.join(map(quote, command)),
    'Restart=on-failure', 'RestartSec=10',
    '[Install]', 'WantedBy=default.target', '',
])
path = pathlib.Path.home() / '.config/systemd/user/lab-onboarding-agent.service'
if path.exists() and path.read_text() != unit:
    backup = path.with_suffix('.service.previous')
    backup.write_text(path.read_text())
path.write_text(unit)
PY
systemctl --user daemon-reload
systemctl --user enable lab-onboarding-agent.service
systemctl --user restart lab-onboarding-agent.service
printf '\n%s\n' 'To keep the service running after Ubuntu logout, this step may ask for your Ubuntu password locally.'
sudo loginctl enable-linger "$(id -un)"
systemctl --user --no-pager --full status lab-onboarding-agent.service
printf '\n%s\n' 'Agent installed. Environment review and native qualification are still required.'
printf '%s\n' 'Diagnostics: journalctl --user -u lab-onboarding-agent.service -n 30 --no-pager'
