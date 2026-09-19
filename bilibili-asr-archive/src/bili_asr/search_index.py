"""SQLite FTS5 full-text search index for completed transcript archives."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Sequence

from .archive import archive_stem
from .artifact_root import ArtifactRoots
from .manifest import ManifestStore

FTS5_TABLE_NAME = "transcripts_fts"
INDEX_META_TABLE = "_index_meta"

# Only completed transcript statuses are indexable when transcript/archive paths exist
COMPLETED_STATUSES = frozenset({"archived", "subtitle_done"})

# Bounded search limits
DEFAULT_SEARCH_LIMIT = 100
MAX_SNIPPET_LENGTH = 150

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(?:https?://)[^\s\"\']+"),
    re.compile(
        r"(?i)(?:sessdata|access[_-]?token|authorization|cookie|token|signature|sign|deadline)"
        r"\s*(?:=|:)\s*[^\s,;]+"
    ),
)


def _redact_text(text: str) -> str:
    """Strip URLs and credential-like values from text/snippets."""
    redacted = text
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


class FTS5UnavailableError(RuntimeError):
    """Raised when SQLite FTS5 extension is not available in the current environment."""


def check_fts5_available(conn: sqlite3.Connection | None = None) -> bool:
    """Return True if SQLite in this environment supports FTS5."""
    close_when_done = False
    if conn is None:
        conn = sqlite3.connect(":memory:")
        close_when_done = True
    try:
        conn.execute("CREATE VIRTUAL TABLE _test_fts5 USING fts5(x);")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        if close_when_done:
            conn.close()


@dataclass(frozen=True)
class SearchQuery:
    """Structured search query with manifest filters and pagination bounds."""

    query: str = ""
    status: str | Sequence[str] | set[str] | None = None
    source: str | Sequence[str] | set[str] | None = None
    language: str | Sequence[str] | set[str] | None = None
    scope: str | None = None
    work_id: str | Sequence[str] | set[str] | None = None
    title: str | None = None
    min_duration_s: float | int | None = None
    max_duration_s: float | int | None = None
    limit: int | None = None
    offset: int = 0
    auto_build: bool = True
    rebuild: bool = False


@dataclass
class SearchResult:
    """A single matched transcript search hit."""

    work_id: str
    title: str
    status: str
    score: float
    path: str
    duration_s: float | int = 0
    transcript_snippet: str = ""
    archive_paths: dict[str, str] = field(default_factory=dict)
    source: str = ""
    language: str = ""
    pubdate: int | None = None
    bvid: str = ""
    page_index: int | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a sanitized dictionary representation of the search hit."""
        bvid_val = self.bvid
        if not bvid_val and ":" in self.work_id:
            bvid_val = self.work_id.split(":")[0]
        elif not bvid_val:
            bvid_val = self.work_id

        return {
            "work_id": self.work_id,
            "bvid": bvid_val,
            "page_index": self.page_index,
            "title": self.title,
            "status": self.status,
            "score": self.score,
            "path": self.path,
            "duration_s": self.duration_s,
            "source": self.source,
            "language": self.language,
            "pubdate": self.pubdate,
            "transcript_snippet": self.transcript_snippet,
            "archive_paths": dict(self.archive_paths),
        }


def _safe_contained_relpath(root: str, path_str: str) -> str | None:
    """Return a relative path within root, or None if path escapes root."""
    try:
        full = path_str if os.path.isabs(path_str) else os.path.join(root, path_str)
        real_full = os.path.realpath(full)
        real_root = os.path.realpath(root)
        if os.path.commonpath([real_full, real_root]) == real_root:
            return os.path.relpath(real_full, real_root)
    except Exception:
        pass
    return None


def _locate_over_bases(
    bases: tuple[Path, ...], value: str
) -> tuple[str, str] | None:
    """The first base that contains ``value``, with the value made relative to it.

    The containment guard stays per base and unchanged (contract §5/§6); only the
    base list is shared, so a legacy value that resolves under the archive root is
    still described relative to it.
    """
    for base in bases:
        base_str = os.fspath(base)
        relative = _safe_contained_relpath(base_str, value)
        if relative:
            return base_str, relative
    return None


def _existing_path(bases: tuple[Path, ...], relative: str) -> str | None:
    """The first base that actually holds ``relative``, or ``None``.

    Containment is lexical and answers for a base that does not exist, so the base a
    file is *read* from is decided by existence — the same "first hit over the ordered
    bases" rule the bundle and audio probes use (contract §5, D8).
    """
    for base in bases:
        full = os.path.join(os.fspath(base), relative)
        if os.path.isfile(full):
            return full
    return None


def extract_transcript_text(
    root: str | os.PathLike[str],
    entry: dict[str, Any],
    *,
    artifact_roots: ArtifactRoots | None = None,
) -> tuple[str, dict[str, str]]:
    """Load transcript text and gather archive paths for an entry.

    ``artifact_roots`` carries the bases the transcripts live under (contract
    §5/§10, D8): every declared value and every on-disk probe walks ``read_bases()``
    in order, while the returned mapping keeps its shape — relative path strings.
    Each located file is read from the base that actually holds it, so a legacy
    transcript at the archive root is still read there instead of being shadowed by
    the configured base that merely contains its name.
    """
    roots = artifact_roots if artifact_roots is not None else ArtifactRoots.of(root)
    bases = roots.read_bases()
    root_str = os.fspath(root)
    try:
        stem = archive_stem(entry)
    except Exception:
        stem = str(entry.get("bvid") or "")

    paths: dict[str, str] = {}
    located: dict[str, str] = {}
    # Collect paths from entry metadata with containment validation
    for k in ("srt_path", "txt_path", "md_path", "raw_path"):
        raw_val = entry.get(k)
        if raw_val:
            found = _locate_over_bases(bases, str(raw_val))
            if found:
                base_str, rel = found
                paths[k] = rel
                located[k] = _existing_path(bases, rel) or os.path.join(base_str, rel)

    # If not in entry metadata, probe standard disk locations
    for k, rel in (
        ("txt_path", os.path.join("transcripts", "txt", f"{stem}.txt")),
        ("srt_path", os.path.join("transcripts", "srt", f"{stem}.srt")),
        ("md_path", os.path.join("transcripts", "md", f"{stem}.md")),
        ("raw_path", os.path.join("transcripts", "raw", f"{stem}.json")),
    ):
        if k in paths:
            continue
        full = _existing_path(bases, rel)
        if full is not None:
            paths[k] = rel
            located[k] = full

    # Load text content
    text = ""
    # 1. Try txt_path
    txt_path = paths.get("txt_path")
    if txt_path:
        full_txt = located.get("txt_path", os.path.join(root_str, txt_path))
        if os.path.isfile(full_txt):
            try:
                with open(full_txt, "r", encoding="utf-8") as fh:
                    text = fh.read().strip()
            except OSError:
                pass

    # 2. If no text, try srt_path
    if not text and "srt_path" in paths:
        srt_path = paths["srt_path"]
        full_srt = located.get("srt_path", os.path.join(root_str, srt_path))
        if os.path.isfile(full_srt):
            try:
                with open(full_srt, "r", encoding="utf-8") as fh:
                    srt_lines = []
                    for line in fh:
                        line = line.strip()
                        if not line or line.isdigit() or "-->" in line:
                            continue
                        srt_lines.append(line)
                    text = " ".join(srt_lines)
            except OSError:
                pass

    # 3. If no text, try raw_path or subtitles/raw
    if not text:
        raw_candidates = []
        if "raw_path" in paths:
            raw_candidates.append(located.get("raw_path", os.path.join(root_str, paths["raw_path"])))
        raw_candidates.extend(
            os.path.join(os.fspath(base), "subtitles", "raw", f"{stem}.json")
            for base in bases
        )
        for raw_cand in raw_candidates:
            if os.path.isfile(raw_cand):
                try:
                    with open(raw_cand, "r", encoding="utf-8") as fh:
                        doc = json.load(fh)
                    if isinstance(doc, dict):
                        if "body" in doc and isinstance(doc["body"], list):
                            text = " ".join(
                                str(item.get("content", ""))
                                for item in doc["body"]
                                if item.get("content")
                            )
                        elif "segments" in doc and isinstance(doc["segments"], list):
                            text = " ".join(
                                str(item.get("text", ""))
                                for item in doc["segments"]
                                if item.get("text")
                            )
                    if text:
                        break
                except (OSError, json.JSONDecodeError):
                    pass

    # 4. If no text, try md_path
    if not text and "md_path" in paths:
        md_path = paths["md_path"]
        full_md = located.get("md_path", os.path.join(root_str, md_path))
        if os.path.isfile(full_md):
            try:
                with open(full_md, "r", encoding="utf-8") as fh:
                    md_content = fh.read().strip()
                if md_content.startswith("---"):
                    parts = md_content.split("---", 2)
                    if len(parts) >= 3:
                        md_content = parts[2].strip()
                text = md_content
            except OSError:
                pass

    return _redact_text(text), paths


def _create_snippet(text: str, query: str = "") -> str:
    """Produce a bounded snippet around the matching keyword or start of text."""
    if not text:
        return ""
    clean_text = " ".join(text.split())
    clean_q = (query or "").strip()
    if not clean_q:
        snippet = clean_text[:MAX_SNIPPET_LENGTH]
        return _redact_text(snippet)

    # Try finding terms from query in text
    terms = [t for t in re.split(r"\s+", clean_q) if len(t) > 1 and not t.startswith(("-", "+", "*"))]
    match_pos = -1
    for term in (terms or [clean_q]):
        idx = clean_text.lower().find(term.lower())
        if idx >= 0:
            match_pos = idx
            break

    if match_pos < 0:
        snippet = clean_text[:MAX_SNIPPET_LENGTH]
    else:
        start = max(0, match_pos - 30)
        end = min(len(clean_text), match_pos + 90)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(clean_text) else ""
        snippet = prefix + clean_text[start:end] + suffix

    return _redact_text(snippet[:MAX_SNIPPET_LENGTH])


def _parse_filter_set(val: Any) -> set[str] | None:
    """Parse a filter argument into a set of non-empty string values."""
    if val is None:
        return None
    if isinstance(val, str):
        tokens = [s.strip() for s in val.split(",") if s.strip()]
        return set(tokens) if tokens else None
    if isinstance(val, (set, frozenset, list, tuple)):
        items: set[str] = set()
        for item in val:
            if isinstance(item, str):
                for s in item.split(","):
                    s = s.strip()
                    if s:
                        items.add(s)
        return items if items else None
    return None


def _parse_scope_clause(
    scope: str,
    root: str,
) -> tuple[str, list[Any]]:
    """Translate scope selector to SQL clause and parameters."""
    scope_str = scope.strip()
    if not scope_str:
        return "", []
    if scope_str == "pending":
        # Pending means non-terminal rows (none of which are indexed)
        return "status NOT IN ('archived', 'gone')", []
    if scope_str == "failed":
        # Load failed work_ids from attempts ledger
        attempts_path = os.path.join(root, "coordinator", "attempts.jsonl")
        failed_ids: set[str] = set()
        if os.path.isfile(attempts_path):
            try:
                with open(attempts_path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        rec = json.loads(line)
                        if rec.get("outcome") == "failed" and rec.get("work_id"):
                            failed_ids.add(str(rec["work_id"]))
            except Exception:
                pass
        if not failed_ids:
            return "1 = 0", []
        placeholders = ", ".join("?" for _ in failed_ids)
        return f"work_id IN ({placeholders})", sorted(failed_ids)

    tokens = [t.strip() for t in re.split(r"[,\s]+", scope_str) if t.strip()]
    if not tokens:
        return "", []
    w_placeholders = ", ".join("?" for _ in tokens)
    b_placeholders = ", ".join("?" for _ in tokens)
    return (
        f"(work_id IN ({w_placeholders}) OR bvid IN ({b_placeholders}))",
        sorted(tokens) + sorted(tokens),
    )


class SearchIndex:
    """Manages {archive_root}/search.db FTS5 virtual table for transcript search."""

    def __init__(
        self,
        root: str | os.PathLike[str] | Path,
        *,
        artifact_roots: ArtifactRoots | None = None,
    ) -> None:
        """``root`` is the archive root: the index file and the manifest stay there.

        ``artifact_roots`` adds the base the transcript products may live under
        (contract §10, D8): the on-disk probes walk ``read_bases()`` in order, while
        ``search.db`` never leaves the archive root — it is state (D13).
        """
        self.root = os.fspath(root)
        self.artifact_roots = (
            artifact_roots if artifact_roots is not None else ArtifactRoots.of(self.root)
        )
        self.db_path = os.path.join(self.root, "search.db")
        self.manifest_path = os.path.join(self.root, "manifest", "manifest.jsonl")

    def count(self) -> int:
        """Return the number of indexed rows in search.db, or 0 if uninitialized."""
        if not os.path.isfile(self.db_path):
            return 0
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {FTS5_TABLE_NAME}")
                row = cur.fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            return 0

    def is_stale(
        self,
        manifest_entries: dict[str, dict[str, Any]] | ManifestStore | None = None,
    ) -> bool:
        """Check if search.db is missing, older than manifest.jsonl, schema mismatch, or row mismatch."""
        if not os.path.isfile(self.db_path):
            return True

        # Check schema compatibility first
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.execute(f"PRAGMA table_info({FTS5_TABLE_NAME})")
                cols = {row[1] for row in cur.fetchall()}
                expected = {
                    "work_id",
                    "title",
                    "status",
                    "transcript_text",
                    "archive_paths",
                    "duration_s",
                    "source",
                    "language",
                    "pubdate",
                }
                if not expected.issubset(cols):
                    return True
            finally:
                conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            return True

        # If manifest file exists, check mtime comparison
        if os.path.isfile(self.manifest_path):
            try:
                manifest_mtime = os.path.getmtime(self.manifest_path)
                db_mtime = os.path.getmtime(self.db_path)
                if manifest_mtime > db_mtime:
                    return True
            except OSError:
                return True

        if manifest_entries is None:
            store = ManifestStore(self.root)
            entries = store.load()
        elif isinstance(manifest_entries, ManifestStore):
            entries = manifest_entries.load()
        else:
            entries = manifest_entries

        # Check completed transcript count vs indexed count
        completed_count = sum(1 for e in entries.values() if self._is_indexable(e))
        indexed_count = self.count()
        if completed_count != indexed_count:
            return True

        return False

    def _is_indexable(self, entry: dict[str, Any]) -> bool:
        """Check if entry is a completed transcript row with paths present."""
        status = entry.get("status")
        if status not in COMPLETED_STATUSES:
            return False

        # Must have transcript / archive paths present in metadata or on disk
        has_meta_paths = bool(
            entry.get("srt_path")
            or entry.get("txt_path")
            or entry.get("md_path")
            or entry.get("raw_path")
        )
        if has_meta_paths:
            return True

        # Check on-disk artifacts
        try:
            stem = archive_stem(entry)
        except Exception:
            stem = str(entry.get("bvid") or "")
        if not stem:
            return False

        candidate_files = tuple(
            os.path.join(os.fspath(base), relative)
            for base in self.artifact_roots.read_bases()
            for relative in (
                os.path.join("transcripts", "txt", f"{stem}.txt"),
                os.path.join("transcripts", "srt", f"{stem}.srt"),
                os.path.join("transcripts", "md", f"{stem}.md"),
                os.path.join("transcripts", "raw", f"{stem}.json"),
                os.path.join("subtitles", "raw", f"{stem}.json"),
            )
        )
        return any(os.path.isfile(p) for p in candidate_files)

    def _extract_transcript_text(self, entry: dict[str, Any]) -> tuple[str, dict[str, str]]:
        """Load transcript text and gather archive paths for an entry."""
        return extract_transcript_text(
            self.root, entry, artifact_roots=self.artifact_roots
        )

    def build(
        self,
        manifest: dict[str, dict[str, Any]] | ManifestStore | None = None,
        force: bool = False,
    ) -> int:
        """Build or rebuild search.db from the manifest.

        Indexes only completed transcript rows (archived or subtitle_done with
        transcript/archive paths present).
        Returns the number of indexed rows.
        """
        del force  # build always produces a fresh index atomically
        if manifest is None:
            store = ManifestStore(self.root)
            entries = store.load()
        elif isinstance(manifest, ManifestStore):
            entries = manifest.load()
        else:
            entries = manifest

        os.makedirs(self.root, exist_ok=True)
        tmp_db = self.db_path + ".tmp"
        if os.path.exists(tmp_db):
            try:
                os.remove(tmp_db)
            except OSError:
                pass

        conn = sqlite3.connect(tmp_db)
        try:
            try:
                conn.execute(
                    f"CREATE VIRTUAL TABLE {FTS5_TABLE_NAME} USING fts5("
                    "work_id, title, status, transcript_text, archive_paths, duration_s, "
                    "source, language, pubdate, bvid, page_index"
                    ");"
                )
            except sqlite3.OperationalError as exc:
                if "no such module: fts5" in str(exc).lower():
                    raise FTS5UnavailableError(
                        "SQLite FTS5 extension is not available in this Python environment"
                    ) from exc
                raise

            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {INDEX_META_TABLE} ("
                "key TEXT PRIMARY KEY, value TEXT"
                ");"
            )

            count = 0
            for entry in entries.values():
                if not self._is_indexable(entry):
                    continue

                work_id = str(entry.get("work_id") or entry.get("bvid") or "")
                if not work_id:
                    continue

                title = str(entry.get("title") or "")
                status = str(entry.get("status") or "")
                duration_s = entry.get("duration_s") or 0
                source = str(entry.get("source") or "")
                language = str(entry.get("sub_lan") or entry.get("lan") or entry.get("language") or "")
                pubdate = entry.get("pubdate")
                pubdate_val = (
                    int(pubdate)
                    if isinstance(pubdate, (int, float)) or (isinstance(pubdate, str) and str(pubdate).isdigit())
                    else None
                )
                bvid = str(entry.get("bvid") or "")
                page_idx = entry.get("page_index")
                page_idx_val = int(page_idx) if page_idx is not None and str(page_idx).isdigit() else None

                transcript_text, paths_dict = self._extract_transcript_text(entry)
                archive_paths_json = json.dumps(paths_dict, ensure_ascii=False)

                conn.execute(
                    f"INSERT INTO {FTS5_TABLE_NAME}("
                    "work_id, title, status, transcript_text, archive_paths, duration_s, "
                    "source, language, pubdate, bvid, page_index"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    (
                        work_id,
                        title,
                        status,
                        transcript_text,
                        archive_paths_json,
                        duration_s,
                        source,
                        language,
                        pubdate_val,
                        bvid,
                        page_idx_val,
                    ),
                )
                count += 1

            manifest_mtime = (
                str(os.path.getmtime(self.manifest_path))
                if os.path.isfile(self.manifest_path)
                else ""
            )
            conn.execute(
                f"INSERT OR REPLACE INTO {INDEX_META_TABLE}(key, value) "
                "VALUES ('manifest_mtime', ?);",
                (manifest_mtime,),
            )
            conn.execute(
                f"INSERT OR REPLACE INTO {INDEX_META_TABLE}(key, value) "
                "VALUES ('indexed_count', ?);",
                (str(count),),
            )
            conn.commit()
        finally:
            conn.close()

        os.replace(tmp_db, self.db_path)
        return count

    def search_query(self, query: SearchQuery) -> list[SearchResult]:
        """Execute a structured SearchQuery against the search index."""
        if query.limit is not None and query.limit <= 0:
            return []
        if query.offset < 0:
            return []

        clean_q = (query.query or "").strip()
        has_filter = any(
            x is not None
            for x in (
                query.status,
                query.source,
                query.language,
                query.scope,
                query.work_id,
                query.title,
                query.min_duration_s,
                query.max_duration_s,
            )
        )
        if not clean_q and not has_filter:
            return []

        if query.rebuild:
            self.build(force=True)
        elif not os.path.isfile(self.db_path):
            if query.auto_build:
                self.build()
            else:
                return []
        elif query.auto_build and self.is_stale():
            self.build()

        if not os.path.isfile(self.db_path):
            return []

        return self._execute_query(query)

    def _execute_query(self, query: SearchQuery) -> list[SearchResult]:
        conn = sqlite3.connect(self.db_path)
        try:
            where_clauses: list[str] = []
            params: list[Any] = []

            clean_q = (query.query or "").strip()
            has_match = bool(clean_q)
            if has_match:
                where_clauses.append(f"{FTS5_TABLE_NAME} MATCH ?")
                params.append(clean_q)

            # Status filter
            status_set = _parse_filter_set(query.status)
            if status_set is not None:
                placeholders = ", ".join("?" for _ in status_set)
                where_clauses.append(f"status IN ({placeholders})")
                params.extend(sorted(status_set))

            # Source filter
            source_set = _parse_filter_set(query.source)
            if source_set is not None:
                placeholders = ", ".join("?" for _ in source_set)
                where_clauses.append(f"source IN ({placeholders})")
                params.extend(sorted(source_set))

            # Language filter
            lang_set = _parse_filter_set(query.language)
            if lang_set is not None:
                placeholders = ", ".join("?" for _ in lang_set)
                where_clauses.append(f"language IN ({placeholders})")
                params.extend(sorted(lang_set))

            # Work_id filter (matches work_id OR bvid)
            work_id_set = _parse_filter_set(query.work_id)
            if work_id_set is not None:
                w_placeholders = ", ".join("?" for _ in work_id_set)
                b_placeholders = ", ".join("?" for _ in work_id_set)
                where_clauses.append(f"(work_id IN ({w_placeholders}) OR bvid IN ({b_placeholders}))")
                params.extend(sorted(work_id_set))
                params.extend(sorted(work_id_set))

            # Scope filter
            if query.scope:
                clause, scope_params = _parse_scope_clause(query.scope, self.root)
                if clause:
                    where_clauses.append(clause)
                    params.extend(scope_params)

            # Title filter
            if query.title:
                where_clauses.append("title LIKE ?")
                params.append(f"%{query.title.strip()}%")

            # Duration filters
            if query.min_duration_s is not None:
                where_clauses.append("duration_s >= ?")
                params.append(query.min_duration_s)
            if query.max_duration_s is not None:
                where_clauses.append("duration_s <= ?")
                params.append(query.max_duration_s)

            sql = (
                f"SELECT work_id, title, status, archive_paths, duration_s, "
                f"transcript_text, source, language, pubdate, bvid, page_index, rank "
                f"FROM {FTS5_TABLE_NAME} "
            )
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)

            if has_match:
                sql += " ORDER BY rank ASC, work_id ASC"
            else:
                sql += " ORDER BY work_id ASC"

            # Pagination
            if query.limit is not None:
                sql += " LIMIT ?"
                params.append(query.limit)
                if query.offset > 0:
                    sql += " OFFSET ?"
                    params.append(query.offset)
            elif query.offset > 0:
                sql += " LIMIT -1 OFFSET ?"
                params.append(query.offset)

            try:
                cur = conn.execute(sql, params)
                rows = cur.fetchall()
            except sqlite3.OperationalError as exc:
                if "no such module: fts5" in str(exc).lower():
                    raise FTS5UnavailableError(
                        "SQLite FTS5 extension is not available in this Python environment"
                    ) from exc
                # Syntax error fallback: wrap in double quotes for plain phrase search
                if has_match:
                    escaped_query = '"' + clean_q.replace('"', '""') + '"'
                    params[0] = escaped_query
                    try:
                        cur = conn.execute(sql, params)
                        rows = cur.fetchall()
                    except sqlite3.OperationalError:
                        return []
                else:
                    return []

            results: list[SearchResult] = []
            for row in rows:
                (
                    work_id,
                    title,
                    status,
                    archive_paths_raw,
                    duration_s,
                    transcript_text,
                    source,
                    language,
                    pubdate,
                    bvid,
                    page_index,
                    rank_score,
                ) = row
                paths_dict: dict[str, str] = {}
                primary_path = ""
                if archive_paths_raw:
                    try:
                        paths_dict = json.loads(archive_paths_raw)
                        if isinstance(paths_dict, dict):
                            primary_path = (
                                paths_dict.get("txt_path")
                                or paths_dict.get("srt_path")
                                or paths_dict.get("md_path")
                                or paths_dict.get("raw_path")
                                or ""
                            )
                    except (json.JSONDecodeError, TypeError):
                        primary_path = str(archive_paths_raw)

                score_val = float(rank_score) if rank_score is not None else 0.0
                snippet = _create_snippet(transcript_text or "", clean_q)

                results.append(
                    SearchResult(
                        work_id=str(work_id),
                        title=str(title),
                        status=str(status),
                        score=score_val,
                        path=primary_path,
                        duration_s=duration_s or 0,
                        transcript_snippet=snippet,
                        archive_paths=paths_dict,
                        source=str(source or ""),
                        language=str(language or ""),
                        pubdate=pubdate if isinstance(pubdate, int) else None,
                        bvid=str(bvid or ""),
                        page_index=page_index if isinstance(page_index, int) else None,
                    )
                )
            return results
        finally:
            conn.close()

    def search(
        self,
        query: str | SearchQuery,
        limit: int | None = None,
        auto_build: bool = True,
    ) -> list[SearchResult]:
        """Query the FTS5 index for matching transcripts with ranking."""
        if isinstance(query, SearchQuery):
            q = query
            if limit is not None:
                q = SearchQuery(
                    query=q.query,
                    status=q.status,
                    source=q.source,
                    language=q.language,
                    scope=q.scope,
                    work_id=q.work_id,
                    title=q.title,
                    min_duration_s=q.min_duration_s,
                    max_duration_s=q.max_duration_s,
                    limit=limit,
                    offset=q.offset,
                    auto_build=auto_build,
                    rebuild=q.rebuild,
                )
            return self.search_query(q)

        sq = SearchQuery(
            query=query,
            limit=limit,
            auto_build=auto_build,
        )
        return self.search_query(sq)


def search(
    archive_root: str | os.PathLike[str] | Path,
    query: SearchQuery | str,
    *,
    artifact_roots: ArtifactRoots | None = None,
) -> list[dict[str, object]]:
    """Search completed transcripts in the archive using SearchQuery filters.

    Returns list of sanitized dictionaries with bounded snippets and relative paths.
    ``artifact_roots`` is forwarded to the index, so the transcripts it reads may live
    under a configured root while ``search.db`` stays at the archive root (§10, D13).
    """
    if isinstance(query, str):
        query = SearchQuery(query=query)
    index = SearchIndex(archive_root, artifact_roots=artifact_roots)
    results = index.search_query(query)
    return [r.to_dict() for r in results]
