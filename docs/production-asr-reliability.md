# ASR reliability repair and production acceptance (#450–#452)

The production server was powered off during this repair. The following describes
code and offline test coverage, not a claim about an active production worker or
a successful re-alignment of the retained production sample.

## Boundaries and repair scope

* #450 adds one allowlisted failure vocabulary at both sides of the ASR process
  boundary and in the generic workflow executor. Only phase, a reviewed exception
  type, numeric errno/SQLite codes and validated symbolic names cross IPC. Parent
  code adds its trusted job, attempt, profile and acquisition-run correlation.
  Existing reviewed business errors and cancellation/lease fencing retain their
  behavior. A failure to persist failure details emits a minimal independent
  stderr event; it cannot make a broken database capable of recording itself.
  Exception messages, tracebacks, paths, model text, cookies and `.env` content
  never enter this fallback diagnostic. Historical missing evidence stays missing.
* #451 adds a versioned optional `deadline` extension inside the frozen v2 ASR
  profile. Existing default/fixed snapshots retain their original canonical bytes
  and digest. Planning a scaled profile creates a new immutable identity; changing
  an environment variable or retrying an old task does not change its timeout.
  One process protocol now supervises both persistent and one-shot inference.
* #452 distinguishes expected untimed punctuation from unmatched meaningful
  recognized text and excess aligner units. It retains recognized text, original
  cue values and a bounded private aligner witness and rejects unresolved alignment
  through the existing admission assessment. This also catches a mismatch hidden
  by a later positive-duration cue merge. It does not delete text, add milliseconds,
  sort/clamp cues or invent a new alignment. Individual zero-span character units
  are retained as evidence; the cue contract still determines representability.

The existing `preserve_inference` transaction records inference completion before
`require_admission` can block publication or paid proofreading. The private witness
is limited to 512 units and 8192 characters per affected chunk, explicitly recording
truncation and original counts. The already-existing complete recognized text and
original inference segments remain in private assessment evidence. Public failures
contain stable issue codes/counts and no witness text.

## New production profiles must explicitly enable scaled deadlines

The plan default remains `fixed` for compatibility. To address the observed healthy
long-input timeout, the production plan **must** opt into `audio-scaled`; restarting
an old 1800-second task does not activate the new policy. Preserve the original
model/revision, precision, chunk, language and runtime fields when constructing a
replacement profile; the following shows only the new deadline options:

```console
bili-asr workflow plan --archive-root ARCHIVE_ROOT --part-id PART_ID --profile-key qwen3-production-scaled-v1 --inference-timeout-policy audio-scaled --inference-timeout 1800 --inference-max-rtf 0.25 --inference-startup-seconds 300 --inference-hard-cap-seconds 14400 --inference-no-progress-seconds 600
```

The frozen total budget in seconds is:

```text
min(hard_cap, max(inference_timeout_seconds, startup_seconds + audio_duration_seconds * max_rtf))
```

With these initial acceptance settings, a four-hour input gets a 3900-second total
budget. The 1800-second minimum does not permit a 1800-second hang: startup has a
300-second bound until the first actual work completion, then a separate 600-second
no-progress bound applies. The hard total deadline cannot be extended by progress.
These are proposed acceptance settings based on the captured timeout evidence;
production GPU throughput and phase durations must be measured before tuning them.

Only actual model readiness, prepared audio/chunks, decoded batches, aligned batches
and completed chunks advance progress. Entering `load`, `decode` or `align`, a
thread heartbeat or a duplicate/out-of-order progress sequence does not advance it.
The parent kills/reaps a timed-out child and its next request starts a new session.
Checkpoint, authoritative cancellation, lease and stale-response guards still apply.
CPU profiles which explicitly select this policy also use the killable boundary.

Scaled mode requires a positive integer `duration_ms` in the verified fixed audio
dependency evidence. Missing, zero, boolean, string or fractional duration is refused
as `asr_deadline_duration_unavailable` before inference. There is no implicit metadata
guess or fallback to an unbounded CPU path. First obtain and validate the audio
duration, then create a new replacement input/profile through the existing planner.
An explicitly selected legacy `fixed` profile remains available for an inspected
case, retaining exactly its configured total timeout and no invented duration.

## Frozen replacement and retained evidence

Do not update `workflow_asr_profile_configs`, old payloads, attempts or holds in place.
For a completed but unusable output with retained assessment evidence, use the
existing `workflow repair-asr --job-id ... --profile-config ... --reason ...` flow
with a full reviewed `AsrProfile` JSON and the new deadline fields. A timed-out job
has no completed inference assessment; `repair-asr` deliberately refuses to pretend
it does. Plan a new profile through the existing planning API and retain the original
timeout attempt. Use normal dependency/recovery inspection for downstream work.

For `BV1PM411U789` P1, original aligner units were not captured in the historical
failed run. The new behavior safely rejects a reproduced unmatched first sentence
and preserves new raw evidence; it does not establish why the production aligner
missed it. Re-run the retained audio under a newly frozen inspected alignment profile,
compare the full recognized text, unit matching, intervals, coverage and publication,
and keep the old attempt/assessment identity before considering #452 resolved.

## Acceptance still required on the production host

1. Activate the verified candidate release and check each worker's actual code/profile
   identity before using the new switches. Keep the previous release for rollback.
2. Run a short sample and one of the original four-hour samples with the scaled
   profile. Inspect effective total budget, real chunk progression, GPU utilization,
   final admission and publication. Tune budgets using measured phase durations.
3. Re-align the retained zero-first-cue sample. Inspect private raw units and complete
   text without pasting transcript content into an issue. Require legal cue intervals
   and successful admission/publication; a structured refusal alone is not a recovery.
4. Confirm new SQLite/OS/model failures have safe codes and trusted run/attempt links,
   while cancellation and lease loss never commit stale output. Historical empty
   diagnostics remain explicitly unavailable.

Offline suites cover frozen v2 golden digests and extensions, CLI/runtime budgeting,
actual spawn-process success/progress/hang/crash and secret sentinels, real SQLite
`SQLITE_BUSY`/`SQLITE_CANTOPEN`, private evidence retention, chunk boundaries,
admission and paid-work blocking. `RLIMIT_NOFILE` exhaustion is a POSIX-only isolated
test; Windows runs report it skipped rather than claim a Linux FD experiment passed.
