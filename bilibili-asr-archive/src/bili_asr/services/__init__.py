"""Application services over normalized storage and typed gateways."""

from bili_asr.services.metadata_ingest import (
    IngestionRunResult,
    MetadataIngestor,
)

__all__ = ["IngestionRunResult", "MetadataIngestor"]
