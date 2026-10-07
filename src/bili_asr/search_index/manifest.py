"""Manifest implementation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from bili_asr.archive import archive_stem, bundle_relpaths_for_stem
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.manifest import JOURNAL_NAME, ManifestStore
import bili_asr.search_index.common as _dependency_common
import bili_asr.search_index.constants as _dependency_constants
import bili_asr.search_index.errors as _dependency_errors
import bili_asr.search_index.models as _dependency_models
import bili_asr.search_index.readers as _dependency_readers


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
                cur = conn.execute(f"SELECT COUNT(*) FROM {_dependency_constants.FTS5_TABLE_NAME}")
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
                cur = conn.execute(f"PRAGMA table_info({_dependency_constants.FTS5_TABLE_NAME})")
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

        # The index itself is authoritative for rows it already contains.
        # Only probe the filesystem for completed manifest rows missing from
        # the index; archived rows can otherwise trigger many remote stat calls
        # on every search.
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                indexed_work_ids = {
                    str(row[0])
                    for row in conn.execute(
                        f"SELECT work_id FROM {_dependency_constants.FTS5_TABLE_NAME}"
                    )
                }
            finally:
                conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            return True

        manifest_work_ids: set[str] = set()
        for entry in entries.values():
            work_id = str(entry.get("work_id") or entry.get("bvid") or "")
            if not work_id:
                continue
            if work_id in indexed_work_ids:
                manifest_work_ids.add(work_id)
                if entry.get("status") in _dependency_constants.COMPLETED_STATUSES:
                    continue
                # An indexed row that is no longer complete invalidates the index.
                return True
            if self._is_indexable(entry):
                return True

        # Also detect indexed rows removed from the manifest, including the
        # same-count replacement case that a count-only check misses.
        if indexed_work_ids != manifest_work_ids:
            return True

        return False

    def _is_indexable(self, entry: dict[str, Any]) -> bool:
        """Check if entry is a completed transcript row with paths present."""
        status = entry.get("status")
        if status not in _dependency_constants.COMPLETED_STATUSES:
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
        return _dependency_readers.extract_transcript_text(
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
                    f"CREATE VIRTUAL TABLE {_dependency_constants.FTS5_TABLE_NAME} USING fts5("
                    "work_id, title, status, transcript_text, archive_paths, duration_s, "
                    "source, language, pubdate, bvid, page_index"
                    ");"
                )
            except sqlite3.OperationalError as exc:
                if "no such module: fts5" in str(exc).lower():
                    raise _dependency_errors.FTS5UnavailableError(
                        "SQLite FTS5 extension is not available in this Python environment"
                    ) from exc
                raise

            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_dependency_constants.INDEX_META_TABLE} ("
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
                    f"INSERT INTO {_dependency_constants.FTS5_TABLE_NAME}("
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
                f"INSERT OR REPLACE INTO {_dependency_constants.INDEX_META_TABLE}(key, value) "
                "VALUES ('manifest_mtime', ?);",
                (manifest_mtime,),
            )
            conn.execute(
                f"INSERT OR REPLACE INTO {_dependency_constants.INDEX_META_TABLE}(key, value) "
                "VALUES ('indexed_count', ?);",
                (str(count),),
            )
            conn.commit()
        finally:
            conn.close()

        os.replace(tmp_db, self.db_path)
        return count

    def search_query(self, query: _dependency_models.SearchQuery) -> list[_dependency_models.SearchResult]:
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

    def _execute_query(self, query: _dependency_models.SearchQuery) -> list[_dependency_models.SearchResult]:
        conn = sqlite3.connect(self.db_path)
        try:
            where_clauses: list[str] = []
            params: list[Any] = []

            clean_q = (query.query or "").strip()
            has_match = bool(clean_q)
            if has_match:
                where_clauses.append(f"{_dependency_constants.FTS5_TABLE_NAME} MATCH ?")
                params.append(clean_q)

            # Status filter
            status_set = _dependency_common._parse_filter_set(query.status)
            if status_set is not None:
                placeholders = ", ".join("?" for _ in status_set)
                where_clauses.append(f"status IN ({placeholders})")
                params.extend(sorted(status_set))

            # Source filter
            source_set = _dependency_common._parse_filter_set(query.source)
            if source_set is not None:
                placeholders = ", ".join("?" for _ in source_set)
                where_clauses.append(f"source IN ({placeholders})")
                params.extend(sorted(source_set))

            # Language filter
            lang_set = _dependency_common._parse_filter_set(query.language)
            if lang_set is not None:
                placeholders = ", ".join("?" for _ in lang_set)
                where_clauses.append(f"language IN ({placeholders})")
                params.extend(sorted(lang_set))

            # Work_id filter (matches work_id OR bvid)
            work_id_set = _dependency_common._parse_filter_set(query.work_id)
            if work_id_set is not None:
                w_placeholders = ", ".join("?" for _ in work_id_set)
                b_placeholders = ", ".join("?" for _ in work_id_set)
                where_clauses.append(f"(work_id IN ({w_placeholders}) OR bvid IN ({b_placeholders}))")
                params.extend(sorted(work_id_set))
                params.extend(sorted(work_id_set))

            # Scope filter
            if query.scope:
                clause, scope_params = _dependency_common._parse_scope_clause(query.scope, self.root)
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
                f"FROM {_dependency_constants.FTS5_TABLE_NAME} "
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
                    raise _dependency_errors.FTS5UnavailableError(
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

            results: list[_dependency_models.SearchResult] = []
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
                snippet = _dependency_common._create_snippet(transcript_text or "", clean_q)

                results.append(
                    _dependency_models.SearchResult(
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
        query: str | _dependency_models.SearchQuery,
        limit: int | None = None,
        auto_build: bool = True,
    ) -> list[_dependency_models.SearchResult]:
        """Query the FTS5 index for matching transcripts with ranking."""
        if isinstance(query, _dependency_models.SearchQuery):
            q = query
            if limit is not None:
                q = _dependency_models.SearchQuery(
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

        sq = _dependency_models.SearchQuery(
            query=query,
            limit=limit,
            auto_build=auto_build,
        )
        return self.search_query(sq)


def search(
    archive_root: str | os.PathLike[str] | Path,
    query: _dependency_models.SearchQuery | str,
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
        query = _dependency_models.SearchQuery(query=query)
    if auto_build is None:
        auto_build = True
    if auto_build is not None:
        query = _dependency_models.SearchQuery(
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
