"""Concrete, per-invocation handlers for the workflow control plane.

This adapter holds only short-lived clients and model runners.  Durable state
is written exclusively through the metadata/transcript repositories and the
workflow repository; a later worker can therefore resume any job independently.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from bili_asr import archive, asr, audio, bili_client
from bili_asr.artifact_root import ArtifactRoots, usable_audio_path, resolve_audio_path
from bili_asr.formatting import duration_s_from_ms, pubdate_utc
from bili_asr.page_identity import PageIdentity, artifact_stem
from bili_asr.path_policy import confined_audio_path
from bili_asr.services.subtitle_ingest import SubtitleIngestor, SubtitleSelection
from bili_asr.services.transcript_projection import ordered_candidates, writer_segments
from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
from bili_asr.storage import (
    AcquisitionRunRecord,
    TranscriptRepository,
    TranscriptSegmentRecord,
)
from bili_asr.storage.workflow import (
    AsrProfile,
    JobKind,
    WorkflowJob,
    WorkflowRepository,
)


class ArchiveWorkflowHandlers:
    """Build concrete handlers without giving them scheduling responsibilities."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        repository: WorkflowRepository,
        *,
        archive_root: str | os.PathLike[str],
        sessdata: str | None,
        artifact_roots: ArtifactRoots | None = None,
    ) -> None:
        self.connection = connection
        self.repository = repository
        self.artifact_roots = artifact_roots or ArtifactRoots.of(archive_root)
        self.archive_root = self.artifact_roots.archive_root
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self.sessdata = sessdata
        self._client: bili_client.BiliClient | None = None
        self._runners: dict[int, asr.ASRRunner] = {}

    def handlers(self) -> Mapping[JobKind, Any]:
        return {
            JobKind.SUBTITLE: self.subtitle,
            JobKind.AUDIO: self.audio,
            JobKind.ASR: self.local_asr,
            JobKind.PUBLISH: self.publish,
        }

    def close(self) -> None:
        for runner in self._runners.values():
            runner.release()
        self._runners.clear()

    def subtitle(self, job: WorkflowJob) -> Mapping[str, Any]:
        self.repository.assert_lease(job)
        part = self._part(job)
        ingestor = SubtitleIngestor(
            BilibiliApiGateway(sessdata=self.sessdata),
            TranscriptRepository(self.connection, write_guard=lambda: self.repository.assert_lease(job)),
            credential_present=self.sessdata is not None,
            checkpoint=lambda: self.repository.assert_lease(job),
        )
        result = ingestor.harvest(
            SubtitleSelection(
                bvid=str(part["bvid"]),
                page_index=int(part["page_index"]),
                limit=1,
            )
        )
        outcome = result.parts[0] if result.parts else None
        if outcome is None or outcome.outcome == "failed":
            raise RuntimeError(outcome.error_code if outcome is not None else "subtitle_empty")
        publication_job_id = None
        if outcome.source_kind is not None and outcome.language is not None and outcome.version is not None:
            transcript = self.connection.execute(
                """SELECT transcript_id FROM transcripts
                   WHERE video_part_id = ? AND source_kind = ? AND language = ? AND version = ?""",
                (int(part["video_part_id"]), outcome.source_kind, outcome.language, outcome.version),
            ).fetchone()
            if transcript is not None:
                publication_job_id, _ = self.repository.request_publication(
                    video_part_id=int(part["video_part_id"]),
                    transcript_id=int(transcript["transcript_id"]),
                    source_job=job,
                )
        return {
            "run_id": result.run_id,
            "outcome": outcome.outcome,
            "source": outcome.source_kind,
            "publication_job_id": publication_job_id,
        }

    def audio(self, job: WorkflowJob) -> Mapping[str, Any]:
        self.repository.assert_lease(job)
        part = self._part(job)
        identity = PageIdentity(
            work_id=f"{part['bvid']}:p{part['page_index']}",
            bvid=str(part["bvid"]),
            page_index=int(part["page_index"]),
            cid=int(part["cid"]),
            page_label=str(part["title"]),
        )
        relative = f"audio/{artifact_stem(identity)}.m4a"
        target = confined_audio_path(self.artifact_roots.write_base, relative, require_exists=False)
        if target is None:
            raise OSError("invalid audio path")
        existing = usable_audio_path(self.artifact_roots, [relative, relative.removesuffix(".m4a") + ".flac"])
        if existing is not None:
            return self._store_audio(job, part, existing[2], existing[2])
        client = self._client or bili_client.BiliClient(sessdata=self.sessdata)
        self._client = client
        self.repository.assert_lease(job)
        with tempfile.TemporaryDirectory(prefix=".workflow-audio-", dir=target.parent) as staging:
            staged_audio = Path(staging) / "audio"
            staged_audio.mkdir()
            return self._download_audio(job, part, client, identity, staged_audio / target.name, target)

    def _download_audio(self, job, part, client, identity, staged_target: Path, target: Path):
        staging_roots = ArtifactRoots.of(staged_target.parent.parent)
        final = Path(audio.download_audio(client, identity, staged_target, artifact_roots=staging_roots))
        # The downloader may keep a FLAC stream when ffmpeg is unavailable.
        target = target.with_suffix(final.suffix)
        return self._store_audio(job, part, final, target)

    def _store_audio(self, job, part, final: Path, target: Path):
        self.repository.assert_lease(job)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", os.fspath(final)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        duration_s = float(json.loads(probe.stdout)["format"]["duration"])
        if not math.isfinite(duration_s) or duration_s <= 0:
            raise RuntimeError("invalid_audio_duration")
        duration_ms = max(1, round(duration_s * 1000))
        digest = hashlib.sha256(final.read_bytes()).hexdigest()
        self.repository.assert_lease(job)
        storage_key = next(target.relative_to(base).as_posix()
                           for base in self.artifact_roots.read_bases() if target.is_relative_to(base))
        now = int(time.time())
        byte_size = final.stat().st_size
        media_format = final.suffix.removeprefix(".")
        with self.repository.owned_transaction(job):
            if final != target:
                os.replace(final, target)
            self.connection.execute(
                """INSERT INTO audio_objects(sha256, byte_size, format, duration_ms, storage_key, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(sha256) DO UPDATE SET duration_ms = excluded.duration_ms""",
                (digest, byte_size, media_format, duration_ms, storage_key, now),
            )
            audio_id = self.connection.execute(
                "SELECT audio_id FROM audio_objects WHERE sha256 = ?", (digest,)
            ).fetchone()["audio_id"]
            self.connection.execute(
                """INSERT OR IGNORE INTO part_audio_objects(video_part_id, audio_id, acquired_at, acquisition_source)
                   VALUES (?, ?, ?, 'workflow')""",
                (int(part["video_part_id"]), audio_id, now),
            )
        return {"storage_key": storage_key, "sha256": digest, "duration_ms": duration_ms}

    def local_asr(self, job: WorkflowJob) -> Mapping[str, Any]:
        self.repository.assert_lease(job)
        if job.profile_id is None:
            raise RuntimeError("missing_profile")
        part = self._part(job)
        audio_result = self.repository.dependency_result(job, JobKind.AUDIO)
        storage_key = audio_result.get("storage_key")
        if not isinstance(storage_key, str) or not storage_key:
            raise RuntimeError("audio_result_missing_storage_key")
        audio_path = resolve_audio_path(self.artifact_roots, storage_key)
        if audio_path is None:
            raise RuntimeError("audio_missing")
        profile = self.repository.profile(job.profile_id)
        config = profile.asr_config()
        reference_id = job.payload.get("reference_transcript_id")
        paired_text = self._paired_subtitle_text(
            None if reference_id is None else int(reference_id)
        )
        started = int(time.time())
        run_id = str(uuid4())
        transcripts = TranscriptRepository(self.connection, write_guard=lambda: self.repository.assert_lease(job))
        transcripts.start_acquisition_run(
            AcquisitionRunRecord(
                run_id=run_id,
                kind="asr",
                selector_kind="bvid",
                selector_target=str(part["bvid"]),
                requested_limit=1,
                credential_present=False,
                started_at=started,
            )
        )
        try:
            self.repository.assert_lease(job)
            diagnostics: dict[str, Any] = {}
            if profile.device.casefold().startswith(("cuda", "rocm")):
                segments, provenance, coverage = asr.transcribe_with_timeout(
                    config,
                    os.fspath(audio_path),
                    paired_subtitle_text=paired_text,
                    timeout_seconds=config.inference_timeout_seconds,
                    diagnostics_sink=diagnostics,
                )
                language = asr.provenance_language(provenance)
            else:
                runner = self._runner(job.profile_id)
                segments = asr.two_pass_transcribe(
                    runner, os.fspath(audio_path), paired_subtitle_text=paired_text
                )
                provenance = runner.provenance()
                language = asr.provenance_language(provenance)
                coverage = asr.transcribed_coverage(runner)
                diagnostics_reader = getattr(runner, "diagnostics", None)
                if callable(diagnostics_reader):
                    diagnostics = diagnostics_reader()
            self.repository.assert_lease(job)
            records = tuple(
                TranscriptSegmentRecord(
                    start_ms=int(round(float(cue["start"]) * 1000)),
                    end_ms=int(round(float(cue["end"]) * 1000)),
                    text=str(cue["text"]),
                )
                for cue in segments
            )
            if not records:
                raise RuntimeError("empty_transcript")
            finished = int(time.time())
            stored = transcripts.record_local_transcript(
                run_id=run_id,
                video_part_id=int(part["video_part_id"]),
                language=language,
                segments=records,
                model_name=profile.model_name,
                model_revision=profile.model_revision,
                started_at=started,
                finished_at=finished,
                created_at=finished,
                coverage=coverage,
                asr_evidence={
                    "schema_version": 1,
                    "profile_id": job.profile_id,
                    "config_sha256": self.repository.profile_digest(job.profile_id),
                    "reference_transcript_id": reference_id,
                    "audio": dict(audio_result),
                    "provenance": provenance,
                    "diagnostics": diagnostics,
                },
            )
            transcripts.finish_acquisition_run(run_id, int(time.time()))
        except BaseException:
            transcripts.finish_acquisition_run(
                run_id, int(time.time()), outcome="failed"
            )
            raise
        publication_job_id, _ = self.repository.request_publication(
            video_part_id=int(part["video_part_id"]), transcript_id=stored.transcript_id, source_job=job,
        )
        return {
            "run_id": run_id,
            "transcript_id": stored.transcript_id,
            "version": stored.version,
            "source_kind": "asr-local",
            "publication_job_id": publication_job_id,
            "quality": diagnostics.get("quality", {"status": "not-evaluable", "flags": []}),
        }

    def publish(self, job: WorkflowJob) -> Mapping[str, Any]:
        """Project the currently preferred stored transcript into an archive bundle."""
        self.repository.assert_lease(job)
        if job.video_part_id is None:
            raise RuntimeError("missing_video_part")
        rows = self.connection.execute(
            """SELECT vp.video_part_id, vp.bvid, vp.page_index, vp.cid,
                      vp.title AS part_title, vp.duration_ms, v.pubdate, v.title AS video_title,
                      t.transcript_id, t.source_kind, t.language, t.model_id,
                      t.version, t.content_sha256, t.created_at
               FROM transcripts AS t
               JOIN video_parts AS vp ON vp.video_part_id = t.video_part_id
               JOIN videos AS v ON v.bvid = vp.bvid
               WHERE t.video_part_id = ?
               ORDER BY t.video_part_id, t.source_kind, t.language, t.version DESC""",
            (job.video_part_id,),
        ).fetchall()
        candidates = ordered_candidates(rows)
        if len(candidates) != 1:
            raise RuntimeError("transcript_missing")
        candidate = candidates[0]
        transcript_id = int(candidate.transcript["transcript_id"])
        segment_rows = self.connection.execute(
            """SELECT start_ms, end_ms, text FROM transcript_segments
               WHERE transcript_id = ? ORDER BY ordinal""",
            (transcript_id,),
        ).fetchall()
        segments = writer_segments(
            tuple(
                TranscriptSegmentRecord(
                    start_ms=int(row["start_ms"]), end_ms=int(row["end_ms"]), text=str(row["text"])
                )
                for row in segment_rows
            )
        )
        part = candidate.part
        source_kind = str(candidate.transcript["source_kind"])
        entry = {
            "bvid": part["bvid"],
            "cid": part["cid"],
            "page_index": part["page_index"],
            "work_id": candidate.work_id,
            "title": part["part_title"],
            "video_title": part["video_title"],
            "duration_s": duration_s_from_ms(int(part["duration_ms"])),
            "pubdate_str": pubdate_utc(int(part["pubdate"])),
        }
        asr_provenance = None
        if source_kind == "asr-local":
            model = self.connection.execute(
                """SELECT model_name, revision FROM asr_models
                   WHERE model_id = ?""",
                (candidate.transcript["model_id"],),
            ).fetchone()
            asr_provenance = {
                "model": str(model["model_name"]) if model is not None else "unknown",
                "revision": str(model["revision"]) if model is not None else "",
            }
        paths = {key: os.path.relpath(path, self.artifact_roots.write_base).replace(os.sep, "/")
                 for key, path in archive.bundle_paths(self.artifact_roots.write_base, entry).items()}

        @contextmanager
        def publication_guard(invalidate):
            # Marker, final bytes and publication fact share cancellation's lock.
            # The writer invalidates the marker if this transaction cannot commit.
            with self.repository.owned_transaction(job, on_rollback=invalidate):
                yield
                self.connection.execute(
                    """INSERT INTO workflow_publications(
                           video_part_id, transcript_id, published_at, artifact_json
                       ) VALUES (?, ?, ?, ?)
                       ON CONFLICT(video_part_id, transcript_id) DO UPDATE SET
                           published_at = excluded.published_at, artifact_json = excluded.artifact_json""",
                    (int(part["video_part_id"]), transcript_id, int(time.time()),
                     json.dumps(paths, ensure_ascii=False, separators=(",", ":"))),
                )

        paths = archive.write_archive(
            self.artifact_roots.write_base,
            entry,
            segments,
            source="asr" if source_kind == "asr-local" else "subtitle",
            asr_provenance=asr_provenance,
            before_replace=lambda: self.repository.assert_lease(job),
            publication_guard=publication_guard,
        )
        return {
            "requested_transcript_id": int(job.payload["transcript_id"]),
            "transcript_id": transcript_id,
            "source_kind": source_kind,
            **paths,
        }

    def _runner(self, profile_id: int) -> asr.ASRRunner:
        existing = self._runners.get(profile_id)
        if existing is not None:
            return existing
        profile: AsrProfile = self.repository.profile(profile_id)
        runner = asr.ASRRunner(profile.asr_config())
        self._runners[profile_id] = runner
        return runner

    def _part(self, job: WorkflowJob) -> sqlite3.Row:
        if job.video_part_id is None:
            raise RuntimeError("missing_video_part")
        row = self.connection.execute(
            "SELECT video_part_id, bvid, page_index, cid, title FROM video_parts WHERE video_part_id = ?",
            (job.video_part_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("unknown_video_part")
        return row

    def _paired_subtitle_text(self, transcript_id: int | None) -> str | None:
        if transcript_id is None:
            return None
        rows = self.connection.execute(
            """
            SELECT ts.text FROM transcripts AS t
            JOIN transcript_segments AS ts ON ts.transcript_id = t.transcript_id
            WHERE t.transcript_id = ?
            ORDER BY ts.ordinal
            """,
            (transcript_id,),
        ).fetchall()
        return "".join(str(row["text"]) for row in rows) or None
