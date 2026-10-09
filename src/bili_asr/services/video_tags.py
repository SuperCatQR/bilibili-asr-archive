"""Best-effort source-tag refresh with durable observation evidence."""
from __future__ import annotations

import asyncio
from collections.abc import Iterable
import sqlite3
import time

from bili_asr.sources.models import BilibiliGateway, GatewayError
from bili_asr.storage import MetadataRepository, VideoTagRecord

ERROR_CODES = frozenset({"auth_error", "rate_limited", "not_found", "transport_error",
                         "response_error", "shape_error", "unavailable"})


def bounded_tag_error(code: str | None) -> str:
    return code if code in ERROR_CODES else "unavailable"


def refresh_video_tags(connection: sqlite3.Connection, gateway: BilibiliGateway,
                       bvids: Iterable[str]) -> dict[str, int]:
    """Refresh only archived videos; failure never replaces successful tags."""
    selected = tuple(dict.fromkeys(bvids))
    for bvid in selected:
        if connection.execute("SELECT 1 FROM videos WHERE bvid=?", (bvid,)).fetchone() is None:
            raise ValueError("fetch-tags: unknown archived BVID")

    async def refresh():
        succeeded = failed = 0
        repository = MetadataRepository(connection)
        for bvid in selected:
            error = None
            try:
                tags = await gateway.get_video_tags(bvid)
                if tags is None:
                    error = bounded_tag_error(getattr(gateway, "tag_error_code", None))
            except GatewayError as exc:
                tags, error = None, bounded_tag_error(exc.code)
            state = "unavailable" if tags is None else "success_nonempty" if tags else "success_empty"
            with repository.transaction():
                if tags is not None:
                    repository.upsert_video_tags(bvid, [VideoTagRecord(
                        bvid=bvid, tag_id=tag.tag_id, tag_name=tag.tag_name, tag_type=tag.tag_type
                    ) for tag in tags])
                connection.execute(
                    "INSERT INTO video_tag_observations VALUES (?, ?, ?, ?, NULL) "
                    "ON CONFLICT(bvid) DO UPDATE SET state=excluded.state, observed_at=excluded.observed_at, "
                    "error_code=excluded.error_code, run_id=NULL", (bvid, state, int(time.time()), error),
                )
            if tags is None:
                failed += 1
            else:
                succeeded += 1
        return {"attempted": len(selected), "succeeded": succeeded, "failed": failed}

    return asyncio.run(refresh())
