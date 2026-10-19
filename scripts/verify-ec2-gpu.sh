#!/usr/bin/env bash
# Offline-only validation of the disabled, independent EC2 pilot root.
set -euo pipefail
cd "$(dirname "$0")/.."
work=$(mktemp -d /tmp/academy-ec2-verify.XXXXXX)
trap 'rm -rf "$work"' EXIT
# Validate a fresh copy: never read an operator's local Terraform state.
mkdir -p "$work/infra/ec2-gpu" "$work/ops/ec2-gpu"
cp infra/ec2-gpu/*.tf infra/ec2-gpu/*.tftpl infra/ec2-gpu/.terraform.lock.hcl "$work/infra/ec2-gpu/"
cp ops/ec2-gpu/academy-native.service "$work/ops/ec2-gpu/"
module="$work/infra/ec2-gpu"
unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_ROLE_ARN AWS_WEB_IDENTITY_TOKEN_FILE
unset TF_CLI_ARGS TF_CLI_ARGS_plan TF_CLI_ARGS_init TF_CLI_ARGS_show
# Explicit overrides prevent ambient TF_VAR_enabled/account/profile from selecting a real account.
export AWS_EC2_METADATA_DISABLED=true
export AWS_CONFIG_FILE=/dev/null
export AWS_SHARED_CREDENTIALS_FILE=/dev/null
export TF_DATA_DIR="$work/providers"
terraform -chdir="$module" fmt -check
terraform -chdir="$module" init -backend=false -input=false -lockfile=readonly > "$work/init.log"
terraform -chdir="$module" validate
terraform -chdir="$module" plan -input=false -refresh=false -lock=false \
  -var=enabled=false -out="$work/disabled.tfplan" > "$work/plan.log"
terraform -chdir="$module" show -json "$work/disabled.tfplan" > "$work/disabled.json"
python3 - "$work/disabled.json" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
if plan['planned_values']['outputs']['resources_enabled']['value'] is not False:
    raise SystemExit('Offline plan must keep the paid resource gate false')
changes = plan.get('resource_changes', [])
if any(item['change']['actions'] != ['no-op'] for item in changes):
    raise SystemExit('Offline plan unexpectedly changes resources')
if plan.get('planned_values', {}).get('root_module', {}).get('resources'):
    raise SystemExit('Offline plan unexpectedly contains resources')
print('EC2 pilot: disabled plan verified; zero resources, no account or apply.')
PY
