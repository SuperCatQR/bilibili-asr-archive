# Operational Run Ledger

> Source: audit DIR-01 (`.mstar/plans/audit-2026-08-24/README.md`).
> Iteration: `iter-2026-08-pilot-ops`.
> Execution mode: `sdd`.

## Status

- Priority: P1
- Category: product / operations
- Status: Done
- Depends on: none
- Findings cleanup: zero-residual

## Goal

Treat archive progress as a first-class **operator-visible** ledger (DIR-01): persist per-run metadata (cursor, last error code, coverage summary) and expose it via `bili-asr status` / `bili-asr runs`, without changing the transport seam or JSONL row schema.

## Global Constraints

- No manifest schema migration; JSONL rows keep last-write-wins per `work_id`; ledger is a sidecar file, not extra columns on the row.
- `bili_client.py` remains the only HTTP owner; ledger I/O lives in a new module `bili_asr.run_ledger` imported only from `cli` (never from `bili_client`). No new runtime dependencies.
- No credentials, signed URLs, or raw exception text in the ledger (same redaction markers as `meta_cursor._FORBIDDEN_MARKERS`).
- `meta-cursor.json` (`MetaCursorStore`) stays the crawl-cursor SSOT (`mid`, `next_page`, `total`, `state` ∈ {`risk_interrupted`,`limited`,`complete`}, `last_api_error_code`, `updated_at`; `running` is in-memory only). Ledger complements it; do not replace atomic cursor replace with JSONL append.
- No live HTTP in tests. Risk taxonomy unchanged.

## Interfaces (locked)

- New `bili_asr.run_ledger.RunLedger(root)`: `{archive_root}/run-ledger.jsonl` (append-only, one JSON object per line; crash-safe: never leave a truncated line).
- Record fields (locked): `run_id` (opaque timestamp+random string), `command` (`fetch-meta` | `pilot` | later `run`), optional `mid` (int) and/or `work_ids` (list[str]), `started_at` / `finished_at` (ISO-8601 Z), `exit_code` (int), `pages_fetched` / `records_fetched` / `records_existing` (int | null), `last_api_error_code` (int | short str | null — never exception text), `coverage_summary` (dict of **manifest `status`** → count; keys from `VALID_STATUSES` only), `cursor_snapshot` (copy of the six `MetaCursorStore` keys or null if no cursor).
- Do not name the coverage map `state`; cursor `state` and row `status` stay distinct.
- CLI: `bili-asr status --archive-root <root>` keeps current per-`status` counts and adds run-history + coverage from the ledger; `bili-asr runs [--limit N] [--archive-root]` is a dedicated verb (not only `status --runs`).
- Commands that append a run record: `fetch-meta` on exit 0 and 2; `pilot` on process exit (any code). Plan E `run` must append a compatible `command="run"` record (coordinator stage JSONL is a different sidecar).

## Tasks

### Task 1: Persist run records

- [x] `RunLedger` append-only JSONL writer + loader; atomic per-line writes (no partial records on crash).
- [x] Fetch-meta appends a record on exit 0 and exit 2 with cursor snapshot.
- [x] `pilot` appends a run record (branch counts live in coverage_summary / command field; no raw exceptions).
- [x] Records contain no cookies/SESSDATA/signed URLs/raw exceptions.

Run: focused `tests/test_run_ledger.py` passes.

### Task 2: Inspectable status/runs

- [x] `bili-asr status` prints run history + per-status coverage summary (manifest `status` counts).
- [x] `bili-asr runs [--limit N]` lists recent runs with exit codes and cursor `state`.
- [x] README documents ledger schema and status/runs output.

Run: focused tests + full suite exit 0.

## Acceptance Criteria

- Every `fetch-meta` run (exit 0 or 2) and every `pilot` run leaves an inspectable record (run_id, command, timestamps, exit_code, cursor snapshot, last_api_error_code, per-status coverage); crash leaves no partial record.
- `bili-asr status` and `bili-asr runs` expose coverage without claiming full enumeration for `limited`.
- Ledger is a sidecar; JSONL manifest rows unchanged (last-write-wins per `work_id`).
- No credentials/signed URLs/raw exceptions in ledger or operator output.
- Full Python 3.12 suite passes; no live HTTP.

## STOP Conditions

- Ledger requires manifest row schema change → STOP (sidecar only).
- Coverage summary cannot be derived without contradicting `complete`/`limited` semantics → STOP, align with cursor contract.

## Prepare → Execute Handoff

Lock field schema and whether `status` output changes break existing tests. Execute ledger writer first, then status/runs surfaces.

## Durable Review Summary

- **QC (tri, sdd)**: Approve — 3/3 seats (qc1 architecture, qc2 security/correctness, qc3 perf/reliability). 0 Critical/Important/Warning. 1 nit + 1 suggestion fixed in `cffe0f1` (load() non-dict diagnostic; VALID_COMMANDS docstring); targeted re-review qc1+qc2 Approve. Future-scale flock/reverse-seek suggestions documented keep-as-is. Reports: `.mstar/sdd/20260825-operational-ledger/review/qc1-3.md` + `qc-consolidated.md`.
- **QA (mandatory, acceptance-only)**: **Pass / Recommend Done** — AC1–AC5 all verified (L1 evidence reuse + targeted re-runs; 28 focused + 218 full tests; checkout aligned at `cffe0f1`; 0 open residuals). Report: `.mstar/sdd/20260825-operational-ledger/review/qa.md`.
- **Residuals**: none open (zero-residual).
