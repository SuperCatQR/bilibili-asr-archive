# Cursor-Based Resumable Metadata Enumeration

> Candidate source: `.mstar/plans/audit-2026-08-24/002-cursor-based-resume.md`.
> Iteration: `iter-2026-08-archive-foundations`.
> Execution mode: `sdd`.

## Status

- Priority: P1
- Category: bug / reliability
- State: Done
- Depends on: `20260824-multipart-page-aware-pipeline`
- Scheduled after: `20260824-multipart-page-aware-pipeline`
- Findings cleanup: zero-residual

## Goal

Make `fetch-meta --resume` continue after a risk-control stop from the last unenumerated page, while preserving already merged JSONL records and an honest terminal summary.

## Locked Prepare Decisions

- Cursor storage: archive-root `meta-cursor.json` sidecar, not a special JSONL row.
- Cursor is keyed by mid and contains `next_page`, `total`, `state`, `last_api_error_code`, and `updated_at`.
- Cursor writes use same-directory temporary file plus `os.replace`.
- Successful page persistence advances the cursor; risk stop preserves the next page and exits 2.
- Full enumeration and a deliberate page limit use distinct non-resumable terminal states; only full enumeration may claim the visible archive was completely enumerated. The deliberate-limit state records the next unenumerated page so a future intentionally broader run has an honest continuation point, while `--resume` automatically consumes only risk-interrupted cursors.
- Cursor never stores cookies, SESSDATA, signed URLs, or raw exception messages.

## Global Constraints

- Preserve `ManifestStore` JSONL row compatibility and existing API risk taxonomy.
- Keep HTTP ownership in `bili_client.py`; cursor filesystem ownership remains in the manifest/CLI seam.
- No duplicate `work_id` rows after resume (plan 001 keys JSONL by `work_id`); no live requests in tests; no model downloads.
- Do not change subtitle/audio/ASR behavior in this plan.

## Interfaces

Locked in `.mstar/iterations/iter-2026-08-archive-foundations/specs/meta-cursor.md`.

- Preserve `ManifestStore(root, rel_path=...)`, `load()`, `upsert()`, `save()` (keys are `work_id` after plan 001).
- Preserve `fetch_pages(mid, max_pages=None)` via default `start_page=1`.
- Add `start_page: int = 1` only; no filesystem I/O in `bili_client`.
- `bili_asr.meta_cursor.MetaCursorStore`: archive-root `meta-cursor.json`, same-dir temp + `os.replace`.
- `state`: `risk_interrupted` | `limited` | `complete` (plus in-memory `running` never flushed as success).

## Tasks

### Task 1: Persist and consume cursor

- [x] Implement `MetaCursorStore` schema (`mid`, `next_page`, `total`, `state`, `last_api_error_code`, `updated_at`).
- [x] Persist after successful JSONL merge; on risk exhaustion set `risk_interrupted` and `next_page=last_failed_page`, exit 2.
- [x] `--resume` consumes only matching-mid `risk_interrupted`; without `--resume`, replace stale cursor after first successful page of the new run.
- [x] `complete` vs `limited` (retain next unenumerated page); summary never calls a capped run complete.
- [x] `fetch_pages(..., start_page=1)` initializes `pn = start_page`.

### Task 2: Prove idempotency and security

- [x] Stop at page 2, assert `next_page=2`, resume at page 2.
- [x] Assert no duplicate JSONL records and no false claim for failed page.
- [x] Assert cursor contains no credentials, signed URL, or raw exception text.
- [x] Document exact resume and exit-2 behavior in README.

## Acceptance Criteria

- A risk stop on page 2 persists a resumable cursor and a later `--resume` starts at page 2.
- Resumption does not duplicate rows or re-enumerate successful pages.
- Completed and intentional-limit runs are not treated as interrupted; `complete` and `limited` remain distinguishable, and only `complete` claims full enumeration.
- Cursor writes are atomic and contain only safe scalar metadata.
- Full Python 3.12 test suite passes; no live HTTP or model downloads.

## STOP Conditions

- Cursor cannot be persisted atomically without coupling HTTP to filesystem I/O.
- Limit semantics cannot distinguish intentional stop from risk interruption.
- Existing JSONL compatibility requires an unplanned schema migration.
- A proposed change alters retry limits or risk taxonomy.

## Prepare → Execute Handoff

After PM lock and specialist edits, execute cursor tests first, then implementation, then README/idempotency coverage. Plan QC is mandatory tri-review and QA is mandatory/full.

## Durable Review Summary

- Feature HEAD / merge: `3505c2f6cd9f7e8e370ca29745795f01250a1d08` (FF into `iteration/iter-2026-08-archive-foundations`).
- QC tri + targeted revalidations: Approve (final `qc-consolidated.md`). Open Critical/Warning: 0.
- QA mandatory/full: Approve. `PYTHONPATH=src .venv-pm/bin/python -m pytest -q` → 168 passed.
- L2 reviews: Task 1 Approved after stale-cursor fix (`7d4161f`); Task 2 Approved (`ef21dde`).
- Notable decisions: per-page JSONL merge + cursor persist on resume and recrawl (mid-run `risk_interrupted`, `next_page = last_merged_pn + 1`); `known_bvids` seeded only with `--resume` (F-005); `--limit-pages` counts pages this call; stop at `ceil(total/ps)` / no-new-bvid / two empty pages.
