"""Pure producer policies and dependency graphs, independent of SQLite."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from bili_asr.editorial import EditorialConfig, TEMPLATE_VERSION
from bili_asr.workflow_models import AsrPolicy, JobKind


@dataclass(frozen=True)
class PlanningPart:
    video_part_id: int
    quality_score: float | None = None
    reference_transcript_id: int | None = None


@dataclass(frozen=True)
class JobSpec:
    key: str
    kind: JobKind
    video_part_id: int
    payload: Mapping[str, Any]
    dedupe_key: str | None = None
    profile_id: int | None = None
    policy_key: str | None = None
    prerequisites: tuple[str, ...] = ()
    payload_references: tuple[tuple[str, str], ...] = ()

    def materialize(self, job_ids: Mapping[str, str]) -> tuple[dict[str, Any], str]:
        payload = dict(self.payload)
        payload.update((name, job_ids[key]) for name, key in self.payload_references)
        if self.dedupe_key is not None:
            return payload, self.dedupe_key
        if self.kind is JobKind.PROOFREAD:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
            return payload, f"proofread:{self.video_part_id}:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"
        if self.kind is JobKind.RENDER_DOCUMENT:
            return payload, f"render:{payload['proofread_job_id']}:{payload['template_version']}"
        raise ValueError(f"missing dedupe key for {self.kind}")


def editorial_specs(part_id: int, payload: Mapping[str, Any], *,
                    prerequisite: str | None = None) -> tuple[JobSpec, JobSpec]:
    proof_key = f"proofread:{part_id}"
    render_key = f"render:{part_id}"
    return (
        JobSpec(proof_key, JobKind.PROOFREAD, part_id, payload,
                prerequisites=() if prerequisite is None else (prerequisite,),
                payload_references=() if prerequisite is None else (("asr_job_id", prerequisite),)),
        JobSpec(render_key, JobKind.RENDER_DOCUMENT, part_id, {"template_version": TEMPLATE_VERSION},
                prerequisites=(proof_key,), payload_references=(("proofread_job_id", proof_key),)),
    )


def plan_producers(parts: Sequence[PlanningPart], *, policy: AsrPolicy, profile_id: int,
                   profile_digest: str, quality_threshold: float | None = None,
                   editorial_config: Mapping[str, Any] | None = None) -> tuple[JobSpec, ...]:
    if not isinstance(policy, AsrPolicy):
        raise ValueError("unsupported ASR policy")
    if policy is AsrPolicy.BELOW_THRESHOLD and (
            quality_threshold is None or not 0.0 <= quality_threshold <= 1.0):
        raise ValueError("quality_threshold must be between 0 and 1")
    if editorial_config is not None:
        # Validation belongs to the policy boundary, before any jobs are written.
        EditorialConfig(**editorial_config)
    specs: list[JobSpec] = []
    for part in parts:
        part_id = part.video_part_id
        subtitle_key, audio_key, asr_key = (f"{kind}:{part_id}" for kind in ("subtitle", "audio", "asr"))
        specs.append(JobSpec(subtitle_key, JobKind.SUBTITLE, part_id,
                             {"video_part_id": part_id}, dedupe_key=subtitle_key))
        if policy is AsrPolicy.BELOW_THRESHOLD and (
                part.quality_score is None or part.quality_score >= float(quality_threshold)):
            continue
        specs.append(JobSpec(audio_key, JobKind.AUDIO, part_id,
                             {"video_part_id": part_id}, dedupe_key=audio_key))
        specs.append(JobSpec(
            asr_key, JobKind.ASR, part_id,
            {"video_part_id": part_id, "profile_id": profile_id,
             "reference_transcript_id": part.reference_transcript_id},
            dedupe_key=f"asr:{part_id}:{profile_digest}", profile_id=profile_id,
            policy_key=policy.value, prerequisites=(audio_key,),
        ))
        if editorial_config is not None:
            specs.extend(editorial_specs(part_id, {"editorial_config": dict(editorial_config)}, prerequisite=asr_key))
    return tuple(specs)
