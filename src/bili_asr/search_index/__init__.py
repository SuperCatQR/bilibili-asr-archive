"""SQLite FTS5 transcript search public boundary."""

from .common import (
    _cjk_bigram_stream,
    _create_snippet,
    _md_block_key,
    _redact_text,
    _store_block_key,
    check_fts5_available,
)
from .errors import FTS5UnavailableError, SearchIndexMissingError, TranscriptStoreError
from .models import TranscriptSearchHit
from .readers import extract_transcript_text
from .store import TranscriptSearchIndex

__all__ = [
    "FTS5UnavailableError", "SearchIndexMissingError", "TranscriptSearchHit",
    "TranscriptSearchIndex", "TranscriptStoreError",
    "check_fts5_available", "extract_transcript_text",
]
