"""Coordinator implementation."""

from __future__ import annotations

import bili_asr.asr.coverage as _module_asr_coverage
import bili_asr.asr.provenance as _module_asr_provenance


import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable
from bili_asr import asr as asr_module
from bili_asr import subtitles as subtitles_module
from bili_asr.artifact_root import ArtifactRoots, iter_audio_paths
from bili_asr.audio_budget import AudioUsageError, AudioUsageTracker
from bili_asr.manifest import TERMINAL_STATUSES, ManifestStore
from bili_asr.persistence import utc_now_iso
from bili_asr.page_identity import PageIdentity, identity_from_entry
from bili_asr.path_policy import confined_audio_path
import bili_asr.pipeline.attempts as _dependency_attempts
import bili_asr.pipeline.locks as _dependency_locks
import bili_asr.pipeline.models as _dependency_models
import bili_asr.pipeline.stages as _dependency_stages
import bili_asr.pipeline.writeback as _dependency_writeback
from bili_asr.persistence import file_lock

# The coordinator remains the composition boundary for callers that need the
# result records; their definitions live with the pipeline model layer.
RunSummary = _dependency_models.RunSummary
RowResult = _dependency_models.RowResult
AttemptLedger = _dependency_attempts.AttemptLedger
ArchiveBusyError = _dependency_locks.ArchiveBusyError

@contextmanager
def archive_writer(root: str | os.PathLike[str], *, blocking: bool = False):
    """Coordinator seam for the archive lock, retaining injectable lock tests."""
    original = _dependency_locks.file_lock
    _dependency_locks.file_lock = file_lock
    try:
        with _dependency_locks.archive_writer(root, blocking=blocking):
            yield
    finally:
        _dependency_locks.file_lock = original


class RunCoordinator:
    """Per-stage coordinator over one manifest batch.

    ``client`` is the single HTTP owner (BiliClient); pass ``None`` for
    offline runs — harvest/download stages are then skipped with reason
    ``offline`` and never touch the network.

    ``artifact_roots`` carries the root the products live under when it is not
    the archive root (contract §4); ``self.root`` stays the archive root, which
    is where every piece of state and the writer lock stay (D13/D14).
    ``keep_audio`` is the retention policy the command boundary resolved and
    merely passed down (contract §7, D15) — never read from the environment here.
    """

    def __init__(
        self,
        archive_root: str | os.PathLike[str],
        store: ManifestStore,
        *,
        client: Any = None,
        offline: bool = False,
        max_audio_bytes: int = 0,
        sleep: Callable[[float], None] | None = None,
        asr_runner: Any | None = None,
        command: str = "run",
        artifact_roots: ArtifactRoots | None = None,
        keep_audio: bool = True,
    ) -> None:
        self.root = os.fspath(archive_root)
        self.artifact_roots = (
            artifact_roots if artifact_roots is not None else ArtifactRoots.of(self.root)
        )
        self.keep_audio = keep_audio
        self.store = store
        self.client = client
        self.offline = offline
        self.max_audio_bytes = max(0, max_audio_bytes)
        self._sleep = sleep or time.sleep
        self.asr_runner = asr_runner
        # Prefix of the printed model-construction line.  ``run_batch`` is the
        # shared batch entry, so the invoking command names itself here; the
        # default keeps the documented coordinator path's own label.
        self.command = command
        self._batch_asr_items = 0
        self.hotwords_dropped: list[str] = []
        # Re-entrancy tripwire for ``run_batch`` (see its docstring): the
        # denominator above is per-coordinator, not per-batch.
        self._batch_depth = 0
        self.audio_peak_bytes: int | None = 0
        self._audio_usage: AudioUsageTracker | None = None
        self._audio_usage_error: AudioUsageError | None = None
        self._audio_usage_prepared = False
        # The store write-back (plan r14-routes-writeback): the transcript
        # half of the archive stage — every locally-produced (ASR) or
        # subtitle-sourced transcript owes a ``transcripts`` row taking the
        # part out of ``v_missing_transcript``.  Both are best-effort and
        # lazily wired: the queue source opens on the first archived row, and
        # the ``kind='asr'`` run the write-backs key to is created at most
        # once per batch (``ensure_asr_run``), only when the ASR arm records
        # a transcript.  A store that cannot be opened or refuses the run
        # leaves these ``None`` and every write-back is skipped — the archive
        # on disk is never lost to a store problem.
        self._writeback_source: Any | None = None
        self._writeback_source_failed = False
        self._writeback_refusal_reported = False
        self.ledger = _dependency_attempts.AttemptLedger(self.root)
        # Latest attempt number per (work_id, stage); seeded by the ledger's
        # one-time construction scan and updated by ``AttemptLedger.append``.
        self._attempt_counts = self.ledger._latest_attempts

    # ------------------------------------------------------------ recording

    def _record(
        self,
        stage: str,
        work_id: str,
        outcome: str,
        *,
        error_code: int | str | None = None,
        artifact_paths: list[str] | None = None,
        started_at: str | None = None,
    ) -> dict[str, Any]:
        key = (work_id, stage)
        stored = self.ledger.append(
            {
                "stage": stage,
                "work_id": work_id,
                "attempt": self._attempt_counts.get(key, 0) + 1,
                "outcome": outcome,
                "error_code": error_code,
                "artifact_paths": list(artifact_paths or []),
                "started_at": started_at or utc_now_iso(),
                "finished_at": utc_now_iso(),
            }
        )
        self._attempt_counts[key] = stored["attempt"]
        return stored

    def failed_work_ids(self) -> set[str]:
        """Work ids with at least one recorded failed attempt."""
        return {
            record["work_id"]
            for record in self.ledger._iter_valid()
            if record["outcome"] == "failed"
        }

    # ------------------------------------------------------------ execution

    def _identity_for(self, entry: dict[str, Any], key: str) -> PageIdentity | str:
        return identity_from_entry(entry, key)

    def _current_entry(self, key: str, entry: dict[str, Any]) -> dict[str, Any]:
        return dict(self.store.get(key) or self.store.get_compatible(key) or entry)

    def _subtitle_segments(
        self, entry: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
        stem = artifact_stem_for_entry(entry)
        relative = os.path.join("subtitles", "raw", f"{stem}.json")
        # A read: the harvested document may sit under either base (§5, D8).
        for base in self.artifact_roots.read_bases():
            raw_path = os.path.join(os.fspath(base), relative)
            if not os.path.isfile(raw_path):
                continue
            with open(raw_path, encoding="utf-8") as fh:
                doc = json.load(fh)
            segments = [
                {
                    "start": item.get("from", 0),
                    "end": item.get("to", 0),
                    "text": item.get("content", ""),
                }
                for item in doc.get("body", [])
            ]
            return segments, doc
        return None

    def _existing_audio(self, entry: dict[str, Any]) -> tuple[Path, str] | None:
        """The row's audio as ``(base, declared)``, first hit over the bases.

        ``declared`` is the root-relative string the row records (`audio/<name>.<ext>`),
        so a caller re-confines it at the base it was found under rather than
        recomputing it against the archive root (§5, D7/D8).
        """
        stem = artifact_stem_for_entry(entry)
        declared_candidates: list[str] = []
        rel = entry.get("audio_path")
        if rel:
            declared_candidates.append(str(rel))
        stem_path = os.path.join("audio", stem)
        declared_candidates.append(stem_path + ".m4a")
        declared_candidates.append(stem_path + ".flac")
        for base, declared, confined in iter_audio_paths(
            self.artifact_roots, declared_candidates
        ):
            try:
                if confined.stat().st_size > 0:
                    return base, str(declared)
            except OSError:
                continue
        return None

    def _declared_audio(self, path: str) -> str | None:
        """The recorded form of one on-disk audio path, from whichever base holds it.

        The download stage may be handed a file the downloader *found* rather than
        wrote: a legacy copy at the archive root keeps resolving there (D6) and
        keeps its shipped ``audio/<name>.<ext>`` string.
        """
        for base in self.artifact_roots.read_bases():
            try:
                declared = os.path.relpath(path, base).replace(os.sep, "/")
            except ValueError:  # Windows across drives
                continue
            if confined_audio_path(base, declared, require_exists=True) is not None:
                return declared
        return None

    # ------------------------------------------------------- store write-back
    #
    # Plan r14-routes-writeback: the archive stage's two transcript routes both
    # owe a ``transcripts`` row.  Both write-backs are best-effort — the archive
    # already succeeded on disk, so a store failure must never turn that into a
    # row failure — and both resolve ``video_part_id`` through the store from
    # ``(bvid, page_index)``, never from a fabricated page index.








    def _mark_archived(
        self, key: str, entry: dict[str, Any], paths: dict[str, str], runner: Any = None
    ) -> None:
        updated = self._current_entry(key, entry)
        updated.update(paths)
        updated["status"] = "archived"
        updated["source"] = "asr" if runner is not None else "subtitle"
        # A coordinator archive owes operational sidecars even when its
        # content source is the same as a standalone stage command's.
        updated["archive_producer"] = "coordinator"
        # Coverage attestation (plan asr-coverage-attestation): the ASR stage's measured span
        # rides the row it archives.  ``runner`` is ``None`` on the subtitle route, which ran no
        # ASR and so makes no measurement — that route leaves the field as it found it, and the
        # helper clears any stale measurement before it writes the new one on the ASR route.
        if runner is not None:
            _module_asr_provenance.apply_provenance_evidence(updated, runner)
            _module_asr_coverage.apply_coverage_evidence(updated, runner)
        self.store.upsert(updated)
        self._reclaim_audio(updated)

    def prepare_audio_usage(self) -> int:
        """Measure once under the writer lock for planning and the next batch."""
        self._audio_usage = AudioUsageTracker(self.artifact_roots.write_base)
        self._audio_usage_error = None
        self._audio_usage_prepared = True
        self.audio_peak_bytes = self._audio_usage.usage_bytes
        return self._audio_usage.usage_bytes

    def audio_usage_bytes(self) -> int:
        if self._audio_usage_error is not None:
            raise self._audio_usage_error
        if self._audio_usage is None:
            try:
                self._audio_usage = AudioUsageTracker(self.artifact_roots.write_base)
                if self.audio_peak_bytes is not None:
                    self.audio_peak_bytes = max(
                        self.audio_peak_bytes, self._audio_usage.usage_bytes
                    )
            except AudioUsageError as exc:
                self._audio_usage_error = exc
                self.audio_peak_bytes = None
                raise
        return self._audio_usage.usage_bytes

    def _note_audio_peak(
        self, entry: dict[str, Any] | None = None, *, rescan: bool = False
    ) -> None:
        """Record observed `{artifact_root}/audio/` usage for campaign proof.

        The cap and the peak measure the configured root (contract §8, D16):
        legacy audio still sitting at the archive root is on another device and
        is not where new bytes land.
        """
        try:
            self.audio_usage_bytes()
            assert self._audio_usage is not None
            if rescan:
                self._audio_usage.rescan()
            elif entry is not None:
                self._audio_usage.refresh_entry(entry)
            usage = self._audio_usage.usage_bytes
            if self.audio_peak_bytes is not None:
                self.audio_peak_bytes = max(self.audio_peak_bytes, usage)
        except (OSError, ValueError):
            # A measurement failure after publication must preserve its archive.
            # Subsequent downloads with a finite cap require reliable usage.
            self._audio_usage_error = AudioUsageError("audio usage unavailable")
            self.audio_peak_bytes = None

    def _reclaim_audio(self, entry: dict[str, Any]) -> None:
        """Best-effort audio reclaim once a row is archived."""
        from bili_asr.audio_reclaim import reclaim_audio

        self._note_audio_peak(entry)
        try:
            reclaim_audio(
                self.root,
                entry,
                artifact_roots=self.artifact_roots,
                keep=self.keep_audio,
            )
        except (OSError, ValueError):
            pass  # per-item non-fatal: transcripts exist; row stays archived
        finally:
            self._note_audio_peak(entry)



    def process_row(self, key: str, entry: dict[str, Any]) -> _dependency_models.RowResult:
        """Execute every applicable stage for one manifest row."""
        work_id = str(entry.get("work_id") or key)
        status = str(entry.get("status") or "pending")
        result = _dependency_models.RowResult(work_id=work_id, final_status=status)

        if status in TERMINAL_STATUSES:
            if status == "archived" and entry.get("transcript_writeback_error"):
                retry_data = self._subtitle_segments(entry)
                if retry_data is not None:
                    retry_segments, retry_raw = retry_data
                    if _dependency_writeback.record_subtitle_transcript(self,
                        entry=entry, raw=retry_raw, segments=retry_segments
                    ):
                        result.ok = True
                        result.final_status = "archived"
                        return result
            result.skipped = True
            result.skip_reason = "already_terminal"
            return result

        try:
            if self.offline or self.client is None:
                # Offline: never call harvest/download. Reprocess only what
                # already exists on disk (subtitle raw / audio) per plan
                # §Interfaces; missing input -> skipped with reason.
                entry = self._current_entry(key, entry)
                audio = self._existing_audio(entry)
                subtitle_raw = self._subtitle_segments(entry)
                if subtitle_raw is not None:
                    _dependency_stages.stage_archive_from_subtitle(self, key, entry, result)
                    return result
                if audio is not None:
                    _dependency_stages.stage_asr_archive(self, key, entry, result)
                    return result
                if status in _dependency_attempts._HARVEST_STATUSES:
                    self._record("harvest", work_id, "skipped",
                                 error_code="offline")
                    result.skipped = True
                    result.skip_reason = "offline"
                    result.final_status = str(entry.get("status") or status)
                    return result
                # subtitle_done without raw / audio row without audio: let
                # the natural stage record its missing-input skip reason.
                if status == "subtitle_done":
                    _dependency_stages.stage_archive_from_subtitle(self, key, entry, result)
                else:
                    _dependency_stages.stage_asr_archive(self, key, entry, result)
                return result

            if status in _dependency_attempts._HARVEST_STATUSES:
                started = utc_now_iso()
                identity = self._identity_for(entry, key)
                try:
                    status = subtitles_module.harvest_subtitle(
                        self.client, identity, self.store, self.root,
                        artifact_roots=self.artifact_roots,
                    )
                except Exception as exc:
                    self._record(
                        "harvest", work_id, "failed",
                        error_code=_dependency_attempts._safe_error_code(exc), started_at=started,
                    )
                    raise
                srt_rel = None
                current = self._current_entry(key, entry)
                if current.get("srt_path"):
                    srt_rel = str(current["srt_path"])
                self._record(
                    "harvest", work_id, "ok",
                    artifact_paths=[srt_rel] if srt_rel else [], started_at=started,
                )
                entry = current
            elif status not in _dependency_attempts._SKIP_HARVEST_STATUSES:
                raise ValueError(f"unexpected status {status!r}")

            if status == "subtitle_done":
                entry = self._current_entry(key, entry)
                _dependency_stages.stage_archive_from_subtitle(self, key, entry, result)
            elif status in {"needs_audio", "audio_ok"}:
                if status == "needs_audio" or self._existing_audio(entry) is None:
                    status = _dependency_stages.stage_download(self, key, entry, result)
                    if result.skipped:
                        return result
                    entry = self._current_entry(key, entry)
                _dependency_stages.stage_asr_archive(self, key, entry, result)
            elif status in _dependency_attempts._HARVEST_STATUSES:
                # harvest returned an unexpected transition
                raise ValueError(f"harvest returned unexpected status {status!r}")
        except Exception as exc:
            code = _dependency_attempts._safe_error_code(exc)
            if code not in result.failure_codes:
                result.failure_codes.append(code)
            # stage-level attempt records are written by the stage wrappers;
            # this catch covers stage-entry errors (e.g. harvest) that did
            # not record yet.
            result.final_status = str(
                (self._current_entry(key, entry) or {}).get("status") or status
            )
            raise
        return result

    def _batch_needs_asr(self, rows: list[tuple[str, dict[str, Any]]]) -> bool:
        for key, entry in rows:
            status = str(entry.get("status") or "pending")
            if status in TERMINAL_STATUSES:
                continue
            current = self._current_entry(key, entry)
            if self._subtitle_segments(current) is not None:
                continue
            if status in {"needs_audio", "audio_ok", "subtitle_done"} and self._existing_audio(current) is not None:
                return True
        return False

    def run_batch(self, rows: list[tuple[str, dict[str, Any]]]) -> _dependency_models.RunSummary:
        """Process one batch while the archive root is owned.

        Not re-entrant, and refused rather than tolerated: the printed line's
        denominator lives on ``self`` (``_batch_asr_items``, written by
        ``_transcribe_row``), so a nested call would zero the outer batch's
        count, clobber it with the inner one, and print a second line for work
        the outer call has not finished.  No caller nests today; the tripwire
        keeps a future one from silently corrupting the count.
        """
        if self._batch_depth:
            raise RuntimeError("run_batch is not re-entrant")
        self._batch_depth += 1
        try:
            return self._run_batch_owned(rows)
        finally:
            self._batch_depth -= 1

    def _run_batch_owned(
        self, rows: list[tuple[str, dict[str, Any]]]
    ) -> _dependency_models.RunSummary:
        injected_runner = self.asr_runner
        # Bound before the ``try`` so the ``finally`` can always read it: the
        # batch entry point may raise before producing a summary (the
        # interrupted-batch tests model exactly that), and the release path
        # must still run.
        summary = _dependency_models.RunSummary()
        completed = False
        with _dependency_locks.archive_writer(self.root):
            if not self._audio_usage_prepared:
                self._audio_usage = None
                self._audio_usage_error = None
                self.audio_peak_bytes = 0
            self._audio_usage_prepared = False
            self.asr_runner = injected_runner
            self._batch_asr_items = 0
            self.hotwords_dropped = []
            constructions_before = (
                getattr(injected_runner, "model_constructions", 0)
                if injected_runner is not None
                else 0
            )
            attempts_before = (
                getattr(injected_runner, "model_load_attempts", 0)
                if injected_runner is not None
                else 0
            )
            try:
                summary = self._run_batch_locked(rows)
                completed = True
            finally:
                # The batch's evidence is stated, the write-back source closed,
                # and the runner handed back on *every* exit path, Ctrl-C
                # included: the assignments and the print sit before the
                # release so a ``BaseException`` cannot carry the count away,
                # and the pending exception still propagates (this ``finally``
                # never swallows or returns).
                if not completed:
                    # The summary is returned only after the loop. Interruption
                    # leaves the invocation incomplete even after write-backs.
                    outcome = "partial"
                elif summary.failed or summary.risk_interrupted:
                    outcome = "partial" if summary.ok_count else "failed"
                else:
                    outcome = None
                _dependency_writeback.close_writeback_source(self, outcome=outcome)
                if injected_runner is None and self.asr_runner is not None:
                    self.asr_runner.release()
                batch_runner = self.asr_runner
                self.asr_runner = injected_runner
                # Observed delta, not a lifetime total: an injected runner
                # reused across batches reports only what this batch added.
                summary.model_constructions = max(
                    0,
                    getattr(batch_runner, "model_constructions", 0)
                    - constructions_before,
                )
                summary.model_load_attempts = max(
                    0,
                    getattr(batch_runner, "model_load_attempts", 0)
                    - attempts_before,
                )
                summary.asr_items = self._batch_asr_items
                summary.hotwords_dropped = list(self.hotwords_dropped)
                self._print_model_constructions(summary)
            return summary

    def _print_model_constructions(self, summary: _dependency_models.RunSummary) -> None:
        """State the batch's reuse once, on stderr, when anything was paid.

        Stderr, not stdout (D2.6 as amended): ``campaign``'s stdout is one
        JSON document, and a line printed there breaks every downstream
        parser.  The guard is "nothing was paid", not "no ASR items": a batch
        that constructed the model and then failed every transcription prints
        ``… for 0 asr item(s)``, because that line is the only evidence of the
        first-decode failure it just paid for.  A subtitle-only batch (neither
        a construction nor a transcript) prints nothing.

        When every model load failed (attempts > 0 but constructions == 0 and
        asr_items == 0), print a diagnostic stating the failed attempts so the
        operator knows the model was tried but never succeeded.

        With fd 2 closed CPython sets ``sys.stderr`` to ``None`` and
        ``print(..., file=None)`` falls back to **stdout**, which would put
        this line inside ``campaign``'s JSON document; a closed stderr means
        the diagnostic has nowhere to go, so nothing is printed.
        """
        from bili_asr.diagnostics import write_stderr

        if summary.asr_items <= 0 and summary.model_constructions <= 0:
            # Check if we had failed load attempts
            if summary.model_load_attempts > 0:
                write_stderr(
                    f"{self.command}: model load failed {summary.model_load_attempts} time(s), "
                    "0 transcripts produced"
                )
            return
        write_stderr(
            _dependency_models.model_constructions_line(
                self.command, summary.model_constructions, summary.asr_items
            )
        )

    def _run_batch_locked(
        self, rows: list[tuple[str, dict[str, Any]]]
    ) -> _dependency_models.RunSummary:
        """Process rows sequentially while the archive root is owned."""
        from bili_asr import bili_client

        summary = _dependency_models.RunSummary()
        for index, (key, entry) in enumerate(rows):
            work_id = str(entry.get("work_id") or key)
            status = str(entry.get("status") or "pending")
            result = _dependency_models.RowResult(work_id=work_id, final_status=status)
            live = status not in TERMINAL_STATUSES and not self.offline

            def _fail(exc: BaseException, r: _dependency_models.RowResult = result) -> None:
                # append once per code: process_row's stage wrappers may
                # have recorded the same scalar already (M1 dedupe)
                code = _dependency_attempts._safe_error_code(exc)
                if code not in r.failure_codes:
                    r.failure_codes.append(code)

            try:
                result = self.process_row(key, entry)
            except bili_client.RiskBudgetExhausted as exc:
                _fail(exc)
                result.final_status = str(
                    (self._current_entry(key, entry) or {}).get("status") or status
                )
                summary.results.append(result)
                summary.risk_interrupted = True
                break
            except bili_client.GoneResponse as exc:
                _fail(exc)
                gone = self._current_entry(key, entry)
                if gone.get("work_id"):
                    gone["status"] = "gone"
                    self.store.upsert(gone)
                result.final_status = "gone"
            except bili_client.APIResponseError as exc:
                _fail(exc)
                current = self._current_entry(key, entry)
                code = _dependency_attempts._safe_error_code(exc)
                if current.get("work_id") and isinstance(code, int):
                    current["last_api_error_code"] = code
                    self.store.upsert(current)
            except Exception as exc:
                _fail(exc)
            summary.results.append(result)
            if live and index != len(rows) - 1:
                self._sleep(3.0)
        return summary


def artifact_stem_for_entry(entry: dict[str, Any]) -> str:
    """The entry's canonical stem (compass D5) — delegates to
    ``page_identity.canonical_stem`` (the archive_stem semantics)."""
    from bili_asr.page_identity import canonical_stem

    return canonical_stem(entry)
