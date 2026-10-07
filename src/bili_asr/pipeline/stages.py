"""Stages implementation."""

from __future__ import annotations

import bili_asr.asr.config as _module_asr_config
import bili_asr.asr.coverage as _module_asr_coverage
import bili_asr.asr.runner as _module_asr_runner


import os
from typing import Any
from bili_asr import asr as asr_module
from bili_asr import audio as audio_module
from bili_asr.persistence import utc_now_iso
from bili_asr.page_identity import artifact_stem
from bili_asr.run_ledger import collect_hotwords_dropped
import bili_asr.pipeline.attempts as _dependency_attempts
import bili_asr.pipeline.models as _dependency_models
import bili_asr.pipeline.writeback as _dependency_writeback


def stage_archive_from_subtitle(
    coordinator, key: str, entry: dict[str, Any], result: _dependency_models.RowResult
) -> None:
    from bili_asr import archive as archive_module

    work_id = str(entry.get("work_id") or key)
    started = utc_now_iso()
    data = coordinator._subtitle_segments(entry)
    if data is None:
        coordinator._record(
            "archive", work_id, "skipped",
            error_code="missing_subtitle_raw", started_at=started,
        )
        result.skipped = True
        result.skip_reason = "missing_subtitle_raw"
        result.final_status = str(entry.get("status") or "")
        return
    segments, raw = data
    try:
        paths = archive_module.write_archive(
            coordinator.artifact_roots.write_base, entry, segments, source="subtitle", raw=raw
        )
    except Exception as exc:  # redacted; batch continues
        coordinator._record(
            "archive", work_id, "failed",
            error_code=_dependency_attempts._safe_error_code(exc), started_at=started,
        )
        raise
    try:
        if not archive_module.archive_bundle_complete(
            coordinator.artifact_roots.write_base, paths
        ):
            raise OSError("archive bundle incomplete")
        coordinator._record(
            "archive", work_id, "ok",
            artifact_paths=sorted(paths.values()), started_at=started,
        )
    except Exception as exc:
        coordinator._record(
            "archive", work_id, "failed",
            error_code=_dependency_attempts._safe_error_code(exc), started_at=started,
        )
        raise
    coordinator._mark_archived(key, entry, paths)
    # Store write-back (plan r14-routes-writeback): the caption-sourced
    # transcript owes a ``transcripts`` row taking the part out of
    # ``v_missing_transcript``.  Best-effort: the archive already
    # succeeded on disk, so a store failure must not disturb the row's
    # archived outcome.
    try:
        _dependency_writeback.record_subtitle_transcript(coordinator, 
            entry=entry, raw=raw, segments=segments
        )
    except Exception as exc:
        # Keep the call-site contract explicit: supplementary store
        # evidence can fail after publication without changing archive: ok.
        _dependency_writeback.record_transcript_writeback_failure(coordinator, entry, exc)
    result.ok = True
    result.final_status = "archived"


def stage_asr_archive(
    coordinator, key: str, entry: dict[str, Any], result: _dependency_models.RowResult
) -> None:
    from bili_asr import archive as archive_module

    work_id = str(entry.get("work_id") or key)
    started = utc_now_iso()
    resolved = coordinator._existing_audio(entry)
    if resolved is None:
        coordinator._record(
            "asr", work_id, "skipped",
            error_code="missing_audio", started_at=started,
        )
        result.skipped = True
        result.skip_reason = "missing_audio"
        result.final_status = str(entry.get("status") or "")
        return
    audio_base, audio_declared = resolved
    try:
        from bili_asr.path_policy import confined_audio_file
        if coordinator.asr_runner is None:
            coordinator.asr_runner = asr_module.ASRRunner(_module_asr_config.default_config())
        runner = coordinator.asr_runner
        # Evidence-based seeding (governance ruling 2026-09-28, plan
        # 20260928-hotword-injection-governance): the run's own first-pass
        # transcript, and the paired AI-subtitle text when the part has a
        # subtitle route, are the only texts that may admit a hotword.
        # Pass 1 runs unguarded; pass 2 is seeded with the tokens pass 1
        # itself produced and re-decodes with a clean model/cache state.
        # Tokens the transcript does not contain are recorded in the archive
        # provenance as ``hotword_dropped_no_evidence``.
        subtitle_raw = coordinator._subtitle_segments(coordinator._current_entry(key, entry))
        paired_subtitle_text = (
            "".join(str(seg.get("text", "")) for seg in subtitle_raw[0])
            if subtitle_raw is not None
            else None
        )
        with confined_audio_file(audio_base, audio_declared) as safe_audio:
            segments = asr_module.two_pass_transcribe(
                runner, safe_audio, paired_subtitle_text=paired_subtitle_text
            )
        collect_hotwords_dropped(coordinator.hotwords_dropped, runner)
    except Exception as exc:  # redacted; batch continues
        coordinator._record(
            "asr", work_id, "failed",
            error_code=_dependency_attempts._safe_error_code(exc), started_at=started,
        )
        raise
    coordinator._record("asr", work_id, "ok", started_at=started)
    # This row produced an ASR transcript: the denominator of the printed
    # reuse line (D2.5).  Counted here, at the `asr: ok` attempt.
    coordinator._batch_asr_items += 1
    started = utc_now_iso()
    try:
        paths = archive_module.write_archive(
            coordinator.artifact_roots.write_base, coordinator._current_entry(key, entry), segments,
            source="asr",
            asr_provenance=coordinator.asr_runner.provenance() if coordinator.asr_runner else None,
            characters=_module_asr_coverage.characters_of(runner),
            # Same measurement as `_mark_archived` writes to the row (I-000188: store *and*
            # bundle).  `runner` is the run's runner, so this reads THIS run's measurement.
            coverage=_module_asr_coverage.transcribed_coverage(runner),
        )
    except Exception as exc:  # redacted; batch continues
        coordinator._record(
            "archive", work_id, "failed",
            error_code=_dependency_attempts._safe_error_code(exc), started_at=started,
        )
        raise
    try:
        if not archive_module.archive_bundle_complete(
            coordinator.artifact_roots.write_base, paths
        ):
            raise OSError("archive bundle incomplete")
        coordinator._record(
            "archive", work_id, "ok",
            artifact_paths=sorted(paths.values()), started_at=started,
        )
    except Exception as exc:
        coordinator._record(
            "archive", work_id, "failed",
            error_code=_dependency_attempts._safe_error_code(exc), started_at=started,
        )
        raise
    current = coordinator._current_entry(key, entry)
    current["audio_path"] = audio_declared
    coordinator._mark_archived(key, current, paths, runner)
    # Store write-back (plan r14-routes-writeback): the locally-produced
    # transcript owes a ``transcripts`` row taking the part out of
    # ``v_missing_transcript``.  Best-effort: the archive already
    # succeeded on disk, so a store failure must not disturb the row's
    # archived outcome.
    _dependency_writeback.record_asr_transcript(coordinator, current, segments)
    result.ok = True
    result.final_status = "archived"


def stage_download(
    coordinator, key: str, entry: dict[str, Any], result: _dependency_models.RowResult
) -> str:
    """Download audio for a needs_audio row; returns new manifest status."""
    # offline / client-less rows never reach this stage: process_row
    # routes them to on-disk reprocessing or a skipped record first.
    work_id = str(entry.get("work_id") or key)
    started = utc_now_iso()
    existing = coordinator._existing_audio(entry)
    if existing is not None:
        _base, declared = existing
        current = coordinator._current_entry(key, entry)
        current.update(status="audio_ok", audio_path=declared)
        coordinator.store.upsert(current)
        coordinator._record(
            "download", work_id, "ok", artifact_paths=[declared], started_at=started,
        )
        coordinator._note_audio_peak(current)
        return "audio_ok"
    if coordinator.max_audio_bytes:
        from bili_asr.audio_budget import SKIP_REASON, would_exceed_budget

        if would_exceed_budget(
            coordinator.artifact_roots.write_base, entry, coordinator.max_audio_bytes,
            usage_bytes=coordinator.audio_usage_bytes(),
        ):
            coordinator._record(
                "download", work_id, "skipped", error_code=SKIP_REASON,
                started_at=started,
            )
            result.skipped = True
            result.skip_reason = SKIP_REASON
            result.final_status = str(entry.get("status") or "needs_audio")
            return result.final_status
    identity = coordinator._identity_for(entry, key)
    stem = artifact_stem(identity)
    out_path = os.path.join(
        os.fspath(coordinator.artifact_roots.write_base), "audio", f"{stem}.m4a"
    )
    # The configured root is the one case the downloader cannot derive from
    # `out_path`/`store.root`; the identity case keeps today's call shape.
    download_kwargs: dict[str, Any] = (
        {"artifact_roots": coordinator.artifact_roots}
        if coordinator.artifact_roots.configured
        else {}
    )
    downloaded = False
    try:
        final = audio_module.download_audio(
            coordinator.client, identity, out_path, store=coordinator.store, **download_kwargs
        )
        downloaded = True
    except Exception as exc:  # redacted; batch continues
        coordinator._record(
            "download", work_id, "failed",
            error_code=_dependency_attempts._safe_error_code(exc), started_at=started,
        )
        raise
    finally:
        # Sample leftover partials as well as a successful file so
        # campaign peak is never below on-disk audio/ after a failed
        # download that left bytes behind.
        coordinator._note_audio_peak(
            coordinator._current_entry(key, entry), rescan=not downloaded
        )
    declared = coordinator._declared_audio(final)
    if declared is None:
        raise OSError("audio path outside archive")
    coordinator._record(
        "download", work_id, "ok", artifact_paths=[declared], started_at=started
    )
    return "audio_ok"
