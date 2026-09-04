---
iteration: iter-2026-08-corpus-coverage
plan_id: 20260828-archive-integrity-recovery
status: implemented
---
# Archive integrity, recovery, and retention contract

## Specify
**Value:** find archive defects and produce safe bounded recovery evidence without treating reclaimed audio as corruption. **Target:** idempotent read-only verifier plus an explicit audit-only recovery selector that never requeues or mutates archive state. **Non-goals:** requeue execution, manifest/status mutation, implicit deletion, remote restoration, concurrent repair, or manifest replacement.

## Clarify
- Required transcript/archive outputs determine integrity; audio absence is valid after successful reclaim.
- Verification never rewrites source state. Recovery requires an explicit bounded target and emits only redacted audit evidence.
- A final truncated attempts line is reported/tolerated for read purposes while valid prior records remain usable.

## Architect review

`IntegrityVerifier.verify(archive_root: Path, *, scope: str | None = None)` reads manifest, attempts, and artifact paths through bounded confined filesystem access; it treats `archived` transcript outputs as sufficient after reclaim, while missing required transcript artifacts remain defects. Verification is idempotent/read-only. `IntegrityVerifier.recover(archive_root: Path, *, work_ids: list[str] | None = None, defect_codes: list[str] | None = None, limit: int = 100)` is a separately explicit bounded audit operation keyed by exact work IDs or current defect classes. It writes only redacted append-only recovery-audit evidence under a process lock; it never requeues work, changes statuses, deletes transcripts, or rewrites manifest/attempts/artifacts. A truncated final attempts line remains a named diagnostic while prior valid lines are usable; malformed or oversized structural input fails closed. Verify: `PYTHONPATH=. uv run --with pytest pytest -q tests/test_integrity.py tests/test_cli_help.py`.
- Interface: `IntegrityVerifier.verify(archive_root: Path, *, scope: str | None = None) -> IntegrityReport`; defect codes are stable.
- Codes cover missing raw subtitle, missing transcript, malformed artifact, identity/path mismatch, truncated sidecar line, and retryable/incomplete state.
- Fixture proves exact categories, multipart identity, reclaimed audio allowance, idempotent verify, unchanged source mtimes/content, and audit-only recovery selection limited to named rows/classes.
- Recovery never requeues, changes manifest status, deletes transcript artifacts, or touches unrelated work IDs; malformed/oversized verifier or audit input fails closed with stable redacted reasons.
- Recovery is exposed only by the explicit `recover` command. It requires exact `--work-id` or bounded `--defect-code` selection, expands the authoritative current report before enforcing the maximum of 100 targets, writes only `coordinator/recovery-audit.jsonl` under a process lock, and never mutates manifest, attempts, audio, or transcript files. An unauthoritative, symlinked, oversized, or malformed source/audit path fails closed.
- Stop if reclaimed audio cannot be distinguished from missing required archive output.
