"""Search index public boundary.

The manifest-backed and store-backed indexes are separate implementations;
their shared readers and result models are exported here for callers that need
the subsystem as one service.
"""

from .common import (
    _cjk_bigram_stream,
    _create_snippet,
    _md_block_key,
    _parse_filter_set,
    _parse_scope_clause,
    _redact_text,
    _store_block_key,
    check_fts5_available,
)
from .errors import FTS5UnavailableError, SearchIndexMissingError, TranscriptStoreError
from .manifest import SearchIndex, search
from .models import SearchQuery, SearchResult, TranscriptSearchHit
from .readers import extract_transcript_text
from .store import TranscriptSearchIndex

import sys
import types
from . import common as _common


class _SearchIndexModule(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == "_redact_text":
            _common._redact_text = value


sys.modules[__name__].__class__ = _SearchIndexModule

__all__ = [
    "FTS5UnavailableError", "SearchIndex", "SearchIndexMissingError", "SearchQuery",
    "SearchResult", "TranscriptSearchHit", "TranscriptSearchIndex", "TranscriptStoreError",
    "check_fts5_available", "extract_transcript_text", "search",
]
