### Task 2: Inspectable status/runs

- [ ] `bili-asr status` prints run history + per-status coverage summary (manifest `status` counts).
- [ ] `bili-asr runs [--limit N]` lists recent runs with exit codes and cursor `state`.
- [ ] README documents ledger schema and status/runs output.

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

(Filled after QC/QA.)
