# Academy 0.2.0 — internal Flex browser DT release

This is a **local source release**, not a deployed GPU service.

- Source commit: `674c1e22808a0b4ad3cca09b90204f0a370ee74f`
- Local annotated tag: `academy-v0.2.0-internal-flex`
- Source archive SHA256: `d1cdf5ec4f0391e3a3563b61ec6b7c07a5e6b12c8ede7b560f4564635b636c6a`
- Image manifest SHA256: `50f51dc64a45b4595378fa04e86e7162d965e4013369f9f6930707334e502882`

The release includes the English synthetic workflow course, owner/version-safe
bounded browser commissioning, native frame evidence and correlation tools, a
pinned image recipe, complete hashed agent/runtime requirements and guarded image
build commands. Machine-readable pins are in `ops/ec2-gpu/academy-release.json`.
That metadata record is a later commit; the source tag intentionally identifies
the tested implementation archived for this release.

| Gate | Current evidence |
|---|---|
| Academy implementation | 482 backend tests and 42 browser journeys passed |
| Release artifacts | Source archive, image manifest, Lambda and 35 web files checksum-bound to the source commit |
| Internal source inputs | Both independent archives restored and verified clean at exact internal pins; LFS assets materialized |
| Native dependencies | 245-package runtime and 39-package agent closures, hash-enforced Linux installation dry runs |
| NVIDIA installer | Official 595.58.03 installer downloaded outside the repo and publisher checksum verified |
| Packer recipe | Actual Amazon 1.8.3 plugin schema validation passed with synthetic inputs and cloud access blocked |
| GPU AMI / host | Not built or started |
| Existing AWS app deployment | Not updated; no push or deployment performed |
| Actual browser → native DT | Pending an authorized GPU host and same-release API/frontend deployment |
| Worker qualification | False; no native acceptance claim |

The protected local handoff directory contains all eight named image inputs,
`SHA256SUMS`, `release.json`, `input-check.json`, `deployment/`, a false-by-default
build variable file and `START-HERE.md`. It is outside every source checkout.
Do not publish its private internal source archives or add enrollment credentials.

Start with [the image build procedure](GPU-IMAGE-BUILD.md), then
[actual browser commissioning](COMMISSIONING.md). The build wrapper's `check`
action is local-only and passed against the assembled inputs. Its `build` action
requires explicit resource/license authorization and verified caller identity.
No paid resource, AMI, KVS channel, account selection, live STS call or cloud write
was performed for this release preparation. Image and browser acceptance remain
separate gates; local synthetic tests do not satisfy them.
