# Production reliability repair plan, issues 449–458

Branch: `codex/fix-production-issues-449-458`. Baseline: `e57edff` (includes
the production OpenCode relay work on top of main `3d5ed3a`). The server is
powered off; the implementation and offline acceptance happen locally.
Historical production snapshots in the [review](../evidence/production-failure-review-2026-10-15.md)
are evidence of the problems, not fresh runtime status.
Implementation, independent baseline comparisons, candidate identity and
remaining host acceptance are recorded in the
[verification record](../evidence/production-reliability-verification-2026-10-15.md).

## Architecture and invariants

Keep the existing workflow database as the job/attempt authority, frozen
profiles as the input identity authority, admission as the transcript quality
gate, and artifact catalog/verified receipts as the storage authority. Do not
create a second job queue, rewrite old payloads/dependencies, discard failed
attempts, manufacture timestamps, or bypass quality checks. Recovery planning
is explicit and never itself invokes a paid provider.

Separate policies which caused the failure chains:

* Request scope owns newly created SDK clients and closes them before its
  event loop exits; it does not close another owner's clients.
* Total inference budget derives from a frozen policy and audio identity;
  no-progress detection derives from real execution progress.
* Copying an additional verified replica is distinct from deleting the source.
  Live consumers and repair holds constrain release, not replica creation.
* A failed job and a successful replacement have separate immutable identities.
  Recovery records their relationship and plans a new downstream chain.
* Build, installed files, process startup identity and host acceptance are
  different facts. A local test cannot attest a powered-off production PID.

## Issue-by-issue scope

| Issue | Design and implementation boundary | Offline acceptance | Host follow-up |
|---|---|---|---|
| #449 | Request-owned SDK pool cleanup; nested scopes, cancellation and failure ownership | Repeated event loops, real SDK allocation without HTTP, all-client cleanup and original-error preservation | Drain/restart old worker; observe FD trend |
| #450 | One bounded exception vocabulary across ASR IPC and executor; safe errno/SQLite/stage details | Real SQLite/validation failures, unknown exceptions and secret sentinels | Confirm new attempts retain safe details |
| #451 | Versioned optional profile deadline policy; legacy profile identity unchanged | Long-input budget, upper bounds, progress/hang/cancel/lease fencing | Representative GPU short/long samples |
| #452 | Preserve unmatched alignment evidence; reject unusable intervals through existing admission without losing raw output | Missing/partial aligner units, first cue and chunk boundaries, full-text preservation | Re-align preserved failed sample and validate publication |
| #453 | Immutable complete-wheel release evidence, startup identity and current-disk drift; per-process lifecycle reports | Build/install/import in isolated target, disk changes after startup, stale/stopped worker reports, secret-free manifests | Candidate environment, DB compatibility, GPU acceptance, controlled switch/rollback |
| #454 | Durable collection supervision state with bounded retry/no-progress policy and explicit escalation | Restart with existing cooldown, no-progress threshold, progress reset, cancellation and incomplete enumeration | Supported upstream access and boundary reconciliation |
| #455 | Existing artifact replica/receipt path; independent copy eligibility and release blockers | Queued AI, old failed jobs, live readers, interrupted/corrupt copy, restart, unique source | Verify local target and migrate external helper policy |
| #456 | Explicit downstream recovery from validated successful replacement; reuse immutable planning | Dry-run/apply, idempotency, stale/active chain, preserved failures and dependencies | Apply reviewed production recovery plan |
| #457 | Provider finish-reason enum and matching bounded retry policy | Filter/length/unknown/empty-stop envelopes; no response text leakage | Check provider output classification in new attempts |
| #458 | Integration record with source/test/production acceptance states | Cross-module regression, packaged contracts, build, review | Close only after individual host acceptance |

Existing #350 contract checks remain strict. The ten captured rejected samples
are regression/acceptance inputs for existing bounded editorial recovery,
not a reason to relax the schema or invent issue references.

## Work ownership and integration order

The primary agent owns request lifecycle, release/runtime identity, integration
and review. ASR/diagnostics, workflow/editorial, and collection/backup agents
work in distinct module groups. Changes to shared CLI/application files are
coordinated explicitly. Integrate foundational ownership and diagnostic
boundaries first, then independent policies and services, then installed CLI
and cross-module acceptance. Commit separate repair concerns on the branch.

Verification uses synthetic or retained private fixtures, never live server
access or paid inference. Package tests must exercise installed entrypoints,
not only editable imports. Record unresolved baseline test migration failures
separately from regressions, and report production acceptance as pending.

## Detailed assessment and repair boundaries

The impact figures below are from the October 15 production review, before the
server was powered off. They are not current queue counts. The complete fault
chains, confidence limits and source fingerprints remain in the linked review.

### #449 — request ownership / P1 / confirmed mechanism

The SDK retained clients keyed by discarded event loops. The historical 782
OperationalError attempts are a cascading symptom, not evidence that SQLite
was corrupt; authentication failures are separate. Scope ownership now covers
all newly created transports and their lazy settings. Existing clients belong
to their creator. Cleanup completes before loop disposal, survives repeated
cancellation, visits every pool even after one failure, and does not replace
the original provider failure. Cleanup has a bounded transport-close wait.
The pre-existing conservative 3–5 second metadata pacing is retained and its
endpoint test is updated. Raising an FD limit remains a mitigation only.

### #450 — diagnostic boundary / P2 / confirmed evidence loss

Unknown exceptions formerly retained little beyond a class name. Add one
closed diagnostic vocabulary and one domain adapter rather than scattered
message sanitizers. Keep SQLite extended code/name, OS errno, stage and bounded
numeric location; never retain arbitrary exception text, traceback, provider
body or a class-supplied unknown error code. Preserve established lease/drain,
model identity, editorial budget and validation codes so retry policy does not
change accidentally. Cover both one-shot and persistent ASR IPC. If diagnostic
persistence itself fails, emit a bounded independent failure signal.

### #451 — long inputs / P2 / confirmed policy mismatch

Two roughly four-hour inputs exceeded the old 1800-second budget and later
succeeded under an explicit larger profile. A larger universal constant would
hide hangs and change historical execution. Add a versioned optional deadline
extension to frozen profiles. `audio-scaled` requires verified duration and
derives a capped total budget; startup and real-completion progress have
separate clocks. A four-hour synthetic input gets 3900 seconds with the stated
policy. Heartbeats and phase entry do not count as work completion. Keep old
canonical v2 bytes/digests and fixed behavior unchanged; operators explicitly
create a new profile. Deadline supervision uses a killable process on CPU too.

### #452 — alignment integrity / P1 / symptom confirmed, original cause pending

One remaining production video had two failed attempts and a zero-duration
first cue containing meaningful text. Healthy decode/hash evidence does not
prove that every alignment unit is correct. Detect unmatched meaningful text
and extra units before a later merge can make them appear representable.
Retain original text/cues plus bounded private aligner evidence through the
existing raw assessment path, and fail the existing admission gate. Do not
drop the sentence, guess duration, sort cues or relax publication. This repairs
the unsafe evidence/admission path; the production sample's successful
re-alignment remains a host acceptance item, not an offline success claim.

### #453 — release identity / P1 / confirmed cross-cutting amplification

Production had both a real mixed-module ImportError and a PID still running
old code after files changed. Complete immutable wheels replace individual
module copying. Embed source commit, lock hash and the complete code/contract
inventory; record the wheel hash outside itself. Cache startup identity once,
verify installed content, and distinguish each worker instance from a recycled
PID. Wrong-build, unattested, stale and stopped records never count as ready.
Drift and health-write failure request the existing drain; observation failure
cannot change the business attempt's outcome. Model configuration stays in
the frozen workflow authority and is referenced by digest. No new deploy
database or mutable global release singleton is introduced. Follow the
[release runbook](../operations/production-release.md) for host switching.

### #454 — source coverage / P1 / prolonged no-progress confirmed

The observed cursor stayed on page 30 through thirteen cooldowns, leaving an
830-video gap against a dynamic observed total. The reason for upstream risk
control is not proven to be a specific IP/account rule. A new bounded service
wraps the existing collector one cycle at a time; it adds no network client or
second queue. Persist policy identity, high-watermark, last real progress,
consecutive failures, accumulated actual wait and next eligible action under
the existing atomic IO/lock contract. Restart cannot reset cooldown/budgets.
Crashes reconcile committed page evidence without inventing a new progress
time. Exhaustion becomes needs_attention, never complete. Continue discovery
only through supported upstream access and reconcile the actual boundary.

### #455 — replication versus deletion / P1 / confirmed policy coupling

515 completed-ASR audio files (about 8.12 GiB) were excluded from copying; this
was not a safe-to-delete list. Introduce a distinct copy-plan contract and keep
the existing offload contract for destructive release. Queue failures, repair
holds and readers can prevent release while a verified extra replica is still
useful. Retention freezes both plans and reports copy backlog separately from
release blockers. Copy operations cannot create or resume release intents,
including anomalous pre-existing persisted rows. At deletion, recheck mode,
schema, stored operation kind, source identity/generation, receipts and every
consumer/pin/hold under the existing final write fence. Do not replace the
storage catalog or receipt mechanism. External production helpers still need
migration to this reviewed policy after the host is available.

### #456 — explicit supersession / P2 / two chains confirmed

Two successful replacement ASR jobs did not release old frozen editorial
dependencies, leaving four consumers waiting. Preserve the original producer,
failed attempts, payload and edges. An explicit read-only recovery plan binds
one validated successful replacement to exact attempt/run/transcript evidence,
then `--apply` with its plan ID creates a new frozen proofread/render DAG.
Retire only never-attempted queued consumers, inside the same transaction.
Reject running, attempted, held, changed or ambiguous chains. Budget and
delivery status stay explicit; queueing does not start paid execution or
authorize audio deletion. Reusing an existing chain is idempotent.

### #457 and existing #350 — provider semantics / P2 / confirmed classification gap

Length truncation, content_filter, unsupported/tool termination, missing or
unknown finish_reason, and an empty stop response have different meanings.
Classify finite envelopes at the provider boundary and preserve usage safely.
Read-only replay of old stored responses improves the status/retry facade
without rewriting historical error codes. Filter/protocol rejection blocks
automatic new paid calls. Existing #350 changed-input repair, chunk reuse,
budgets and strict citation/paragraph/schema checks remain authoritative.
Three synthetic bad-output classes exercise that route; the ten original
private production samples still require their own approved acceptance.

### #458 — integration / tracking

This issue is the acceptance ledger, not another runtime feature. Review
correctness, readability, architecture, security and bounded resource use.
The branch adds no runtime dependency or SQLite schema migration. Commit by
repair concern, verify packaged contracts and installed entrypoints, record
baseline/platform failures separately, and keep all child issues open until
their actual production criteria are satisfied. The final verification record
must distinguish implemented, offline-tested, installed, loaded and accepted.
