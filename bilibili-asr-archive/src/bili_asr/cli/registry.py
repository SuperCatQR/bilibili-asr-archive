"""Command routing and invocation policies shared by parser and entry point.

Handler names deliberately resolve through ``bili_asr.cli`` at dispatch time:
the package attributes are the existing public monkeypatch seams.
Archive mutation describes store/manifest/state writes, independently of artifact
writes (proofreading writes products without taking the archive-state lock).
Search may refresh a derived index without mutating canonical archive state;
its READ artifact policy describes its access to the transcript artifact root.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class ArtifactPolicy(Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class CommandSpec:
    handler: str
    mutates_archive: bool
    artifacts: ArtifactPolicy
    retains_audio: bool = False

    def __post_init__(self) -> None:
        if type(self.mutates_archive) is not bool or type(self.retains_audio) is not bool:
            raise TypeError("command mutation and retention policies must be bool")
        if not isinstance(self.artifacts, ArtifactPolicy):
            raise TypeError("command artifact policy must be ArtifactPolicy")


COMMANDS = MappingProxyType({
    "workflow": CommandSpec("_cmd_workflow", mutates_archive=False, artifacts=ArtifactPolicy.NONE),
    "fetch-meta": CommandSpec("_cmd_fetch_meta", mutates_archive=True, artifacts=ArtifactPolicy.NONE),
    "status": CommandSpec("_cmd_status", mutates_archive=False, artifacts=ArtifactPolicy.NONE),
    "coverage": CommandSpec("_cmd_coverage", mutates_archive=False, artifacts=ArtifactPolicy.READ),
    "verify": CommandSpec("_cmd_verify", mutates_archive=False, artifacts=ArtifactPolicy.READ),
    "recover": CommandSpec("_cmd_recover", mutates_archive=True, artifacts=ArtifactPolicy.READ),
    "runs": CommandSpec("_cmd_runs", mutates_archive=False, artifacts=ArtifactPolicy.NONE),
    "asr": CommandSpec("_cmd_asr", mutates_archive=True, artifacts=ArtifactPolicy.WRITE, retains_audio=True),
    "pilot": CommandSpec("_cmd_pilot", mutates_archive=True, artifacts=ArtifactPolicy.WRITE, retains_audio=True),
    "probe-subs": CommandSpec("_cmd_probe_subs", mutates_archive=False, artifacts=ArtifactPolicy.NONE),
    "harvest-subs": CommandSpec("_cmd_harvest_subs", mutates_archive=True, artifacts=ArtifactPolicy.NONE),
    "derive-manifest": CommandSpec("_cmd_derive_manifest", mutates_archive=True, artifacts=ArtifactPolicy.NONE),
    "derive-audio-inventory": CommandSpec("_cmd_derive_audio_inventory", mutates_archive=True, artifacts=ArtifactPolicy.READ),
    "adopt-transcripts": CommandSpec("_cmd_adopt_transcripts", mutates_archive=True, artifacts=ArtifactPolicy.READ),
    "publish-transcripts": CommandSpec("_cmd_publish_transcripts", mutates_archive=True, artifacts=ArtifactPolicy.WRITE),
    "proofread": CommandSpec("_cmd_proofread", mutates_archive=False, artifacts=ArtifactPolicy.WRITE),
    "proofread-merge": CommandSpec("_cmd_proofread_merge", mutates_archive=False, artifacts=ArtifactPolicy.WRITE),
    "download-audio": CommandSpec("_cmd_download_audio", mutates_archive=True, artifacts=ArtifactPolicy.WRITE),
    "search": CommandSpec("_cmd_search", mutates_archive=False, artifacts=ArtifactPolicy.READ),
    "search-index": CommandSpec("_cmd_search_index", mutates_archive=False, artifacts=ArtifactPolicy.READ),
    "evaluate-concurrency": CommandSpec("_cmd_evaluate_concurrency", mutates_archive=False, artifacts=ArtifactPolicy.NONE),
    "check-asr-env": CommandSpec("_cmd_check_asr_env", mutates_archive=False, artifacts=ArtifactPolicy.NONE),
    "export": CommandSpec("_cmd_export", mutates_archive=False, artifacts=ArtifactPolicy.READ),
    "run": CommandSpec("_cmd_run", mutates_archive=True, artifacts=ArtifactPolicy.WRITE, retains_audio=True),
    "campaign": CommandSpec("_cmd_campaign", mutates_archive=True, artifacts=ArtifactPolicy.WRITE, retains_audio=True),
    "schedule": CommandSpec("_cmd_schedule", mutates_archive=True, artifacts=ArtifactPolicy.WRITE, retains_audio=True),
})

# Compatibility exports, derived rather than separately maintained policy lists.
ARCHIVE_WRITER_COMMANDS = frozenset(
    name for name, spec in COMMANDS.items() if spec.mutates_archive
)
ARTIFACT_WRITER_COMMANDS = frozenset(
    name for name, spec in COMMANDS.items() if spec.artifacts is ArtifactPolicy.WRITE
)


def add_policy_arguments(subparsers: argparse._SubParsersAction) -> None:
    """Attach only the artifact/retention flags each registered command honors."""
    from bili_asr.cli._shared import _ARTIFACT_ROOT_HELP, _KEEP_AUDIO_HELP

    if set(subparsers.choices) != set(COMMANDS):
        raise ValueError("CLI parser commands do not match the command registry")
    for name, parser in subparsers.choices.items():
        spec = COMMANDS[name]
        if spec.artifacts is not ArtifactPolicy.NONE:
            parser.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
        if spec.retains_audio:
            parser.add_argument(
                "--keep-audio", action=argparse.BooleanOptionalAction,
                default=None, help=_KEEP_AUDIO_HELP,
            )
