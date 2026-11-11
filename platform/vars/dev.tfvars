region                    = "ca-central-1"
environment               = "dev"
expected_account_id       = "247893369214"
remote_execution_enabled  = false
self_signup_email_domains = ["utoronto.ca"]
# Account quota is currently 10 total: reservations require unreserved headroom.
reserve_lambda_concurrency = false
learner_request_rate       = 5
github_oidc_provider_arn   = "arn:aws:iam::247893369214:oidc-provider/token.actions.githubusercontent.com"
github_oidc_subject_prefix = "repo:SissiFeng@38707787/matterix-academy@1393332016"

# Optional notifications (confirm the email subscription after apply)
# alarm_email        = "operator@example.org"
# Wakeup for the reviewed Ohio GPU host; does not enable native execution.
gpu_instance_id = "i-0f369ff6e01f8d623"
gpu_worker_id   = "ec2-flex-ohio-1"
# monthly_budget_usd = 100

# GPU host region (EC2/SSM only; Cognito, DynamoDB, KVS stay in `region`).
# Change together with gpu_instance_id: the two must name the same host.
gpu_region = "us-east-2"

# Optional photo-to-twin (GPT-6 Astra). Enable model access in the region and store the
# Bedrock API key in an existing ca-central-1 secret first; Terraform never sees the key.
# twin_region             = "us-east-1"
# twin_api_key_secret_arn = "arn:aws:secretsmanager:ca-central-1:247893369214:secret:matterix-academy/dev/bedrock-twin-key-AbCdEf"
