#!/usr/bin/env bash
# Use the lockfile's Playwright CLI; keep apt failures separate from CDN failures.
set -euo pipefail
cd "$(dirname "$0")/../app/frontend"
log_dir="../../build/browser-install-logs"
mkdir -p "$log_dir"

retry_install() {
  local phase="$1" seconds="$2" attempt status
  shift 2
  for attempt in 1 2; do
    echo "$phase: attempt $attempt of 2" | tee -a "$log_dir/$phase.log"
    if timeout --kill-after=15s "${seconds}s" ./node_modules/.bin/playwright "$@" 2>&1 | tee -a "$log_dir/$phase.log"; then
      return 0
    else
      status=$?
    fi
    echo "$phase: attempt $attempt failed (exit $status)" | tee -a "$log_dir/$phase.log"
    if [ "$attempt" -lt 2 ]; then
      sleep 15
    fi
  done
  return "$status"
}

export PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=60000
retry_install chromium-download 120 install chromium

# Hosted runners already carry the shared libraries Chromium needs, so the package
# mirrors are only consulted when the downloaded browser cannot start.
if node --input-type=module -e 'import { chromium } from "@playwright/test"; await (await chromium.launch()).close();' \
  >>"$log_dir/system-dependencies.log" 2>&1; then
  echo "system-dependencies: Chromium starts without extra packages" |
    tee -a "$log_dir/system-dependencies.log"
  exit 0
fi

# Hosted runners list Azure's Ubuntu mirror first. When its name stops resolving, every
# package waits out a DNS timeout before the next mirror is tried, so drop it up front.
mirrors=/etc/apt/apt-mirrors.txt
if [ -f "$mirrors" ] && ! getent hosts azure.archive.ubuntu.com >/dev/null; then
  echo "system-dependencies: azure.archive.ubuntu.com does not resolve; using the remaining mirrors" |
    tee -a "$log_dir/system-dependencies.log"
  sudo sed -i '/azure\.archive\.ubuntu\.com/d' "$mirrors"
fi

# GNU timeout bounds stalled package mirrors and also terminates stubborn children.
retry_install system-dependencies 300 install-deps chromium
