"""SQLite FTS5 full-text search over archived transcripts.

Two index layers live here:

* ``SearchIndex`` — the original manifest-backed index (``search.db`` at the
  archive root).  Kept intact behind the ``search`` command's legacy manifest
  filters; a later cleanup plan retires it.
* ``TranscriptSearchIndex`` — the store-backed index this module's active
  search path uses.  The FTS table (``transcript_fts``) lives **inside
  ``archive.db``** and is created only by the ``search-index`` command, behind
  a gated FTS migration shim: after the normal schema contract check, the
  command runs ``CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts …`` plus a
  small bookkeeping table, and never bumps ``user_version`` — the virtual
  table's own existence is the state (no-migration rule: no ALTER, no
  user_version bump, no schema-transcripts.sql change).  Read paths never
  auto-create the table: a missing index is backlog-class (exit 0 with an
  explicit "index missing — run search-index" hint), store corruption is
  defect-class (exit 1).

Index schema — one row per time-bounded transcript block (a stored segment):

    CREATE VIRTUAL TABLE transcript_fts USING fts5(
        block_key, bvid, page_index, start_ms, end_ms, pubdate,
        text,        -- segment text, searchable
        bigram,      -- auxiliary CJK bigram column, searchable
        source,      -- which route served the text: 'store' | 'published-md'
        tokenize='unicode61'
    );

Tokenizer rationale: the corpus is overwhelmingly CJK (Chinese lecture
transcripts), so the whole-block text is tokenized with ``unicode61``, whose
case folding and punctuation rules fit the Latin fragments (bvid numbers,
borrowed terms) exactly as the pre-migration ``search.db`` index tokenized
them.  CJK has no whitespace, so any single-tokenizer scheme leaves Chinese
unsearchable; the ``bigram`` auxiliary column therefore also carries an
overlapping bigram stream of the same text, which makes arbitrary CJK
substrings matchable while keeping ranking and snippets anchored to ``text``.
At build time the available tokenizer set is probed and the declaration is
chosen accordingly: the ``trigram`` tokenizer (a pure bigram/substring engine
with its own built-in segmentation) when present, otherwise
``tokenize='simple'`` — the two are equivalent for matching because this
module queries the aux column only, never builds phrases across it, and the
active interpreter here ships ``trigram`` but not ``simple``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Sequence

from .archive import archive_stem, bundle_relpaths_for_stem
from .artifact_root import ArtifactRoots
from .manifest import JOURNAL_NAME, ManifestStore

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
    probe = "CREATE VIRTUAL TABLE _test_fts5 USING fts5(x);"
    close_when_done = False
    if conn is None:
        conn = sqlite3.connect(":memory:")
        close_when_done = True
    try:
        conn.execute(probe)
        conn.execute("DROP TABLE IF EXISTS _test_fts5")
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
        ("txt_path", bundle_relpaths_for_stem(stem)["txt_path"]),
        ("srt_path", bundle_relpaths_for_stem(stem)["srt_path"]),
        ("md_path", bundle_relpaths_for_stem(stem)["md_path"]),
        ("raw_path", bundle_relpaths_for_stem(stem)["raw_path"]),
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
        self.journal_path = os.path.join(self.root, "manifest", JOURNAL_NAME)

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
        """Check if search.db is missing, older than the manifest snapshot or its
        append journal, schema mismatch, or row mismatch."""
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

        # If manifest files exist, check mtime comparison.  The journal is a
        # live sidecar of the snapshot (ManifestStore.upsert appends there
        # without touching manifest.jsonl), so a journaled same-count change
        # must also invalidate the index.
        mtimes = [
            os.path.getmtime(path)
            for path in (self.manifest_path, self.journal_path)
            if os.path.isfile(path)
        ]
        if mtimes:
            try:
                db_mtime = os.path.getmtime(self.db_path)
                if max(mtimes) > db_mtime:
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
                bundle_relpaths_for_stem(stem)["txt_path"],
                bundle_relpaths_for_stem(stem)["srt_path"],
                bundle_relpaths_for_stem(stem)["md_path"],
                bundle_relpaths_for_stem(stem)["raw_path"],
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
    auto_build: bool | None = None,
) -> list[dict[str, object]]:
    """Search completed transcripts in the archive using SearchQuery filters.

    Returns list of sanitized dictionaries with bounded snippets and relative paths.
    ``artifact_roots`` is forwarded to the index, so the transcripts it reads may live
    under a configured root while ``search.db`` stays at the archive root (§10, D13).
    """
    if isinstance(query, str):
        query = SearchQuery(query=query)
    if auto_build is None:
        auto_build = True
    if auto_build is not None:
        query = SearchQuery(
            query=query.query,
            status=query.status,
            source=query.source,
            language=query.language,
            scope=query.scope,
            work_id=query.work_id,
            title=query.title,
            min_duration_s=query.min_duration_s,
            max_duration_s=query.max_duration_s,
            limit=query.limit,
            offset=query.offset,
            auto_build=auto_build,
            rebuild=query.rebuild,
        )
    index = SearchIndex(archive_root, artifact_roots=artifact_roots)
    results = index.search_query(query)
    return [r.to_dict() for r in results]


# ---------------------------------------------------------------------------
# Store-backed search layer (transcript store / archive.db)
# ---------------------------------------------------------------------------

STORE_FTS5_TABLE = "transcript_fts"
STORE_INDEX_META_TABLE = "transcript_fts_index_meta"

#: The store segment query is the index's only source of truth for text and
#: time ranges; ``videos.pubdate`` joins the date window.
_STORE_BLOCKS_SQL = (
    "SELECT t.transcript_id, t.video_part_id, vp.bvid, vp.page_index, "
    "vp.cid, vd.pubdate, vd.title AS video_title, vp.title AS part_title, "
    "ts.ordinal, ts.start_ms, ts.end_ms, ts.text "
    "FROM transcripts AS t "
    "JOIN video_parts AS vp ON vp.video_part_id = t.video_part_id "
    "JOIN videos AS vd ON vd.bvid = vp.bvid "
    "JOIN transcript_segments AS ts ON ts.transcript_id = t.transcript_id "
    "ORDER BY t.transcript_id, ts.ordinal"
)

INDEX_BUILD_BATCH_SIZE = 500

_SOURCE_STORE = "store"
_SOURCE_PUBLISHED_MD = "published-md"


def _cjk_bigram_stream(text: str) -> str:
    """Overlapping bigram stream of a text's non-space characters.

    The stream feeds the auxiliary FTS column that makes arbitrary CJK
    substrings matchable; whitespace and punctuation collapse out, so
    ``否定之否定`` becomes ``否定 定之 之否 否定``.
    """
    compact = "".join(ch for ch in text if not ch.isspace())
    return " ".join(
        compact[i : i + 2] for i in range(max(0, len(compact) - 1))
    )


#: Block-key namespaces keep the two id spaces apart: store segments are keyed
#: by (transcript_id, ordinal), published-md fallback rows by video_part_id.
#: A mixed-namespace MAX stamp silently skips store rows (QC F1, 2026-09-28).
_STORE_KEY_PREFIX = "t"
_MD_KEY_PREFIX = "m"


def _store_block_key(transcript_id: int, ordinal: int) -> str:
    return f"{_STORE_KEY_PREFIX}{transcript_id}:{ordinal}"


def _md_block_key(video_part_id: int) -> str:
    return f"{_MD_KEY_PREFIX}{video_part_id}:0"


def _published_md_bases(artifact_roots: ArtifactRoots) -> tuple[Path, ...]:
    """Bases that may hold published per-part markdown transcripts."""
    return artifact_roots.read_bases()


def _parse_published_md_text(path: str) -> str | None:
    """Read one published markdown transcript's text blocks.

    The published projection is not this plan's contract: the parse accepts
    the conventional shapes — fenced code blocks and ``HH:MM:SS``-headed
    sections — and a leading YAML front matter is skipped.  Anything else
    yields ``None`` so the row is simply not indexed from this source.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return None
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2]
    lines = content.splitlines()
    blocks: list[str] = []
    in_fence = False
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            current.append(stripped)
            continue
        if re.match(r"^\d{1,2}:\d{2}:\d{2}\b", stripped):
            if current:
                blocks.append(" ".join(current))
                current = []
            remainder = stripped[8:].strip()
            if remainder:
                current.append(remainder)
            continue
        if stripped:
            current.append(stripped)
    if current:
        blocks.append(" ".join(current))
    if not blocks:
        return None
    return "\n".join(blocks)


class SearchIndexMissingError(RuntimeError):
    """The store-backed FTS table does not exist (backlog class, never a defect)."""


class TranscriptStoreError(RuntimeError):
    """The transcript store is unreadable or corrupt (defect class)."""


@dataclass(frozen=True)
class TranscriptSearchHit:
    """One matched time-bounded transcript block."""

    block_key: str
    bvid: str
    page_index: int
    start_ms: int
    end_ms: int
    pubdate: int
    text: str
    source: str
    rank: float
    snippet: str
    video_title: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "block_key": self.block_key,
            "bvid": self.bvid,
            "page_index": self.page_index,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "pubdate": self.pubdate,
            "text": self.text,
            "source": self.source,
            "rank": self.rank,
            "snippet": self.snippet,
            "video_title": self.video_title,
        }


def _store_fts_ddl(tokenizer: str) -> str:
    return (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {STORE_FTS5_TABLE} USING fts5("
        "block_key UNINDEXED, bvid UNINDEXED, page_index UNINDEXED, "
        "start_ms UNINDEXED, end_ms UNINDEXED, pubdate UNINDEXED, "
        "text, bigram, source UNINDEXED, "
        f"tokenize='{tokenizer}'"
        ");"
    )


class TranscriptSearchIndex:
    """Store-backed FTS5 index over archived transcript blocks in ``archive.db``.

    The index table is created only through :meth:`build` (the ``search-index``
    command path) — never from the store's own ``open_database`` — per the
    no-migration rule: no ALTER, no ``user_version`` bump, and
    ``schema-transcripts.sql`` is untouched, so old stores keep their shape.
    Builds are incremental and idempotent: existing rows are left alone
    (re-running changes nothing) and only newly stored transcript segments are
    appended, one transaction per batch.
    """

    def __init__(
        self,
        root: str | os.PathLike[str] | Path,
        *,
        artifact_roots: ArtifactRoots | None = None,
    ) -> None:
        self.root = os.fspath(root)
        self.artifact_roots = (
            artifact_roots if artifact_roots is not None else ArtifactRoots.of(self.root)
        )
        self.db_path = os.path.join(self.root, "archive.db")

    # -- helpers -----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open the store; missing means backlog (the search-index path creates)."""
        if not os.path.isfile(self.db_path):
            raise SearchIndexMissingError(
                "transcript store missing — index missing; run `bili-asr search-index`"
            )
        try:
            return sqlite3.connect(self.db_path)
        except sqlite3.DatabaseError as exc:
            raise TranscriptStoreError(f"transcript store unreadable: {exc}") from exc

    def _connect_for_build(self) -> sqlite3.Connection:
        """Open the store for indexing, creating a fresh one when absent.

        Only the ``search-index`` path may reach here — read paths never
        auto-create the store or the index (exit-contract §1–§2: a missing
        index is backlog, not a defect).
        """
        os.makedirs(self.root, exist_ok=True)
        fresh = not os.path.exists(self.db_path)
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
        except sqlite3.DatabaseError as exc:
            raise TranscriptStoreError(f"transcript store unreadable: {exc}") from exc
        if fresh:
            # Bootstrap the contract schema, exactly as the store's own
            # ``open_database`` does — the search-index path may create a
            # store (an empty archive indexes to zero blocks) but never
            # ALTERs one.
            from .storage import open_database

            conn.close()
            conn = open_database(self.db_path)
            return conn
        if not self._looks_like_store(conn):
            raise TranscriptStoreError(
                f"transcript store corrupt: {self.db_path} is not a valid archive database"
            )
        return conn

    @staticmethod
    def _looks_like_store(conn: sqlite3.Connection) -> bool:
        """A store always carries the contract's user table after bootstrap."""
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'bilibili_users'"
            ).fetchone()
            return row is not None
        except sqlite3.DatabaseError:
            return False

    def _probe_tokenizer(self, conn: sqlite3.Connection) -> str:
        """Pick the auxiliary-column tokenizer this SQLite build supports.

        A failed probe leaves the connection inside an aborted transaction
        (SQLite auto-opens one for the failing DDL), so each attempt rolls
        back before the next.
        """
        for tokenizer in ("trigram", "simple", "unicode61"):
            try:
                if tokenizer == "unicode61":
                    # The default tokenizer (unicode61): present whenever FTS5 is.
                    conn.execute("CREATE VIRTUAL TABLE _fts_tok_probe USING fts5(x);")
                else:
                    conn.execute(
                        "CREATE VIRTUAL TABLE _fts_tok_probe "
                        f"USING fts5(x, tokenize='{tokenizer}');"
                    )
                conn.execute("DROP TABLE _fts_tok_probe;")
                return tokenizer
            except sqlite3.OperationalError:
                conn.rollback()
        raise FTS5UnavailableError(
            "SQLite FTS5 extension is not available in this Python environment"
        )

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """The gated FTS migration shim: run only from the search-index path."""
        if not check_fts5_available(conn):
            raise FTS5UnavailableError(
                "SQLite FTS5 extension is not available in this Python environment"
            )
        if self._has_index(conn):
            # Re-CREATE is a no-op and the stored tokenizer declaration stays
            # authoritative — a re-run must not fail because this build would
            # have picked a different tokenizer for a fresh table.
            pass
        else:
            tokenizer = self._probe_tokenizer(conn)
            conn.execute(_store_fts_ddl(tokenizer))
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {STORE_INDEX_META_TABLE} ("
            "key TEXT PRIMARY KEY, value TEXT"
            ");"
        )

    def _has_index(self, conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (STORE_FTS5_TABLE,),
        ).fetchone()
        return row is not None

    def stamp(self) -> int:
        """The last indexed segment's ``(transcript_id, ordinal)`` stamp, or -1."""
        conn = self._connect()
        try:
            if not self._has_index(conn):
                return -1
            row = conn.execute(
                f"SELECT MAX(CAST(substr(block_key, 2, instr(block_key, ':') - 2) AS INTEGER)) "
                f"AS m FROM {STORE_FTS5_TABLE} "
                f"WHERE substr(block_key, 1, 1) = ?",
                (_STORE_KEY_PREFIX,),
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else -1
        except sqlite3.DatabaseError as exc:
            raise TranscriptStoreError(f"transcript store corrupt: {exc}") from exc
        finally:
            conn.close()

    def count(self) -> int:
        """Number of indexed blocks, or 0 when no index exists."""
        conn = self._connect()
        try:
            if not self._has_index(conn):
                return 0
            row = conn.execute(f"SELECT COUNT(*) FROM {STORE_FTS5_TABLE}").fetchone()
            return int(row[0]) if row else 0
        except sqlite3.DatabaseError as exc:
            raise TranscriptStoreError(f"transcript store corrupt: {exc}") from exc
        finally:
            conn.close()

    def metadata(self) -> dict[str, str]:
        """Return build metadata without exposing the SQLite connection.

        A missing index is a normal pre-build state, so it returns an empty mapping;
        malformed store state remains a typed store error like :meth:`count`.
        """
        conn = self._connect()
        try:
            if not self._has_index(conn):
                return {}
            rows = conn.execute(
                f"SELECT key, value FROM {STORE_INDEX_META_TABLE} ORDER BY key"
            ).fetchall()
            return {str(row[0]): str(row[1]) for row in rows}
        except sqlite3.DatabaseError as exc:
            raise TranscriptStoreError(f"transcript store corrupt: {exc}") from exc
        finally:
            conn.close()

    # -- build -------------------------------------------------------------

    def _new_store_rows(self, conn: sqlite3.Connection, after_transcript_id: int) -> list[sqlite3.Row]:
        return list(
            conn.execute(
                _STORE_BLOCKS_SQL.replace(
                    "ORDER BY t.transcript_id, ts.ordinal",
                    "WHERE t.transcript_id > ? ORDER BY t.transcript_id, ts.ordinal",
                ),
                (after_transcript_id,),
            ).fetchall()
        )

    def _published_md_candidates(
        self, conn: sqlite3.Connection, exclude: set[int] | None = None
    ) -> list[sqlite3.Row]:
        """Parts the store holds but has no stored transcript for.

        These are the only candidates for the published-markdown fallback;
        parts already indexed (from the store or from markdown) carry a
        ``transcript_fts`` row keyed by their ``video_part_id`` and are
        excluded here, in SQL, so the caller never re-probes or re-reads
        their markdown on a rebuild.
        """
        params: list[object] = []
        stamped_clause = ""
        if exclude:
            stamped_clause = (
                "AND vp.video_part_id NOT IN ("
                + ",".join("?" for _ in exclude)
                + ") "
            )
            params.extend(sorted(exclude))
        return list(
            conn.execute(
                "SELECT vp.video_part_id, vp.bvid, vp.page_index, vp.duration_ms, "
                "vp.cid, vd.pubdate "
                "FROM video_parts AS vp JOIN videos AS vd ON vd.bvid = vp.bvid "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM transcripts AS t WHERE t.video_part_id = vp.video_part_id) "
                + stamped_clause
                + "ORDER BY vp.video_part_id",
                params,
            ).fetchall()
        )

    def _published_md_text_for(self, bvid: str, page_index: int) -> str | None:
        """Best-effort published-markdown text for one part, first hit wins."""
        stem = f"{bvid}.p{page_index}"
        for base in _published_md_bases(self.artifact_roots):
            for rel in (
                bundle_relpaths_for_stem(stem)["md_path"],
                os.path.join("published", "md", f"{stem}.md"),
                os.path.join("published", f"{stem}.md"),
            ):
                full = os.path.join(os.fspath(base), rel)
                if os.path.isfile(full):
                    return _parse_published_md_text(full)
        return None

    def build(self, force: bool = False) -> int:
        """Create the index when absent and index new transcript blocks.

        Idempotent: existing rows are never re-written, so re-running after a
        complete build appends nothing and changes nothing.  Incremental:
        only segments newer than the last indexed ``transcript_id`` are
        appended, one transaction per batch of
        :data:`INDEX_BUILD_BATCH_SIZE` rows.  ``force`` keeps the historical
        rebuild flag shape; the store layer's idempotent incremental build
        needs no special-casing to honour it, and a drop-and-rebuild is
        deliberately not offered under the no-migration rule.

        Returns the number of rows appended by this invocation.
        """
        conn = self._connect_for_build()
        try:
            self._ensure_schema(conn)
            after_id = -1 if force else self.stamp()

            pending: list[tuple[str, str, int, int, int, int, str, str, str]] = []
            indexed = 0

            def flush() -> None:
                nonlocal indexed
                if not pending:
                    return
                conn.executemany(
                    f"INSERT INTO {STORE_FTS5_TABLE}("
                    "block_key, bvid, page_index, start_ms, end_ms, pubdate, "
                    "text, bigram, source"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    pending,
                )
                conn.commit()
                indexed += len(pending)
                pending.clear()

            for row in self._new_store_rows(conn, after_id):
                text = _redact_text(str(row["text"]))
                pending.append(
                    (
                        _store_block_key(int(row["transcript_id"]), int(row["ordinal"])),
                        str(row["bvid"]),
                        int(row["page_index"]),
                        int(row["start_ms"]),
                        int(row["end_ms"]),
                        int(row["pubdate"]),
                        text,
                        _cjk_bigram_stream(text),
                        _SOURCE_STORE,
                    )
                )
                if len(pending) >= INDEX_BUILD_BATCH_SIZE:
                    flush()

            conn.commit()  # flush() may have left a partial batch uncommitted
            # Only md-sourced rows carry a video_part_id in the key
            # (``m<video_part_id>:0``); store rows are ``t<transcript_id>:<ordinal>``,
            # so the id is read from after the ``m`` prefix — reading from column 1
            # would harvest store transcript_ids and never the stamped part.
            stamped_part_ids = {
                int(r[0])
                for r in conn.execute(
                    f"SELECT DISTINCT CAST(substr(block_key, 2, instr(block_key, ':') - 2) "
                    f"AS INTEGER) FROM {STORE_FTS5_TABLE} "
                    f"WHERE substr(block_key, 1, 1) = ?",
                    (_MD_KEY_PREFIX,),
                )
            }
            for part in self._published_md_candidates(conn, stamped_part_ids):
                part_id = int(part["video_part_id"])
                text = self._published_md_text_for(
                    str(part["bvid"]), int(part["page_index"])
                )
                if not text:
                    continue
                text = _redact_text(text)
                pending.append(
                    (
                        _md_block_key(part_id),
                        str(part["bvid"]),
                        int(part["page_index"]),
                        0,
                        int(part["duration_ms"]),
                        int(part["pubdate"]),
                        text,
                        _cjk_bigram_stream(text),
                        _SOURCE_PUBLISHED_MD,
                    )
                )
                if len(pending) >= INDEX_BUILD_BATCH_SIZE:
                    flush()

            flush()
            total_indexed = int(
                conn.execute(f"SELECT COUNT(*) FROM {STORE_FTS5_TABLE}").fetchone()[0]
            )
            conn.execute(
                f"INSERT OR REPLACE INTO {STORE_INDEX_META_TABLE}(key, value) "
                "VALUES ('indexed_count', ?);",
                (str(total_indexed),),
            )
            conn.execute(
                f"INSERT OR REPLACE INTO {STORE_INDEX_META_TABLE}(key, value) "
                "VALUES ('built_at', ?);",
                (str(int(time.time())),),
            )
            conn.commit()
            return indexed
        except sqlite3.DatabaseError as exc:
            conn.rollback()
            raise TranscriptStoreError(f"transcript store corrupt: {exc}") from exc
        finally:
            conn.close()

    # -- query -------------------------------------------------------------

    def search_blocks(
        self,
        query: str,
        *,
        pubdate_from: int | None = None,
        pubdate_to: int | None = None,
        limit: int | None = 20,
    ) -> list[TranscriptSearchHit]:
        """Query the index for matching blocks, optionally date-windowed.

        Read-only against the store except the index table; never creates the
        index — a missing ``transcript_fts`` raises :class:`SearchIndexMissingError`
        (backlog class) and a corrupt store raises :class:`TranscriptStoreError`
        (defect class).
        """
        if limit is not None and limit <= 0:
            return []
        clean_q = (query or "").strip()
        if not clean_q:
            return []

        conn = self._connect()
        try:
            if not self._has_index(conn):
                raise SearchIndexMissingError(
                    "index missing — run `bili-asr search-index` to build it"
                )
            where = [f"{STORE_FTS5_TABLE} MATCH ?"]
            params: list[Any] = [clean_q]
            if pubdate_from is not None:
                where.append("pubdate >= ?")
                params.append(pubdate_from)
            if pubdate_to is not None:
                where.append("pubdate < ?")
                params.append(pubdate_to)
            sql = (
                f"SELECT block_key, bvid, page_index, start_ms, end_ms, pubdate, "
                f"text, source, rank FROM {STORE_FTS5_TABLE} "
                f"WHERE {' AND '.join(where)} ORDER BY rank ASC, block_key ASC"
            )
            if limit is not None:
                sql += " LIMIT ?"
                params.append(limit)
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # FTS5 query-syntax error (unclosed quote, bare NOT, …): the
                # plain-text intent is retried as one literal phrase.
                params[0] = '"' + clean_q.replace('"', '""') + '"'
                try:
                    rows = conn.execute(sql, params).fetchall()
                except sqlite3.OperationalError:
                    # Also a clean-empty exit: prove the store is readable
                    # before reporting no hits (an unusable FTS index must not
                    # mask a damaged `videos` table).
                    self._probe_videos_readable(conn)
                    rows = []
            if not rows:
                # Defect class must not depend on the match count: prove the
                # store is readable before reporting a clean empty result, the
                # way the (pre-batching) eager title read did.  A damaged
                # `videos` table still surfaces as TranscriptStoreError here.
                self._probe_videos_readable(conn)
                return []
            # Batch the per-hit reads: one query fetches the snippets for ALL
            # hit block_keys and one bounds the title scan to the hit bvids —
            # a constant query count, not one-per-hit (residual O-R3).  Both
            # helpers chunk their ``IN (...)`` lists (keys per batch) so the
            # list never approaches SQLite's variable ceiling (~250000 on the
            # 3.45.1 build here) and no single batch can degrade the rest.
            block_keys = [str(row[0]) for row in rows]
            bvids = sorted({str(row[1]) for row in rows})
            snippets = self._snippets_for_hits(conn, block_keys, clean_q)
            titles = self._titles_for_bvids(conn, bvids)
            hits: list[TranscriptSearchHit] = []
            for (
                block_key, bvid, page_index, start_ms, end_ms, pubdate,
                text, source, rank,
            ) in rows:
                hits.append(
                    TranscriptSearchHit(
                        block_key=str(block_key),
                        bvid=str(bvid),
                        page_index=int(page_index),
                        start_ms=int(start_ms),
                        end_ms=int(end_ms),
                        pubdate=int(pubdate),
                        text=str(text),
                        source=str(source),
                        rank=float(rank) if rank is not None else 0.0,
                        snippet=snippets.get(str(block_key), ""),
                        video_title=titles.get(str(bvid), ""),
                    )
                )
            return hits
        except sqlite3.DatabaseError as exc:
            raise TranscriptStoreError(f"transcript store corrupt: {exc}") from exc
        finally:
            conn.close()

    def _probe_videos_readable(self, conn: sqlite3.Connection) -> None:
        """Prove the ``videos`` table is readable, or raise the defect class.

        With no hits to decorate, the batched title read never runs — and a
        zero-hit query on a store whose ``videos`` table is missing/damaged
        would otherwise read as a clean empty result (exit 0) where the
        pre-batching code raised :class:`TranscriptStoreError` (exit 1).

        The probe must force the SAME decode the title path performs: a
        ``bvid``-only read is answered from the covering index (and ``LIMIT 1``
        stops on the first leaf page), so it survives exactly the damage this
        probe exists to catch.  Reading both columns without a LIMIT makes the
        whole table's column data get decoded, so a schema drift (``title``
        renamed/dropped) and page-level corruption both surface here.
        """

        conn.execute("SELECT bvid, title FROM videos").fetchall()

    # SQLite's bound-variable ceiling is ~250000 on the 3.45.1 build here; this
    # is a conservative chunk so a large result set never approaches it.
    _IN_CHUNK = 900

    @staticmethod
    def _chunked(items: Sequence[str]):
        """Yield ``items`` in bounded slices (keeps every IN (...) list small)."""

        for start in range(0, len(items), TranscriptSearchIndex._IN_CHUNK):
            yield items[start : start + TranscriptSearchIndex._IN_CHUNK]

    def _snippets_for_hits(
        self, conn: sqlite3.Connection, block_keys: Sequence[str], query: str
    ) -> dict[str, str]:
        """Snippets for ALL hit block_keys, in bounded batched queries (no N+1)."""
        if not block_keys:
            return {}
        snippets: dict[str, str] = {}
        for chunk in self._chunked(list(block_keys)):
            placeholders = ", ".join("?" for _ in chunk)
            try:
                rows = conn.execute(
                    f"SELECT block_key, snippet({STORE_FTS5_TABLE}, 6, '[', ']', '…', 12) "
                    f"FROM {STORE_FTS5_TABLE} WHERE {STORE_FTS5_TABLE} MATCH ? "
                    f"AND block_key IN ({placeholders})",
                    (query, *chunk),
                ).fetchall()
            except sqlite3.DatabaseError:
                # Snippets are presentation-only; a damaged snippet read degrades
                # this chunk rather than failing the search (pre-existing shape).
                continue
            snippets.update(
                {str(row[0]): _redact_text(str(row[1])) for row in rows if row[1]}
            )
        return snippets

    def _titles_for_bvids(
        self, conn: sqlite3.Connection, bvids: Sequence[str]
    ) -> dict[str, str]:
        """Titles for exactly the hit bvids (bounded scan, not the whole table).

        Deliberately does not swallow ``sqlite3.DatabaseError``: a corrupt
        ``videos`` read must propagate to ``search_blocks``'s handler and stay
        defect-class (exit 1), exactly as it was when this read sat inline.
        Chunked so a large hit set never approaches the variable ceiling.
        """

        if not bvids:
            return {}
        titles: dict[str, str] = {}
        for chunk in self._chunked(list(bvids)):
            placeholders = ", ".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT bvid, title FROM videos WHERE bvid IN ({placeholders})",
                tuple(chunk),
            ).fetchall()
            titles.update({str(row[0]): str(row[1]) for row in rows})
        return titles


