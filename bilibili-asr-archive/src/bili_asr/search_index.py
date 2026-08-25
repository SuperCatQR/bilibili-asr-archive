"""SQLite FTS5 full-text search index for completed transcript archives."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import sqlite3
from typing import Any

from .archive import archive_stem
from .manifest import ManifestStore

FTS5_TABLE_NAME = "transcripts_fts"
INDEX_META_TABLE = "_index_meta"

# Only completed transcript statuses are indexable when transcript/archive paths exist
COMPLETED_STATUSES = frozenset({"archived", "subtitle_done"})


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


def extract_transcript_text(
    root: str | os.PathLike[str],
    entry: dict[str, Any],
) -> tuple[str, dict[str, str]]:
    """Load transcript text and gather archive paths for an entry."""
    root_str = os.fspath(root)
    try:
        stem = archive_stem(entry)
    except Exception:
        stem = str(entry.get("bvid") or "")

    paths: dict[str, str] = {}
    # Collect paths from entry metadata
    for k in ("srt_path", "txt_path", "md_path", "raw_path"):
        if entry.get(k):
            paths[k] = str(entry[k])

    # If not in entry metadata, probe standard disk locations
    if "txt_path" not in paths:
        rel = os.path.join("transcripts", "txt", f"{stem}.txt")
        if os.path.isfile(os.path.join(root_str, rel)):
            paths["txt_path"] = rel
    if "srt_path" not in paths:
        rel = os.path.join("transcripts", "srt", f"{stem}.srt")
        if os.path.isfile(os.path.join(root_str, rel)):
            paths["srt_path"] = rel
    if "md_path" not in paths:
        rel = os.path.join("transcripts", "md", f"{stem}.md")
        if os.path.isfile(os.path.join(root_str, rel)):
            paths["md_path"] = rel
    if "raw_path" not in paths:
        rel = os.path.join("transcripts", "raw", f"{stem}.json")
        if os.path.isfile(os.path.join(root_str, rel)):
            paths["raw_path"] = rel

    # Load text content
    text = ""
    # 1. Try txt_path
    txt_path = paths.get("txt_path")
    if txt_path:
        full_txt = (
            txt_path if os.path.isabs(txt_path) else os.path.join(root_str, txt_path)
        )
        if os.path.isfile(full_txt):
            try:
                with open(full_txt, "r", encoding="utf-8") as fh:
                    text = fh.read().strip()
            except OSError:
                pass

    # 2. If no text, try srt_path
    if not text and "srt_path" in paths:
        srt_path = paths["srt_path"]
        full_srt = (
            srt_path if os.path.isabs(srt_path) else os.path.join(root_str, srt_path)
        )
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
            raw_candidates.append(
                paths["raw_path"] if os.path.isabs(paths["raw_path"])
                else os.path.join(root_str, paths["raw_path"])
            )
        raw_candidates.append(
            os.path.join(root_str, "subtitles", "raw", f"{stem}.json")
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

    return text, paths


class SearchIndex:
    """Manages {archive_root}/search.db FTS5 virtual table for transcript search."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = os.fspath(root)
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
        """Check if search.db is missing, older than manifest.jsonl, or has row count mismatch."""
        if not os.path.isfile(self.db_path):
            return True

        # If manifest file exists, check mtime comparison first
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

        candidate_files = (
            os.path.join(self.root, "transcripts", "txt", f"{stem}.txt"),
            os.path.join(self.root, "transcripts", "srt", f"{stem}.srt"),
            os.path.join(self.root, "transcripts", "md", f"{stem}.md"),
            os.path.join(self.root, "transcripts", "raw", f"{stem}.json"),
            os.path.join(self.root, "subtitles", "raw", f"{stem}.json"),
        )
        return any(os.path.isfile(p) for p in candidate_files)

    def _extract_transcript_text(self, entry: dict[str, Any]) -> tuple[str, dict[str, str]]:
        """Load transcript text and gather archive paths for an entry."""
        return extract_transcript_text(self.root, entry)

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
                    "work_id, title, status, transcript_text, archive_paths, duration_s"
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
                transcript_text, paths_dict = self._extract_transcript_text(entry)
                archive_paths_json = json.dumps(paths_dict, ensure_ascii=False)

                conn.execute(
                    f"INSERT INTO {FTS5_TABLE_NAME}("
                    "work_id, title, status, transcript_text, archive_paths, duration_s"
                    ") VALUES (?, ?, ?, ?, ?, ?);",
                    (
                        work_id,
                        title,
                        status,
                        transcript_text,
                        archive_paths_json,
                        duration_s,
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

    def search(
        self,
        query: str,
        limit: int | None = None,
        auto_build: bool = True,
    ) -> list[SearchResult]:
        """Query the FTS5 index for matching transcripts with ranking."""
        query = query.strip()
        if not query:
            return []

        if limit is not None and limit <= 0:
            return []

        if not os.path.isfile(self.db_path):
            if auto_build:
                self.build()
            else:
                return []
        elif auto_build and self.is_stale():
            self.build()

        if not os.path.isfile(self.db_path):
            return []

        conn = sqlite3.connect(self.db_path)
        try:
            sql = (
                f"SELECT work_id, title, status, archive_paths, duration_s, transcript_text, rank "
                f"FROM {FTS5_TABLE_NAME} "
                f"WHERE {FTS5_TABLE_NAME} MATCH ? "
                f"ORDER BY rank"
            )
            params: list[Any] = [query]
            if limit is not None:
                sql += " LIMIT ?"
                params.append(limit)

            try:
                cur = conn.execute(sql, params)
                rows = cur.fetchall()
            except sqlite3.OperationalError as exc:
                if "no such module: fts5" in str(exc).lower():
                    raise FTS5UnavailableError(
                        "SQLite FTS5 extension is not available in this Python environment"
                    ) from exc
                # Syntax error fallback: wrap in quotes for plain phrase search
                escaped_query = '"' + query.replace('"', '""') + '"'
                params[0] = escaped_query
                try:
                    cur = conn.execute(sql, params)
                    rows = cur.fetchall()
                except sqlite3.OperationalError:
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

                results.append(
                    SearchResult(
                        work_id=work_id,
                        title=title,
                        status=status,
                        score=float(rank_score),
                        path=primary_path,
                        duration_s=duration_s or 0,
                        transcript_snippet=transcript_text[:100] if transcript_text else "",
                        archive_paths=paths_dict,
                    )
                )
            return results
        finally:
            conn.close()
