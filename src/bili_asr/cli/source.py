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


def _cmd_source(args):
    from bili_asr.archive_session import ArchiveSession, ArchiveAccessMode
    from bili_asr.source_identity import youtube_ref
    from bili_asr.sources.registry import SourceRegistry
    from bili_asr.sources.youtube_source import youtube_environment
    from bili_asr.sources.models import GatewayError
    from bili_asr.storage.sources import SourceRepository
    try:
        environment = youtube_environment()
        if args.source_action == "doctor":
            print(json.dumps(environment, sort_keys=True))
            return 0 if environment["ready"] else 1
        if not environment["ready"]:
            raise ValueError("YouTube runtime not ready; run source doctor and install the locked youtube extra/JS runtime")
        ref = youtube_ref(args.youtube)
        with ArchiveSession(args.archive_root, mode=ArchiveAccessMode.WRITE) as session:
            source = SourceRegistry(cookie_file=Path(args.cookies) if args.cookies else None).source(ref)
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
