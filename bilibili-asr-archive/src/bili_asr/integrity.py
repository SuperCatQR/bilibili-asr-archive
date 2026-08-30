"""Deterministic, read-only archive integrity verification."""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import fcntl
from .archive import archive_stem, _safe_name
from .page_identity import artifact_stem, page_identity, parse_work_id
from .coordinator import _validate_attempt

MISSING_RAW_SUBTITLE = "missing_raw_subtitle"
MISSING_TRANSCRIPT = "missing_transcript"
MALFORMED_ARTIFACT = "malformed_artifact"
IDENTITY_PATH_MISMATCH = "identity_path_mismatch"
TRUNCATED_ATTEMPTS_LINE = "truncated_attempts_line"
RETRYABLE_INCOMPLETE = "retryable_incomplete"
STRUCTURAL_INPUT_ERROR = "structural_input_error"
MANIFEST_ROW_LIMIT_EXCEEDED = "manifest_row_limit_exceeded"
MISSING_ATTEMPTS = "missing_attempts_sidecar"
ATTEMPTS_ROW_LIMIT_EXCEEDED = "attempts_row_limit_exceeded"
ATTEMPTS_BYTE_LIMIT_EXCEEDED = "attempts_byte_limit_exceeded"
RECOVERY_REQUIRES_EXPLICIT_TARGET = "recovery_requires_explicit_target"
RECOVERY_TARGET_NOT_FOUND = "recovery_target_not_found"
RECOVERY_TARGET_LIMIT_EXCEEDED = "recovery_target_limit_exceeded"
RECOVERY_NOT_AUTHORITATIVE = "recovery_not_authoritative"
RECOVERY_MALFORMED_SIDECAR = "recovery_malformed_sidecar"
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
_AUDIT_FORBIDDEN_MARKERS = ("SESSDATA", "cookie", "Cookie", "http://", "https://", "Traceback")
_AUDIT_WRITE_LOCK = threading.Lock()
_MAX_ROWS = 10000
_MAX_ATTEMPTS_BYTES = 8 * 1024 * 1024


def _valid_recovery_audit_record(record: object) -> bool:
    if not isinstance(record, dict) or set(record) != _AUDIT_RECORD_KEYS:
        return False
    if record.get("action") != "requeue":
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
                or any(marker in value for marker in _AUDIT_FORBIDDEN_MARKERS)):
            return False
    return all(code in _RECOVERY_DEFECT_CODES for code in defect_codes)


@dataclass(frozen=True)
class IntegrityDefect:
    work_id: str
    code: str
    def to_dict(self) -> dict[str, object]: return {"work_id": self.work_id, "code": self.code}

@dataclass
class IntegrityReport:
    checked: int = 0
    defects: list[IntegrityDefect] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    authoritative: bool = True
    def to_dict(self) -> dict[str, object]:
        return {"checked": self.checked, "defect_count": len(self.defects), "defects": [d.to_dict() for d in self.defects], "diagnostics": list(self.diagnostics), "authoritative": self.authoritative}

class IntegrityVerifier:
    def verify(self, archive_root: Path, *, scope: str | None = None) -> IntegrityReport:
        root = Path(archive_root).resolve(); report = IntegrityReport()
        if not root.is_dir():
            report.authoritative = False
            report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
            return report
        entries, manifest_valid = self._read_manifest(root, report)
        attempts, attempts_valid, truncated = self._read_attempts(root, report)
        manifest_present = (root / "manifest" / "manifest.jsonl").is_file()
        attempts_present = (root / "coordinator" / "attempts.jsonl").is_file()
        report.authoritative = manifest_present and attempts_present and manifest_valid and attempts_valid
        if not manifest_present: report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
        if not attempts_present:
            if manifest_present and manifest_valid:
                report.diagnostics.append(MISSING_ATTEMPTS)
            elif not manifest_present:
                report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
        # Legacy archives may predate the coordinator sidecar.  Keep their
        # manifest rows checkable while withholding the authoritative claim.
        selected = self._select(entries, scope, attempts if attempts_valid else []) if manifest_valid and (attempts_valid or not attempts_present) else []
        report.checked = len(selected)
        for key, row in selected:
            work_id = str(row.get("work_id") or key); status = str(row.get("status") or ""); defects: set[str] = set()
            cid = row.get("cid")
            if cid is not None and (isinstance(cid, bool) or not isinstance(cid, int)):
                report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
                continue
            required = self._required_paths(row, root)
            canonical_required = self._canonical_required_paths(row, root)
            for declared, canonical in zip(required, canonical_required):
                if declared != canonical:
                    defects.add(IDENTITY_PATH_MISMATCH)
            for path in required:
                if not self._safe_path(path, root): defects.add(IDENTITY_PATH_MISMATCH)
            present = [p for p in canonical_required if self._safe_path(p, root) and p.is_file()]
            if status in {"archived", "asr_done", "subtitle_done"} and len(present) < len(canonical_required): defects.add(MISSING_TRANSCRIPT)
            raw = root / "subtitles" / "raw" / f"{self._canonical_stem(row)}.json"
            declared_raw = row.get("raw_path")
            if isinstance(declared_raw, str):
                declared_raw_path = Path(declared_raw) if Path(declared_raw).is_absolute() else root / declared_raw
                legacy_raw_path = root / "transcripts" / "raw" / raw.name
                if declared_raw_path not in {raw, legacy_raw_path} or not self._safe_path(declared_raw_path, root):
                    defects.add(IDENTITY_PATH_MISMATCH)
            if status == "subtitle_done" and not self._safe_path(raw, root): defects.add(IDENTITY_PATH_MISMATCH)
            elif status == "subtitle_done" and not raw.is_file(): defects.add(MISSING_RAW_SUBTITLE)
            artifact_paths = list(canonical_required)
            if status == "subtitle_done": artifact_paths.append(raw)
            if any(not self._valid_artifact(path, row) for path in artifact_paths if path.is_file()):
                defects.add(MALFORMED_ARTIFACT)
            if status in {"pending", "meta_ok", "sub_checked", "needs_audio", "audio_ok"}: defects.add(RETRYABLE_INCOMPLETE)
            report.defects.extend(IntegrityDefect(work_id, code) for code in sorted(defects))
        if truncated: report.diagnostics.append(TRUNCATED_ATTEMPTS_LINE)
        report.defects.sort(key=lambda d: (d.work_id, d.code)); return report

    @staticmethod
    def recover(archive_root: Path, *, work_ids: list[str] | None = None,
                defect_codes: list[str] | None = None, limit: int = 100) -> dict[str, object]:
        """Append one bounded, redacted recovery audit record.

        ``limit`` must be an integer from 1 through 100.  Defect-code
        selection is expanded first, then checked against that effective cap.
        The existing audit sidecar is validated and retained atomically; any
        malformed, oversized, or over-row evidence fails closed without a
        write.
        """
        root = Path(archive_root).resolve()
        if not work_ids and not defect_codes:
            return {"ok": False, "code": RECOVERY_REQUIRES_EXPLICIT_TARGET, "selected": []}
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            return {"ok": False, "code": RECOVERY_TARGET_LIMIT_EXCEEDED, "selected": []}
        effective_limit = min(limit, _RECOVERY_MAX_TARGETS)
        selected_ids = sorted({str(value) for value in (work_ids or []) if str(value)})
        if len(selected_ids) > effective_limit:
            return {"ok": False, "code": RECOVERY_TARGET_LIMIT_EXCEEDED, "selected": []}
        report = IntegrityVerifier().verify(root)
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
        audit = {"action": "requeue", "work_ids": selected_ids,
                 "defect_codes": sorted({code for work_id in selected_ids for code in defects_by_id[work_id]})}
        if (len(audit["work_ids"]) > _RECOVERY_MAX_TARGETS
                or len(audit["defect_codes"]) > _RECOVERY_MAX_TARGETS
                or not _valid_recovery_audit_record(audit)):
            return {"ok": False, "code": RECOVERY_TARGET_LIMIT_EXCEEDED, "selected": []}
        audit_path = root / _AUDIT_REL_PATH
        line_bytes = (json.dumps(audit, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        with _AUDIT_WRITE_LOCK:
            lock_path = root / _AUDIT_LOCK_REL_PATH
            temporary_path: Path | None = None
            try:
                audit_path.parent.mkdir(parents=True, exist_ok=True)
                with lock_path.open("a+b") as lock_handle:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                    existing = audit_path.read_bytes() if audit_path.exists() else b""
                    if len(existing) > _AUDIT_MAX_BYTES or len(existing) + len(line_bytes) > _AUDIT_MAX_BYTES:
                        return {"ok": False, "code": RECOVERY_MALFORMED_SIDECAR, "selected": []}
                    existing_lines = [line for line in existing.splitlines() if line.strip()]
                    if len(existing_lines) >= _AUDIT_MAX_ROWS:
                        return {"ok": False, "code": RECOVERY_MALFORMED_SIDECAR, "selected": []}
                    for line in existing_lines:
                        prior = json.loads(line.decode("utf-8"))
                        if not _valid_recovery_audit_record(prior):
                            raise ValueError
                    temporary_path = audit_path.with_name(audit_path.name + ".tmp")
                    with temporary_path.open("wb") as handle:
                        handle.write(existing)
                        if existing and not existing.endswith(b"\n"):
                            handle.write(b"\n")
                        handle.write(line_bytes)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary_path, audit_path)
                    temporary_path = None
                    try:
                        directory_fd = os.open(audit_path.parent, os.O_RDONLY)
                        try:
                            os.fsync(directory_fd)
                        finally:
                            os.close(directory_fd)
                    except OSError:
                        pass
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                if temporary_path is not None and temporary_path.exists():
                    try:
                        temporary_path.unlink()
                    except OSError:
                        pass
                return {"ok": False, "code": RECOVERY_MALFORMED_SIDECAR, "selected": []}
        return {"ok": True, "selected": selected_ids, "audit_path": _AUDIT_REL_PATH}

    @staticmethod
    def _read_manifest(root: Path, report: IntegrityReport) -> tuple[dict[str, dict[str, Any]], bool]:
        path=root/"manifest"/"manifest.jsonl"; entries={}; valid=True
        if not path.is_file(): return entries, True
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            non_empty_rows = sum(bool(line.strip()) for line in lines)
            if non_empty_rows > _MAX_ROWS:
                valid = False
                report.diagnostics.append(MANIFEST_ROW_LIMIT_EXCEEDED)
            for number, line in enumerate(lines[:_MAX_ROWS]):
                if not line.strip(): continue
                value=json.loads(line)
                if not isinstance(value,dict): raise ValueError
                for field_name in ("work_id", "bvid", "status", "srt_path", "txt_path", "md_path", "raw_path"):
                    if field_name in value and value[field_name] is not None and not isinstance(value[field_name], str): raise ValueError
                if "cid" in value and value["cid"] is not None and (isinstance(value["cid"], bool) or not isinstance(value["cid"], int)): raise ValueError
                key=value.get("work_id") or value.get("bvid") or ""
                if not key: raise ValueError
                entries[key]=value
        except (OSError,UnicodeError,json.JSONDecodeError,ValueError):
            valid=False; report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
        return entries, valid

    @staticmethod
    def _read_attempts(root: Path, report: IntegrityReport) -> tuple[list[dict[str, Any]], bool, bool]:
        path = root / "coordinator" / "attempts.jsonl"
        if not path.is_file(): return [], True, False
        records=[]; truncated=False; valid=True
        try:
            if path.stat().st_size > _MAX_ATTEMPTS_BYTES:
                report.diagnostics.append(ATTEMPTS_BYTE_LIMIT_EXCEEDED)
                return [], False, False
            lines = path.read_text(encoding="utf-8").splitlines()
            if sum(bool(line.strip()) for line in lines) > _MAX_ROWS:
                report.diagnostics.append(ATTEMPTS_ROW_LIMIT_EXCEEDED)
                return [], False, False
        except (OSError, UnicodeError):
            report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
            return [], False, False
        last_non_empty = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
        for index, line in enumerate(lines):
            if not line.strip(): continue
            try:
                value=json.loads(line)
            except json.JSONDecodeError:
                if index == last_non_empty: truncated=True
                else: valid=False; report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
                continue
            try: record=_validate_attempt(value)
            except (TypeError,ValueError): valid=False; report.diagnostics.append(STRUCTURAL_INPUT_ERROR); continue
            records.append(record)
        return records,valid,truncated

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
        stem=IntegrityVerifier._canonical_stem(row)
        defaults=[f"transcripts/srt/{stem}.srt",f"transcripts/txt/{stem}.txt",f"transcripts/md/{stem}.md"]
        return [Path(v) if isinstance(v,str) and Path(v).is_absolute() else root/(v if isinstance(v,str) else defaults[i]) for i,v in enumerate(values)]

    @classmethod
    def _canonical_required_paths(cls, row, root):
        stem = cls._canonical_stem(row)
        if not row.get("title") and not row.get("pubdate_str"):
            md_path = root / f"transcripts/md/{stem}.md"
        else:
            md_name = f"{row.get('pubdate_str', 'unknown')}_{stem}_{_safe_name(str(row.get('title') or row.get('bvid')))}.md"
            md_path = root / "transcripts" / "md" / md_name
        return [root / f"transcripts/{kind}/{stem}.{kind}" for kind in ("srt", "txt")] + [md_path]
    @staticmethod
    def _canonical_stem(row):
        bvid=str(row.get("bvid") or ""); work=str(row.get("work_id") or "")
        if work and not row.get("unresolved"):
            try:
                wb,pi=parse_work_id(work)
                if bvid and bvid!=wb:return work
                return artifact_stem(page_identity(wb,pi,int(row.get("cid") or 0)))
            except (TypeError,ValueError): return work
        return archive_stem(row)


    @staticmethod
    def _valid_artifact(path: Path, row: dict[str, Any]) -> bool:
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                return False
            text = path.read_text(encoding="utf-8")
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
            try:
                document = json.loads(text)
            except (TypeError, ValueError):
                return False
            if isinstance(document, dict):
                items = document.get("body", document.get("segments"))
            else:
                items = document
            if not isinstance(items, list):
                return False
            if any(not isinstance(item, dict) for item in items[:10000]):
                return False
        return True

    @staticmethod
    def _valid_srt_time(value: str) -> bool:
        match = re.match(r"^\d{1,3}:[0-5]\d:[0-5]\d[,.]\d{1,3}$", value)
        return bool(match)

    @staticmethod
    def _safe_path(path,root):
        try: path.resolve().relative_to(root); return True
        except ValueError:return False
