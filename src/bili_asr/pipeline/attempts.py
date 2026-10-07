"""Attempts implementation."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from bili_asr.persistence import append_jsonl_record, file_lock


STAGES = ("harvest", "download", "asr", "archive")


OUTCOMES = ("ok", "failed", "skipped")


_HARVEST_STATUSES = frozenset({"pending", "meta_ok", "sub_checked"})


_SKIP_HARVEST_STATUSES = frozenset(
    {"subtitle_done", "needs_audio", "audio_ok", "archived"}
)


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
    sidecar).  The single-writer fast path (D12) trusts that map without
    re-reading, so a batch pays no per-row re-read; cross-process safety is
    restored by a cheap fingerprint, not by scanning growing state:

    * The sidecar is append-only and never compacted (D12), so its size is a
      monotone write fingerprint.  ``append`` records the size it last saw;
      under the flock, a foreign append since then shows up as a size delta.
    * On that collision only, the ledger re-reads the journal tail (the bytes
      past the last seen size) strictly — a malformed tail raises before
      anything is written — and replays those records into the in-memory map
      before numbering.  The journal is small and the tail shorter still, so
      the collision path is cheap; the no-collision path stays O(1).
    """

    # Bounded window for the fingerprint snap-back: the record boundary is
    # nearly always within this many bytes of the (unflocked) fingerprint, so
    # the common case does not read the whole prefix.
    _FINGERPRINT_WINDOW = 8192

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = os.fspath(root)
        self.path = os.path.join(self.root, ATTEMPTS_REL_PATH)
        self._latest_attempts: dict[tuple[str, str], int] = {}
        # Lenient seeding (load() stays tolerant), but remember whether the
        # history we seeded from contained malformed records: an authoritative
        # append must fail closed on a corrupt sidecar instead of extending
        # it, without re-reading the file per append.
        self._history_malformed = False
        # Monotone write fingerprint of the append-only sidecar (D12): its
        # byte size as of the last load/replay this instance performed.
        # Captured BEFORE the seeding read: a foreign append landing between
        # the read and this fingerprint would otherwise be absorbed into an
        # already-current size and never replayed (a duplicate attempt
        # number).  The sidecar only grows, so a pre-read size is
        # conservative — the first append replays that window as a tail.
        # None until the sidecar exists or this instance itself appends.
        self._last_seen_size = self._file_size()
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        prior = _validate_attempt(json.loads(line))
                    except (json.JSONDecodeError, ValueError):
                        self._history_malformed = True
                        continue
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
            # Single-writer fast path (D12): when the sidecar size matches the
            # last size this instance saw, no foreign append happened and the
            # in-memory map is authoritative — no re-read.  A size delta means
            # another process appended under the same flock; replay only the
            # new tail strictly (malformed tail fails closed) and refresh the
            # map before numbering.
            #
            # The malformed verdict is re-derived here, per append, instead of
            # being latched for the instance's lifetime: a construction-time
            # read can catch a foreign writer's torn tail, and a healed journal
            # must not leave the instance permanently unable to record
            # evidence.  The O(1) no-delta path performs no read at all.
            if self._file_size() != self._last_seen_size:
                self._replay_tail(self._last_seen_size or 0)
            if self._history_malformed:
                # Seeding (or the tail replay) found malformed history: grade
                # the bytes that are on disk NOW.  A journal that healed since
                # recovers; one that is still malformed fails closed.
                self._revalidate_history()
                if self._history_malformed:
                    raise ValueError("malformed attempt history")
            key = (stored["work_id"], stored["stage"])
            latest = self._latest_attempts.get(key, 0)
            if record.get("_preserve_attempt"):
                next_attempt = stored["attempt"]
            else:
                next_attempt = max(stored["attempt"], latest + 1)
            stored["attempt"] = next_attempt
            self._latest_attempts[key] = next_attempt
            append_jsonl_record(self.path, stored, lock_path=lock_path)
            self._last_seen_size = self._file_size()
        return stored

    def _file_size(self) -> int | None:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return None

    def _replay_tail(self, offset: int) -> None:
        """Re-read and strictly validate only the journal tail past ``offset``.

        The sidecar is append-only and never truncated (D12), so the bytes at
        the fingerprint are a foreign append; replaying them into the in-memory
        map restores cross-process numbering without a full scan.  Strict
        validation keeps the authoritative append fail-closed on a malformed
        history, as it was before the in-memory map landed.

        The fingerprint is a byte offset taken *without* the flock, so it can
        land inside a record or inside a multi-byte character.  Two alignment
        rules keep a valid journal from being accused:

        * the read starts at the last ``b"\\n"`` at or before the offset, so the
          tail always begins on a record boundary (the extra bytes before the
          offset are re-validated too — they are already-known records);
        * the tail is split on ``"\\n"`` only, never ``str.splitlines()``, which
          also breaks on U+2028/U+2029/U+0085 — legal inside a JSON string and
          written raw by this repo's own writer (``ensure_ascii=False``).

        Invalid UTF-8 is corruption, not a substitution opportunity: decoding is
        strict so a mutilated record cannot pass as valid through U+FFFD.
        """

        try:
            with open(self.path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                start = min(offset, size)
                if start > 0:
                    fh.seek(start - 1)
                    if fh.read(1) != b"\n":
                        # The fingerprint landed mid-record: walk back to the
                        # record boundary so the tail parses as whole records.
                        # The walk is O(offset) in the worst case, so scan a
                        # bounded window first (the boundary is nearly always
                        # within a few hundred bytes) and only fall back to the
                        # full prefix when that window holds no newline.
                        window = self._FINGERPRINT_WINDOW
                        lo = max(0, start - window)
                        fh.seek(lo)
                        chunk = fh.read(start - lo)
                        boundary = chunk.rfind(b"\n")
                        if boundary >= 0:
                            start = lo + boundary + 1
                        else:
                            fh.seek(0)
                            head = fh.read(start)
                            found = head.rfind(b"\n")
                            start = found + 1 if found >= 0 else 0
                fh.seek(start)
                raw = fh.read()
        except FileNotFoundError:
            # A missing journal is a normal, self-healing state (base recreated
            # it): fall back to absent-on-disk instead of failing the append.
            self._last_seen_size = None
            self._history_malformed = False
            return
        except OSError as exc:
            raise ValueError("attempt history unavailable") from exc
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            self._history_malformed = True
            raise ValueError("malformed attempt history in tail") from exc
        if text:
            self._replay_lines(text, context="tail")

    def _revalidate_history(self) -> None:
        """Re-derive the malformed verdict from the journal on disk, now.

        Called only on the no-delta path when seeding already flagged the
        history: a torn tail observed at construction heals when the foreign
        writer finishes, and the instance must recover instead of refusing
        every later append for its whole lifetime.  Also refreshes the
        in-memory map (the healed tail's records belong in it).
        """

        try:
            with open(self.path, "rb") as fh:
                raw = fh.read()
        except FileNotFoundError:
            # Same self-healing state as a missing tail: treat as absent.
            self._last_seen_size = None
            self._history_malformed = False
            return
        except OSError as exc:
            raise ValueError("attempt history unavailable") from exc
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            self._history_malformed = True
            raise ValueError("malformed attempt history") from exc
        self._history_malformed = False
        self._replay_lines(text, context="history", strict=False)

    def _replay_lines(self, text: str, *, context: str, strict: bool = True) -> None:
        """Replay whole JSONL records from ``text`` into the in-memory map.

        ``strict`` marks the tail path, where a malformed record means the
        authoritative append must fail closed; the re-validation path passes
        ``strict=False`` because it is deriving the verdict, not enforcing it.
        """

        for line_number, line in enumerate(text.split("\n"), 1):
            if not line.strip():
                continue
            try:
                prior = _validate_attempt(json.loads(line))
            except (json.JSONDecodeError, ValueError) as exc:
                if strict:
                    self._history_malformed = True
                    raise ValueError(
                        f"malformed attempt history at {context} line {line_number}"
                    ) from exc
                self._history_malformed = True
                continue
            key = (prior["work_id"], prior["stage"])
            self._latest_attempts[key] = max(
                self._latest_attempts.get(key, 0), prior["attempt"]
            )

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
