"""Deterministic, read-only archive integrity verification."""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os
import re
import stat
import tempfile
import threading
from pathlib import Path
from typing import Any

if os.name == "nt":
    import msvcrt
else:
    import fcntl
from .archive import (
    archive_bundle_complete,
    bundle_paths_for_stem,
)
from .artifact_root import ArtifactRoots
from .manifest import BACKLOG_STATUSES, JOURNAL_NAME
from .page_identity import canonical_stem
from .coordinator import _validate_attempt
from .sidecar_projection import (
    ORDINARY_HISTORY_DIAGNOSTICS, ReaderPolicy, is_plain_cli_archive,
    project_attempt_records, project_manifest_records,
)

MISSING_RAW_SUBTITLE = "missing_raw_subtitle"
MISSING_TRANSCRIPT = "missing_transcript"
MALFORMED_ARTIFACT = "malformed_artifact"
IDENTITY_PATH_MISMATCH = "identity_path_mismatch"
TRUNCATED_ATTEMPTS_LINE = "truncated_attempts_line"
RETRYABLE_INCOMPLETE = "retryable_incomplete"
STRUCTURAL_INPUT_ERROR = "structural_input_error"
MANIFEST_ROW_LIMIT_EXCEEDED = "manifest_row_limit_exceeded"
MANIFEST_INVALID_STATUS = "manifest_invalid_status"
MANIFEST_INVALID_BVID = "manifest_invalid_bvid"
MISSING_ATTEMPTS = "missing_attempts_sidecar"
ATTEMPTS_ROW_LIMIT_EXCEEDED = "attempts_row_limit_exceeded"
ATTEMPTS_BYTE_LIMIT_EXCEEDED = "attempts_byte_limit_exceeded"
RECOVERY_REQUIRES_EXPLICIT_TARGET = "recovery_requires_explicit_target"
RECOVERY_TARGET_NOT_FOUND = "recovery_target_not_found"
RECOVERY_TARGET_LIMIT_EXCEEDED = "recovery_target_limit_exceeded"
RECOVERY_NOT_AUTHORITATIVE = "recovery_not_authoritative"
RECOVERY_MALFORMED_SIDECAR = "recovery_malformed_sidecar"
RECOVERY_INVALID_SELECTOR = "recovery_invalid_selector"
#: The two finding classes (exit-code contract §2).  Only ``RETRYABLE_INCOMPLETE``
#: is backlog: it means the chain has not reached this row yet — normal operations,
#: not corruption.  Every other code above is defect-class.
DEFECT_CATEGORY = "defect"
BACKLOG_CATEGORY = "backlog"
BACKLOG_CODES: frozenset[str] = frozenset({RETRYABLE_INCOMPLETE})
_RECOVERY_MAX_TARGETS = 100
_AUDIT_REL_PATH = "coordinator/recovery-audit.jsonl"
_AUDIT_LOCK_REL_PATH = "coordinator/recovery-audit.lock"
_AUDIT_MAX_ROWS = 1000
_AUDIT_MAX_BYTES = 1024 * 1024
_AUDIT_MAX_FIELD_CHARS = 256
_AUDIT_RECORD_KEYS = frozenset({"action", "work_ids", "defect_codes"})
_RECOVERY_DEFECT_CODES = frozenset({
    MISSING_RAW_SUBTITLE,
    MISSING_TRANSCRIPT,
    MALFORMED_ARTIFACT,
    IDENTITY_PATH_MISMATCH,
    RETRYABLE_INCOMPLETE,
})
_AUDIT_FORBIDDEN_MARKERS = ("sessdata", "cookie", "http://", "https://", "traceback")
_AUDIT_WRITE_LOCK = threading.Lock()
_MAX_ROWS = 10000
_MAX_ATTEMPTS_BYTES = 8 * 1024 * 1024
#: The four recorded bundle paths; the same order the writers publish them in.
from .artifacts import REQUIRED_ARTIFACT_KEYS as _BUNDLE_PATH_KEYS


def _fsync_directory(directory: Path) -> None:
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _open_coordinator(root: Path) -> tuple[int, Path]:
    coordinator = root / "coordinator"
    try:
        coordinator_fd = os.open(coordinator, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        os.mkdir(coordinator, 0o755)
        coordinator_fd = os.open(coordinator, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    return coordinator_fd, coordinator


def _reject_symlink(path: Path) -> None:
    try:
        if path.is_symlink():
            raise OSError(f"symlinked recovery path: {path.name}")
    except OSError:
        raise


def _valid_recovery_audit_record(record: object) -> bool:
    if not isinstance(record, dict) or set(record) != _AUDIT_RECORD_KEYS:
        return False
    if record.get("action") != "audit":
        return False
    work_ids = record.get("work_ids")
    defect_codes = record.get("defect_codes")
    if (not isinstance(work_ids, list) or not isinstance(defect_codes, list)
            or not work_ids or not defect_codes
            or len(work_ids) > _RECOVERY_MAX_TARGETS
            or len(defect_codes) > _RECOVERY_MAX_TARGETS):
        return False
    for value in work_ids + defect_codes:
        if (not isinstance(value, str) or not value
                or len(value) > _AUDIT_MAX_FIELD_CHARS
                or any(marker in value.casefold() for marker in _AUDIT_FORBIDDEN_MARKERS)):
            return False
    return all(code in _RECOVERY_DEFECT_CODES for code in defect_codes)


class _RootConfinedReader:
    """Open archive files without following attacker-controlled path links."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def _relative_path(self, path: Path) -> Path:
        return path.relative_to(self._root) if path.is_absolute() else path

    def close(self) -> None:
        if self._root_fd >= 0:
            os.close(self._root_fd)
            self._root_fd = -1

    def _open(self, path: Path, flags: int) -> int:
        path = self._relative_path(path)
        parts = path.parts
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise OSError("unsafe relative path")
        directory_fd = os.dup(self._root_fd)
        try:
            for component in parts[:-1]:
                next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            return os.open(parts[-1], flags | os.O_NOFOLLOW, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)

    def read(self, path: Path, max_bytes: int) -> bytes:
        file_fd = -1
        try:
            file_fd = self._open(path, os.O_RDONLY | os.O_NONBLOCK)
            file_stat = os.fstat(file_fd)
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > max_bytes:
                raise OSError("unsafe or oversized file")
            chunks: list[bytes] = []
            total = 0
            while total <= max_bytes:
                chunk = os.read(file_fd, min(65536, max_bytes + 1 - total))
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                total += len(chunk)
            raise OSError("oversized file")
        finally:
            if file_fd >= 0:
                os.close(file_fd)

    def is_regular(self, path: Path) -> bool:
        try:
            file_fd = self._open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return False
        try:
            return stat.S_ISREG(os.fstat(file_fd).st_mode)
        finally:
            os.close(file_fd)


def _open_artifact_bases(
    root: Path, roots: ArtifactRoots, archive_reader: _RootConfinedReader
) -> list[tuple[Path, _RootConfinedReader]]:
    """The ordered ``(base, reader)`` pairs a row's artifacts are probed under (§5).

    The archive base reuses the reader ``verify`` already opened and keeps the
    resolved state root, so the unconfigured path stays byte-identical.  A configured
    base opens its own no-follow reader, because a candidate must only ever be opened
    relative to the base it was validated against.  A base that cannot be opened
    cannot hold an artifact and is skipped: the archive base still answers, so an
    unusable configured root never degrades the report into an empty inventory
    (contract §10, D17) — refusing that root is the command boundary's job (§9).
    """
    pairs: list[tuple[Path, _RootConfinedReader]] = []
    for base in roots.read_bases():
        if base == roots.archive_root:
            pairs.append((root, archive_reader))
            continue
        try:
            pairs.append((base, _RootConfinedReader(base)))
        except OSError:
            continue
    return pairs


def _safe_over_bases(
    artifact_bases: list[tuple[Path, _RootConfinedReader]], candidates: list[Path]
) -> bool:
    """Whether one recorded path is confined at a base that could hold it (§5/§10).

    ``candidates`` is that path expressed under every base, in ``read_bases()`` order,
    so each form is judged by its own base's confinement.  A path is legal when *some*
    base confines it: with one base this is the shipped check unchanged, and with two it
    never invents a mismatch for a value that is legal where the file actually is.
    """
    return any(
        IntegrityVerifier._safe_path(path, base)
        for (base, _base_reader), path in zip(artifact_bases, candidates)
    )


def _locate_over_bases(
    artifact_bases: list[tuple[Path, _RootConfinedReader]], candidates: list[list[Path]]
) -> list[tuple[Path, _RootConfinedReader] | None]:
    """For each recorded path, the first base that holds it and that base's reader (§5).

    ``candidates[index]`` is one recorded path under every base, in ``read_bases()``
    order, so a candidate is only ever opened against the base it was built from — never
    against a neighbouring base's confinement.  A base that cannot legally hold the path
    is skipped rather than asked, so a later base still answers for it: that is what
    keeps a legacy row's verdict independent of where the other copies happen to be.
    """
    located: list[tuple[Path, _RootConfinedReader] | None] = []
    for per_index in candidates:
        hit: tuple[Path, _RootConfinedReader] | None = None
        for (base, base_reader), path in zip(artifact_bases, per_index):
            if IntegrityVerifier._safe_path(path, base) and base_reader.is_regular(path):
                hit = (path, base_reader)
                break
        located.append(hit)
    return located


@dataclass(frozen=True)
class IntegrityDefect:
    work_id: str
    code: str

    @property
    def category(self) -> str:
        """``"backlog"`` for work-not-yet-done codes, ``"defect"`` otherwise (contract §2)."""
        return BACKLOG_CATEGORY if self.code in BACKLOG_CODES else DEFECT_CATEGORY

    def to_dict(self) -> dict[str, object]: return {"work_id": self.work_id, "code": self.code, "category": self.category}

@dataclass
class IntegrityReport:
    checked: int = 0
    defects: list[IntegrityDefect] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    authoritative: bool = True

    @property
    def defect_count(self) -> int:
        """Defect-class findings only — backlog is reported separately (contract §2)."""
        return sum(1 for defect in self.defects if defect.category == DEFECT_CATEGORY)

    @property
    def backlog_count(self) -> int:
        return sum(1 for defect in self.defects if defect.category == BACKLOG_CATEGORY)

    def to_dict(self) -> dict[str, object]:
        return {"checked": self.checked, "defect_count": self.defect_count, "backlog_count": self.backlog_count, "defects": [d.to_dict() for d in self.defects], "diagnostics": list(self.diagnostics), "authoritative": self.authoritative}

class IntegrityVerifier:
    """Read-only archive integrity verifier."""

    def verify(self, archive_root: Path, *, scope: str | None = None,
               policy: ReaderPolicy | None = None,
               artifact_roots: ArtifactRoots | None = None) -> IntegrityReport:
        """Verify archive evidence without modifying source artifacts.

        Direct inspection defaults to bounded input. A trusted local caller must
        explicitly pass ``ReaderPolicy(mode="trusted_archive")``.

        ``artifact_roots`` carries the bases a row's artifacts are probed under
        (contract §5/§10, D8); the manifest and attempts reads are state and stay at
        the archive root.  ``report.authoritative`` remains a function of those state
        reads alone, so an unusable artifact root is the command boundary's refusal
        (§9), never a non-authoritative report.
        """
        root = Path(archive_root).resolve()
        if not root.is_dir():
            report = IntegrityReport(authoritative=False)
            report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
            return report
        roots = artifact_roots if artifact_roots is not None else ArtifactRoots.of(root)
        reader = _RootConfinedReader(root)
        artifact_bases = _open_artifact_bases(root, roots, reader)
        try:
            return self._verify_with_reader(
                root, scope, reader, policy or ReaderPolicy(), artifact_bases
            )
        finally:
            reader.close()
            for _base, base_reader in artifact_bases:
                if base_reader is not reader:
                    base_reader.close()

    def _verify_with_reader(self, root: Path, scope: str | None, reader: _RootConfinedReader, policy: ReaderPolicy, artifact_bases: list[tuple[Path, _RootConfinedReader]]) -> IntegrityReport:
        report = IntegrityReport()
        entries, manifest_state, manifest_diagnostics = project_manifest_records(
            root / "manifest" / "manifest.jsonl", policy=policy
        )
        attempts, attempts_state, attempt_diagnostics = project_attempt_records(
            root / "coordinator" / "attempts.jsonl", policy=policy
        )
        manifest_valid = manifest_state == "available"
        attempts_valid = attempts_state in {"available", "missing"}
        for diagnostic in sorted(manifest_diagnostics | attempt_diagnostics):
            if diagnostic == "manifest_row_limit_exceeded":
                report.diagnostics.append(MANIFEST_ROW_LIMIT_EXCEEDED)
            elif diagnostic in {"attempts_row_limit_exceeded", "attempts_byte_limit_exceeded"}:
                report.diagnostics.append({"attempts_row_limit_exceeded": ATTEMPTS_ROW_LIMIT_EXCEEDED, "attempts_byte_limit_exceeded": ATTEMPTS_BYTE_LIMIT_EXCEEDED}[diagnostic])
            elif diagnostic == "truncated_attempts_line":
                report.diagnostics.append(TRUNCATED_ATTEMPTS_LINE)
            elif diagnostic in {"manifest_invalid_status", "manifest_invalid_bvid"}:
                report.diagnostics.append(diagnostic)
            elif diagnostic == "structural_input_error" and MANIFEST_ROW_LIMIT_EXCEEDED in report.diagnostics:
                continue
            elif diagnostic == "manifest_malformed" and MANIFEST_ROW_LIMIT_EXCEEDED in report.diagnostics:
                continue
            elif diagnostic == "manifest_malformed":
                # §6 assertion 2: a malformed manifest line is a defect, not
                # history.  Swallowing it here made `verify` exit 0 with no
                # findings of either class while `coverage` reported it.
                report.diagnostics.append(MALFORMED_ARTIFACT)
            elif diagnostic == "attempt_invalid_record":
                continue
            elif diagnostic in ORDINARY_HISTORY_DIAGNOSTICS:
                continue
            else:
                report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
        # A small new ledger lives entirely in its append journal until the
        # compaction threshold is reached.  The projection validates and replays
        # both files; either confined regular file establishes ledger presence.
        manifest_present = reader.is_regular(Path("manifest/manifest.jsonl")) or reader.is_regular(
            Path("manifest") / JOURNAL_NAME
        )
        attempts_path = root / "coordinator" / "attempts.jsonl"
        attempts_present = attempts_path.is_file() and not attempts_path.is_symlink()
        report.authoritative = manifest_present and attempts_present and manifest_valid and attempts_valid and not any(
            diagnostic in {"structural_input_error", "attempts_row_limit_exceeded", "attempts_byte_limit_exceeded"}
            for diagnostic in attempt_diagnostics
        ) and not ({"manifest_invalid", "manifest_invalid_status", "manifest_invalid_bvid"} & manifest_diagnostics)
        if not manifest_present and MANIFEST_ROW_LIMIT_EXCEEDED not in report.diagnostics: report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
        plain_cli_archive = is_plain_cli_archive(entries)
        if not attempts_present and not plain_cli_archive:
            if manifest_present and manifest_valid:
                if MANIFEST_ROW_LIMIT_EXCEEDED not in report.diagnostics:
                    report.diagnostics.append(MISSING_ATTEMPTS)
            elif not manifest_present:
                if MANIFEST_ROW_LIMIT_EXCEEDED not in report.diagnostics:
                    report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
        if attempts_valid:
            selected = self._select(entries, scope, attempts)
        elif scope is None:
            selected = sorted(entries.items())
        else:
            selected = []
        report.checked = len(selected)
        for key, row in selected:
            work_id = str(row.get("work_id") or key); status = str(row.get("status") or ""); defects: set[str] = set()
            cid = row.get("cid")
            if cid is not None and (isinstance(cid, bool) or not isinstance(cid, int)):
                report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
                continue
            declared_bundle: dict[str, str] = {}
            complete_candidate = True
            for bundle_key in _BUNDLE_PATH_KEYS:
                value = row.get(bundle_key)
                if not isinstance(value, str):
                    complete_candidate = False
                    break
                declared_bundle[bundle_key] = value
            # §10: every recorded path — and the raw document — is probed over the ordered
            # bases, each candidate against its own base.  The bundle decides completeness
            # only (complete at either base is complete), while a path is answered by the
            # first base that holds it, so a defect is read where the file actually is.
            required = [list(paths) for paths in zip(*[self._required_paths(row, base) for base, _reader in artifact_bases])]
            canonical_required = [list(paths) for paths in zip(*[self._canonical_required_paths(row, base) for base, _reader in artifact_bases])]
            bundle_complete = complete_candidate and any(
                archive_bundle_complete(base, declared_bundle) for base, _reader in artifact_bases
            )
            for index, declared_paths in enumerate(required):
                if row.get("md_path") is not None and declared_paths[0] != canonical_required[index][0] and row.get("title"):
                    defects.add(IDENTITY_PATH_MISMATCH)
                if not _safe_over_bases(artifact_bases, declared_paths):
                    defects.add(IDENTITY_PATH_MISMATCH)
            present = [located[0] for located in _locate_over_bases(artifact_bases, required) if located is not None]
            for value in declared_bundle.values():
                candidate = [Path(value) if Path(value).is_absolute() else base / value for base, _reader in artifact_bases]
                if not _safe_over_bases(artifact_bases, candidate):
                    defects.add(IDENTITY_PATH_MISMATCH)
            # §2d: the declared candidates `quality.py` probes, so both readers
            # answer the same archive the same way.  Containment only — an absent
            # artifact is not this finding (that stays backlog), and the probe is a
            # no-op for shipped rows, which declare canonical relative paths.
            extra_values: list[object] = []
            for extra_key in ("subtitle_path", "artifact_path", "artifact_paths"):
                value = row.get(extra_key)
                if isinstance(value, (list, tuple)):
                    extra_values.extend(value)
                elif value is not None:
                    extra_values.append(value)
            for value in extra_values:
                if not isinstance(value, str):
                    continue          # a non-string cannot be a path; not this finding
                candidates = [
                    Path(value) if Path(value).is_absolute() else base / value
                    for base, _reader in artifact_bases
                ]
                if not _safe_over_bases(artifact_bases, candidates):
                    defects.add(IDENTITY_PATH_MISMATCH)
            if status in {"archived", "asr_done", "subtitle_done"} and (len(present) < len(canonical_required) or not bundle_complete): defects.add(MISSING_TRANSCRIPT)
            # §2f: BOTH raw locations are writer-real (`archive.py:469` declares `raw_path`
            # under transcripts/{stem}/bundle.raw.json; the subtitle path writes
            # subtitles/raw/), so both are
            # inferred candidates and both are asked the containment question for every status.
            # compass D5: an identity-invalid row has no guessable stem, so it
            # contributes no inferred raw candidates — its declared raw_path
            # (if any) is still probed below.
            try:
                raw_stem = self._canonical_stem(row)
            except (KeyError, TypeError, ValueError):
                raw_stem = None
            raw_candidates = (
                [
                    [base / "subtitles" / "raw" / f"{raw_stem}.json" for base, _reader in artifact_bases],
                    [bundle_paths_for_stem(base, raw_stem)["raw_path"] for base, _reader in artifact_bases],
                ]
                if raw_stem is not None else []
            )
            declared_raw = row.get("raw_path")
            if isinstance(declared_raw, str):
                declared_raw_paths = [Path(declared_raw) if Path(declared_raw).is_absolute() else base / declared_raw for base, _reader in artifact_bases]
                if not _safe_over_bases(artifact_bases, declared_raw_paths):
                    defects.add(IDENTITY_PATH_MISMATCH)
            located_raw: tuple[Path, _RootConfinedReader] | None = None
            escaped_raw = False
            for raw in raw_candidates:
                if not _safe_over_bases(artifact_bases, raw):
                    defects.add(IDENTITY_PATH_MISMATCH)
                    escaped_raw = True
                    continue                      # §2f: an escaping path is not "missing"
                if status == "subtitle_done" and located_raw is None:
                    located_raw = _locate_over_bases(artifact_bases, [raw])[0]
            # §2f item 3, measured: the per-candidate `continue` alone does not suppress the
            # ask.  The *sibling* candidate is confined and absent, so `located_raw` stays
            # None and the code set remained
            # `{identity_path_mismatch, missing_raw_subtitle, missing_transcript}` — the
            # side effect §2f removes.  An escape means the row's raw document cannot be
            # known to be missing from any candidate, so the ask is suppressed for the whole
            # row (this is also what un-widens `recover --defect-code missing_raw_subtitle`).
            if status == "subtitle_done" and located_raw is None and not escaped_raw:
                defects.add(MISSING_RAW_SUBTITLE)
            artifact_paths = [located for located in _locate_over_bases(artifact_bases, canonical_required) if located is not None]
            if located_raw is not None: artifact_paths.append(located_raw)
            if any(not self._valid_artifact(path, row, base_reader) for path, base_reader in artifact_paths):
                defects.add(MALFORMED_ARTIFACT)
            if status in BACKLOG_STATUSES:
                defects.add(RETRYABLE_INCOMPLETE)
            report.defects.extend(IntegrityDefect(work_id, code) for code in sorted(defects))
        report.defects.sort(key=lambda d: (d.work_id, d.code))
        return report

    @staticmethod
    def recover(archive_root: Path, *, work_ids: list[str] | None = None,
                defect_codes: list[str] | None = None, limit: int = 100,
                artifact_roots: ArtifactRoots | None = None) -> dict[str, object]:
        """Append one bounded, redacted recovery audit record.

        ``limit`` must be an integer from 1 through 100.  Defect-code
        selection is expanded first, then checked against that effective cap.
        The existing audit sidecar is validated and retained atomically; any
        malformed, oversized, or over-row evidence fails closed without a
        write.  Defect selection runs through ``verify``, so ``artifact_roots`` is
        forwarded into it (contract §10) — a ``recover`` that dropped it would grade
        every artifact against the wrong base.  The audit sidecar is state and stays
        under ``{archive_root}/coordinator/`` (D13).
        """
        root = Path(archive_root).resolve()
        if not work_ids and not defect_codes:
            return {"ok": False, "code": RECOVERY_REQUIRES_EXPLICIT_TARGET, "selected": []}
        if work_ids and defect_codes:
            return {"ok": False, "code": RECOVERY_INVALID_SELECTOR, "selected": []}
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            return {"ok": False, "code": RECOVERY_TARGET_LIMIT_EXCEEDED, "selected": []}
        effective_limit = min(limit, _RECOVERY_MAX_TARGETS)
        if work_ids is not None and (not isinstance(work_ids, list) or
                not work_ids or any(not isinstance(value, str) or not value or
                                    len(value) > _AUDIT_MAX_FIELD_CHARS for value in work_ids)):
            return {"ok": False, "code": RECOVERY_INVALID_SELECTOR, "selected": []}
        if defect_codes is not None and (not isinstance(defect_codes, list) or
                not defect_codes or any(not isinstance(value, str) or not value or
                                        len(value) > _AUDIT_MAX_FIELD_CHARS or
                                        value not in _RECOVERY_DEFECT_CODES for value in defect_codes)):
            return {"ok": False, "code": RECOVERY_INVALID_SELECTOR, "selected": []}
        selected_ids = sorted(set(work_ids or []))
        if len(selected_ids) > effective_limit:
            return {"ok": False, "code": RECOVERY_TARGET_LIMIT_EXCEEDED, "selected": []}
        report = IntegrityVerifier().verify(root, artifact_roots=artifact_roots)
        if not report.authoritative:
            return {"ok": False, "code": RECOVERY_NOT_AUTHORITATIVE, "selected": []}
        defect_filter = set(defect_codes or [])
        defects_by_id: dict[str, set[str]] = {}
        for defect in report.defects:
            defects_by_id.setdefault(defect.work_id, set()).add(defect.code)
        if defect_filter:
            selected_ids = sorted(work_id for work_id, codes in defects_by_id.items() if codes & defect_filter)
        if len(selected_ids) > effective_limit:
            return {"ok": False, "code": RECOVERY_TARGET_LIMIT_EXCEEDED, "selected": []}
        if not selected_ids or any(work_id not in defects_by_id for work_id in selected_ids):
            return {"ok": False, "code": RECOVERY_TARGET_NOT_FOUND, "selected": []}
        audit = {"action": "audit", "work_ids": selected_ids,
                 "defect_codes": sorted({code for work_id in selected_ids for code in defects_by_id[work_id]})}
        if (len(audit["work_ids"]) > _RECOVERY_MAX_TARGETS
                or len(audit["defect_codes"]) > _RECOVERY_MAX_TARGETS
                or not _valid_recovery_audit_record(audit)):
            return {"ok": False, "code": RECOVERY_TARGET_LIMIT_EXCEEDED, "selected": []}
        audit_path = root / _AUDIT_REL_PATH
        line_bytes = (json.dumps(audit, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        with _AUDIT_WRITE_LOCK:
            temporary_path: Path | None = None
            temporary_owned = False
            rollback_path: Path | None = None
            rollback_owned = False
            fallback_path: Path | None = None
            fallback_owned = False
            coordinator_fd = -1
            try:
                coordinator_fd, coordinator = _open_coordinator(root)
                for name in ("recovery-audit.jsonl", "recovery-audit.lock",
                             "recovery-audit.jsonl.tmp", "recovery-audit.jsonl.rollback"):
                    _reject_symlink(coordinator / name)
                lock_fd = os.open(_AUDIT_LOCK_REL_PATH.rsplit("/", 1)[-1], os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=coordinator_fd)
                with os.fdopen(lock_fd, "a+b") as lock_handle:
                    if os.name == "nt":
                        # ``msvcrt.locking`` locks a byte range and requires
                        # an existing byte at the current file position.
                        lock_handle.seek(0, os.SEEK_END)
                        if lock_handle.tell() == 0:
                            lock_handle.write(b"0")
                            lock_handle.flush()
                        lock_handle.seek(0)
                        msvcrt.locking(lock_handle.fileno(), msvcrt.LK_LOCK, 1)
                    else:
                        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                    try:
                        existing = os.open("recovery-audit.jsonl", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=coordinator_fd)
                        audit_existed = True
                        if not stat.S_ISREG(os.fstat(existing).st_mode):
                            raise OSError("recovery audit sidecar is not a regular file")
                    except FileNotFoundError:
                        existing = None
                        audit_existed = False
                    try:
                        chunks = []
                        total = 0
                        while existing is not None:
                            chunk = os.read(existing, _AUDIT_MAX_BYTES + 1 - total)
                            if not chunk:
                                break
                            chunks.append(chunk)
                            total += len(chunk)
                            if total > _AUDIT_MAX_BYTES:
                                break
                        existing_bytes = b"".join(chunks)
                    finally:
                        if existing is not None: os.close(existing)
                    separator = b"\n" if existing_bytes and not existing_bytes.endswith(b"\n") else b""
                    replacement = existing_bytes + separator + line_bytes
                    if len(replacement) > _AUDIT_MAX_BYTES:
                        return {"ok": False, "code": RECOVERY_MALFORMED_SIDECAR, "selected": []}
                    existing_lines = [line for line in existing_bytes.splitlines() if line.strip()]
                    if len(existing_lines) >= _AUDIT_MAX_ROWS:
                        return {"ok": False, "code": RECOVERY_MALFORMED_SIDECAR, "selected": []}
                    for line in existing_lines:
                        if not _valid_recovery_audit_record(json.loads(line.decode("utf-8"))): raise ValueError
                    temp_fd, temp_name = tempfile.mkstemp(prefix=".recovery-audit.", suffix=".tmp", dir=coordinator)
                    temporary_path = coordinator / temp_name; temporary_owned = True
                    with os.fdopen(temp_fd, "wb") as handle:
                        handle.write(replacement); handle.flush(); os.fsync(handle.fileno())
                    os.replace(temp_name, "recovery-audit.jsonl", src_dir_fd=coordinator_fd, dst_dir_fd=coordinator_fd)
                    temporary_owned = False; temporary_path = None
                    try:
                        _fsync_directory(coordinator)
                    except OSError:
                        try:
                            if audit_existed:
                                rollback_fd, rollback_name = tempfile.mkstemp(prefix=".recovery-audit.", suffix=".rollback", dir=coordinator)
                                rollback_path = coordinator / rollback_name; rollback_owned = True
                                with os.fdopen(rollback_fd, "wb") as handle:
                                    handle.write(existing_bytes); handle.flush(); os.fsync(handle.fileno())
                                os.replace(rollback_name, "recovery-audit.jsonl", src_dir_fd=coordinator_fd, dst_dir_fd=coordinator_fd)
                                rollback_owned = False; rollback_path = None
                            else:
                                os.unlink("recovery-audit.jsonl", dir_fd=coordinator_fd)
                        except OSError:
                            # Best effort fallback; preserve the primary fsync failure.
                            try:
                                if audit_existed:
                                    fallback_fd, fallback_name = tempfile.mkstemp(prefix=".recovery-audit.", suffix=".rollback", dir=coordinator)
                                    fallback_path = coordinator / fallback_name; fallback_owned = True
                                    with os.fdopen(fallback_fd, "wb") as handle:
                                        handle.write(existing_bytes); handle.flush(); os.fsync(handle.fileno())
                                    os.replace(fallback_name, "recovery-audit.jsonl", src_dir_fd=coordinator_fd, dst_dir_fd=coordinator_fd)
                                    fallback_owned = False; fallback_path = None
                                else:
                                    os.unlink("recovery-audit.jsonl", dir_fd=coordinator_fd)
                            except OSError:
                                pass
                        try:
                            try: _fsync_directory(coordinator)
                            except OSError: pass
                        finally:
                            for path, owned in ((rollback_path, rollback_owned), (fallback_path, fallback_owned)):
                                if path is not None and owned:
                                    try: path.unlink()
                                    except OSError: pass
                            for path, owned in ((temporary_path, temporary_owned),):
                                if path is not None and owned:
                                    try: path.unlink()
                                    except OSError: pass
                        return {"ok": False, "code": RECOVERY_MALFORMED_SIDECAR, "selected": []}
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                for path, owned in ((temporary_path, temporary_owned), (rollback_path, rollback_owned), (fallback_path, fallback_owned)):
                    if path is not None and owned:
                        try: path.unlink()
                        except OSError: pass
                return {"ok": False, "code": RECOVERY_MALFORMED_SIDECAR, "selected": []}
            finally:
                if coordinator_fd >= 0: os.close(coordinator_fd)
        return {"ok": True, "selected": selected_ids, "audit_path": _AUDIT_REL_PATH}

    @staticmethod
    def _select(entries, scope, attempts):
        if not scope: return sorted(entries.items())
        tokens={p for p in scope.replace(","," ").split() if p}
        if "pending" in tokens: return sorted((k,v) for k,v in entries.items() if v.get("status")=="pending")
        if "failed" in tokens:
            failed={r["work_id"] for r in attempts if r.get("outcome")=="failed"}
            return sorted((k,v) for k,v in entries.items() if k in failed)
        return sorted((k,v) for k,v in entries.items() if k in tokens or str(v.get("bvid")) in tokens)

    @staticmethod
    def _required_paths(row, root):
        names=("srt_path","txt_path","md_path"); values=[row.get(n) for n in names]
        try:
            stem = IntegrityVerifier._canonical_stem(row)
        except (KeyError, TypeError, ValueError):
            # compass D5: an identity-invalid row (missing bvid / malformed
            # work_id) has no guessable stem, so no default path may be
            # inferred from one; the row's own declared values are still
            # probed.
            stem = None
        if stem is None:
            # compass D5: an identity-invalid row has no guessable stem, so
            # no default path may be inferred from one. Declared values are
            # still probed; undeclared slots have no candidate at all.
            return [Path(v) if isinstance(v, str) and Path(v).is_absolute() else root / v for v in values if isinstance(v, str)]
        defaults = [bundle_paths_for_stem("", stem)[k].as_posix() for k in ("srt_path","txt_path","md_path")]
        return [Path(v) if isinstance(v,str) and Path(v).is_absolute() else root/(v if isinstance(v,str) else defaults[i]) for i,v in enumerate(values)]

    @classmethod
    def _canonical_required_paths(cls, row, root):
        # Shape A: the markdown no longer embeds the pubdate and title, so the
        # branch that used to name it differently from its three siblings is
        # gone -- all four are fixed names in the work's own directory.
        #
        # compass D5: an identity-invalid row (missing bvid / malformed
        # work_id) has no canonical stem; the inferred canonical bundle is
        # therefore empty — the row's declared paths (if any) carry what can
        # be probed, and an inferred path must not be guessed.
        try:
            paths = bundle_paths_for_stem(root, cls._canonical_stem(row))
        except (KeyError, TypeError, ValueError):
            return []
        return [paths[k] for k in ("srt_path", "txt_path", "md_path")]
    @staticmethod
    def _canonical_stem(row):
        """The row's canonical stem (compass D5) — delegates to
        ``page_identity.canonical_stem``."""
        return canonical_stem(row)


    @staticmethod
    def _valid_artifact(path: Path, row: dict[str, Any], reader: _RootConfinedReader) -> bool:
        try:
            text = reader.read(path, 8 * 1024 * 1024).decode("utf-8")
        except (OSError, UnicodeError):
            return False
        if not text.strip():
            return False
        if path.suffix == ".srt":
            for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
                lines = [line.strip() for line in block.splitlines() if line.strip()]
                if not lines:
                    continue
                timing = next((line for line in lines if "-->" in line), None)
                if timing is None:
                    return False
                parts = [part.strip() for part in timing.split("-->", 1)]
                if len(parts) != 2 or not all(IntegrityVerifier._valid_srt_time(part) for part in parts):
                    return False
        elif path.suffix == ".json":
            from .cues import CueParseError, read_cues

            try:
                cues, malformed, empty = read_cues(
                    path, text, require_source="asr" if row.get("source") == "asr" else None
                )
            except CueParseError:
                return False
            if malformed or empty or any(not cue.text.strip() for cue in cues):
                return False
        return True

    @staticmethod
    def _valid_srt_time(value: str) -> bool:
        match = re.match(r"^\d{1,3}:[0-5]\d:[0-5]\d[,.]\d{1,3}$", value)
        return bool(match)

    @staticmethod
    def _safe_path(path,root):
        """Whether ``path`` resolves inside ``root`` — the containment probe, asked resolved.

        A candidate is always ``base / <recorded value>``, so resolving only one side makes
        every base whose *ancestor* is a symlink confine nothing: that configuration is legal
        (the configured value stays lexical, D9/§3.2, and ``roots_for`` refuses only a
        symlinked root itself), so the one-sided compare reads a present artifact as missing.
        Both sides are resolved here, exactly as the sibling readers' resolve-based guards do
        (``quality._contained``, ``coverage_report._contained_path``).  The base stays lexical
        everywhere it is compared for identity; that is a different question, decided in
        ``artifact_root.py``.
        """
        try: path.resolve().relative_to(Path(root).resolve()); return True
        except ValueError:return False
