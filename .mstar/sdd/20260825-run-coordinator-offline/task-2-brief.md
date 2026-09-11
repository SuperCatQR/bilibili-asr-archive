### Task 2: Offline reprocessing + surfaces

- [ ] `--offline` reprocesses only artifacts on disk; missing input → skipped with reason, no network calls.
- [ ] Failure summary per run; nonzero exit when scope not fully processed.
- [ ] README documents coordinator stages, offline mode, and the live-vs-deterministic boundary.

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

(Filled after QC/QA.)
