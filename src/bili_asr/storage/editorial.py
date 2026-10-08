"""Editorial persistence adapter; workers consume frozen data, never latest files."""

from __future__ import annotations

import json
from contextlib import contextmanager
import sqlite3
import time
from typing import Any
from uuid import uuid4

from bili_asr.editorial import ARTIFACT_ROLES, TEMPLATE_VERSION, EditorialConfig, canonical, digest, language_key, prepare_input
from bili_asr.storage.database import require_editorial_schema
from bili_asr.storage.transcripts import TranscriptRepository
from bili_asr.storage.workflow import WorkflowJob


class EditorialRepository:
    def __init__(self, connection: sqlite3.Connection):
        require_editorial_schema(connection)
        self.connection = connection

    @contextmanager
    def owned_transaction(self, job: WorkflowJob):
        require_editorial_schema(self.connection)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.assert_lease(job)
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def read_source(self, transcript_id: int):
        row = self.connection.execute("SELECT * FROM transcripts WHERE transcript_id = ?", (transcript_id,)).fetchone()
        if row is None:
            raise ValueError("unknown transcript ID")
        return TranscriptRepository(self.connection).read_transcript(
            int(row["video_part_id"]), row["source_kind"], row["language"], int(row["version"]))

    def latest_sources(self, part_id: int) -> tuple[int, int | None]:
        base = self.connection.execute(
            "SELECT * FROM transcripts WHERE video_part_id = ? AND source_kind = 'asr-local' "
            "ORDER BY created_at DESC, transcript_id DESC LIMIT 1", (part_id,)).fetchone()
        if base is None:
            raise ValueError("part has no stored ASR transcript")
        return int(base["transcript_id"]), self.latest_reference(part_id, base["language"])

    def latest_reference(self, part_id: int, language: str) -> int | None:
        reference = self.connection.execute(
            "SELECT transcript_id, language FROM transcripts WHERE video_part_id = ? "
            "AND source_kind IN ('subtitle-ai', 'subtitle-cc') "
            "ORDER BY CASE source_kind WHEN 'subtitle-cc' THEN 0 ELSE 1 END, "
            "created_at DESC, transcript_id DESC", (part_id,)).fetchall()
        return next((int(row["transcript_id"]) for row in reference
                     if language_key(row["language"]) == language_key(language)), None)

    def prepare(self, base_id: int, reference_id: int | None, config: EditorialConfig) -> dict[str, Any]:
        require_editorial_schema(self.connection)
        base = self.read_source(base_id)
        prepared = prepare_input(base, self.read_source(reference_id) if reference_id else None, config,
                                 metadata=self.metadata(base.video_part_id))
        snapshot = prepared["snapshot"]
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO editorial_inputs VALUES (?, ?, ?, ?, ?, ?)",
                (prepared["input_id"], snapshot["video_part_id"], base_id, reference_id, canonical(prepared), int(time.time())))
        stored = self.load_input(prepared["input_id"])
        if stored != prepared:
            raise RuntimeError("input identity collision")
        return stored

    def load_input(self, input_id: str) -> dict[str, Any]:
        require_editorial_schema(self.connection)
        row = self.connection.execute("SELECT prepared_json FROM editorial_inputs WHERE input_id = ?", (input_id,)).fetchone()
        if row is None:
            raise ValueError("unknown editorial input")
        try:
            prepared = json.loads(row["prepared_json"])
            if prepared["input_id"] != input_id or digest(prepared["snapshot"]) != input_id:
                raise ValueError("editorial input identity mismatch")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid frozen editorial input") from exc
        return prepared

    def freeze_job_input(self, job: WorkflowJob) -> dict[str, Any]:
        row = self.connection.execute("SELECT input_id FROM editorial_job_inputs WHERE job_id = ?", (job.job_id,)).fetchone()
        if row:
            return self.load_input(row["input_id"])
        if "input_id" in job.payload:
            prepared = self.load_input(str(job.payload["input_id"]))
        else:
            # Automatic acquisition chain fixes the exact ASR prerequisite result,
            # rather than selecting whichever ASR happens to be newest on retry.
            prerequisite = self.connection.execute(
                "SELECT result_json FROM workflow_attempts WHERE job_id = ? AND outcome = 'succeeded' "
                "ORDER BY finished_at DESC, rowid DESC LIMIT 1", (job.payload["asr_job_id"],)).fetchone()
            if prerequisite is None:
                raise ValueError("ASR prerequisite result is missing")
            base_id = int(json.loads(prerequisite["result_json"])["transcript_id"])
            base = self.read_source(base_id)
            reference_id = self.latest_reference(base.video_part_id, base.language)
            prepared = self.prepare(base_id, reference_id, EditorialConfig(**job.payload["editorial_config"]))
        if prepared["snapshot"]["video_part_id"] != job.video_part_id:
            raise ValueError("editorial input belongs to another video part")
        with self.owned_transaction(job):
            self.connection.execute("INSERT OR IGNORE INTO editorial_job_inputs VALUES (?, ?)", (job.job_id, prepared["input_id"]))
        return prepared

    def begin_call(self, job: WorkflowJob, input_id: str, chunk_id: str, request: dict[str, Any]) -> str:
        now, call_id = int(time.time()), uuid4().hex
        with self.owned_transaction(job):
            attempt = self.connection.execute(
                "SELECT attempt_id FROM workflow_attempts WHERE job_id = ? AND worker_id = ? AND outcome = 'running'",
                (job.job_id, job.lease_owner)).fetchone()
            if attempt is None:
                raise RuntimeError("running editorial attempt missing")
            self.connection.execute("INSERT INTO editorial_model_calls(call_id, attempt_id, input_id, chunk_id, request_json, started_at) "
                                    "VALUES (?, ?, ?, ?, ?, ?)",
                                    (call_id, attempt["attempt_id"], input_id, chunk_id, canonical(request), now))
        return call_id

    def finish_call(self, call_id: str, response: dict[str, Any] | None, error_code: str | None = None) -> None:
        require_editorial_schema(self.connection)
        with self.connection:
            self.connection.execute("UPDATE editorial_model_calls SET response_json = ?, error_code = ?, finished_at = ? WHERE call_id = ?",
                                    (None if response is None else canonical(response), error_code, int(time.time()), call_id))

    def assert_lease(self, job: WorkflowJob) -> None:
        row = self.connection.execute("SELECT status, lease_owner, lease_expires_at, attempt_count FROM workflow_jobs WHERE job_id = ?",
                                      (job.job_id,)).fetchone()
        if (row is None or row["status"] != "running" or row["lease_owner"] != job.lease_owner
                or row["attempt_count"] != job.attempt_count or row["lease_expires_at"] <= int(time.time())):
            raise RuntimeError("editorial lease was lost")

    def chunk_result(self, input_id: str, chunk_id: str) -> list[dict[str, Any]] | None:
        require_editorial_schema(self.connection)
        row = self.connection.execute("SELECT blocks_json FROM editorial_chunk_results WHERE input_id = ? AND chunk_id = ?",
                                      (input_id, chunk_id)).fetchone()
        return json.loads(row["blocks_json"]) if row else None

    def save_chunk(self, job: WorkflowJob, input_id: str, chunk_id: str, call_id: str, blocks: list[dict[str, Any]]) -> None:
        with self.owned_transaction(job):
            self.connection.execute("INSERT OR IGNORE INTO editorial_chunk_results VALUES (?, ?, ?, ?)",
                                    (input_id, chunk_id, call_id, canonical(blocks)))

    def commit_revision(self, job: WorkflowJob, prepared: dict[str, Any]) -> str:
        blocks = []
        for chunk in prepared["chunks"]:
            result = self.chunk_result(prepared["input_id"], chunk["chunk_id"])
            if result is None:
                raise ValueError("cannot commit an incomplete editorial revision")
            blocks.extend(result)
        expected = [s["segment_id"] for s in prepared["snapshot"]["base"]["segments"]]
        if [segment_id for b in blocks for segment_id in b["segment_ids"]] != expected:
            raise ValueError("revision does not cover the exact base segment order")
        revision_id = digest({"input_id": prepared["input_id"], "blocks": blocks})
        needs_review = any(b["issues"] for b in blocks) or prepared["snapshot"]["unassigned_reference_ids"]
        with self.owned_transaction(job):
            self.connection.execute("INSERT OR IGNORE INTO editorial_revisions VALUES (?, ?, ?, ?, ?, ?)",
                                    (revision_id, prepared["input_id"], job.job_id, canonical(blocks),
                                     "needs-review" if needs_review else "ai-unreviewed", int(time.time())))
        return revision_id

    def revision(self, revision_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        require_editorial_schema(self.connection)
        row = self.connection.execute("SELECT * FROM editorial_revisions WHERE revision_id = ?", (revision_id,)).fetchone()
        if row is None:
            raise ValueError("unknown editorial revision")
        prepared = self.load_input(row["input_id"])
        try:
            blocks = json.loads(row["blocks_json"])
            if digest({"input_id": row["input_id"], "blocks": blocks}) != revision_id:
                raise ValueError("editorial revision identity mismatch")
        except json.JSONDecodeError as exc:
            raise ValueError("invalid frozen editorial revision") from exc
        return prepared, blocks

    def revision_for_job(self, job_id: str) -> str:
        require_editorial_schema(self.connection)
        row = self.connection.execute("SELECT revision_id FROM editorial_revisions WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            # Different jobs may share the same immutable input/checkpoints.
            row = self.connection.execute("SELECT r.revision_id FROM editorial_revisions r JOIN editorial_job_inputs i "
                                          "ON r.input_id = i.input_id WHERE i.job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("proofreading revision not committed")
        return str(row["revision_id"])

    def metadata(self, part_id: int) -> dict[str, Any]:
        row = self.connection.execute("SELECT p.bvid, p.page_index, v.title FROM video_parts p "
                                      "JOIN videos v ON v.bvid = p.bvid WHERE p.video_part_id = ?", (part_id,)).fetchone()
        if row is None:
            raise ValueError("unknown video part")
        return dict(row)

    def preflight_artifacts(self, revision_id: str, template: str, artifacts: dict[str, tuple[str, str]]) -> None:
        """Check the complete fixed pair before a renderer writes any bytes."""
        require_editorial_schema(self.connection)
        if template != TEMPLATE_VERSION or set(artifacts) != set(ARTIFACT_ROLES):
            raise ValueError("unsupported document artifact contract")
        prepared, _ = self.revision(revision_id)
        part_id = prepared["snapshot"]["video_part_id"]
        prefix = f"documents/part-{part_id}/{revision_id}/{TEMPLATE_VERSION}"
        for name, (path, sha256) in artifacts.items():
            if (path != f"{prefix}/{name}" or len(sha256) != 64
                    or any(c not in "0123456789abcdef" for c in sha256)):
                raise ValueError("invalid document artifact identity")
            row = self.connection.execute("SELECT * FROM document_artifacts WHERE revision_id = ? "
                                          "AND template_version = ? AND artifact_name = ?", (revision_id, template, name)).fetchone()
            if row and (row["relative_path"] != path or row["content_sha256"] != sha256
                        or row["manuscript_role"] != ARTIFACT_ROLES[name]):
                raise ValueError("document content drift requires a new template version")
            owner = self.connection.execute("SELECT revision_id, template_version, artifact_name "
                                            "FROM document_artifacts WHERE relative_path = ?", (path,)).fetchone()
            if owner and tuple(owner) != (revision_id, template, name):
                raise ValueError("document artifact path belongs to another identity")

    def record_artifacts(self, revision_id: str, template: str, artifacts: dict[str, tuple[str, str]]) -> None:
        # The rendering worker owns the surrounding fenced transaction.
        self.preflight_artifacts(revision_id, template, artifacts)
        for name, (path, sha256) in artifacts.items():
            self.connection.execute(
                "INSERT OR IGNORE INTO document_artifacts "
                "(revision_id, template_version, artifact_name, manuscript_role, relative_path, content_sha256) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (revision_id, template, name, ARTIFACT_ROLES[name], path, sha256))
