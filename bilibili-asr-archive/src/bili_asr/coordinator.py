"""Run coordinator: per-stage attempt ledger + stage execution (DIR-03).

Composes the existing live seams (``subtitles.harvest_subtitle``,
``audio.download_audio``, ``asr.transcribe``, ``archive.write_archive``)
without forking their signatures. Persistence is a sidecar append-only
JSONL at ``{archive_root}/coordinator/attempts.jsonl``; the manifest
schema, ``VALID_STATUSES`` and ``classify_risk`` are untouched.

No credentials, signed URLs, or raw exception texts are persisted —
only redacted scalar error codes.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from . import asr as asr_module
from . import audio as audio_module
from . import subtitles as subtitles_module
from .manifest import ManifestStore
from .page_identity import PageIdentity, artifact_stem, identity_from_entry
from .persistence import append_jsonl_record, file_lock
from .path_policy import confined_audio_path

STAGES = ("harvest", "download", "asr", "archive")
OUTCOMES = ("ok", "failed", "skipped")

# statuses that still require the live harvest seam
_HARVEST_STATUSES = frozenset({"pending", "meta_ok", "sub_checked"})
# statuses that never need harvest again
_SKIP_HARVEST_STATUSES = frozenset(
    {"subtitle_done", "needs_audio", "audio_ok", "archived"}
)
# terminal manifest rows: reruns always skip these
TERMINAL_STATUSES = frozenset({"archived", "gone"})

# Sidecar may hold only redacted scalar codes — never cookies, URLs, traces.
_FORBIDDEN_MARKERS = (
    "SESSDATA",
    "cookie",
    "Cookie",
    "http://",
    "https://",
    "Traceback",
)
_MAX_ERROR_CODE_LEN = 64

ATTEMPTS_REL_PATH = os.path.join("coordinator", "attempts.jsonl")
ARCHIVE_WRITER_LOCK = os.path.join("coordinator", "archive-writer.lock")


class ArchiveBusyError(RuntimeError):
    """Raised when another sequential archive operation owns the root."""

    def __init__(self) -> None:
        super().__init__("archive_busy")


_ARCHIVE_WRITER_STATE = threading.local()


@contextmanager
def archive_writer(root: str | os.PathLike[str], *, blocking: bool = False) -> Iterator[None]:
    """Own the archive root, reentrant only within the owning thread."""
    lock_target = os.path.join(os.fspath(root), ARCHIVE_WRITER_LOCK)
    owned = getattr(_ARCHIVE_WRITER_STATE, "owned", None)
    if owned == lock_target:
        yield
        return
    lock = file_lock(lock_target, blocking=blocking)
    try:
        lock.__enter__()
    except OSError as exc:
        if not blocking and isinstance(exc.__cause__, BlockingIOError):
            raise ArchiveBusyError() from exc
        raise
    _ARCHIVE_WRITER_STATE.owned = lock_target
    try:
        yield
    except BaseException as exc:
        _ARCHIVE_WRITER_STATE.owned = None
        if not lock.__exit__(type(exc), exc, exc.__traceback__):
            raise
    else:
        _ARCHIVE_WRITER_STATE.owned = None
        lock.__exit__(None, None, None)


def _utc_now_iso() -> str:
    from .run_ledger import utc_now_iso

    return utc_now_iso()


# qc3-S2: a hostile/odd .code string may itself carry forbidden markers;
# strip them (case-insensitive) so recording a failure never throws and
# never masks the original stage exception.
_MARKER_RE = re.compile(
    "|".join(re.escape(m) for m in _FORBIDDEN_MARKERS), re.IGNORECASE
)


def _sanitize_code_str(value: str) -> str:
    return _MARKER_RE.sub("", value)[:_MAX_ERROR_CODE_LEN]


def _safe_error_code(exc: BaseException) -> int | str:
    """Extract a redacted scalar error code from an exception."""
    for attr in ("code", "last_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, str)):
            if isinstance(value, str):
                return _sanitize_code_str(value)
            return value
    name = type(exc).__name__
    return _sanitize_code_str(name)


def _validate_attempt(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("attempt record must be a dict")
    missing = [
        k
        for k in ("stage", "work_id", "attempt", "outcome",
                  "error_code", "artifact_paths", "started_at", "finished_at")
        if k not in record
    ]
    if missing:
        raise ValueError(f"attempt record missing fields: {missing}")
    if record["stage"] not in STAGES:
        raise ValueError(f"unknown stage {record['stage']!r}")
    if record["outcome"] not in OUTCOMES:
        raise ValueError(f"unknown outcome {record['outcome']!r}")
    if not isinstance(record["work_id"], str) or not record["work_id"]:
        raise ValueError("work_id must be a non-empty str")
    attempt = record["attempt"]
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError("attempt must be an int >= 1")
    error_code = record["error_code"]
    if error_code is not None:
        if isinstance(error_code, bool) or not isinstance(error_code, (int, str)):
            raise ValueError("error_code must be int, str, or null")
        if isinstance(error_code, str) and len(error_code) > _MAX_ERROR_CODE_LEN:
            raise ValueError("error_code is not a redacted code")
    paths = record["artifact_paths"]
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise ValueError("artifact_paths must be a list of str")
    for p in paths:
        if os.path.isabs(p):
            raise ValueError(f"artifact path must be relative: {p!r}")
    for key in ("started_at", "finished_at"):
        if not isinstance(record[key], str) or not record[key]:
            raise ValueError(f"{key} must be a non-empty ISO-8601 str")
    stored = {
        "stage": record["stage"],
        "work_id": record["work_id"],
        "attempt": attempt,
        "outcome": record["outcome"],
        "error_code": error_code,
        "artifact_paths": list(paths),
        "started_at": record["started_at"],
        "finished_at": record["finished_at"],
    }
    dumped = json.dumps(stored, ensure_ascii=False).lower()
    for marker in _FORBIDDEN_MARKERS:
        if marker.lower() in dumped:
            raise ValueError(f"record contains forbidden marker: {marker!r}")
    return stored


class AttemptLedger:
    """Append-only JSONL sidecar at ``{archive_root}/coordinator/attempts.jsonl``.

    Each append writes one newline-terminated record and fsyncs the file and
    parent directory; history is never rewritten.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = os.fspath(root)
        self.path = os.path.join(self.root, ATTEMPTS_REL_PATH)

    def load(self) -> list[dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        records: list[dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(_validate_attempt(json.loads(line)))
                except (json.JSONDecodeError, ValueError):
                    continue
        return records

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        stored = _validate_attempt(record)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        lock_path = self.path + ".lock"
        with file_lock(lock_path):
            key = (stored["work_id"], stored["stage"])
            latest = 0
            for prior in self._iter_valid(strict=True):
                if (prior["work_id"], prior["stage"]) == key:
                    latest = max(latest, prior["attempt"])
            if record.get("_preserve_attempt"):
                next_attempt = stored["attempt"]
            else:
                next_attempt = max(stored["attempt"], latest + 1)
            stored["attempt"] = next_attempt
            append_jsonl_record(self.path, stored, lock_path=lock_path)
        return stored

    def _iter_valid(self, *, strict: bool = False):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for line_number, line in enumerate(fh, 1):
                    if not line.strip():
                        continue
                    try:
                        yield _validate_attempt(json.loads(line))
                    except (json.JSONDecodeError, ValueError) as exc:
                        if strict:
                            raise ValueError(f"malformed attempt history at line {line_number}") from exc
        except OSError as exc:
            if strict:
                raise ValueError("attempt history unavailable") from exc
            return



@dataclass
class RowResult:
    work_id: str
    final_status: str
    ok: bool = False
    skipped: bool = False
    skip_reason: str = ""
    failure_codes: list[int | str] = field(default_factory=list)


@dataclass
class RunSummary:
    results: list[RowResult] = field(default_factory=list)
    risk_interrupted: bool = False

    @property
    def failed(self) -> list[RowResult]:
        return [r for r in self.results if not r.ok and not r.skipped]

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def skipped_rows(self) -> list[RowResult]:
        return [r for r in self.results if r.skipped]

    @property
    def fully_processed(self) -> bool:
        """True when no row failed/unprocessed and no risk interruption.

        An empty selection is vacuously fully processed. Terminal-scope
        reruns (rows skipped as ``already_terminal``) count as processed:
        nothing remains to do for those rows (F-002).
        """
        return not self.risk_interrupted and all(
            r.ok or r.skip_reason == "already_terminal" for r in self.results
        )


class RunCoordinator:
    """Per-stage coordinator over one manifest batch.

    ``client`` is the single HTTP owner (BiliClient); pass ``None`` for
    offline runs — harvest/download stages are then skipped with reason
    ``offline`` and never touch the network.
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
    ) -> None:
        self.root = os.fspath(archive_root)
        self.store = store
        self.client = client
        self.offline = offline
        self.max_audio_bytes = max(0, max_audio_bytes)
        self._sleep = sleep or time.sleep
        self.asr_runner = asr_runner
        self.audio_peak_bytes = 0
        self.ledger = AttemptLedger(self.root)
        self._attempt_counts: dict[tuple[str, str], int] = {}
        for rec in self.ledger._iter_valid(strict=True):
            key = (rec["work_id"], rec["stage"])
            self._attempt_counts[key] = max(
                self._attempt_counts.get(key, 0), rec["attempt"]
            )

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
                "started_at": started_at or _utc_now_iso(),
                "finished_at": _utc_now_iso(),
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
        raw_path = os.path.join(self.root, "subtitles", "raw", f"{stem}.json")
        if not os.path.isfile(raw_path):
            return None
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

    def _existing_audio(self, entry: dict[str, Any]) -> str | None:
        stem = artifact_stem_for_entry(entry)
        candidates: list[str] = []
        rel = entry.get("audio_path")
        if rel:
            p = rel if os.path.isabs(str(rel)) else os.path.join(self.root, str(rel))
            candidates.append(p)
        base = os.path.join(self.root, "audio", stem)
        candidates.append(base + ".m4a")
        candidates.append(base + ".flac")
        for path in candidates:
            try:
                declared = os.path.relpath(path, self.root)
                confined = confined_audio_path(self.root, declared, require_exists=True)
                if confined is not None and confined.stat().st_size > 0:
                    return str(confined)
            except OSError:
                continue
        return None

    def _stage_archive_from_subtitle(
        self, key: str, entry: dict[str, Any], result: RowResult
    ) -> None:
        from . import archive as archive_module

        work_id = str(entry.get("work_id") or key)
        started = _utc_now_iso()
        data = self._subtitle_segments(entry)
        if data is None:
            self._record(
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
                self.root, entry, segments, source="subtitle", raw=raw
            )
        except Exception as exc:  # redacted; batch continues
            self._record(
                "archive", work_id, "failed",
                error_code=_safe_error_code(exc), started_at=started,
            )
            raise
        try:
            if not archive_module.archive_bundle_complete(self.root, paths):
                raise OSError("archive bundle incomplete")
            self._record(
                "archive", work_id, "ok",
                artifact_paths=sorted(paths.values()), started_at=started,
            )
        except Exception as exc:
            self._record(
                "archive", work_id, "failed",
                error_code=_safe_error_code(exc), started_at=started,
            )
            raise
        self._mark_archived(key, entry, paths)
        result.ok = True
        result.final_status = "archived"

    def _mark_archived(
        self, key: str, entry: dict[str, Any], paths: dict[str, str]
    ) -> None:
        updated = self._current_entry(key, entry)
        updated.update(paths)
        updated["status"] = "archived"
        self.store.upsert(updated)
        self._reclaim_audio(updated)

    def _note_audio_peak(self) -> None:
        """Record observed `{archive_root}/audio/` usage for campaign proof."""
        from .audio_budget import audio_dir_usage_bytes

        usage = audio_dir_usage_bytes(self.root)
        if usage > self.audio_peak_bytes:
            self.audio_peak_bytes = usage

    def _reclaim_audio(self, entry: dict[str, Any]) -> None:
        """Best-effort audio reclaim once a row is archived."""
        from .audio_reclaim import reclaim_audio

        self._note_audio_peak()
        try:
            reclaim_audio(self.root, entry)
        except (OSError, ValueError):
            pass  # per-item non-fatal: transcripts exist; row stays archived

    def _stage_asr_archive(
        self, key: str, entry: dict[str, Any], result: RowResult
    ) -> None:
        from . import archive as archive_module

        work_id = str(entry.get("work_id") or key)
        started = _utc_now_iso()
        audio_path = self._existing_audio(entry)
        if audio_path is None:
            self._record(
                "asr", work_id, "skipped",
                error_code="missing_audio", started_at=started,
            )
            result.skipped = True
            result.skip_reason = "missing_audio"
            result.final_status = str(entry.get("status") or "")
            return
        try:
            from .path_policy import confined_audio_file
            if self.asr_runner is None:
                self.asr_runner = asr_module.ASRRunner(
                    asr_module.ASRConfig(model_name=asr_module.DEFAULT_MODEL)
                )
            with confined_audio_file(self.root, os.path.relpath(audio_path, self.root)) as safe_audio:
                segments = self.asr_runner.transcribe(safe_audio)
        except Exception as exc:  # redacted; batch continues
            self._record(
                "asr", work_id, "failed",
                error_code=_safe_error_code(exc), started_at=started,
            )
            raise
        self._record("asr", work_id, "ok", started_at=started)
        started = _utc_now_iso()
        try:
            paths = archive_module.write_archive(
                self.root, self._current_entry(key, entry), segments, source="asr"
            )
        except Exception as exc:  # redacted; batch continues
            self._record(
                "archive", work_id, "failed",
                error_code=_safe_error_code(exc), started_at=started,
            )
            raise
        try:
            if not archive_module.archive_bundle_complete(self.root, paths):
                raise OSError("archive bundle incomplete")
            self._record(
                "archive", work_id, "ok",
                artifact_paths=sorted(paths.values()), started_at=started,
            )
        except Exception as exc:
            self._record(
                "archive", work_id, "failed",
                error_code=_safe_error_code(exc), started_at=started,
            )
            raise
        try:
            audio_rel = os.path.relpath(audio_path, self.root)
        except ValueError:
            raise OSError("audio path outside archive")
        current = self._current_entry(key, entry)
        current["audio_path"] = audio_rel
        self._mark_archived(key, current, paths)
        result.ok = True
        result.final_status = "archived"

    def _stage_download(
        self, key: str, entry: dict[str, Any], result: RowResult
    ) -> str:
        """Download audio for a needs_audio row; returns new manifest status."""
        # offline / client-less rows never reach this stage: process_row
        # routes them to on-disk reprocessing or a skipped record first.
        work_id = str(entry.get("work_id") or key)
        started = _utc_now_iso()
        if self.max_audio_bytes:
            from .audio_budget import SKIP_REASON, would_exceed_budget

            if would_exceed_budget(self.root, entry, self.max_audio_bytes):
                self._record(
                    "download", work_id, "skipped", error_code=SKIP_REASON,
                    started_at=started,
                )
                result.skipped = True
                result.skip_reason = SKIP_REASON
                result.final_status = str(entry.get("status") or "needs_audio")
                return result.final_status
        identity = self._identity_for(entry, key)
        stem = artifact_stem(identity)
        out_path = os.path.join(self.root, "audio", f"{stem}.m4a")
        try:
            final = audio_module.download_audio(
                self.client, identity, out_path, store=self.store
            )
        except Exception as exc:  # redacted; batch continues
            self._record(
                "download", work_id, "failed",
                error_code=_safe_error_code(exc), started_at=started,
            )
            raise
        finally:
            # Sample leftover partials as well as a successful file so
            # campaign peak is never below on-disk audio/ after a failed
            # download that left bytes behind.
            self._note_audio_peak()
        try:
            rel = os.path.relpath(final, self.root)
            confined = confined_audio_path(self.root, rel, require_exists=True)
            if confined is None:
                raise OSError("audio path outside archive")
            rel = os.path.relpath(confined, self.root)
        except (OSError, ValueError, TypeError):
            raise OSError("audio path outside archive")
        self._record(
            "download", work_id, "ok", artifact_paths=[rel], started_at=started
        )
        return "audio_ok"

    def process_row(self, key: str, entry: dict[str, Any]) -> RowResult:
        """Execute every applicable stage for one manifest row."""
        work_id = str(entry.get("work_id") or key)
        status = str(entry.get("status") or "pending")
        result = RowResult(work_id=work_id, final_status=status)

        if status in TERMINAL_STATUSES:
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
                    self._stage_archive_from_subtitle(key, entry, result)
                    return result
                if audio is not None:
                    self._stage_asr_archive(key, entry, result)
                    return result
                if status in _HARVEST_STATUSES:
                    self._record("harvest", work_id, "skipped",
                                 error_code="offline")
                    result.skipped = True
                    result.skip_reason = "offline"
                    result.final_status = str(entry.get("status") or status)
                    return result
                # subtitle_done without raw / audio row without audio: let
                # the natural stage record its missing-input skip reason.
                if status == "subtitle_done":
                    self._stage_archive_from_subtitle(key, entry, result)
                else:
                    self._stage_asr_archive(key, entry, result)
                return result

            if status in _HARVEST_STATUSES:
                started = _utc_now_iso()
                identity = self._identity_for(entry, key)
                try:
                    status = subtitles_module.harvest_subtitle(
                        self.client, identity, self.store, self.root
                    )
                except Exception as exc:
                    self._record(
                        "harvest", work_id, "failed",
                        error_code=_safe_error_code(exc), started_at=started,
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
            elif status not in _SKIP_HARVEST_STATUSES:
                raise ValueError(f"unexpected status {status!r}")

            if status == "subtitle_done":
                entry = self._current_entry(key, entry)
                self._stage_archive_from_subtitle(key, entry, result)
            elif status in {"needs_audio", "audio_ok"}:
                if status == "needs_audio":
                    status = self._stage_download(key, entry, result)
                    if result.skipped:
                        return result
                    entry = self._current_entry(key, entry)
                self._stage_asr_archive(key, entry, result)
            elif status in _HARVEST_STATUSES:
                # harvest returned an unexpected transition
                raise ValueError(f"harvest returned unexpected status {status!r}")
        except Exception as exc:
            code = _safe_error_code(exc)
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

    def run_batch(self, rows: list[tuple[str, dict[str, Any]]]) -> RunSummary:
        injected_runner = self.asr_runner
        with archive_writer(self.root):
            self.asr_runner = injected_runner
            try:
                return self._run_batch_locked(rows)
            finally:
                if injected_runner is None and self.asr_runner is not None:
                    self.asr_runner.release()
                self.asr_runner = injected_runner

    def _run_batch_locked(
        self, rows: list[tuple[str, dict[str, Any]]]
    ) -> RunSummary:
        """Process rows sequentially while the archive root is owned."""
        from . import bili_client

        summary = RunSummary()
        for index, (key, entry) in enumerate(rows):
            work_id = str(entry.get("work_id") or key)
            status = str(entry.get("status") or "pending")
            result = RowResult(work_id=work_id, final_status=status)
            live = status not in TERMINAL_STATUSES and not self.offline

            def _fail(exc: BaseException, r: RowResult = result) -> None:
                # append once per code: process_row's stage wrappers may
                # have recorded the same scalar already (M1 dedupe)
                code = _safe_error_code(exc)
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
                code = _safe_error_code(exc)
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
    """Reuse archive.archive_stem for page-aware stems."""
    from .archive import archive_stem

    return archive_stem(entry)
