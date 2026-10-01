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
import sys
import threading
import time
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from . import asr as asr_module
from . import audio as audio_module
from . import subtitles as subtitles_module
from .artifact_root import ArtifactRoots
from .manifest import TERMINAL_STATUSES, ManifestStore
from .persistence import utc_now_iso
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

    The per-``(work_id, stage)`` latest attempt number is kept in an in-memory
    map seeded once at construction (a single full scan of any existing
    sidecar) and trusted thereafter, so ``append`` never re-reads the file.
    Numbering therefore assumes the project's sequential-no-daemon
    single-writer contract (decision D12): another process appending between
    this ledger's construction and its next append is out of contract.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = os.fspath(root)
        self.path = os.path.join(self.root, ATTEMPTS_REL_PATH)
        self._latest_attempts: dict[tuple[str, str], int] = {}
        for prior in self._iter_valid():
            key = (prior["work_id"], prior["stage"])
            self._latest_attempts[key] = max(
                self._latest_attempts.get(key, 0), prior["attempt"]
            )

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
            # Trust the in-memory map (seeded once at construction) instead
            # of re-scanning the whole sidecar per append; single-writer is
            # by design (decision D12).
            latest = self._latest_attempts.get(key, 0)
            if record.get("_preserve_attempt"):
                next_attempt = stored["attempt"]
            else:
                next_attempt = max(stored["attempt"], latest + 1)
            stored["attempt"] = next_attempt
            self._latest_attempts[key] = next_attempt
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



def model_constructions_line(command: str, constructions: int, asr_items: int) -> str:
    """The one line a batch prints to state how much reuse it got.

    Single source of the shipped string: README quotes this literal, and the
    in-process ``asr`` / ``pilot`` loops print through it as well
    (``cli._print_in_process_constructions``), so all five labels — ``run``,
    ``schedule`` and ``campaign`` via ``RunCoordinator.run_batch``, ``asr`` and
    ``pilot`` via that CLI helper — come from this one format string.
    """
    return (
        f"{command}: model constructions={constructions} "
        f"for {asr_items} asr item(s)"
    )


@dataclass
class RowResult:
    work_id: str
    final_status: str
    ok: bool = False
    skipped: bool = False
    skip_reason: str = ""
    failure_codes: list[int | str] = field(default_factory=list)


@dataclass
@dataclass
class RunSummary:
    results: list[RowResult] = field(default_factory=list)
    risk_interrupted: bool = False
    # Constructions this batch paid (delta over the batch's runner, so a
    # caller-injected runner reused across batches still reports per-batch
    # truth) and how many rows actually produced an ASR transcript.
    model_constructions: int = 0
    model_load_attempts: int = 0
    asr_items: int = 0

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
        # Re-entrancy tripwire for ``run_batch`` (see its docstring): the
        # denominator above is per-coordinator, not per-batch.
        self._batch_depth = 0
        self.audio_peak_bytes = 0
        self.ledger = AttemptLedger(self.root)
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
        for base in self.artifact_roots.read_bases():
            for declared in declared_candidates:
                try:
                    confined = confined_audio_path(base, declared, require_exists=True)
                    if confined is not None and confined.stat().st_size > 0:
                        return base, declared
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
                declared = os.path.relpath(path, base)
            except ValueError:  # Windows across drives
                continue
            if confined_audio_path(base, declared, require_exists=True) is not None:
                return declared
        return None

    def _stage_archive_from_subtitle(
        self, key: str, entry: dict[str, Any], result: RowResult
    ) -> None:
        from . import archive as archive_module

        work_id = str(entry.get("work_id") or key)
        started = utc_now_iso()
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
                self.artifact_roots.write_base, entry, segments, source="subtitle", raw=raw
            )
        except Exception as exc:  # redacted; batch continues
            self._record(
                "archive", work_id, "failed",
                error_code=_safe_error_code(exc), started_at=started,
            )
            raise
        try:
            if not archive_module.archive_bundle_complete(
                self.artifact_roots.write_base, paths
            ):
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
        """Record observed `{artifact_root}/audio/` usage for campaign proof.

        The cap and the peak measure the configured root (contract §8, D16):
        legacy audio still sitting at the archive root is on another device and
        is not where new bytes land.
        """
        from .audio_budget import audio_dir_usage_bytes

        usage = audio_dir_usage_bytes(self.artifact_roots.write_base)
        if usage > self.audio_peak_bytes:
            self.audio_peak_bytes = usage

    def _reclaim_audio(self, entry: dict[str, Any]) -> None:
        """Best-effort audio reclaim once a row is archived."""
        from .audio_reclaim import reclaim_audio

        self._note_audio_peak()
        try:
            reclaim_audio(
                self.root,
                entry,
                artifact_roots=self.artifact_roots,
                keep=self.keep_audio,
            )
        except (OSError, ValueError):
            pass  # per-item non-fatal: transcripts exist; row stays archived

    def _stage_asr_archive(
        self, key: str, entry: dict[str, Any], result: RowResult
    ) -> None:
        from . import archive as archive_module

        work_id = str(entry.get("work_id") or key)
        started = utc_now_iso()
        resolved = self._existing_audio(entry)
        if resolved is None:
            self._record(
                "asr", work_id, "skipped",
                error_code="missing_audio", started_at=started,
            )
            result.skipped = True
            result.skip_reason = "missing_audio"
            result.final_status = str(entry.get("status") or "")
            return
        audio_base, audio_declared = resolved
        try:
            from .path_policy import confined_audio_file
            if self.asr_runner is None:
                self.asr_runner = asr_module.ASRRunner(asr_module.default_config())
            runner = self.asr_runner
            # Evidence-based seeding (governance ruling 2026-09-28, plan
            # 20260928-hotword-injection-governance): the run's own first-pass
            # transcript, and the paired AI-subtitle text when the part has a
            # subtitle route, are the only texts that may admit a hotword.
            # Pass 1 runs unguarded; pass 2 is seeded with the tokens pass 1
            # itself produced and re-decodes with a clean model/cache state.
            # Tokens the transcript does not contain are recorded in the archive
            # provenance as ``hotword_dropped_no_evidence``.
            subtitle_raw = self._subtitle_segments(self._current_entry(key, entry))
            paired_subtitle_text = (
                "".join(str(seg.get("text", "")) for seg in subtitle_raw[0])
                if subtitle_raw is not None
                else None
            )
            with confined_audio_file(audio_base, audio_declared) as safe_audio:
                segments = asr_module.two_pass_transcribe(
                    runner, safe_audio, paired_subtitle_text=paired_subtitle_text
                )
        except Exception as exc:  # redacted; batch continues
            self._record(
                "asr", work_id, "failed",
                error_code=_safe_error_code(exc), started_at=started,
            )
            raise
        self._record("asr", work_id, "ok", started_at=started)
        # This row produced an ASR transcript: the denominator of the printed
        # reuse line (D2.5).  Counted here, at the `asr: ok` attempt.
        self._batch_asr_items += 1
        started = utc_now_iso()
        try:
            paths = archive_module.write_archive(
                self.artifact_roots.write_base, self._current_entry(key, entry), segments,
                source="asr",
                asr_provenance=self.asr_runner.provenance() if self.asr_runner else None,
                characters=asr_module.characters_of(runner),
            )
        except Exception as exc:  # redacted; batch continues
            self._record(
                "archive", work_id, "failed",
                error_code=_safe_error_code(exc), started_at=started,
            )
            raise
        try:
            if not archive_module.archive_bundle_complete(
                self.artifact_roots.write_base, paths
            ):
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
        current = self._current_entry(key, entry)
        current["audio_path"] = audio_declared
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
        started = utc_now_iso()
        if self.max_audio_bytes:
            from .audio_budget import SKIP_REASON, would_exceed_budget

            if would_exceed_budget(
                self.artifact_roots.write_base, entry, self.max_audio_bytes
            ):
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
        out_path = os.path.join(
            os.fspath(self.artifact_roots.write_base), "audio", f"{stem}.m4a"
        )
        # The configured root is the one case the downloader cannot derive from
        # `out_path`/`store.root`; the identity case keeps today's call shape.
        download_kwargs: dict[str, Any] = (
            {"artifact_roots": self.artifact_roots}
            if self.artifact_roots.configured
            else {}
        )
        try:
            final = audio_module.download_audio(
                self.client, identity, out_path, store=self.store, **download_kwargs
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
        declared = self._declared_audio(final)
        if declared is None:
            raise OSError("audio path outside archive")
        self._record(
            "download", work_id, "ok", artifact_paths=[declared], started_at=started
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
    ) -> RunSummary:
        injected_runner = self.asr_runner
        # Bound before the ``try`` so the ``finally`` can always read it: the
        # batch entry point may raise before producing a summary (the
        # interrupted-batch tests model exactly that), and the release path
        # must still run.
        summary = RunSummary()
        with archive_writer(self.root):
            self.asr_runner = injected_runner
            self._batch_asr_items = 0
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
            finally:
                # The batch's evidence is stated and the runner handed back on
                # *every* exit path, Ctrl-C included: the assignments and the
                # print sit before the release so a ``BaseException`` cannot
                # carry the count away, and the pending exception still
                # propagates (this ``finally`` never swallows or returns).
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
                self._print_model_constructions(summary)
            return summary

    def _print_model_constructions(self, summary: RunSummary) -> None:
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
        if summary.asr_items <= 0 and summary.model_constructions <= 0:
            # Check if we had failed load attempts
            if summary.model_load_attempts > 0:
                if sys.stderr is not None:
                    print(
                        f"{self.command}: model load failed {summary.model_load_attempts} time(s), "
                        f"0 transcripts produced",
                        file=sys.stderr,
                    )
            return
        if sys.stderr is None:
            return
        print(
            model_constructions_line(
                self.command, summary.model_constructions, summary.asr_items
            ),
            file=sys.stderr,
        )

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
