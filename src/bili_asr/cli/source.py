"""Single-video source ingestion and explicit local environment checks."""
from __future__ import annotations

import json
from pathlib import Path
from bili_asr.diagnostics import write_stderr


def add_source_parser(subparsers, *, archive_root):
    parser = subparsers.add_parser("source", help="Import one provider video into an explicitly created universal archive")
    actions = parser.add_subparsers(dest="source_action", required=True)
    check = actions.add_parser("doctor", help="Inspect the locked YouTube adapter dependencies without network or installation")
    check.set_defaults(database_policy=None)
    fetch = actions.add_parser("import", help="Fetch YouTube metadata for one video; outputs its internal part ID")
    fetch.add_argument("--youtube", required=True)
    fetch.add_argument("--archive-root", default=archive_root)
    fetch.add_argument("--cookies", help="Explicit private yt-dlp Netscape cookie file, kept inside the adapter")
    metadata = actions.add_parser("metadata", help="Read private original observations and reproject offline")
    metadata.set_defaults(database_policy=None)
    location = metadata.add_mutually_exclusive_group(required=True)
    location.add_argument("--archive-root")
    location.add_argument("--database", type=Path, help="Standalone archive.db from a verified backup")
    identity = metadata.add_mutually_exclusive_group(required=True)
    identity.add_argument("--youtube")
    identity.add_argument("--bvid")
    metadata.add_argument("--mapping-version", default="source-superset/v1")
    metadata.add_argument("--observed-after", type=int, help="Inclusive Unix timestamp for bounded historical reads")
    metadata.add_argument("--observed-before", type=int, help="Inclusive Unix timestamp for bounded historical reads")
    metadata.add_argument("--limit", type=int, default=1000, help="Fail if matching observations exceed this count")


def _cmd_source(args):
    from bili_asr.archive_session import ArchiveSession, ArchiveAccessMode
    from bili_asr.source_identity import youtube_ref
    from bili_asr.sources.registry import SourceRegistry
    from bili_asr.sources.youtube_source import youtube_environment
    from bili_asr.sources.models import GatewayError
    from bili_asr.storage.sources import SourceRepository
    try:
        if args.source_action == "metadata":
            from contextlib import closing
            from bili_asr.platform_identity import ContentRef
            from bili_asr.storage.database import connect_database
            from bili_asr.storage.snapshots import validate_snapshot_database
            from bili_asr.storage.source_observations import ObservationRepository
            ref = youtube_ref(args.youtube) if args.youtube else ContentRef("bilibili", args.bvid)
            database = args.database if args.database else Path(args.archive_root) / "archive.db"
            if args.archive_root:
                with ArchiveSession(args.archive_root, mode=ArchiveAccessMode.READ) as session:
                    report = ObservationRepository(session.connection).superset(
                        ref.platform, ref.external_video_id, mapping_version=args.mapping_version,
                        observed_after=args.observed_after, observed_before=args.observed_before, limit=args.limit)
            else:
                validate_snapshot_database(database)
                with closing(connect_database(database, readonly=True, must_exist=True)) as connection:
                    report = ObservationRepository(connection).superset(
                        ref.platform, ref.external_video_id, mapping_version=args.mapping_version,
                        observed_after=args.observed_after, observed_before=args.observed_before, limit=args.limit)
            print(json.dumps(report, ensure_ascii=True, sort_keys=True))
            return 0
        environment = youtube_environment()
        if args.source_action == "doctor":
            print(json.dumps(environment, sort_keys=True))
            return 0 if environment["ready"] else 1
        if not environment["ready"]:
            raise ValueError("YouTube runtime not ready; run source doctor and install the locked youtube extra/JS runtime")
        ref = youtube_ref(args.youtube)
        with ArchiveSession(args.archive_root, mode=ArchiveAccessMode.WRITE) as session:
            source = SourceRegistry(cookie_file=Path(args.cookies) if args.cookies else None).source(ref)
            from bili_asr.services.metadata_observations import bind_observations
            from bili_asr.storage.metadata import MetadataRepository
            captured = bind_observations(source, MetadataRepository(session.connection))
            if not captured:
                write_stderr("source import: raw metadata coverage unavailable; explicitly upgrade to source-observations/v1")
            metadata = source.metadata(ref)
            with session.connection:
                part_id = SourceRepository(session.connection).upsert_video(metadata)
            print(json.dumps({"platform": ref.platform, "external_video_id": ref.external_video_id,
                              "video_part_id": part_id, "url": source_url(ref)}, sort_keys=True))
        return 0
    except (ValueError, OSError, GatewayError) as exc:
        message = exc.code if isinstance(exc, GatewayError) else str(exc)
        write_stderr(f"source: {message}")
        return 1


from bili_asr.source_identity import source_url
