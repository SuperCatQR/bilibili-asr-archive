"""Explicit source refresh, independent of creator pagination and its cursor."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json

from bili_asr.metadata_policy import MetadataRefreshPolicy
from bili_asr.services._common import _now
from bili_asr.services.video_tags import read_tags
from bili_asr.sources.models import BilibiliGateway, GatewayError, GatewayShapeError
from bili_asr.storage.metadata import MetadataRepository
from bili_asr.storage.models import VideoRecord, VideoPartRecord, VideoDetailRecord, VideoTagRecord, UserRecord


@dataclass(frozen=True, slots=True)
class MetadataRefreshOutcome:
    bvid: str
    operation: str
    state: str
    error_code: str | None = None


class MetadataRefreshService:
    """Refresh selected archived videos; failed reads preserve successful facts."""

    def __init__(self, gateway: BilibiliGateway, repository: MetadataRepository):
        self.gateway, self.repository = gateway, repository

    def refresh(self, bvids, *, operations=("summary", "details", "parts", "tags"),
                policy: MetadataRefreshPolicy | None = None) -> tuple[MetadataRefreshOutcome, ...]:
        selected = tuple(dict.fromkeys(bvids))
        if not selected or len(selected) > 1000:
            raise ValueError("refresh requires between 1 and 1000 archived videos")
        operations = tuple(dict.fromkeys(operations))
        if not operations or any(operation not in {"summary", "details", "parts", "tags"} for operation in operations):
            raise ValueError("unknown metadata refresh operation")
        for bvid in selected:
            if self.repository.connection.execute("SELECT 1 FROM videos WHERE bvid=?", (bvid,)).fetchone() is None:
                raise ValueError("metadata refresh requires archived BVIDs")
        return asyncio.run(self._refresh(selected, operations, policy or MetadataRefreshPolicy()))

    def failed_targets(self, *, limit: int = 100) -> tuple[tuple[str, str], ...]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("failed refresh limit must be between 1 and 1000")
        if not self.repository.observations_supported():
            raise ValueError("refresh-failed requires the explicit universal-v2 observation contract")
        return tuple((row[0], row[1]) for row in self.repository.connection.execute(
            """SELECT bvid, operation FROM (
                 SELECT bvid, operation, state,
                    ROW_NUMBER() OVER (PARTITION BY bvid, operation ORDER BY finished_at DESC, rowid DESC) newest
                 FROM metadata_refresh_attempts
               ) WHERE newest=1 AND state IN ('unavailable','denied') ORDER BY bvid,operation LIMIT ?""", (limit,)))

    def retry_failed(self, *, limit: int = 100) -> tuple[MetadataRefreshOutcome, ...]:
        outcomes = []
        replayed = set()
        for bvid, operation in self.failed_targets(limit=limit):
            if self.repository.connection.execute("SELECT 1 FROM videos WHERE bvid=?", (bvid,)).fetchone():
                current = self.refresh((bvid,), operations=(operation,))
                outcomes.extend(current)
                if any(outcome.error_code in {"auth_error", "rate_limited", "request_budget_exhausted"} for outcome in current):
                    break
                continue
            row = self.repository.connection.execute(
                "SELECT details_json FROM metadata_refresh_attempts WHERE bvid=? AND operation=? ORDER BY finished_at DESC,rowid DESC LIMIT 1",
                (bvid, operation)).fetchone()
            details = json.loads(row[0])
            mid, page = details.get("mid"), details.get("page_number")
            if type(mid) is not int or mid < 1 or type(page) is not int or page < 1:
                outcomes.append(MetadataRefreshOutcome(bvid, operation, "unavailable", "metadata_retry_context_missing"))
                continue
            if (mid, page) in replayed:
                continue
            replayed.add((mid, page))
            from bili_asr.services.metadata_ingest import MetadataIngestor
            result = MetadataIngestor(self.gateway, self.repository).replay_page(mid=mid, page_number=page)
            archived = self.repository.connection.execute("SELECT 1 FROM videos WHERE bvid=?", (bvid,)).fetchone() is not None
            recovered = archived and result.outcome in {"complete", "limited"}
            code = None if recovered else result.error_code or "metadata_retry_context_changed"
            state = "present" if recovered else "denied" if code == "auth_error" else "unavailable"
            if not recovered:
                with self.repository.transaction():
                    now = _now()
                    self.repository.record_metadata_attempt(bvid, operation, state, now, now, code,
                        details={"mid": mid, "page_number": page})
            outcomes.append(MetadataRefreshOutcome(bvid, operation, state, code))
            if code in {"auth_error", "rate_limited", "request_budget_exhausted"}:
                break
        return tuple(outcomes)

    async def _refresh(self, bvids, operations, policy):
        outcomes = []
        for bvid in bvids:
            metadata = None
            metadata_error = None
            for operation in operations:
                started = _now()
                observed_state = "present"
                if not self._needs_read(bvid, operation, policy, started):
                    outcomes.append(MetadataRefreshOutcome(bvid, operation, "reused"))
                    continue
                try:
                    if operation in {"summary", "details"}:
                        if metadata_error is not None:
                            raise metadata_error
                        if metadata is None:
                            try:
                                metadata = await self.gateway.get_video_metadata(bvid)
                            except GatewayError as error:
                                metadata_error = error
                                raise
                        self._write_metadata(bvid, operation, metadata, started)
                    elif operation == "parts":
                        title = self.repository.connection.execute("SELECT title FROM videos WHERE bvid=?", (bvid,)).fetchone()[0]
                        parts = metadata.parts if metadata is not None and metadata.parts is not None else await self.gateway.get_video_parts(bvid, video_title_fallback=title)
                        self._validate_parts(bvid, parts)
                        with self.repository.transaction():
                            for part in parts:
                                self.repository.upsert_part(VideoPartRecord(
                                    bvid, part.page_index, part.cid, part.title, part.duration_ms,
                                    "metadata_collected", started, _now()))
                            self.repository.record_metadata_attempt(bvid, operation, "present", started, _now())
                    else:
                        read = await read_tags(self.gateway, bvid)
                        if read.tags is None:
                            raise GatewayError(read.error_code)
                        with self.repository.transaction():
                            self.repository.upsert_video_tags(bvid, [VideoTagRecord(bvid, tag.tag_id, tag.tag_name, tag.tag_type) for tag in read.tags])
                            self.repository.connection.execute(
                                "INSERT INTO video_tag_observations VALUES (?, ?, ?, NULL, NULL) ON CONFLICT(bvid) DO UPDATE SET state=excluded.state, observed_at=excluded.observed_at, error_code=NULL, run_id=NULL",
                                (bvid, "success_nonempty" if read.tags else "success_empty", _now()))
                            self.repository.record_metadata_attempt(bvid, operation, "present" if read.tags else "empty", started, _now())
                        observed_state = "present" if read.tags else "empty"
                    outcomes.append(MetadataRefreshOutcome(bvid, operation, observed_state))
                except (GatewayError, ValueError) as error:
                    if isinstance(error, ValueError) and str(error) != "metadata_part_identity_conflict":
                        raise
                    code = error.code if isinstance(error, GatewayError) else "metadata_part_identity_conflict"
                    state = "denied" if code == "auth_error" else "unavailable"
                    with self.repository.transaction():
                        self.repository.record_metadata_attempt(bvid, operation, state, started, _now(), code)
                        if operation == "tags":
                            from bili_asr.services.video_tags import bounded_tag_error
                            self.repository.connection.execute(
                                "INSERT INTO video_tag_observations VALUES (?, 'unavailable', ?, ?, NULL) ON CONFLICT(bvid) DO UPDATE SET state=excluded.state, observed_at=excluded.observed_at,error_code=excluded.error_code,run_id=NULL",
                                (bvid, _now(), bounded_tag_error(code)))
                    outcomes.append(MetadataRefreshOutcome(bvid, operation, state, code))
                    if code in {"auth_error", "rate_limited", "request_budget_exhausted"}:
                        return tuple(outcomes)
        return tuple(outcomes)

    def _needs_read(self, bvid, operation, policy, now):
        connection = self.repository.connection
        if operation == "parts":
            row = connection.execute("SELECT COUNT(*), MIN(updated_at) FROM video_parts WHERE bvid=?", (bvid,)).fetchone()
            present, observed = row[0] > 0, row[1]
        elif operation == "tags":
            row = connection.execute("SELECT state, observed_at FROM video_tag_observations WHERE bvid=?", (bvid,)).fetchone()
            present, observed = row is not None and row[0] != "unavailable", row[1] if row else None
        elif operation == "details":
            row = connection.execute('SELECT pic, "desc", tid, observed_at FROM video_details WHERE bvid=?', (bvid,)).fetchone()
            present, observed = row is not None and all(value is not None for value in row[:3]), row[3] if row else None
        else:
            row = connection.execute("SELECT pubdate, aid, updated_at FROM videos WHERE bvid=?", (bvid,)).fetchone()
            present, observed = row[0] > 0 and row[1] is not None, None
        if self.repository.observations_supported() and operation in {"summary", "details"}:
            required = {"pubdate", "aid"} if operation == "summary" else {"pic", "desc", "tid"}
            facts = {row[0]: row[1:] for row in connection.execute(
                "SELECT field,state,last_success_at FROM source_metadata_observations WHERE platform='bilibili' AND external_id=? AND operation=?",
                (bvid, operation))}
            present = all(field in facts and facts[field][0] in {"present", "empty"} for field in required)
            observed = min((facts[field][1] for field in required), default=None) if present else None
        return policy.needs_read(known_video=True, present=present, observed_at=observed, now=now)

    def _validate_parts(self, bvid, parts):
        if not parts or any(part.bvid != bvid for part in parts):
            raise GatewayShapeError()
        current = {row[0]: row[1] for row in self.repository.connection.execute(
            "SELECT page_index,cid FROM video_parts WHERE bvid=?", (bvid,))}
        if any(part.page_index in current and current[part.page_index] != part.cid for part in parts):
            raise GatewayShapeError(code="metadata_part_identity_conflict")
        if any(index not in {part.page_index for part in parts} for index in current):
            raise GatewayShapeError(code="metadata_part_topology_changed")

    def _write_metadata(self, bvid, operation, read, started):
        summary = read.summary
        stored = self.repository.connection.execute("SELECT mid FROM videos WHERE bvid=?", (bvid,)).fetchone()
        if summary.bvid != bvid or stored[0] != summary.mid:
            raise GatewayShapeError(code="metadata_owner_conflict")
        fields = tuple(field for field in read.fields if (field.field in {"title", "pubdate", "aid"}) == (operation == "summary"))
        now = _now()
        with self.repository.transaction():
            if operation == "summary":
                self.repository.upsert_video(VideoRecord(bvid, summary.aid, summary.mid, summary.title,
                    summary.pubdate, started, now), refresh_pubdate=True)
                if summary.author is not None:
                    self.repository.upsert_user(UserRecord(summary.mid, summary.author, started, now))
            else:
                self.repository.observe_video_details(VideoDetailRecord(bvid, summary.pic, summary.desc, summary.tid, now), fields)
            self.repository.record_field_observations(bvid, operation, fields, now)
            self.repository.record_metadata_attempt(bvid, operation, "present", started, now)


__all__ = ["MetadataRefreshService", "MetadataRefreshOutcome"]
