### Task 2: Pin idempotent reruns and dependency errors

- [ ] Completed pilot rerun skips archived rows / produces no duplicate artifacts or manifest rows.
- [ ] Missing optional ASR dependency returns a clear nonzero result and does not mark the row archived.
- [ ] Subtitle branch never calls ASR; audio branch calls it exactly once.

Run: focused suite above exits 0.

## Acceptance Criteria

- Fresh `meta_ok` fixture drives a bounded `pilot --n N` to both branch outcomes under fakes (operator-visible summary: branch counts, terminal states, missing-branch reason).
- Subtitle-hit rows archived without ASR; audio rows archived only after successful transcript writing.
- Missing ASR dependency leaves row non-archived, nonzero result, install hint (`pip install -e "bilibili-asr-archive/[asr]"`).
- Unavailable branch coverage → nonzero exit identifying what is missing; completed rerun is idempotent (no duplicate artifacts/rows).
- When a selected bvid has multiple pagelist parts, each `work_id` (`bvid:pN`) is processed or reported failed (no silent page-1-only pilot).
- Focused pytest exits 0; README documents execution, branch coverage, rerun, optional-ASR failure.
- `git status --short` shows only in-scope files.

## STOP Conditions

- Frozen spec read as selection-only pilot → STOP and escalate before changing behavior.
- Manifest cannot distinguish subtitle hit from ASR result without a `status` change → STOP, align the status machine first.
- Fake ASR seam cannot be injected without importing FunASR at import time → STOP; preserve lazy import.

## Prepare → Execute Handoff

Interfaces are locked: live harvest/download may use injected fake HTTP; tests never call the network. Execute with fake client + monkeypatched ASR proving both branches, then focused suite before plan B broadens entrypoint integration coverage.

## Durable Review Summary

(Filled after QC/QA.)
