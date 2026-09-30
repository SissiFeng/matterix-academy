# Connect an existing Ubuntu simulation host

Status: administrator handoff. No Ubuntu deployment or real streaming has been performed by this release. Academy is ready for local course development without a server; students cannot enable remote execution themselves.

## Information needed for the first integration

- Existing SSH alias or host/user and the operator's approved authentication method. Keep passwords and private keys out of chat, repository and shell command arguments.
- Matterix checkout path, current commit, asset checkout/version, Isaac installation/version and the known-working Flex startup command.
- GPU model/driver and a running Flex scene with the first-transfer actions and native state readback available.
- Reachability from the Academy API to Ubuntu, and from student browsers to the authenticated media endpoint. Configure these separately.

Do not reinstall drivers, expose new ports or change the operator's current simulation environment merely to check readiness. First reproduce the existing working scene, then install the new gateway alongside it with an explicit deployment procedure.

## What Academy currently provides

- A read-only authenticated `/api/remote/status` endpoint. It accepts no browser-supplied host, token or URL. Its response never includes service credentials or the configured host.
- An HTTPS client for the proposed [gateway contract](MATTERIX-CONTRACT.md), including recovery by allocation and command IDs known before transmission.
- Student UI states for not configured, unavailable and awaiting qualification. All states keep remote execution disabled. A successful capability response is not an execution or streaming acceptance test.

The operator supplies `ACADEMY_GATEWAY_URL` (HTTPS base URL, no embedded credentials/query/fragment) and `ACADEMY_GATEWAY_TOKEN` through a protected environment or deployment secret. The API uses these to request `/v1/capabilities`. Do not put the service token in frontend environment variables, student forms, URLs or logs. AWS secret wiring and private network reachability require deployment configuration; adding these environment variables locally is not an AWS deployment.

## Qualification order

1. Read-only capability and version checks against the actual Ubuntu host.
2. Gateway-side single active learner lease and waiting queue. An existing desktop session is never taken over silently.
3. Allocate a clean first-transfer scene, verify object identities and return versioned observations.
4. Execute one 100 µL transfer with acknowledgements and native observations; explicitly mark absent observations instead of deriving them from video.
5. Lose a response deliberately, resolve it through the original command ID, and prove the liquid transfer occurred at most once.
6. Pause/reconnect, reset all participating state, release, and verify a subsequent learner starts clean. Failed cleanup must prevent reassignment.
7. Add session-scoped, expiring, authenticated streaming with controlled camera/object interaction. No general-purpose Isaac editor or shell is exposed.
8. Record the engine/assets, test results and installed-version-specific media configuration. Only then implement and enable the live student execution route.

The existing synthetic course remains separately labeled. It never substitutes its model output for a failed or unavailable remote operation. The single-user lease scheduler, Ubuntu gateway server, native state adapter and authenticated media integration remain to be implemented with access to the actual host.
