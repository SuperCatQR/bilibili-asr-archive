"""Deterministic, read-only archive integrity verification."""
from __future__ import annotations
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any
from .archive import archive_stem, _safe_name
from .page_identity import artifact_stem, page_identity, parse_work_id
from .quality import QualityAnalyzer
from .coordinator import _validate_attempt

MISSING_RAW_SUBTITLE = "missing_raw_subtitle"
MISSING_TRANSCRIPT = "missing_transcript"
MALFORMED_ARTIFACT = "malformed_artifact"
IDENTITY_PATH_MISMATCH = "identity_path_mismatch"
TRUNCATED_ATTEMPTS_LINE = "truncated_attempts_line"
RETRYABLE_INCOMPLETE = "retryable_incomplete"
STRUCTURAL_INPUT_ERROR = "structural_input_error"
MANIFEST_ROW_LIMIT_EXCEEDED = "manifest_row_limit_exceeded"
_MAX_ROWS = 10000

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
        entries, manifest_valid = self._read_manifest(root, report)
        attempts, attempts_valid, truncated = self._read_attempts(root, report)
        report.authoritative = manifest_valid and attempts_valid
        selected = self._select(entries, scope, attempts if attempts_valid else []) if report.authoritative else []
        report.checked = len(selected)
        analyzer = QualityAnalyzer()
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
            present = [p for p in required if self._safe_path(p, root) and p.is_file()]
            if status in {"archived", "asr_done", "subtitle_done"} and len(present) < len(required): defects.add(MISSING_TRANSCRIPT)
            raw = root / "subtitles" / "raw" / f"{self._canonical_stem(row)}.json"
            if status == "subtitle_done" and not self._safe_path(raw, root): defects.add(IDENTITY_PATH_MISMATCH)
            elif status == "subtitle_done" and not raw.is_file(): defects.add(MISSING_RAW_SUBTITLE)
            quality = analyzer.analyze(row, root)
            if "malformed" in quality.reasons:
                defects.add(MALFORMED_ARTIFACT)
            if "identity_mismatch" in quality.reasons: defects.add(IDENTITY_PATH_MISMATCH)
            if status in {"pending", "meta_ok", "sub_checked", "needs_audio", "audio_ok"}: defects.add(RETRYABLE_INCOMPLETE)
            report.defects.extend(IntegrityDefect(work_id, code) for code in sorted(defects))
        if truncated: report.diagnostics.append(TRUNCATED_ATTEMPTS_LINE)
        report.defects.sort(key=lambda d: (d.work_id, d.code)); return report

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
                for field_name in ("work_id", "bvid", "status", "srt_path", "txt_path", "md_path"):
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
        path=root/"coordinator"/"attempts.jsonl"
        if not path.is_file(): return [], True, False
        records=[]; truncated=False; valid=True
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
            return [], False, False
        last_non_empty = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
        for index, line in enumerate(lines):
            if not line.strip(): continue
            try:
                value=json.loads(line)
            except json.JSONDecodeError:
                if index == last_non_empty:
                    truncated=True
                else:
                    valid=False; report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
                continue
            try:
                record=_validate_attempt(value)
            except (TypeError,ValueError):
                valid=False; report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
                continue
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
    def _safe_path(path,root):
        try: path.resolve().relative_to(root); return True
        except ValueError:return False
