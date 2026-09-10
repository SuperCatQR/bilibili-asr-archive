"""Normalized SQLite storage for Bilibili metadata.

The package root is the single import surface: the repository, the record
models, and the bootstrap helpers are all re-exported here.
"""

from .database import (
    DatabaseConnection,
    MetadataRepository,
    duration_to_ms,
    initialize_schema,
    normalize_page_index,
    open_database,
)
from .models import (
    ALLOWED_CURSOR_STATES,
    ALLOWED_PAGE_OUTCOMES,
    ALLOWED_PROCESSING_STATUS,
    ALLOWED_RUN_OUTCOMES,
    CursorRecord,
    CursorState,
    DiscoveryRecord,
    IngestionPageRecord,
    IngestionRunRecord,
    PageOutcome,
    ProcessingStatus,
    RunOutcome,
    UserRecord,
    VideoPartRecord,
    VideoRecord,
    validate_error_code,
)

__all__ = [
    "ALLOWED_CURSOR_STATES",
    "ALLOWED_PAGE_OUTCOMES",
    "ALLOWED_PROCESSING_STATUS",
    "ALLOWED_RUN_OUTCOMES",
    "CursorRecord",
    "CursorState",
    "DatabaseConnection",
    "DiscoveryRecord",
    "IngestionPageRecord",
    "IngestionRunRecord",
    "MetadataRepository",
    "PageOutcome",
    "ProcessingStatus",
    "RunOutcome",
    "UserRecord",
    "VideoPartRecord",
    "VideoRecord",
    "duration_to_ms",
    "initialize_schema",
    "normalize_page_index",
    "open_database",
    "validate_error_code",
]
