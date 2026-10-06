"""Common implementation."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any
import bili_asr.search_index.constants as _dependency_constants


def _redact_text(text: str) -> str:
    """Strip URLs and credential-like values from text/snippets."""
    redacted = text
    for pattern in _dependency_constants._SENSITIVE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


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


def _create_snippet(text: str, query: str = "") -> str:
    """Produce a bounded snippet around the matching keyword or start of text."""
    if not text:
        return ""
    clean_text = " ".join(text.split())
    clean_q = (query or "").strip()
    if not clean_q:
        snippet = clean_text[:_dependency_constants.MAX_SNIPPET_LENGTH]
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
        snippet = clean_text[:_dependency_constants.MAX_SNIPPET_LENGTH]
    else:
        start = max(0, match_pos - 30)
        end = min(len(clean_text), match_pos + 90)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(clean_text) else ""
        snippet = prefix + clean_text[start:end] + suffix

    return _redact_text(snippet[:_dependency_constants.MAX_SNIPPET_LENGTH])


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


def _store_block_key(transcript_id: int, ordinal: int) -> str:
    return f"{_dependency_constants._STORE_KEY_PREFIX}{transcript_id}:{ordinal}"


def _md_block_key(video_part_id: int) -> str:
    return f"{_dependency_constants._MD_KEY_PREFIX}{video_part_id}:0"


def _store_fts_ddl(tokenizer: str) -> str:
    return (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {_dependency_constants.STORE_FTS5_TABLE} USING fts5("
        "block_key UNINDEXED, bvid UNINDEXED, page_index UNINDEXED, "
        "start_ms UNINDEXED, end_ms UNINDEXED, pubdate UNINDEXED, "
        "text, bigram, source UNINDEXED, "
        f"tokenize='{tokenizer}'"
        ");"
    )
