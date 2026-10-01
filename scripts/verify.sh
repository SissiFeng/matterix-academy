#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run ruff check app/backend infra/cognito scripts/release.py
uv run ruff format --check app/backend infra/cognito scripts/release.py
uv run pytest -q
npm --prefix app/frontend run build
npm --prefix app/frontend run format:check
terraform -chdir=infra fmt -check
terraform -chdir=infra init -backend=false -input=false >/dev/null
terraform -chdir=infra validate
