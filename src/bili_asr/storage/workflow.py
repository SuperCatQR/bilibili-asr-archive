"""SQLite-backed workflow control plane for independent archive producers.

The repository contains no network, filesystem, model, or global-process
state.  Workers claim immutable job descriptions, execute outside the
transaction, and report a terminal attempt afterwards.  This keeps scheduling
recoverable without allowing a subtitle observation to suppress local ASR.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import sqlite3
import time
from typing import Any, Iterable, Mapping
from uuid import uuid4


class JobKind(StrEnum):
    SUBTITLE = "subtitle"
    AUDIO = "audio"
    ASR = "asr"
    PUBLISH = "publish"
    INDEX = "index"
    PROOFREAD = "proofread"
    RENDER_DOCUMENT = "render_document"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AsrPolicy(StrEnum):
    ALL = "all"
    SELECTED = "selected"
    BELOW_THRESHOLD = "below-threshold"


class LeaseLostError(RuntimeError):
    """A superseded worker cannot report an authoritative terminal result."""


@dataclass(frozen=True)
class AsrProfile:
    profile_key: str
    model_name: str
    model_revision: str = ""
    aligner_name: str = "Qwen/Qwen3-ForcedAligner-0.6B-hf"
    device: str = "cuda"
    language: str | None = None

    def canonical(self) -> str:
        return json.dumps(
            {
                "aligner_name": self.aligner_name,
                "device": self.device,
                "language": self.language,
                "model_name": self.model_name,
                "model_revision": self.model_revision,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


@dataclass(frozen=True)
class WorkflowJob:
    job_id: str
    kind: JobKind
    video_part_id: int | None
    profile_id: int | None
    policy_key: str | None
    payload: Mapping[str, Any]
    status: JobStatus
    attempt_count: int
    lease_owner: str | None = None


@dataclass(frozen=True)
class WorkflowPlan:
    subtitle_jobs: int
    audio_jobs: int
    asr_jobs: int
    proofread_jobs: int = 0
    document_jobs: int = 0


def _now() -> int:
    return int(time.time())


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class WorkflowRepository:
    """Control-plane persistence with explicit job dependencies."""

    def __init__(self, connection: sqlite3.Connection):
        if connection.row_factory is None:
            raise TypeError("connection must return sqlite3.Row objects")
        self.connection = connection

    def register_profile(self, profile: AsrProfile) -> int:
        if not isinstance(profile, AsrProfile):
            raise TypeError("profile must be AsrProfile")
        if not profile.profile_key.strip() or not profile.model_name.strip():
            raise ValueError("profile_key and model_name must be non-empty")
        digest = hashlib.sha256(profile.canonical().encode("utf-8")).hexdigest()
        now = _now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO workflow_asr_profiles(
                    profile_key, model_name, model_revision, aligner_name, device,
                    language, config_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_key) DO UPDATE SET
                    model_name = excluded.model_name,
                    model_revision = excluded.model_revision,
                    aligner_name = excluded.aligner_name,
                    device = excluded.device,
                    language = excluded.language,
                    config_sha256 = excluded.config_sha256
                """,
                (
                    profile.profile_key,
                    profile.model_name,
                    profile.model_revision,
                    profile.aligner_name,
                    profile.device,
                    profile.language,
                    digest,
                    now,
                ),
            )
            row = self.connection.execute(
                "SELECT profile_id FROM workflow_asr_profiles WHERE profile_key = ?",
                (profile.profile_key,),
            ).fetchone()
        return int(row["profile_id"])

    def plan(
        self,
        *,
        part_ids: Iterable[int],
        policy: AsrPolicy,
        profile_id: int | None = None,
        quality_threshold: float | None = None,
        editorial_config: Mapping[str, Any] | None = None,
    ) -> WorkflowPlan:
        """Create independent producer jobs for selected video parts.

        Every selected part receives a subtitle job.  ASR policy independently
        chooses ASR jobs; each selected ASR job gets an audio prerequisite.
        No subtitle state appears in this decision or dependency graph.
        """
        ids = tuple(dict.fromkeys(int(part_id) for part_id in part_ids))
        if not ids:
            return WorkflowPlan(0, 0, 0)
        if profile_id is None:
            raise ValueError("profile_id is required for ASR planning")
        if policy is AsrPolicy.BELOW_THRESHOLD:
            if quality_threshold is None or not 0.0 <= quality_threshold <= 1.0:
                raise ValueError("quality_threshold must be between 0 and 1")
        valid = {
            int(row["video_part_id"])
            for row in self.connection.execute(
                "SELECT video_part_id FROM video_parts WHERE video_part_id IN ("
                + ",".join("?" for _ in ids)
                + ") AND processing_status <> 'gone'",
                ids,
            )
        }
        if valid != set(ids):
            raise ValueError("part_ids contains unknown or gone video parts")
        if editorial_config is not None:
            self._require_editorial_contract()
        subtitles = audio = asr = proofread = documents = 0
        with self.connection:
            for part_id in ids:
                subtitle_id, created = self._ensure_job(
                    kind=JobKind.SUBTITLE,
                    video_part_id=part_id,
                    profile_id=None,
                    policy_key=None,
                    payload={"video_part_id": part_id},
                    dedupe_key=f"subtitle:{part_id}",
                )
                subtitles += int(created)
                if policy is AsrPolicy.BELOW_THRESHOLD and not self._below_threshold(
                    part_id, float(quality_threshold)
                ):
                    continue
                audio_id, created = self._ensure_job(
                    kind=JobKind.AUDIO,
                    video_part_id=part_id,
                    profile_id=None,
                    policy_key=None,
                    payload={"video_part_id": part_id},
                    dedupe_key=f"audio:{part_id}",
                )
                audio += int(created)
                profile_row = self.connection.execute(
                    "SELECT config_sha256 FROM workflow_asr_profiles WHERE profile_id = ?",
                    (profile_id,),
                ).fetchone()
                if profile_row is None:
                    raise ValueError("unknown ASR profile")
                profile_digest = str(profile_row["config_sha256"])
                asr_id, created = self._ensure_job(
                    kind=JobKind.ASR,
                    video_part_id=part_id,
                    profile_id=profile_id,
                    policy_key=policy.value,
                    payload={"video_part_id": part_id, "profile_id": profile_id},
                    dedupe_key=f"asr:{part_id}:{profile_digest}",
                )
                self.connection.execute(
                    """INSERT OR IGNORE INTO workflow_job_dependencies(job_id, prerequisite_job_id)
                       VALUES (?, ?)""",
                    (asr_id, audio_id),
                )
                asr += int(created)
                if editorial_config is not None:
                    _, _, p_created, d_created = self._editorial_jobs(
                        video_part_id=part_id,
                        payload={"asr_job_id": asr_id, "editorial_config": dict(editorial_config)},
                        prerequisite_job_id=asr_id,
                    )
                    proofread += int(p_created)
                    documents += int(d_created)
        return WorkflowPlan(subtitles, audio, asr, proofread, documents)

    def claim(self, worker_id: str, *, lease_seconds: int = 900,
              kinds: Iterable[JobKind] | None = None) -> WorkflowJob | None:
        if not worker_id.strip() or lease_seconds < 1:
            raise ValueError("worker_id and lease_seconds must be valid")
        now = _now()
        selected = None if kinds is None else tuple(k.value for k in kinds)
        if selected == ():
            return None
        kind_filter = "" if selected is None else " AND j.kind IN (" + ",".join("?" for _ in selected) + ")"
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                """UPDATE workflow_attempts
                   SET outcome = 'failed', finished_at = ?, error_code = 'lease_expired'
                   WHERE outcome = 'running' AND job_id IN (
                       SELECT job_id FROM workflow_jobs
                       WHERE status = 'running' AND lease_expires_at <= ?
                   )""",
                (now, now),
            )
            self.connection.execute(
                """UPDATE workflow_jobs
                   SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL,
                       updated_at = ?
                   WHERE status = 'running' AND lease_expires_at <= ?""",
                (now, now),
            )
            row = self.connection.execute(
                """
                SELECT j.* FROM workflow_jobs AS j
                WHERE j.status = 'queued' AND j.available_at <= ?
                  AND NOT EXISTS (
                    SELECT 1 FROM workflow_job_dependencies AS d
                    JOIN workflow_jobs AS prerequisite ON prerequisite.job_id = d.prerequisite_job_id
                    WHERE d.job_id = j.job_id AND prerequisite.status <> 'succeeded'
                  )
                """ + kind_filter + """
                ORDER BY j.priority DESC, j.created_at, j.job_id
                LIMIT 1
                """,
                (now, *(selected or ())),
            ).fetchone()
            if row is None:
                self.connection.commit()
                return None
            attempt_id = str(uuid4())
            self.connection.execute(
                """UPDATE workflow_jobs
                   SET status = 'running', lease_owner = ?, lease_expires_at = ?,
                       attempt_count = attempt_count + 1, updated_at = ?
                   WHERE job_id = ? AND status = 'queued'""",
                (worker_id, now + lease_seconds, now, row["job_id"]),
            )
            self.connection.execute(
                """INSERT INTO workflow_attempts(attempt_id, job_id, worker_id, started_at, outcome)
                   VALUES (?, ?, ?, ?, 'running')""",
                (attempt_id, row["job_id"], worker_id, now),
            )
            claimed = self.connection.execute(
                "SELECT * FROM workflow_jobs WHERE job_id = ?", (row["job_id"],)
            ).fetchone()
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return self._job_from_row(claimed)

    def renew_lease(self, job: WorkflowJob, *, lease_seconds: int) -> None:
        now = _now()
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE workflow_jobs SET lease_expires_at = ?, updated_at = ? "
                "WHERE job_id = ? AND status = 'running' AND lease_owner = ? "
                "AND attempt_count = ? AND lease_expires_at > ?",
                (now + lease_seconds, now, job.job_id, job.lease_owner, job.attempt_count, now))
            if cursor.rowcount != 1:
                raise LeaseLostError("job lease was lost")

    def _require_editorial_contract(self) -> None:
        row = self.connection.execute("SELECT sql FROM sqlite_master WHERE name = 'workflow_jobs'").fetchone()
        if row is None or "'proofread'" not in row["sql"]:
            raise ValueError("workflow schema predates AI proofreading; use a rebuilt archive database")

    def request_editorial(self, *, video_part_id: int, input_id: str) -> tuple[str, str, bool, bool]:
        self._require_editorial_contract()
        with self.connection:
            return self._editorial_jobs(video_part_id=video_part_id, payload={"input_id": input_id})

    def _editorial_jobs(self, *, video_part_id: int, payload: Mapping[str, Any],
                        prerequisite_job_id: str | None = None) -> tuple[str, str, bool, bool]:
        from bili_asr.editorial import TEMPLATE_VERSION

        digest = hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()
        proof_id, created = self._ensure_job(
            kind=JobKind.PROOFREAD, video_part_id=video_part_id, profile_id=None,
            policy_key=None, payload=payload, dedupe_key=f"proofread:{video_part_id}:{digest}")
        if prerequisite_job_id:
            self.connection.execute("INSERT OR IGNORE INTO workflow_job_dependencies VALUES (?, ?)",
                                    (proof_id, prerequisite_job_id))
        render_id, render_created = self._ensure_job(
            kind=JobKind.RENDER_DOCUMENT, video_part_id=video_part_id, profile_id=None,
            policy_key=None, payload={"proofread_job_id": proof_id, "template_version": TEMPLATE_VERSION},
            dedupe_key=f"render:{proof_id}:{TEMPLATE_VERSION}")
        self.connection.execute("INSERT OR IGNORE INTO workflow_job_dependencies VALUES (?, ?)", (render_id, proof_id))
        return proof_id, render_id, created, render_created

    def request_document(self, *, video_part_id: int, revision_id: str, template_version: str) -> tuple[str, bool]:
        self._require_editorial_contract()
        with self.connection:
            job_id, created = self._ensure_job(
                kind=JobKind.RENDER_DOCUMENT, video_part_id=video_part_id, profile_id=None, policy_key=None,
                payload={"revision_id": revision_id, "template_version": template_version},
                dedupe_key=f"render:{revision_id}:{template_version}")
            # Explicit rerender repairs missing artifacts without re-inference.
            self.connection.execute("UPDATE workflow_jobs SET status = 'queued', available_at = ?, updated_at = ? "
                                    "WHERE job_id = ? AND status IN ('succeeded', 'failed')", (_now(), _now(), job_id))
        return job_id, created

    def finish(
        self,
        job_id: str,
        *,
        worker_id: str,
        result: Mapping[str, Any] | None = None,
        expected_attempt_count: int | None = None,
    ) -> None:
        self._terminal(job_id, worker_id=worker_id, outcome="succeeded", result=result,
                       expected_attempt_count=expected_attempt_count)

    def fail(
        self,
        job_id: str,
        *,
        worker_id: str,
        error_code: str,
        retry_at: int | None = None,
        expected_attempt_count: int | None = None,
    ) -> None:
        if not error_code or len(error_code) > 64:
            raise ValueError("error_code must be 1-64 characters")
        self._terminal(
            job_id,
            worker_id=worker_id,
            outcome="failed",
            error_code=error_code,
            retry_at=retry_at,
            expected_attempt_count=expected_attempt_count,
        )

    def list_jobs(self) -> list[WorkflowJob]:
        rows = self.connection.execute(
            "SELECT * FROM workflow_jobs ORDER BY created_at, job_id"
        ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def count_by_status(self) -> dict[str, int]:
        return {
            str(row["status"]): int(row["count"])
            for row in self.connection.execute(
                "SELECT status, COUNT(*) AS count FROM workflow_jobs GROUP BY status"
            )
        }

    def requeue_failed(self, *, part_ids: Iterable[int] | None = None) -> int:
        """Make failed jobs eligible for another worker without erasing attempts."""
        ids = None if part_ids is None else tuple(dict.fromkeys(int(part_id) for part_id in part_ids))
        if ids == ():
            return 0
        now = _now()
        where = "status = 'failed'"
        values: list[Any] = [now, now]
        if ids is not None:
            where += " AND video_part_id IN (" + ",".join("?" for _ in ids) + ")"
            values.extend(ids)
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE workflow_jobs
                   SET status = 'queued', available_at = ?, lease_owner = NULL,
                       lease_expires_at = NULL, last_error_code = NULL, updated_at = ?
                   WHERE """
                + where,
                values,
            )
        return int(cursor.rowcount)

    def request_publication(
        self,
        *,
        video_part_id: int,
        transcript_id: int,
    ) -> tuple[str, bool]:
        """Queue publication for a part after a transcript version is durable.

        Publication is keyed by part, rather than by transcript version.  The
        publication worker chooses the best stored version when it runs, so a
        later local-ASR result cannot overwrite a preferred subtitle merely
        because it completed later.  A changed requested transcript reopens a
        completed publication job to let a later, better source be projected.
        """
        now = _now()
        payload = {"transcript_id": int(transcript_id), "video_part_id": int(video_part_id)}
        dedupe_key = f"publish:{video_part_id}"
        with self.connection:
            row = self.connection.execute(
                "SELECT job_id, payload_json, status FROM workflow_jobs WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            if row is None:
                job_id, created = self._ensure_job(
                    kind=JobKind.PUBLISH,
                    video_part_id=video_part_id,
                    profile_id=None,
                    policy_key=None,
                    payload=payload,
                    dedupe_key=dedupe_key,
                )
                return job_id, created
            previous = json.loads(str(row["payload_json"]))
            if int(previous.get("transcript_id", -1)) != transcript_id:
                if row["status"] == "running":
                    # Keep the current lease intact.  _terminal sees the newer
                    # request and returns this part to the queue once this
                    # attempt records its result.
                    self.connection.execute(
                        "UPDATE workflow_jobs SET payload_json = ?, updated_at = ? WHERE job_id = ?",
                        (_json(payload), now, row["job_id"]),
                    )
                else:
                    self.connection.execute(
                        """UPDATE workflow_jobs
                           SET payload_json = ?, status = 'queued', available_at = ?,
                               lease_owner = NULL, lease_expires_at = NULL,
                               last_error_code = NULL, updated_at = ?
                           WHERE job_id = ?""",
                        (_json(payload), now, now, row["job_id"]),
                    )
            return str(row["job_id"]), False

    def profile(self, profile_id: int) -> AsrProfile:
        row = self.connection.execute(
            "SELECT * FROM workflow_asr_profiles WHERE profile_id = ?", (profile_id,)
        ).fetchone()
        if row is None:
            raise ValueError("unknown ASR profile")
        return AsrProfile(
            profile_key=str(row["profile_key"]),
            model_name=str(row["model_name"]),
            model_revision=str(row["model_revision"]),
            aligner_name=str(row["aligner_name"]),
            device=str(row["device"]),
            language=row["language"],
        )

    def _ensure_job(
        self,
        *,
        kind: JobKind,
        video_part_id: int,
        profile_id: int | None,
        policy_key: str | None,
        payload: Mapping[str, Any],
        dedupe_key: str,
    ) -> tuple[str, bool]:
        now = _now()
        job_id = str(uuid4())
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO workflow_jobs(
                job_id, kind, video_part_id, profile_id, policy_key, dedupe_key,
                payload_json, status, available_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
            """,
            (job_id, kind.value, video_part_id, profile_id, policy_key, dedupe_key, _json(payload), now, now, now),
        )
        if cursor.rowcount:
            return job_id, True
        row = self.connection.execute(
            "SELECT job_id FROM workflow_jobs WHERE dedupe_key = ?", (dedupe_key,)
        ).fetchone()
        return str(row["job_id"]), False

    def _below_threshold(self, part_id: int, threshold: float) -> bool:
        row = self.connection.execute(
            """
            SELECT score FROM workflow_quality_assessments
            WHERE video_part_id = ?
            ORDER BY assessed_at DESC, assessment_id DESC LIMIT 1
            """,
            (part_id,),
        ).fetchone()
        return row is not None and float(row["score"]) < threshold

    def _terminal(
        self,
        job_id: str,
        *,
        worker_id: str,
        outcome: str,
        result: Mapping[str, Any] | None = None,
        error_code: str | None = None,
        retry_at: int | None = None,
        expected_attempt_count: int | None = None,
    ) -> None:
        now = _now()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            job = self.connection.execute(
                "SELECT status, lease_owner, kind, payload_json, attempt_count "
                "FROM workflow_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if job is None or job["status"] != "running" or job["lease_owner"] != worker_id:
                raise LeaseLostError("job is not leased by this worker")
            if expected_attempt_count is not None and job["attempt_count"] != expected_attempt_count:
                raise LeaseLostError("job lease was lost")
            current_payload = json.loads(str(job["payload_json"]))
            request_changed_while_running = (
                outcome == "succeeded"
                and job["kind"] == JobKind.PUBLISH.value
                and result is not None
                and int(current_payload.get("transcript_id", -1))
                != int(result.get("requested_transcript_id", -1))
            )
            new_status = "queued" if retry_at is not None or request_changed_while_running else outcome
            self.connection.execute(
                """UPDATE workflow_jobs
                   SET status = ?, available_at = ?, lease_owner = NULL, lease_expires_at = NULL,
                       last_error_code = ?, updated_at = ? WHERE job_id = ?""",
                (
                    new_status,
                    retry_at if retry_at is not None else now,
                    error_code,
                    now,
                    job_id,
                ),
            )
            cursor = self.connection.execute(
                """UPDATE workflow_attempts
                   SET finished_at = ?, outcome = ?, error_code = ?, result_json = ?
                   WHERE job_id = ? AND worker_id = ? AND outcome = 'running'""",
                (now, outcome, error_code, _json(result or {}), job_id, worker_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("running attempt is missing")
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> WorkflowJob:
        return WorkflowJob(
            job_id=str(row["job_id"]),
            kind=JobKind(str(row["kind"])),
            video_part_id=int(row["video_part_id"]) if row["video_part_id"] is not None else None,
            profile_id=int(row["profile_id"]) if row["profile_id"] is not None else None,
            policy_key=row["policy_key"],
            payload=json.loads(str(row["payload_json"])),
            status=JobStatus(str(row["status"])),
            attempt_count=int(row["attempt_count"]),
            lease_owner=row["lease_owner"],
        )
