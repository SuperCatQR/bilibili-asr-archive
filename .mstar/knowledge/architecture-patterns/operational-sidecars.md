---
module: bili-asr operational layer
date: 2026-08-25
last_updated: 2026-09-18
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: 20260825-run-coordinator-offline
applies_when:
  - adding operator-visible run history without changing JSONL rows
  - searching completed transcripts without a second SSOT
  - reprocessing on-disk artifacts without live HTTP
  - reconciling bounded campaign evidence against cumulative coverage
  - verifying integrity or recording recovery candidates without requeueing
  - evaluating future concurrency without enabling it
  - splitting quality observations into deciding defect codes and advisory content codes
  - retiring a parallel quality report without losing a signal
  - comparing an archived transcript against a second transcript of the same audio
tags:
  - sidecar-jsonl
  - run-ledger
  - fts5
  - run-coordinator
  - offline-reprocess
  - campaign-evidence-and-coverage-reconciliation
  - integrity-audit
  - quality-reason-classes-and-reference-comparison
---

# Operational sidecars and evidence projections

## Context

The frozen MVP keeps `work_id`-keyed JSONL as the archive state machine and
`bili_client` as the only HTTP owner. Operators still need per-run progress,
search/export of completed transcripts, and a way to retry ASR/archive after
downloads already exist — without migrating the manifest schema or mixing
live-risk HTTP into deterministic local work.

## Guidance

Keep the `work_id`-keyed manifest as the only item state machine. Add bounded
sidecars and deterministic derived stores for operator evidence; never rewrite
`VALID_STATUSES` or `classify_risk`.

1. **Run ledger** (`RunLedger`, command `runs` / `status` summary): append-only
   JSONL next to the archive. Record cursor snapshot, last API error *code*
   (never raw exception text), and per-status coverage. `command` is
   `fetch-meta` | `pilot` | `run` | `schedule`. Atomic tmp + fsync + same-directory replace; also
   fsync the parent directory after replace.

2. **FTS5 search/export**: SQLite read model over rows that already have
   transcript artifacts. Manifest remains SSOT; search never writes JSONL.
   Empty query → exit 1 with a clear message. Export writes metadata JSON/CSV;
   `--with-text` is optional.

3. **Run coordinator** (`bili-asr run`): stage-attempt ledger at
   `{archive_root}/coordinator/attempts.jsonl` with
   `harvest|download|asr|archive` × `ok|failed|skipped`. Compose existing
   seams (`harvest_subtitle`, `download_audio`, `transcribe`, `write_archive`);
   do not add a second HTTP client. **Every executed stage must persist an
   attempt**, including download/archive failures — otherwise `--scope failed`
   silently drops rows.

4. **Scheduler sidecar** (scheduler.json): additive state for bounded
   `bili-asr schedule` batches (complete / limited / risk_interrupted).
   `--resume` consumes only a matching-scope `risk_interrupted` sidecar.
   Default pending/failed selection keeps the 45-minute short-video policy;
   `--allow-long-live` is the explicit multi-hour opt-in and cannot set
   `--max-audio-gb 0`.

5. **Campaign projection** (`{archive-root}/campaign.json`): one aggregate checkpoint around a
   bounded sequential coordinator run. The manifest and `{archive-root}/scheduler.json` retain
   per-row ownership. Resume is valid only when scope, limit, policy fingerprint,
   selected/processed IDs, and a risk-interrupted scheduler checkpoint reconcile.
   Atomic file and directory durability is required; malformed or mismatched
   evidence fails closed. Because stdout here is the single JSON document
   downstream callers parse, diagnostics go to `stderr`; a closed fd 2 drops
   them rather than folding them into the document.

6. **Coverage and quality reports** (`coverage [--quality]`): read-only deterministic projections with an
   explicit manifest-snapshot denominator. Keep cumulative and latest-batch evidence separate. Missing
   denominators, limited/risk-interrupted states, sidecar contradictions, and missing terminal artifacts
   remain named diagnostics; no count is inferred. Quality reason codes describe structural artifacts and
   recorded content measurements only, and none claims semantic correctness. Only one of the two classes
   decides: `DEFECT_REASON_CODES` (the structural seven) drives `QualityResult.reasons`, and so
   `valid_work_items` and the exit status, while `CONTENT_REASON_CODES` (`low_confidence`, `leading_mark`,
   `fragment_cue`, `overlong_cue`, `duplicate_cue`, `repeated_ngram`, `reference_disagreement`) is advisory
   in `content_reasons` and decides nothing; `REASON_CODES` stays the ordered union, so spelling and sort
   order survive. Keep the class knowledge in one module — the CLI projects both fields into
   `rows[].reasons` (defect first) without naming a code — because one union field would flip healthy ASR
   archives to exit 1 unless every consumer learned which codes are defects. Content signals now come from
   this surface alone: the retired parallel quality script's every reachable output has a named replacement
   except `p10`, `min`, and `chars-per-min`, dropped outright (the last is not reproducible from the
   archive at all). Parity is per **artefact shape**: a `.txt`/`.md`-only row takes the plain-text arm,
   which yields no cues, so cue-level content reasons are absent for that shape — while production always
   publishes `srt`+`txt`+`md`+`raw` together. `--reference <path>` compares one selected row against a
   second transcript of the same audio (flattened text, `SequenceMatcher` with `autojunk` off, reason
   `reference_disagreement` below the `0.95` floor, no fabricated ratio when the row has no comparable
   text). Bound its *work*, not only its bytes: a long low-entropy pair costs roughly ×4 per doubling, so a
   byte-capped 8 MiB reference hangs — hence the per-side character bound, refused loudly and naming the
   side. Publish the **basename only** plus the two compared character counts, and keep the credential scan
   separator-aware (hyphen *and* underscore adjacency), because a trailing word boundary never fires after
   an underscore. A `--fail-under` knob is deliberately not ported: the mean is already archived per row
   and the reason set drives the exit.

7. **Integrity and recovery audit** (`verify`, `recover`): verification reads
   manifest, attempts, and required transcript artifacts through bounded confined
   paths. Reclaimed audio is valid after required transcript outputs exist.
   Recovery selects exact work IDs or an authoritative current defect class,
   enforces a maximum of 100 targets, and appends one redacted audit record under
   a process lock. It never requeues, changes manifest status, or edits artifacts;
   malformed, oversized, symlinked, or non-authoritative evidence fails closed.

8. **Concurrency evidence gate** (`evaluate-concurrency`): pure `go`/`no-go`
   evaluation over exact evidence and threshold schemas. Campaign identity,
   denominators, freshness, throughput, API risk, disk/reclaim, crash/restart,
   duplicate ownership, checkpoint reconciliation, taxonomy stability, and five
   write-isolation targets must all pass. Inputs are bounded and sensitive values
   fail closed. The report always retains `sequential-no-daemon`; even `go` is
   evidence for a separate approved plan, not an enablement side effect.

`--offline` never calls harvest or download. It only runs `asr` / `archive`
when `{stem}.m4a`/`.flac` or subtitle raw JSON already exist; missing input
is `skipped` with a reason. Batch continues on per-item failure. Explicit
rerun of an already-terminal `work_id` is idempotent (exit 0). `run` and
`schedule` complement frozen `pilot`; they do not replace it.

10. Keep durable sidecars append-oriented and projection-based at scale. Protect each mutation with the archive-root single-writer boundary, append revisions or attempts durably, and derive the latest validated row/run without materializing unbounded history. Preserve legacy compact snapshots for reads, but never let a malformed later revision replace the last valid state. Use trusted-local streaming only for an explicitly operator-owned archive; bounded hostile-input inspection remains capped and fail-closed.

11. Publish transcript bundles as one owned generation rather than exposing independently replaced files. Stage and fsync the complete `srt`/`txt`/`md`/raw set, replace owned outputs deterministically, then write a marker containing exact paths and digests last. Readers accept only a complete marker-matched generation. Apply the same confined-path policy to audio lookup, persistence, and reclaim; reject absolute, traversing, symlink-escaping, directory, and non-regular paths before descriptor-backed consumers use them.

## Boundary and outcome contract

The scheduler is a bounded sequential orchestration layer, not a second state
machine. Its additive scheduler.json records `complete`, `limited`, or
`risk_interrupted` for the selected scope; only a matching risk interruption
is resumable. A finite limit or a duration-policy hold must not be reported as
full-corpus completion. The existing mixed-outcome precedence remains stable:
risk interruption exits 2, any per-item failure or non-terminal skip exits 1,
and only all successful/already-terminal work exits 0. Successful rows and
retryable failures remain durable in the manifest and stage-attempt ledger.

The evidence chain is directional: a campaign records a bounded run; coverage
reconciles it against the manifest denominator; quality and integrity classify
local artifacts; the recovery surface records candidates without execution; and
the concurrency gate consumes reviewed aggregate evidence without changing the
operating mode. None of these projections may back-write an inferred truth into
the manifest. This prevents a limited batch, stale index, missing reclaimed
audio, or optimistic gate result from becoming a false production state.

## Why This Matters

Sidecars keep the frozen risk taxonomy and JSONL contract intact while giving
operators inspectable runs, reconciled coverage, structural defects and advisory
content measurements, searchable transcripts, confined integrity checks, and
auditable recovery selection. Recording every stage failure keeps `--scope
failed` and crash recovery honest; explicit denominators and non-enablement keep
bounded success from being misreported as corpus completion or permission to run
concurrently. Keeping defect and content codes in separate fields keeps a
content observation from turning a healthy archive into a failed exit code.

## When to Apply

Apply when extending this CLI (or similar archive CLIs) with operator surfaces
that must not become a second state machine. The concurrency gate pattern is
appropriate for evaluating a future mode, not for implementing that mode. Do
not use these projections to justify a daemon, concurrent writer, schema change,
or replacement of `pilot` as the MVP proof command.

## Evidence

- Iteration: `iter-2026-08-pilot-ops`
- Plans: `20260825-operational-ledger`, `20260825-search-export-fts5`,
  `20260825-run-coordinator-offline`
- Implementation: `bilibili-asr-archive/src/bili_asr/run_ledger.py`,
  `bilibili-asr-archive/src/bili_asr/search_index.py`,
  `bilibili-asr-archive/src/bili_asr/coordinator.py`
- Verification: 277 passed on Python 3.12 (QA, no live HTTP)
- Corpus-operations update: `.mstar/specs/asr-archive-cli.md` and commit `ad5253d` (mixed-outcome and scheduler changes); integration revision `ad5253d` preserves the frozen manifest/risk taxonomy and verifies 392 tests with honest exit precedence for risk, per-item failure, and already-terminal work.
- Corpus-coverage update: `.mstar/iterations/iter-2026-08-corpus-coverage/specs/` promoted into this guidance. Integration revision `69b9530` ships campaign checkpoints, reconciled coverage/quality, filtered explorer surfaces, confined integrity verification, audit-only recovery, and the non-enabling concurrency gate; the merged Python 3.12 suite passes 612 tests without live traffic.
- Persistence-scale update: `.mstar/iterations/iter-2026-08-persistence-scale-safety/specs/persistence-scale-safety.md` refreshed this guidance with durable append/projection, single-writer, atomic bundle, and confined-audio contracts; integration revision `c871da6` preserves the sequential/no-daemon boundary and the mandatory fixture-only QA evidence.
- Quality-surface update: `.mstar/iterations/iter-2026-09-asr-ops-hardening/specs/03-quality-surface.md` promoted into guidance 6 — the defect/content split, the retired standalone quality report with its three dropped outputs, and the bounded `--reference` comparison. QA `acceptance-only` (`.mstar/sdd/20260912-quality-signal-merge/review/qa-gate.md`) approved it on a fixture root rebuilt from the recorded run: 1491 passed, 4 skipped, no live HTTP.
- Current implementation anchors: `bilibili-asr-archive/src/bili_asr/campaign.py`, `bilibili-asr-archive/src/bili_asr/coverage_report.py`, `bilibili-asr-archive/src/bili_asr/quality.py`, `bilibili-asr-archive/src/bili_asr/search_index.py`, `bilibili-asr-archive/src/bili_asr/integrity.py`, and `bilibili-asr-archive/src/bili_asr/concurrency_gate.py`; operator contracts are in `bilibili-asr-archive/README.md`.

## Manifest well-formedness: one definition, three readers

The manifest is **append-only by design** (invariant 10 above). One `work_id` therefore legitimately
appears on several lines — `needs_audio` → `audio_ok` → `archived` — and the projection takes the latest
valid row. **That history is well-formed.** It is not a defect and not a malformation.

That sentence has to be *the same sentence* in every reader, and on 2026-09-18 it was not. The projection
emits `manifest_duplicate_work_id` for ordinary history; three callers then disagreed:

| Reader | What it did | Cost |
|---|---|---|
| `integrity.py` (`verify`) | the code was absent from its recognised-diagnostic vocabulary, so the else-branch mapped it to `structural_input_error`; the exit rule counts *any* diagnostic | `defects: 0` but **exit 1** on a healthy archive — the integrity gate could not be satisfied |
| `coverage_report.py` (plain `coverage`) | forced `manifest_state = "malformed"`, which blanks `denominator_available` | `{count: null, state: "unavailable"}` — the completeness command could not state its own denominator |
| `cli._cmd_coverage_quality` | no override | reported the same archive correctly — and thereby proved the other two wrong |

**The rule, and how to keep it.** Name the code once (`ORDINARY_HISTORY_DIAGNOSTICS` beside the
projection that emits it) and have every reader subtract it **by name** — a reader that filters it by
quoting the raw string literal is a regression waiting to happen. The emitter stays: the projection is
allowed to report what it saw, and the *readers* decide what it means.

**Two traps this defect taught, both worth remembering:**

- **A half-fix passes a casual check.** Deleting only the coverage override restores the denominator but
  leaves the code in `diagnostics`, and `_cmd_coverage` exits non-zero on any diagnostic — so the command
  is still red while looking repaired. The fix has to be bidirectional: healthy history reaches exit 0 /
  `available`, **and** genuinely malformed input still fails closed. Pin both directions with a fixture
  that writes **two or more rows for one `work_id`**; a clean-archive fixture with one row per work_id
  asserts `defects == []` and never sees the defect at all.
- **Dead code holds judgements too.** `coverage_report._read_manifest` carries a second, contradictory
  judgement (`valid = False` on the same code, spelled with the raw literal) and has **zero call sites**.
  It is harmless until someone wires it up, at which point it re-opens exactly this defect. When a rule is
  "named once", grep for the literal — the duplicate is usually in the code nobody runs.
