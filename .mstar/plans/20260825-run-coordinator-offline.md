# Run Coordinator + Offline Reprocessing

> Source: audit DIR-03 (`.mstar/plans/audit-2026-08-24/README.md`).
> Iteration: `iter-2026-08-pilot-ops`.
> Execution mode: `sdd`.

## Status

- Priority: P2
- Category: product / operations
- Status: Done
- Depends on: `20260825-executable-pilot-workflow`, `20260825-operational-ledger` (stage-attempt ledger builds on run ledger)
- Findings cleanup: zero-residual

## Goal

Separate live-risk operations from deterministic local processing (DIR-03): a run coordinator persists per-stage attempts and permits `bili-asr run --offline` reprocessing of already-downloaded subtitles/audio. **`run` complements frozen `pilot`; it does not replace the MVP proof command.**

## Global Constraints

- `bili_client.py` remains the only HTTP owner; coordinator composes existing seams (`subtitles.harvest_subtitle`, `audio.download_audio`, `asr.transcribe`, `archive.write_archive`, `ManifestStore`). Do not fork those signatures or add a second HTTP client.
- Do not split `harvest_subtitle` into a separate `probe` stage: live harvest already probes + downloads. Diagnostic CLI `probe-subs` stays out of the coordinator.
- Stage-attempt persistence is sidecar JSONL; no manifest schema migration; `VALID_STATUSES` and `classify_risk` unchanged.
- No credentials/signed URLs/raw exceptions persisted.
- No live HTTP in tests; fake transport + stubbed `transcribe`.
- `--offline` never calls `harvest_subtitle` or `download_audio` (both always HTTP). It only runs `transcribe` / `write_archive` when inputs already exist on disk; missing input → `skipped` with reason, no silent re-download.
- `run` complements frozen `pilot`; it does not replace it.

## Interfaces (locked)

- New `bili_asr.coordinator.RunCoordinator`: per-stage attempt ledger, append-only JSONL under `{archive_root}/coordinator/attempts.jsonl`. Fields: `stage` (`harvest` | `download` | `asr` | `archive`), `work_id`, `attempt` (int), `outcome` (`ok` | `failed` | `skipped`), `error_code` (int | short str | null), `artifact_paths` (list[str] relative to archive root), `started_at` / `finished_at`.
- Stage → live seam:
  - `harvest` → `harvest_subtitle(client, PageIdentity, store, archive_root)` → status `subtitle_done` | `needs_audio`
  - `download` → `download_audio(client, PageIdentity, out_path, store=store)` → audio path; `out_path` from `artifact_stem`
  - `asr` → `transcribe(audio_path, model_name=None)`
  - `archive` → `write_archive(archive_root, entry, segments, *, source="subtitle"|"asr", raw=...)`
- CLI: `bili-asr run --scope pending|failed|<work_id>... [--offline] [--limit N] [--archive-root]` — per manifest `status`, bounded, resumable. Rerun skips already-`archived` / `gone`.
- `--offline` allowed stages: `asr` if `{archive_root}/audio/{stem}.m4a` (or `.flac` sibling) exists; `archive` if subtitle raw `{archive_root}/subtitles/raw/{stem}.json` or ASR segments can be produced from on-disk audio. `harvest`/`download` are `skipped` with reason `offline`.
- Stage failures recorded; batch continues per `work_id`. Also append a compatible `RunLedger` record (`command="run"`) when plan C is present.

## Tasks

### Task 1: Stage-attempt ledger + coordinator core

- [x] `RunCoordinator` records per-stage attempts atomically (append-only, no partial lines).
- [x] `run` command executes stages according to manifest `status`; per-item failures recorded and batch continues.
- [x] Bounded `--limit`; rerun skips already-terminal rows.

Run: focused `tests/test_coordinator.py` passes with fake transport + stubbed ASR.

### Task 2: Offline reprocessing + surfaces

- [x] `--offline` reprocesses only artifacts on disk; missing input → skipped with reason, no network calls.
- [x] Failure summary per run; nonzero exit when scope not fully processed.
- [x] README documents coordinator stages, offline mode, and the live-vs-deterministic boundary.

Run: focused tests + full suite exit 0.

## Acceptance Criteria

- Stage attempts persisted for every executed stage; crash leaves no partial record.
- `bili-asr run --offline` never issues HTTP; missing on-disk input → skipped with reason; operator sees a per-run failure summary.
- Nonzero exit when the requested scope is not fully processed; per-item CDN/ASR failures do not stop the batch.
- Reruns skip already-terminal rows (idempotent artifacts/manifest).
- `run` does not change `pilot` semantics or the frozen risk taxonomy.
- Full Python 3.12 suite passes; no live HTTP.

## STOP Conditions

- Coordinator requires manifest schema change → STOP (sidecar only).
- Offline mode cannot be proven network-free in tests → STOP until a test seam exists.
- Stage semantics conflict with frozen status machine (`VALID_STATUSES`) → STOP, align first.

## Prepare → Execute Handoff

Stage set and `--offline` semantics are locked; `run` complements frozen `pilot` and does not replace it. Execute attempt ledger first, then run command, then offline mode.

## Durable Review Summary

**Review Gate Summary**

- `Decision`: **Approve** (after one fix round)
- `Review range / Diff basis`: `5b392cc64f44099e48f83e32a8fc2ade6fe01e4c..d665034` (branch commits 6827180 T1, 2abf3e4 T2, d665034 QC-fix)
- `Review bundle`: `.mstar/sdd/20260825-run-coordinator-offline/review/`
- `QC inputs`: `qc1.md` / `qc2.md` / `qc3.md` + `qc-consolidated.md`
- `Blocking result`: fixed — W1 download/archive stage-failure ledger records (×3 seats converge) + F-002 explicit-scope terminal rerun exit; fixed in `d665034`, revalidated in place (Approve ×3, 0 open)
- `Residual findings`: none (zero-residual; M3 carries an in-code `simplify:` marker instead)
- L2 task reviews: T1 Approved (0C/0I/5M → M1/M2/M4 fixed in T2), T2 Approved (0C/0I/2M noted)
- Tests at close: implementer-reported 277 passed (255 baseline + 22 coordinator); runtime verification → QA gate
