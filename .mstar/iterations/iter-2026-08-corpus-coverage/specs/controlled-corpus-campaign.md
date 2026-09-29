---
iteration: iter-2026-08-corpus-coverage
plan_id: 20260828-controlled-corpus-campaign
status: implemented
---
# Controlled corpus campaign contract

## Specify
**Value:** operators can run bounded sequential production batches and recover risk interruptions without duplicate ownership or false completion. **Target:** campaign state is atomic, redacted, scope-bound, and composes the shipped `schedule`/`RunCoordinator` seams. **Non-goals:** concurrent workers, daemonization, schema/status-taxonomy changes, automatic credentials, and live traffic in tests.

## Clarify
- `schedule --limit` remains the bounded primitive; campaign adds checkpoint/reporting, not a second state machine.
- Resume is valid only for a matching, uncorrupted risk-interruption checkpoint; deliberate limited/complete states are not auto-resumed.
- Manifest JSONL remains SSOT; campaign evidence is a redacted sidecar.

## Architect review

The runner composes existing bounded `RunCoordinator`/scheduler seams and does not reimplement stage transitions. `scheduler.json` remains the per-invocation batch checkpoint and its `SchedulerStore` resume vocabulary is authoritative; the new `campaign.json` is only a campaign-level aggregate/audit projection and never owns per-row stage transitions. Inputs are `scope: str`, `batch_limit: int > 0`, explicit `archive_root: Path`, `resume: bool`, plus the existing client/offline/audio-budget seams. Checkpoint fields are scope/policy fingerprint, selected/processed work IDs, `complete|limited|risk_interrupted`, and redacted reason codes. Atomic replace plus directory fsync is required. Malformed, mismatched, unknown-state, or out-of-scope IDs are drift and STOP. Rollback removes only the new campaign projection. Verify: `PYTHONPATH=. uv run --with pytest pytest -q tests/test_campaign.py tests/test_cli_help.py`.

## Runtime wiring clarification

`CampaignRunner` accepts the existing `RunCoordinator` inputs (`client`, `offline`, `max_audio_bytes`, and pacing callback) and a scope-row selector supplied by the CLI adapter; tests use a fake selector/coordinator. Live campaign mode must not force offline execution. The `campaign` CLI command is a bounded convenience surface over this runner and uses the existing `--sessdata` resolution without printing or persisting its value. `campaign.json` may contain only aggregate IDs/codes and the latest bounded checkpoint; it is not a second manifest or scheduler state machine.

## Plan and acceptance
- Input contract: `scope` plus integer `batch_limit > 0`; optional `resume`; archive root is explicit.
- Output contract: `CampaignSummary.to_dict()` has stable keys for selected, processed, skipped, failed, checkpoint state, and redacted reason codes.
- Atomicity: a crash leaves either the prior complete checkpoint or one complete replacement; no partial JSONL record is accepted.
- Ownership: checkpoint records only work IDs successfully processed or already terminal; budget/offline/missing-artifact skips remain retryable.
- Verification: fixture tests cover restart, duplicate prevention, malformed/mismatched checkpoint, redaction, and exits 0/1/2. No credential, URL, model, or media bytes appear in fixtures.
- Stop: if current scheduler/coordinator signatures differ, update this contract before implementation; if a second HTTP client or concurrency is required, stop.
