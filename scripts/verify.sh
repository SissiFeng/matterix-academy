#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run ruff check app/backend infra/cognito scripts/release.py scripts/package-native.py scripts/ec2-gpu-costs.py scripts/ec2-gpu-prepare.py scripts/ec2-gpu-release.py scripts/ec2-gpu-sources.py scripts/ec2-gpu-bootstrap.py scripts/ec2-gpu-driver.py scripts/ec2-gpu-inputs.py scripts/ec2-gpu-build.py scripts/verify-gpu-image.py
uv run ruff format --check app/backend infra/cognito scripts/release.py scripts/package-native.py scripts/ec2-gpu-costs.py scripts/ec2-gpu-prepare.py scripts/ec2-gpu-release.py scripts/ec2-gpu-sources.py scripts/ec2-gpu-bootstrap.py scripts/ec2-gpu-driver.py scripts/ec2-gpu-inputs.py scripts/ec2-gpu-build.py scripts/verify-gpu-image.py
uv run --extra native-worker pytest -q
npm --prefix app/frontend run build
npm --prefix app/frontend run format:check
node --check app/frontend/commissioning.mjs
node --test app/frontend/commissioning-response.test.mjs
terraform -chdir=infra fmt -check
terraform -chdir=infra init -backend=false -input=false >/dev/null
terraform -chdir=infra validate

bash scripts/verify-ec2-gpu.sh

bash -n ops/ec2-gpu/image/provision.sh ops/ec2-gpu/image/finalize.sh
if [[ -n "${PACKER_BIN:-}" ]]; then
  "$PACKER_BIN" fmt -check ops/ec2-gpu/image
  "$PACKER_BIN" validate -syntax-only ops/ec2-gpu/image
  uv run python scripts/verify-gpu-image.py --packer "$PACKER_BIN"
fi
