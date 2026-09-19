---
module: bili-asr queue bridge (archive.db → manifest derivation)
date: 2026-09-19
last_updated: 2026-09-19
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: 20260919-sqlite-queue-bridge
applies_when:
  - deriving operational ledger rows from a recorded store
  - appending to an append-only manifest a running chain already reads
  - deciding which states a derived row may claim
  - consulting an existing ledger additively before writing a row
tags:
  - manifest
  - archive-db
  - append-only
  - queue-derivation
  - effective-key
  - work-id
---

# Deriving a work queue from a recorded store (`derive-manifest`)

## Context

Two records of the same archive coexist, and they answer different questions.
`{archive_root}/archive.db` records what happened — parts, stored captions, attempts, provenance — while
`{archive_root}/manifest/manifest.jsonl` states what the ASR/audio chain is to do next, in its own status
vocabulary (`needs_audio` → `audio_ok` → `asr_done`/`archived`). Since the SQLite caption cutover the store
path writes **no filesystem projection**: `bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py`
records a run, its attempts and the transcript and touches no path at all, so nothing on disk told the chain
which parts still needed audio. The queue had to be hand-built into the manifest by the operator.

`bili-asr derive-manifest` (module
`bilibili-asr-archive/src/bili_asr/services/manifest_derivation.py`, command `cli.py:1089`) is that bridge:
it reads the store's own work relation and appends the manifest rows the chain needs, in one run,
without restructuring the chain and without a migration or a schema change. This document is the
contract for such a bridge — which rows it may derive, what "additive" buys, and where its one
measured hole is. The operator surface (flags, output lines, exit codes, writer lock) is published in
`bilibili-asr-archive/README.md` under
`#### Derived audio queue`; the iteration-level contract is
`{ITERATION_DIR}/iter-2026-09-queue-bridge/specs/sqlite-queue-bridge-contract.md`.

## Guidance

### The queue is the store's own relation, read through the one call that owns it

- The set is "every stored part that holds no transcript and is not `gone`", read through
  `TranscriptRepository.list_pending_subtitle_parts()`
  (`bilibili-asr-archive/src/bili_asr/storage/database.py:1099`) over `v_pending_subtitles`
  (`bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql:106`; the predicate is
  `vp.processing_status <> 'gone' AND NOT EXISTS (SELECT 1 FROM transcripts ...)`, `:138-141`).
- **One home for the predicate and one for the order.** The repository imposes
  `attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC` (`database.py:1122`, `:1129`) and calls it
  the locked contract the CLI reads; a caller that restates either in its own SQL creates a second
  definition that can drift. The bridge calls the method and converts rows with `dict(row)`.
- **The queue is the whole relation.** The command takes no selector and no limit — a subset the command
  chose is not the store's queue — and an empty queue is a legitimate `0`, not an error. The empty-selection
  precedent is `download-audio --missing-subs` (`cli.py:1228`).
- **Name the set where the operator reads it.** The store has a second, unrelated backlog label: `status`
  prints `pending:` for the metadata backlog (`v_pending_metadata`), which is *not* this queue. The command's
  `--help` names "parts with no transcript" (`cli.py:211-220`) rather than reusing the bare label.

### Derive only the rows the bridge alone owns

One status is written — `needs_audio` — and the reason generalizes: **a derived row may carry a recorded
fact plus the state that fact entails; it may never carry a state that asserts an artifact exists.**

| Manifest status | Derived? | Why |
|---|---|---|
| `needs_audio` | **yes — the only one** | "the store holds no transcript for this part" *is* "this part still needs audio/ASR". |
| `pending` / `meta_ok` / `sub_checked` | no | pre-caption states of the legacy chain; the store already holds the metadata, and where a probe ran it already holds the caption outcome. Deriving one would send the chain back to re-answer what the store answered. |
| `subtitle_done` | no — structurally impossible | it asserts a caption document at `{archive_root}/subtitles/raw/{stem}.json`; the store path never writes one. |
| `audio_ok` | no | it asserts an audio artifact; the bridge downloads nothing. |
| `asr_done` / `archived` / `gone` | no | each asserts work the bridge did not do. |

`subtitle_done` is the trap, not a hypothetical: the archive stage reads subtitle segments from the
**filesystem** — the segment reader (`coordinator.py:396-400`) opens
`{archive_root}/subtitles/raw/{stem}.json` and returns `None` when it is absent — and
`_stage_archive_from_subtitle` records `error_code="missing_subtitle_raw"` and skips the row when the
document is absent (`coordinator.py:435-449`). A row synthesized as
`subtitle_done` from stored captions lands exactly there — a skip for a part whose text the archive holds.

**What the bridge writes beyond the manifest: nothing.** No `{archive_root}/subtitles/raw/`, no
`{archive_root}/audio/`, no `{archive_root}/transcripts/{srt,txt,md,raw}/`, and nothing into
`{archive_root}/archive.db`: the store connection is opened read-only
(`cli.py:1124-1126`), so a write would fail inside SQLite rather than reach the file, and the module imports
no HTTP client. The one side effect it inherits is the shipped writer lock's `{archive_root}/coordinator/`
(`cli.py:3204`), the same one `harvest-subs` documents.

### Additive, never authoritative

Per queue row, the bridge computes the candidate row and reads the manifest's **effective** row for that
key; it appends only when there is none (`manifest_derivation.py:122-161`):

```text
candidate = the nine-field row for the part
existing  = effective_row(candidate.work_id)      # ManifestStore.load(), read-only
existing is None                     -> append candidate     (derived)
existing["status"] == "needs_audio"  -> append nothing       (already_derived)
otherwise                            -> append nothing       (chain_owned)
```

- **Never regress, never advance, never restate.** Any status the chain already holds is left
  byte-for-byte as found. An authoritative bridge would do the opposite and fail twice over: it would
  re-queue a part the chain already archived (the store keeps no transcript for chain-produced archives, so
  the part never leaves the queue), and it would overwrite a live `subtitle_done` row whose raw document
  exists on disk.
- **Idempotent and byte-idempotent.** A second run over an unchanged store appends nothing and leaves both
  the effective state and the file unchanged.
- **Resumable.** Rows are appended one at a time through the store's `upsert`
  (`manifest.py:260-298`), which re-reads the latest manifest under the manifest lock, so a
  process killed mid-derivation leaves a valid prefix and re-running completes the queue.
- **Report the skips.** `chain_owned` (and `identity_mismatch`, the store contradicting its own identity
  rule) are printed per row; `already_derived` rows are not (they are the command's own previous output). A
  policy that is additive has to be *visible*, or an operator reads "nothing appended" as a failure.

### The effective key is not the key you write

This is the one measured hole in the shipped bridge, and it generalizes to any additive consult.

`ManifestStore.load()` keys every row by `_entry_key` — `work_id` when present, otherwise `bvid`
(`manifest.py:55-62`, `:150-176`, last row wins) — while a derived row is always page-qualified
`{bvid}:p{n}` (`format_work_id` in `page_identity.py:24-31`, re-validated on write by `upsert`,
`manifest.py:281-290`). A **legacy bare-`bvid` row is therefore never consulted**: a part whose only record is such a row is
appended as `needs_audio` whatever state the row holds — a terminal `archived` row included — and a bounded
run re-downloads and re-runs work the chain already finished. Nothing is overwritten (the stems differ:
`archive_stem` → bare `bvid`, `artifact_stem` → `{bvid}.p{n}`), so the cost is repeated work, not lost
artifacts. Registered as `iter-2026-09-queue-bridge · R2` (low, `defer`), with the measured exposure at
registration time **zero** — the three operator archive roots held no bare rows — and the limit stated on
both published surfaces.

The reusable part: **when an additive policy consults an existing ledger, it consults that ledger's key
function, not the key you are about to write.** Two names for one item (bare `bvid`, page-qualified
`work_id`) are two buckets, and the consult silently misses the bucket you do not write. Enumerate the key
forms the ledger can hold, make the consult use the same function the ledger's own reader uses, and narrow
the published claim to the rows it actually covers.

### One unit, converted once, in the reader's vocabulary

The chain reads seconds and fail-closes on a missing or zero duration, so the conversion is load-bearing
(`manifest_derivation.py:50-68`):

```python
if duration_ms is None:
    return 1
return max(1, duration_ms // 1000)
```

- **Floor, not round**, because it inverts the gateway's own encoding (`math.floor(seconds * 1000)` in
  `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`): an integral source duration
  round-trips exactly.
- **Clamped to ≥ 1**: the schema admits a sub-second part, and the audio budget reads `0` as *unknown* and
  fail-closes, so the smallest usable second keeps the row downloadable.
- **`duration_ms` is not copied onto the row.** The manifest's vocabulary is seconds; a second unit on the
  row is exactly the trap that a single conversion avoids.
- **An absent duration is a module decision, not a contract reading.** `duration_ms` is
  `INTEGER NOT NULL CHECK (duration_ms > 0)`, so no stored row can deliver `None`; mapping it to `1` is
  stated in the module docstring (`:22-26`) and pinned by fabricated input in the tests, so a future
  nullable duration fails a test rather than shipping silently.

### Keep the one-way direction structural

The no-back-write rule ([operational-sidecars.md](operational-sidecars.md), "Boundary and outcome
contract") forbids a projection's *inference* from becoming recorded manifest state; it does not forbid
deriving manifest state from recorded store facts. The bridge stays on the permitted side structurally,
not by convention: the store connection is `mode=ro`, so the forbidden direction (reading the manifest
*into* the store) cannot be executed, and legacy row normalisation stays with `migrate_legacy_rows`
(`manifest.py:332`) — the bridge is not a second migration path. Reading the manifest to avoid regressing
a row is the *permitted* direction and costs one read of a file the command has to open anyway.

## Why This Matters

A derivation bridge is safe to run against a live archive only because of what it refuses to write. The
failure it dodges is filesystem-shaped: a `subtitle_done` row derived from stored captions produces a
`missing_subtitle_raw` skip for a part whose text exists, and no later row repairs it — appending a
correcting row changes the *state* the chain reads, but the artifact the state asserts still does not exist.
Additivity is what makes the command re-runnable at any time: it can be the first step of every corpus run
precisely because it never overrules a row the chain owns, and a second run is a no-op rather than a
regression.

## When to Apply

- Wiring a recorded store to a second consumer that reads its own operational ledger.
- Adding rows to the append-only manifest (or any ledger whose projection is "the last row per key"),
  especially when a chain is already running against it.
- Choosing a conflict policy for a derivation: additive beats authoritative whenever the target ledger's
  states are claims about artifacts the derivation does not produce.
- Any additive consult of an existing ledger — check the ledger's key function first.
- **Not** for the deferred SRT/TXT/MD projection rebuild: that is a different problem (the store holds
  `start_ms`/`end_ms`/`text` while the chain's raw document is `body[].{from,to,content}` in seconds plus
  `lan`/`lan_doc` the store does not hold at all), and it is still open on the register.

## Examples

### Before — the manifest is hand-built

```text
fetch-meta → probe-subs → harvest-subs → (write the manifest by hand) → download-audio --missing-subs → run
```

Nothing on disk connects the store's caption outcome to the chain's queue, so the queue is only as correct
as the last hand edit, and a part recorded `no-subtitle` is indistinguishable from one never considered.

### After — the queue is derived, and only the rows the bridge owns

```text
fetch-meta → probe-subs → harvest-subs → derive-manifest → download-audio --missing-subs → run
```

```text
$ bili-asr derive-manifest --archive-root archive
BV1xx4y1zz:p2: needs_audio (duration_s=3600)
skip BV1aa:p0 chain_owned
derive-manifest: queue=2 derived=1 already_derived=0 chain_owned=1 identity_mismatch=0
```

## Evidence

- Iteration: `iter-2026-09-queue-bridge`; plan `20260919-sqlite-queue-bridge`
  (`## Review Gate Summary`, `## QA Gate Summary`).
- Contract: `{ITERATION_DIR}/iter-2026-09-queue-bridge/specs/sqlite-queue-bridge-contract.md` (§2 the queue,
  §3 the row and the conflict policy, §4 the filesystem trap, §10 the restated no-back-write rule).
- Implementation: `bilibili-asr-archive/src/bili_asr/services/manifest_derivation.py`,
  `bilibili-asr-archive/src/bili_asr/cli.py` (`_cmd_derive_manifest`, `:1089-1193`; subparser `:210-220`;
  writer-lock set `:3204`), `bilibili-asr-archive/src/bili_asr/storage/database.py`
  (`list_pending_subtitle_parts` `:1099`, `read_video_pubdates` `:1133`).
- Verification: 110 passed / 1 skipped across the bridge's four test files —
  `bilibili-asr-archive/tests/test_manifest_derivation.py`,
  `bilibili-asr-archive/tests/test_cli_derive_manifest.py`,
  `bilibili-asr-archive/tests/test_derived_queue_chain.py` and
  `bilibili-asr-archive/tests/test_transcript_repository.py`. QA gate `approve` (targeted); the chain case
  proves a derived row is selected by `download-audio --missing-subs` and reaches `archived` with no
  `missing_subtitle_raw` record.
- Limit: `iter-2026-09-queue-bridge · R2` (the bare-`bvid` effective-key hole above) and
  `iter-2026-09-queue-bridge · R1` (a failed audio attempt leaves no recency, so bounded runs re-select the
  same head) — both open, both disclosed in `bilibili-asr-archive/README.md`.

## See also

- [bilibili-asr-archive-cli.md](bilibili-asr-archive-cli.md) — the operator surface, exit taxonomy and
  writer-lock ordering this command reuses.
- [normalized-transcript-storage.md](normalized-transcript-storage.md) — the store relation read as the
  queue, its evidence columns and its locked order.
- [operational-sidecars.md](operational-sidecars.md) — the append-only manifest, its "last row per key"
  projection, and the no-back-write rule restated here.
- [subtitle-acquisition-contract.md](subtitle-acquisition-contract.md) — the path that fills the store and
  writes no projection.
