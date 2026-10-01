# Ubuntu host enrollment

Students connect to the AWS website. The Ubuntu agent makes outbound HTTPS and
TURN connections; it exposes no SSH, desktop, or simulator listener to students.
Tailscale is optional operator access and is not part of the learner path.

## Operator handoff

After deploying the worker probe/configuration routes and applying the reviewed
`bootstrap.tf` and `media.tf` plan in the existing account, enroll an unqualified
worker with `academy.worker_admin enroll`. Keep its credential in a protected,
ignored local directory. Bind the intended engine and asset commit IDs; do not
mark qualification checks passed based on the environment probe.

Run `scripts/package-native.py --help` for private delivery. It packages committed
agent code, the dependency lock, installer, and machine credential into the
separate bootstrap S3 bucket. It prints only the path to a protected handoff
command. The command contains a short-lived download authorization: share it
privately with the host operator, never in a PR, learner page, or public log.

The operator pastes the command into the existing Ubuntu terminal. It verifies
the bundle SHA256 before extraction, retains a versioned release below
`~/.local/share/lab-onboarding/releases`, installs a separate Python 3.12 virtual
environment, and starts the `lab-onboarding-agent` **user** service. The currently
activated Isaac Python is used only to locate its environment and bootstrap uv.
The installer does not alter Isaac packages, Git trust, or lab services. The
local sudo prompt enables user-service persistence after logout.

The machine credential is stored with mode 0600, is revocable, and expires after
90 days. The private download expires after at most one hour; the S3 object is
eligible for deletion after one day. No AWS credentials are installed on Ubuntu.

## Diagnostics and evidence boundary

```bash
systemctl --user status lab-onboarding-agent.service --no-pager
journalctl --user -u lab-onboarding-agent.service -n 30 --no-pager
```

Successful enrollment uploads a bounded environment report into the machine's
`system#host-probes` record. This is installation evidence only. Native execution
remains disabled until independent Matterix and assets checkouts are pinned,
the host configuration is operator-reviewed, and the mixing/media qualification
report verifies real GPU observations, browser video, recovery, and cleanup.

The agent accepts only typed configuration for the fixed Flex runner. It has no
remote shell or arbitrary-command endpoint. A new idle configuration replaces
the previous one; an active journal always recovers using its original saved
configuration. Missing recovery configuration fails closed.

To stop the agent, use `systemctl --user stop lab-onboarding-agent.service`.
An active native child loses its lease and stops through its own supervisor;
an interrupted run then requires operator reconciliation. Do not delete a
release directory still referenced by the service or an active journal.
