"""Concrete, per-invocation handlers for the workflow control plane.

This adapter holds only short-lived clients and model runners.  Durable state
is written exclusively through the metadata/transcript repositories and the
workflow repository; a later worker can therefore resume any job independently.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import subprocess
import tempfile
import time
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from bili_asr import archive, asr, bili_client
from bili_asr.artifact_inventory import stream_hash
from bili_asr.artifact_root import ArtifactRoots, resolve_audio_path, usable_audio_path
from bili_asr.asr.session import AsrInferenceSession, InferenceRequest
from bili_asr.formatting import duration_s_from_ms, pubdate_utc
from bili_asr.page_identity import PageIdentity, artifact_stem
from bili_asr.path_policy import confined_audio_path
from bili_asr.services.subtitle_ingest import SubtitleIngestor, SubtitleSelection
from bili_asr.services.transcript_projection import ordered_candidates, writer_segments
from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
from bili_asr.sources.bilibili_source import BilibiliAudioSource
from bili_asr.storage import (
    AcquisitionRunRecord,
    TranscriptRepository,
    TranscriptSegmentRecord,
)
from bili_asr.storage.sources import SourceRepository, acquisition_selector
from bili_asr.storage.workflow import WorkflowRepository
from bili_asr.workflow import attempt_checkpoint
from bili_asr.workflow_models import JobKind, WorkflowJob
from bili_asr.workflow_payloads import decode_job_payload
from bili_asr.workflow_runtime_ports import (
    AudioClientFactory,
    ConfigResolver,
    GatewayFactory,
    InferenceSession,
    JobHandler,
    RunnerFactory,
    TimeoutTranscriber,
    WorkflowAsrRunner,
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
        gateway_factory: GatewayFactory | None = None,
        audio_client_factory: AudioClientFactory | None = None,
        runner_factory: RunnerFactory | None = None,
        timeout_transcriber: TimeoutTranscriber | None = None,
        inference_session: InferenceSession | None = None,
        gpu_session: str = "legacy",
        config_resolver: ConfigResolver | None = None,
        asr_prefetch: bool = False,
        asr_prefetch_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.connection = connection
        self.repository = repository
        self.artifact_roots = artifact_roots or ArtifactRoots.of(archive_root)
        self.archive_root = self.artifact_roots.archive_root
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self.sessdata = sessdata
        self.gateway_factory = gateway_factory or BilibiliApiGateway
        self.audio_client_factory = audio_client_factory or bili_client.BiliClient
        self.runner_factory = runner_factory or asr.ASRRunner
        self.timeout_transcriber = timeout_transcriber or asr.transcribe_with_timeout
        if gpu_session not in {"legacy", "persistent", "oneshot"}:
            raise ValueError("unknown GPU session mode")
        self.config_resolver = config_resolver or (lambda config: (config, {}))
        self.inference_session = inference_session or (
            AsrInferenceSession(persistent=gpu_session == "persistent", prefetch=asr_prefetch,
                                prefetch_bytes=asr_prefetch_bytes) if gpu_session != "legacy" else None)
        self.asr_prefetch, self.asr_prefetch_bytes = asr_prefetch, asr_prefetch_bytes
        self._client: bili_client.BiliClient | None = None
        self._runners: dict[int, WorkflowAsrRunner] = {}
        self._runner_bindings: dict[int, str] = {}

    def handlers(self) -> Mapping[JobKind, JobHandler]:
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
        self._runner_bindings.clear()
        if self.inference_session is not None:
            self.inference_session.close()

    def _inference_checkpoint(self, job: WorkflowJob) -> None:
        # Query authoritative cancellation before the heartbeat token, so the executor
        # distinguishes a cancelled job from a lease reclaimed by another attempt.
        self.repository.assert_lease(job)
        attempt_checkpoint(job)

    def subtitle(self, job: WorkflowJob) -> Mapping[str, Any]:
        from bili_asr.workflow_errors import JobExecutionError

        decode_job_payload(job)
        self.repository.assert_lease(job)
        part = self._part(job)
        ingestor = SubtitleIngestor(
            self.gateway_factory(sessdata=self.sessdata),
            TranscriptRepository(self.connection, write_transaction=lambda: self.repository.owned_transaction(job)),
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
            raise JobExecutionError(outcome.error_code or "subtitle_failed" if outcome is not None else "subtitle_empty",
                                    {"run_id": result.run_id, **(outcome.safe_details() if outcome is not None else {})})
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
            **outcome.safe_details(),
        }

    def audio(self, job: WorkflowJob) -> Mapping[str, Any]:
        decode_job_payload(job)
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
            return self.store_audio(job, part, existing[2], existing[2])
        client = self._client or self.audio_client_factory(sessdata=self.sessdata)
        self._client = client
        self.repository.assert_lease(job)
        with tempfile.TemporaryDirectory(prefix=".workflow-audio-", dir=target.parent) as staging:
            staged_audio = Path(staging) / "audio"
            staged_audio.mkdir()
            return self._download_audio(job, part, client, identity, staged_audio / target.name, target)

    def _download_audio(self, job, part, client, identity, staged_target: Path, target: Path):
        source = BilibiliAudioSource(client, resolve_part=lambda ref: identity)
        final = source.download_audio(identity.content_ref, staged_target, staging_root=staged_target.parent.parent)
        if final.suffix not in {".m4a", ".flac"}:
            raise ValueError("invalid_audio_output")
        checked = confined_audio_path(staged_target.parent.parent,
            f"audio/{staged_target.stem}{final.suffix}", require_exists=True)
        if checked is None or checked.absolute() != final.absolute():
            raise ValueError("audio_output_outside_staging")
        # The downloader may keep a FLAC stream when ffmpeg is unavailable.
        target = target.with_suffix(final.suffix)
        return self.store_audio(job, part, final, target)

    def store_audio(self, job, part, final: Path, target: Path):
        """Probe and persist a provider-owned staged audio under the lease fence."""
        self.repository.assert_lease(job)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", os.fspath(final)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        duration_s = float(json.loads(probe.stdout)["format"]["duration"])
        if not math.isfinite(duration_s) or duration_s <= 0:
            raise RuntimeError("invalid_audio_duration")
        duration_ms = max(1, round(duration_s * 1000))
        with final.open("rb") as stream:
            size_bytes, digest = stream_hash(stream)
        self.repository.assert_lease(job)
        storage_key = next(target.relative_to(base).as_posix()
                           for base in self.artifact_roots.read_bases() if target.is_relative_to(base))
        now = int(time.time())
        byte_size = size_bytes
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
        decode_job_payload(job)
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
        config, binding_identity = self.config_resolver(profile.asr_config())
        inference_request = InferenceRequest(job.job_id, job.lease_owner or "", job.attempt_count,
            self.repository.profile_digest(job.profile_id), binding_identity)
        reference_id = job.payload.get("reference_transcript_id")
        paired_text = self._paired_subtitle_text(
            None if reference_id is None else int(reference_id)
        )
        started = int(time.time())
        run_id = str(uuid4())
        selector_kind, selector_target = acquisition_selector(part)
        transcripts = TranscriptRepository(self.connection, write_transaction=lambda: self.repository.owned_transaction(job))
        transcripts.start_acquisition_run(
            AcquisitionRunRecord(
                run_id=run_id,
                kind="asr",
                selector_kind=selector_kind,
                selector_target=selector_target,
                requested_limit=1,
                credential_present=False,
                started_at=started,
            )
        )
        try:
            self.repository.assert_lease(job)
            diagnostics: dict[str, Any] = {}
            if profile.device.casefold().startswith(("cuda", "rocm")):
                infer = self.timeout_transcriber if self.inference_session is None else self.inference_session.transcribe
                session_args = {} if self.inference_session is None else {
                    "request": inference_request, "checkpoint": lambda: self._inference_checkpoint(job)}
                segments, provenance, coverage = infer(
                    config,
                    os.fspath(audio_path),
                    paired_subtitle_text=paired_text,
                    timeout_seconds=config.inference_timeout_seconds,
                    diagnostics_sink=diagnostics,
                    **session_args,
                )
                language = asr.provenance_language(provenance)
            else:
                runner = (self._runner(job.profile_id) if not binding_identity else
                          self._runner(job.profile_id, config=config, binding_request=inference_request))
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
                    start_ms=round(float(cue["start"]) * 1000),
                    end_ms=round(float(cue["end"]) * 1000),
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
                    "runtime_binding": dict(binding_identity),
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
        decode_job_payload(job)
        self.repository.assert_lease(job)
        if job.video_part_id is None:
            raise RuntimeError("missing_video_part")
        source_part = SourceRepository(self.connection).part(job.video_part_id)
        rows = [
            {**source_part, "part_title": source_part["title"], **dict(row)}
            for row in self.connection.execute(
                """SELECT * FROM transcripts WHERE video_part_id = ?
                   ORDER BY source_kind, language, version DESC""", (job.video_part_id,),
            )
        ]
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
            "pubdate_str": "" if part["pubdate"] is None else pubdate_utc(int(part["pubdate"])),
        }
        if source_part["platform"] != "bilibili":
            entry.update(platform=source_part["platform"], external_video_id=source_part["external_video_id"])
        from bili_asr.storage.archive_contracts import UNIVERSAL_V2, runtime_contract
        if runtime_contract(self.connection) == UNIVERSAL_V2:
            from bili_asr.storage.metadata import MetadataRepository
            metadata = MetadataRepository(self.connection).read_source_metadata(job.video_part_id).to_dict()
            entry.update(pubdateUnix=metadata["pubdateUnix"],
                         sourcePublishedAt=metadata["sourcePublishedAt"], sourceMetadata=metadata)
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
                # A part owns one mutable bundle slot. Same-second republishing
                # an earlier transcript must still become the newest committed
                # publication fact, independently of its original row id.
                previous = self.connection.execute(
                    "SELECT MAX(published_at) FROM workflow_publications WHERE video_part_id = ?",
                    (int(part["video_part_id"]),),
                ).fetchone()[0]
                published_at = max(int(time.time()), 0 if previous is None else int(previous) + 1)
                self.connection.execute(
                    """INSERT INTO workflow_publications(
                           video_part_id, transcript_id, published_at, artifact_json
                       ) VALUES (?, ?, ?, ?)
                       ON CONFLICT(video_part_id, transcript_id) DO UPDATE SET
                           published_at = excluded.published_at, artifact_json = excluded.artifact_json""",
                    (int(part["video_part_id"]), transcript_id, published_at,
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

    def _runner(self, profile_id: int, *, config=None, binding_request=None) -> WorkflowAsrRunner:
        existing = self._runners.get(profile_id)
        config = config or self.repository.profile(profile_id).asr_config()
        binding_request = binding_request or InferenceRequest("", "", 0, "", {})
        binding_key = AsrInferenceSession.configuration_key(config, binding_request)
        if existing is not None and self._runner_bindings.get(profile_id) != binding_key:
            existing.release()
            existing = None
        if existing is not None:
            return existing
        runner = self.runner_factory(config)
        if self.asr_prefetch:
            configure = getattr(runner, "configure_prefetch", None)
            if callable(configure):
                configure(enabled=True, max_bytes=self.asr_prefetch_bytes)
        self._runners[profile_id] = runner
        self._runner_bindings[profile_id] = binding_key
        return runner

    def _part(self, job: WorkflowJob) -> Mapping[str, Any]:
        if job.video_part_id is None:
            raise RuntimeError("missing_video_part")
        return SourceRepository(self.connection).part(job.video_part_id)

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
