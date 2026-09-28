#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --frozen
npm --prefix app/frontend ci
ACADEMY_ALLOW_DEMO=true uv run uvicorn academy.main:app --host 127.0.0.1 --port 8000 &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT INT TERM
npm --prefix app/frontend run dev
