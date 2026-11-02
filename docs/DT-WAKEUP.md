# On-demand digital twin

The browser's Cognito access and ID tokens last **60 minutes**. Existing tokens
keep their original expiration; sign in again after deployment to receive the new
duration. Silent renewal remains off, so polling does not extend a login forever.
Refresh tokens, worker credentials, live-video grants and native safety leases
retain their independent policies.

## Capacity request (independent of native execution)

Every authenticated learner with an owned saved session can use **Request GPU**
in Workflow Studio, the first-transfer lesson or an existing mixing session.
`POST /api/sessions/{session_id}/gpu-request` accepts a UUID `request_id` and the
current `expected_version`. It does not require native execution to be enabled,
an active commissioning grant or a compatible scene. This removes the deadlock
where a blocked native run was the only way to wake the worker.

A transaction checks the unchanged saved-session version and commits an
owner-scoped receipt together with GPU demand. It never creates a native run,
reserves a worker, changes the design revision or clears prior cleanup locks.
Only one outstanding request per session is accepted for one hour; repeat clicks
return the same receipt without extending its expiry. Replaying an expired ID
returns that expired receipt; a new request ID is required to request again.
`GET` on the same route recovers the receipt and current GPU state after a lost
response or reload. Reads do not renew demand. Another user's session returns
404; stale versions return 409; an unconfigured allocator returns 503.

A 202 response means the request was recorded, not that an instance was assigned
exclusively, the worker qualified, or Isaac rendered a frame. The current allocator
wakes one pinned shared instance. Availability, busy/queue and capacity failures
are visible separately from saved-workflow execution checks. No native workflow
is automatically submitted when capacity becomes ready.

## Native run request path

1. Save a workflow and request its native run with the current session version.
2. The backend checks JWT ownership, saved revision, supported scene, qualification
   or exact commissioning authority, and previous cleanup. Rejected requests
   cannot create run demand. An independent capacity request remains available.
3. One DynamoDB transaction records the immutable run, session reservation, queue
   entry and demand for the pinned GPU. The run ID is the idempotency key; refresh
   reconciles the same run rather than submitting another one.
4. The API reconciles power immediately. The existing one-minute reaper continues
   reconciliation. EC2 is described before retrying start; only the configured
   instance can start or stop. There is no instance creation, model switching or
   automatic replay of native execution.
5. Once EC2 is running, SSM invokes a parameterless document that starts only the
   installed IMDS firewall and Academy simulation service. A fresh authenticated
   worker poll establishes worker connectivity, never qualification or Isaac
   frames. Actual scene loading and video remain separate run states.
6. The worker claims queued workflows in order, with the existing plan, subject,
   lease and native-evidence checks. Its atomic claim also fences the power state.

The page shows sleeping, GPU startup, worker preparation, queue/busy, capacity
wait, shutdown and operator-attention states. If AWS reports insufficient
capacity, demand stays durable and retries are spaced by at least 60 seconds.
No start-latency guarantee is made when AWS cannot allocate the GPU. A request
queued for an hour expires without dispatch; its versioned reservation is released
with an explicit `never_started` receipt, not a claimed native reset.

## Idle shutdown and races

The GPU remains warm for one hour after the latest accepted request, active run
or verified cleanup, whichever is later. Read-only page polling does not renew
this timer. The controller stops only with an empty queue, no active/unresolved
worker run, and a fresh worker poll from an empty local journal. An expired lease
or missing worker is not sufficient cleanup evidence.

Power operations acquire a 90-second versioned operation fence against worker
claims. A workflow submitted during shutdown remains queued and renews demand;
it cannot claim until shutdown completes and power has been restored. An unknown
SSM result is latched and is not replayed. Worker startup has a ten-minute bound;
failure becomes operator attention, not an endless preparation message. Stale
workers retain the shutdown guard and require operator reconciliation.

The fence exceeds the hard timeout of both calling Lambdas (15/30 seconds), so
an expired invocation cannot later stop a newly claimed run. Before issuing a
power mutation the controller rechecks its token and persists intent. A lost stop
response keeps a separate claim fence even if EC2 still reports running. It is
released only after the controller observes stopped; operator recovery can stop
the host after verifying no active run, then let the normal reconciler observe
that postcondition. Do not clear the fence solely because the worker is polling.

## Deployment

Set `gpu_instance_id` to one existing, reviewed EC2 GPU and `gpu_worker_id` to its
registered worker. Leaving the instance ID empty disables power management.
Terraform adds one fixed SSM document and narrowly scoped power policies for the
existing API/reaper roles. It updates the existing functions' configuration and
Cognito client; it never creates or replaces a GPU, bucket, user pool or table.
Preserve live alert configuration when preparing local tfvars.

Publish the tested application release and review/apply the corresponding saved
Terraform plan following [AWS.md](AWS.md). The installed native service is started
by SSM after wakeup; it need not be enabled on every boot. Keep its exact installed
release and source pins under the existing commissioning procedure.

Power management does **not** set `remote_execution_enabled`, qualify a worker,
extend an expired commissioning grant or authorize arbitrary saved plans. The
current pilot still needs its remaining qualification gates before general
learner execution. A one-hour Cognito login is not native execution authority.

## Validation

Tests exercise the controller with SQLite and mocked DynamoDB/EC2/SSM, including
concurrent demand, capacity backoff, unknown command responses, worker startup
deadline, shutdown/claim fencing, queued expiry and owner rejection. Browser
journeys check startup/capacity messaging, requesting while native execution is
blocked, lost-response recovery, mobile layout and no resubmission across refresh.
These tests are control-plane evidence. Real boot, SSM service start, native
dispatch and idle shutdown require an AWS GPU acceptance exercise when capacity
is available.

Primary references: [EC2 start](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_StartInstances.html),
[EC2 IAM examples](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ExamplePolicies_EC2.html),
[Cognito access-token lifetime](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html).
