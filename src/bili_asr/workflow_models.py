"""Immutable workflow descriptions shared by planning, execution and storage."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


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


class JobCancelledError(LeaseLostError):
    """The cancellation transaction has revoked this attempt's ownership."""


@dataclass(frozen=True)
class CancellationResult:
    job_id: str
    previous_status: str
    status: str
    changed: bool


@dataclass(frozen=True)
class AsrProfile:
    profile_key: str
    model_name: str
    model_revision: str = ""
    aligner_name: str = "Qwen/Qwen3-ForcedAligner-0.6B-hf"
    device: str = "cuda"
    language: str | None = None
    aligner_revision: str | None = None
    chunk_seconds: float = 180.0
    inference_timeout_seconds: float = 1800.0
    hotwords: tuple[str, ...] = ()
    offline: bool = True
    model_id: str | None = None
    tokens_per_second: float = 8.0
    min_new_tokens: int = 256
    second_pass_use_cache: bool = False
    model_dtype: str = "bfloat16"
    aligner_dtype: str = "bfloat16"
    asr_batch_size: int = 1
    aligner_batch_size: int = 1
    batch_max_audio_seconds: float = 360.0
    batch_max_input_bytes: int = 64 * 1024**2
    batch_max_tokens: int = 8192

    def asr_config(self):
        """Reconstruct the frozen configuration without consulting the environment."""
        from bili_asr.asr.config import ASRConfig

        values = asdict(self)
        values.pop("profile_key")
        values["model_revision"] = self.model_revision or None
        ASRConfig(**values)  # Reject bool/string values before numeric normalization.
        for name in ("chunk_seconds", "inference_timeout_seconds", "tokens_per_second", "batch_max_audio_seconds"):
            values[name] = float(values[name])
        return ASRConfig(**values)

    def canonical(self) -> str:
        self.asr_config()  # Validate before hashing or persisting a profile.
        values = asdict(self)
        values.pop("profile_key")
        # Default profiles retain their exact v2 bytes and digest. Explicit
        # precision is a versioned extension inside the existing v2 envelope.
        precision = {name: values.pop(name) for name in ("model_dtype", "aligner_dtype")}
        if any(value != "bfloat16" for value in precision.values()):
            values["precision"] = {"schema_version": 1, **precision}
        batch_defaults = {"asr_batch_size": 1, "aligner_batch_size": 1, "batch_max_audio_seconds": 360.0,
                          "batch_max_input_bytes": 64 * 1024**2, "batch_max_tokens": 8192}
        batching = {name: values.pop(name) for name in batch_defaults}
        batching["batch_max_audio_seconds"] = float(batching["batch_max_audio_seconds"])
        if batching != batch_defaults:
            values["batching"] = {"schema_version": 1, **batching}
        for name in ("chunk_seconds", "inference_timeout_seconds", "tokens_per_second"):
            values[name] = float(values[name])
        return json.dumps(
            {"schema_version": 2, **values},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
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



