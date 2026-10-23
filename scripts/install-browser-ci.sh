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

# GNU timeout bounds stalled package mirrors and also terminates stubborn children.
retry_install system-dependencies 300 install-deps chromium
export PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=60000
retry_install chromium-download 120 install chromium
