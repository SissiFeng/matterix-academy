# Existing AC shared state bucket, verified in account 247893369214.
bucket         = "247893369214-terraform-state"
key            = "matterix-academy/dev/terraform.tfstate"
region         = "ca-central-1"
encrypt        = true
# Existing compatible lock table. Each application's state key has its own lock.
dynamodb_table = "paper-attribution-terraform-locks"
