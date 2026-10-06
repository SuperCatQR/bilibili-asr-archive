"""Run state implementation."""

from __future__ import annotations

from datetime import datetime, timezone


def _partial_run_state(root: str, started_at: str) -> tuple[list[str], dict[str, int]]:
    """Record inputs for a run interrupted before it could summarize.

    The interruption path has no ``RunSummary``: what the run already persisted
    durably is the record's input.  ``work_ids`` are the ids the attempts
    ledger recorded at or after this run's ``started_at``, in order and deduped
    (an earlier run's attempts stay out), and the coverage summary counts the
    manifest statuses as they stand.  ``records_existing`` is *not* derived
    here: it means "records that existed before this run", so the run body
    passes its original count. Membership relies on the archive single-writer
    lock; compare UTC instants because optional fractions do not sort as ISO text.
    """
    from bili_asr.pipeline.attempts import AttemptLedger
    from bili_asr.manifest import ManifestStore
    from bili_asr.run_ledger import compute_coverage_summary

    def instant(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except (ValueError, TypeError, AttributeError):
            return None

    boundary = instant(started_at)
    if boundary is None:
        raise ValueError("invalid run start timestamp")
    attempts = AttemptLedger(root).load()
    work_ids = list(
        dict.fromkeys(
            a["work_id"] for a in attempts
            if (timestamp := instant(a["started_at"])) is not None and timestamp >= boundary
        )
    )
    entries = ManifestStore(root=root).load()
    return work_ids, compute_coverage_summary(entries)
