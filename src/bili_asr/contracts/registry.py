"""Stable contract identities and ownership; no storage or runtime imports."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType

BILIBILI_V1 = "bilibili-v1"
UNIVERSAL_V2 = "universal-v2"
RUNTIME_CONTRACTS = (BILIBILI_V1, UNIVERSAL_V2)
WORKFLOW_PAYLOAD_VERSION = 1
ASR_PROFILE_VERSION = 2
ASR_EVIDENCE_VERSION = 1
BUNDLE_SCHEMA = "archive-bundle-v2"
ORIGIN_PROFILE = "universal-origin-v1"
IMPORT_EXTENSION = "preserved-body-import-v1"
LEGACY_FACTS_POLICY = "legacy-frozen-facts-v1"
STORED_VTT_POLICY = "stored-segments-webvtt/v1"
SOURCE_SUPPLEMENT_POLICY = "legacy-part-title-supplement-v1"
ARTIFACT_STORAGE = "artifact-storage-v1"
ARTIFACT_ONLINE = "artifact-online-v1"
SCHEMA_BASE_URI = "https://github.com/SuperCatQR/bilibili-asr-archive/docs/contracts/"


@dataclass(frozen=True)
class Contract:
    identity: str
    owner: str
    authority: tuple[str, ...]
    consumers: tuple[str, ...]
    capabilities: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    schema: str | None = None


def _json(identity: str, filename: str, owner: str = "publication",
          dependencies: tuple[str, ...] = ()) -> Contract:
    return Contract(identity, owner, (f"src/bili_asr/contracts/schemas/{filename}",),
                    ("export_snapshot", "external-reader"), ("validate", "export"), dependencies, filename)


_CONTRACTS = (
    Contract("archive-reference-backup/v1", "archive", ("src/bili_asr/services/reference_backup.py",),
             ("cli.remote_storage", "services.archive_recovery"), ("validate", "save", "check", "plan", "restore"),
             ("artifact-storage-v1", "artifact-package-v1"), "archive-reference-backup-v1.schema.json"),
    Contract("ssh-directory/v1", "storage", ("src/bili_asr/remote_storage.py", "src/bili_asr/ssh_storage_agent.py"),
             ("services.remote_artifacts", "services.reference_backup"), ("validate", "upload", "read", "range-read"),
             ("artifact-package-v1",), "ssh-directory-v1.schema.json"),
    Contract("artifact-online-v1", "storage", ("src/bili_asr/storage/schema-artifact-online.sql",),
             ("services.artifact_policy", "services.artifact_consumer", "storage.snapshots"),
             ("extension", "snapshot", "explicit-upgrade"), ("artifact-storage-v1",)),
    Contract("artifact-state-v1", "storage", ("src/bili_asr/services/artifact_state.py",),
             ("cli.artifacts",), ("read", "validate"), ("artifact-storage-v1",), "artifact-state-v1.schema.json"),
    Contract("artifact-publication-state-v1", "storage", ("src/bili_asr/services/artifact_state.py",),
             ("coverage_report", "integrity", "services.workflow_projection"), ("read", "validate"),
             ("artifact-storage-v1",), "artifact-publication-state-v1.schema.json"),
    Contract("artifact-storage-v1", "storage", ("src/bili_asr/storage/schema-artifact-storage.sql",),
             ("storage.artifact_catalog", "services.artifact_catalog_upgrade", "storage.snapshots"),
             ("extension", "snapshot", "explicit-upgrade")),
    Contract("artifact-inventory-v1", "storage", ("src/bili_asr/services/artifact_inventory_service.py",),
             ("cli.artifacts",), ("validate", "read"), (), "artifact-inventory-v1.schema.json"),
    Contract("artifact-offload-plan-v1", "storage", ("src/bili_asr/services/artifact_inventory_service.py",),
             ("cli.artifacts", "services.artifact_transfer"), ("validate", "read", "write"),
             ("artifact-storage-v1", "artifact-inventory-v1"), "artifact-offload-plan-v1.schema.json"),
    Contract("artifact-package-v1", "storage", ("src/bili_asr/artifact_packages.py",),
             ("services.artifact_transfer", "services.artifact_access", "services.artifact_restore"),
             ("validate", "read", "write"), ("artifact-storage-v1",), "artifact-package-v1.schema.json"),
    Contract(BILIBILI_V1, "storage", ("src/bili_asr/storage/schema.sql", "src/bili_asr/storage/schema-transcripts.sql",
             "src/bili_asr/storage/schema-workflow.sql", "src/bili_asr/storage/schema-editorial.sql"),
             ("archive_session", "storage.snapshots"), ("runtime", "snapshot")),
    Contract(UNIVERSAL_V2, "storage", ("src/bili_asr/storage/archive_contracts.py", "src/bili_asr/storage/schema-content-v2.sql",
             "src/bili_asr/storage/schema-observations.sql", "src/bili_asr/storage/schema-source-sync.sql"),
             ("archive_session", "storage.snapshots", "services.archive_migration"),
             ("runtime", "snapshot", "migration-target"), (BILIBILI_V1,)),
    Contract("bilibili-migration-source/v1", "storage", ("src/bili_asr/storage/migration-source-bilibili-v1.json",),
             ("storage.migration_source", "services.archive_migration"), ("migration-source",)),
    Contract(IMPORT_EXTENSION, "storage", ("src/bili_asr/storage/schema-preserved-body-import.sql",),
             ("storage.import_origins", "services.preserved_body_import", "storage.snapshots"),
             ("extension", "snapshot"), (UNIVERSAL_V2,)),
    Contract(SOURCE_SUPPLEMENT_POLICY, "sources", ("src/bili_asr/source_supplements.py",
             "src/bili_asr/storage/schema-source-supplements.sql"),
             ("storage.source_supplements", "publication_origins", "storage.snapshots"),
             ("extension", "snapshot", "export"), (IMPORT_EXTENSION,)),
    Contract(LEGACY_FACTS_POLICY, "publication", ("src/bili_asr/contracts/content_policies.py",
             "src/bili_asr/services/preserved_body_import.py"),
             ("storage.import_origins", "publication_origins"), ("content-upgrade", "historical-read"),
             (IMPORT_EXTENSION, "publication-content/v1", "publication-content/v2")),
    Contract(STORED_VTT_POLICY, "transcripts", ("src/bili_asr/services/transcript_derivatives.py", "src/bili_asr/cues.py"),
             ("cli.archive",), ("derive", "export")),
    Contract("workflow-payload/v1", "workflow", ("src/bili_asr/workflow_payloads.py",),
             ("storage.workflow", "workflow"), ("read", "write")),
    Contract("asr-profile/v2", "workflow", ("src/bili_asr/workflow_models.py", "src/bili_asr/storage/schema-workflow.sql"),
             ("storage.workflow", "workflow_runtime"), ("read", "write")),
    Contract("asr-evidence/v1", "transcripts", ("src/bili_asr/storage/transcripts.py", "src/bili_asr/storage/schema-transcripts.sql"),
             ("storage.transcripts",), ("read", "write")),
    Contract("canonical-json/v1", "identity", ("src/bili_asr/canonical_json.py",),
             ("editorial", "publication_identity", "storage.migration_artifacts"), ("hash", "historical-read")),
    Contract(BUNDLE_SCHEMA, "transcripts", ("src/bili_asr/artifacts.py",),
             ("archive", "services.bundle_verification", "services.archive_snapshot"), ("read", "write")),
    Contract("frozen-input/v1", "editorial", ("src/bili_asr/editorial.py", "src/bili_asr/storage/migration_artifacts.py"),
             ("storage.editorial", "manuscript_templates"), ("historical-read", "write"), ("canonical-json/v1",)),
    Contract("frozen-input/v2", "editorial", ("src/bili_asr/storage/editorial.py",),
             ("editorial_runtime", "publication_content_v2"), ("read", "write"), (UNIVERSAL_V2, "canonical-json/v1")),
    Contract("publication-content/v1", "publication", ("src/bili_asr/publication_content.py",),
             ("storage.publication", "publication_export"), ("historical-read", "write"), ("canonical-json/v1",)),
    Contract("publication-content/v2", "publication", ("src/bili_asr/publication_content_v2.py",),
             ("storage.publication", "publication_export"), ("read", "write"), (UNIVERSAL_V2, "canonical-json/v1")),
    Contract("ai-draft-v1", "editorial", ("src/bili_asr/manuscript_templates.py",),
             ("storage.editorial", "storage.migration_artifacts"), ("render", "historical-read"), ("frozen-input/v1",)),
    Contract("ai-draft-v2", "editorial", ("src/bili_asr/publication_content_v2.py",),
             ("manuscript_templates",), ("render",), ("frozen-input/v2",)),
    Contract("publish-v1", "publication", ("src/bili_asr/manuscript_templates.py",),
             ("publication_identity", "storage.migration_artifacts"), ("render", "historical-read"), ("publication-content/v1",)),
    Contract("publish-v2", "publication", ("src/bili_asr/publication_content_v2.py",),
             ("publication", "publication_export"), ("render",), ("publication-content/v2",)),
    Contract("archive-snapshot/v1", "archive", ("src/bili_asr/services/archive_snapshot.py",),
             ("services.archive_snapshot", "services.archive_recovery"), ("save", "check", "restore")),
    _json("source-metadata/v1", "source-metadata-v1.schema.json", "sources"),
    _json("publication-catalog/v2", "publication-catalog.schema.json", dependencies=("publish-v1",)),
    _json("publication-draft-catalog/v2", "publication-draft-catalog.schema.json"),
    _json("publication-catalog/v3", "publication-catalog-v3.schema.json",
          dependencies=("publication-catalog/v2", "source-metadata/v1", "publish-v2")),
    _json("publication-draft-catalog/v3", "publication-draft-catalog-v3.schema.json",
          dependencies=("publication-draft-catalog/v2", "source-metadata/v1")),
    _json("publication-export-manifest/v1", "publication-export-manifest.schema.json"),
    _json("publication-draft-export-manifest/v1", "publication-draft-export-manifest.schema.json"),
    _json("publication-origin-manifest/v2", "publication-origin-manifest-v2.schema.json",
          dependencies=(ORIGIN_PROFILE,)),
    _json(ORIGIN_PROFILE, "publication-origins-v1.schema.json",
          dependencies=("publication-content/v2", SOURCE_SUPPLEMENT_POLICY)),
    _json("editorial-export-manifest/v1", "editorial-export-manifest.schema.json"),
    _json("editorial-import-export-manifest/v1", "editorial-import-export-manifest.schema.json",
          dependencies=(IMPORT_EXTENSION, "editorial-export-manifest/v1")),
    _json("editorial-review/v1", "editorial-review.schema.json"),
    _json("editorial-review-universal/v1", "editorial-review-universal.schema.json", dependencies=("ai-draft-v2",)),
    _json("publication-series/v1", "publication-series.schema.json"),
    _json("publication-series-editorial/v1", "publication-series-editorial.schema.json"),
)
CONTRACTS = MappingProxyType({entry.identity: entry for entry in _CONTRACTS})


def contract(identity: str, *, capability: str | None = None) -> Contract:
    try:
        entry = CONTRACTS[identity]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unsupported contract: {identity}") from exc
    if capability is not None and capability not in entry.capabilities:
        raise ValueError(f"contract {identity} does not support {capability}")
    return entry


def catalog_contract(version: int, *, draft: bool = False) -> str:
    if type(version) is not int:
        raise ValueError("catalog version must be an integer")
    identity = f"publication{'-draft' if draft else ''}-catalog/v{version}"
    return contract(identity, capability="validate").identity


def manifest_contract(kind: str, profile: str | None, *, imported: bool = False) -> str:
    if kind not in {"publication-export", "publication-draft-export", "editorial-export"}:
        raise ValueError("unsupported export kind")
    if profile is not None:
        if profile != ORIGIN_PROFILE or kind == "editorial-export":
            raise ValueError("unsupported export profile")
        return "publication-origin-manifest/v2"
    if imported and kind == "editorial-export":
        return "editorial-import-export-manifest/v1"
    return kind + "-manifest/v1"


def catalog() -> dict:
    from bili_asr.contracts.content_policies import policy_catalog
    return {"format_version": 1, "contracts": [asdict(entry) for entry in _CONTRACTS],
            "upgrades": [asdict(entry) for entry in UPGRADE_EDGES], "content_policies": policy_catalog()}


@dataclass(frozen=True)
class UpgradeEdge:
    """An explicit directed conversion, independent of executable services."""

    identity: str
    source: tuple[str, ...]
    target: tuple[str, ...]
    converter: str
    revision: int
    authority: tuple[str, ...]
    source_reader: str
    target_validator: str
    allowed_changes: tuple[str, ...]
    sample: str
    reversible: bool = False


UPGRADE_EDGES = (
    UpgradeEdge("bilibili-to-universal/v1", (BILIBILI_V1,), (UNIVERSAL_V2,),
                "legacy-migrate", 1, ("services/archive_migration.py", "storage/archive_contracts.py"),
                "bilibili-migration-source/v1", "snapshot-database",
                ("neutral-source-mapping", "frozen-version-registration", "migration-audit"),
                "tests/fixtures/data/bilibili-v1-frozen.zip"),
    UpgradeEdge("preserved-body-extension/v1", (UNIVERSAL_V2,), (UNIVERSAL_V2, IMPORT_EXTENSION),
                "install-preserved-body", 1,
                ("services/preserved_body_import.py", "storage/schema-preserved-body-import.sql"),
                "snapshot-database", "snapshot-database", ("empty-extension-tables",),
                "tests/test_archive_upgrade.py"),
    UpgradeEdge("source-supplement-extension/v1", (UNIVERSAL_V2, IMPORT_EXTENSION),
                (UNIVERSAL_V2, IMPORT_EXTENSION, SOURCE_SUPPLEMENT_POLICY),
                "install-source-supplement", 1,
                ("services/source_supplement.py", "storage/schema-source-supplements.sql"),
                "snapshot-database", "snapshot-database", ("empty-extension-tables",),
                "tests/test_archive_upgrade.py"),
    *(UpgradeEdge("artifact-storage-" + suffix + "/v1", combination, (*combination, ARTIFACT_STORAGE),
                  "install-artifact-storage", 1,
                  ("services/artifact_catalog_upgrade.py", "storage/schema-artifact-storage.sql"),
                  "snapshot-database", "snapshot-database", ("artifact-object-and-replica-backfill",),
                  "tests/test_archive_upgrade.py")
      for suffix, combination in (
          ("native", (UNIVERSAL_V2,)),
          ("preserved", (UNIVERSAL_V2, IMPORT_EXTENSION)),
          ("supplemented", (UNIVERSAL_V2, IMPORT_EXTENSION, SOURCE_SUPPLEMENT_POLICY)))),
    *(UpgradeEdge("artifact-online-" + suffix + "/v1", (*combination, ARTIFACT_STORAGE),
                  (*combination, ARTIFACT_STORAGE, ARTIFACT_ONLINE), "install-artifact-online", 1,
                  ("storage/artifact_online.py", "storage/schema-artifact-online.sql"),
                  "snapshot-database", "snapshot-database", ("empty-extension-tables",),
                  "tests/test_archive_upgrade.py")
      for suffix, combination in (
          ("native", (UNIVERSAL_V2,)),
          ("preserved", (UNIVERSAL_V2, IMPORT_EXTENSION)),
          ("supplemented", (UNIVERSAL_V2, IMPORT_EXTENSION, SOURCE_SUPPLEMENT_POLICY)))),
)


def upgrade_path(source: tuple[str, ...], target: tuple[str, ...], *,
                 selected: tuple[str, ...] | None = None,
                 edges: tuple[UpgradeEdge, ...] = UPGRADE_EDGES) -> tuple[UpgradeEdge, ...]:
    """Select only registered paths; ambiguity requires an exact edge sequence."""
    for identity in (*source, *target):
        contract(identity)
    if source == target:
        raise ValueError("source already has the requested contracts; use snapshot for a copy")
    paths = []

    def visit(current, trail, seen):
        if current == target:
            paths.append(trail)
            return
        for edge in edges:
            if edge.source == current and edge.target not in seen:
                visit(edge.target, (*trail, edge), seen | {edge.target})

    visit(source, (), {source})
    if selected is not None:
        paths = [path for path in paths if tuple(edge.identity for edge in path) == selected]
    if not paths:
        raise ValueError("no registered upgrade path for the exact contract combination")
    if len(paths) != 1:
        raise ValueError("ambiguous upgrade path; select the complete edge sequence explicitly")
    return paths[0]
