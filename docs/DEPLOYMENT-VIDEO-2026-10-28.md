# Browser video recovery — October 28, 2026

The signed-in Academy learner submitted two distinct, operator-scoped Studio
designs on the existing Canadian GPU pilot. Both reached native scene observations,
executed zero transfer actions, failed while waiting for browser video, and
reported native reset verified. These are failed browser acceptance runs:
`6c63cb07-a317-4461-bd76-a7ea4735f1ac` (100 µL) and
`9518ca13-e4c6-4381-a44a-843ceecc53b0` (50 µL, changed tip-rack slot).
Neither is a successful demonstration or qualification result.

The first browser connection was blocked by the deployed CloudFront CSP.
An inspected Terraform target plan updated only the existing response headers
policy (zero additions/deletions). The live header now permits regional
`wss://*.kinesisvideo.ca-central-1.amazonaws.com`, while other regions and
unrelated hosts remain excluded. `infra/main.tf` records that change.

The second browser connection reached signaling, then failed negotiation.
An independent temporary KVS signaling probe, without Isaac or workflow execution,
reproduced empty text messages (`rawLength: 0`) before and after a valid SDP answer.
The browser accepted the aiortc answer, but the production handler attempted
`JSON.parse("")` and closed negotiation with `Unexpected end of JSON input`.
The fix ignores exactly empty text frames. Malformed nonempty messages and
service rejection still close the connection. The existing publisher already
ignores unparsable messages without an identified viewer.

The diagnostic channel was retired. Its generated test track is synthetic and
provides no native rendering, liquid, motion or browser qualification evidence.
No signed URLs, TURN credentials, JWTs or learner identifiers are retained here.
AWS's JavaScript SDK likewise ignores unparsable signaling messages:
[SignalingClient.onMessage](https://github.com/awslabs/amazon-kinesis-video-streams-webrtc-sdk-js/blob/master/src/SignalingClient.ts).

Chromium regression tests exercise the real CSP and the actual viewport component
with synthetic signaling: empty frames surrounding a valid answer survive;
malformed JSON and `STATUS_RESPONSE` still fail. These tests do not prove a real
browser decoded native video. A fresh exact-design commissioning window and full
browser observation are required after publication; do not replay either failed
run or mark the quarantined worker qualified. Global remote execution remains off.
