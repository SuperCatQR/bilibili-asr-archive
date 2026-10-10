"""Registered CLI handlers and their artifact access policy."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from bili_asr.archive_session import ArchiveAccessMode


class ArtifactPolicy(Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class CommandSpec:
    handler: str
    artifacts: ArtifactPolicy
    database: ArchiveAccessMode | None
    write_flags: tuple[str, ...] = ()
    archive_argument: str = "archive_root"

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts, ArtifactPolicy):
            raise TypeError("command artifact policy must be ArtifactPolicy")
        if self.database is not None and not isinstance(self.database, ArchiveAccessMode):
            raise TypeError("command database policy must be ArchiveAccessMode or None")
        if not isinstance(self.write_flags, tuple) or not all(isinstance(name, str) for name in self.write_flags):
            raise TypeError("command write flags must be a tuple of argument names")
        if not isinstance(self.archive_argument, str) or not self.archive_argument:
            raise TypeError("command archive argument must name a parsed argument")

    def database_for(self, args) -> ArchiveAccessMode | None:
        if any(getattr(args, name, False) for name in self.write_flags):
            return ArchiveAccessMode.WRITE
        return getattr(args, "database_policy", self.database)


COMMANDS = MappingProxyType({
    "workflow": CommandSpec("_cmd_workflow", ArtifactPolicy.NONE, ArchiveAccessMode.WRITE, write_flags=("apply",)),
    "snapshot": CommandSpec("_cmd_snapshot", ArtifactPolicy.NONE, ArchiveAccessMode.MAINTENANCE),
    "archive": CommandSpec("_cmd_archive", ArtifactPolicy.NONE, ArchiveAccessMode.MAINTENANCE, archive_argument="source_root"),
    "artifacts": CommandSpec("_cmd_artifacts", ArtifactPolicy.NONE, ArchiveAccessMode.READ),
    "remote": CommandSpec("_cmd_remote", ArtifactPolicy.NONE, None),
    "reference": CommandSpec("_cmd_reference", ArtifactPolicy.NONE, None),
    "source": CommandSpec("_cmd_source", ArtifactPolicy.NONE, ArchiveAccessMode.WRITE),
    "fetch-tags": CommandSpec("_cmd_fetch_tags", ArtifactPolicy.NONE, ArchiveAccessMode.BOOTSTRAP),
    "fetch-meta": CommandSpec("_cmd_fetch_meta", ArtifactPolicy.NONE, ArchiveAccessMode.BOOTSTRAP),
    "status": CommandSpec("_cmd_status", ArtifactPolicy.NONE, ArchiveAccessMode.READ),
    "runs": CommandSpec("_cmd_runs", ArtifactPolicy.NONE, ArchiveAccessMode.READ),
    "coverage": CommandSpec("_cmd_coverage", ArtifactPolicy.READ, ArchiveAccessMode.READ),
    "verify": CommandSpec("_cmd_verify", ArtifactPolicy.READ, ArchiveAccessMode.READ),
    "search": CommandSpec("_cmd_search", ArtifactPolicy.READ, ArchiveAccessMode.READ, write_flags=("rebuild",)),
    "search-index": CommandSpec("_cmd_search_index", ArtifactPolicy.READ, ArchiveAccessMode.WRITE),
    "check-asr-env": CommandSpec("_cmd_check_asr_env", ArtifactPolicy.NONE, None),
    "export": CommandSpec("_cmd_export", ArtifactPolicy.READ, ArchiveAccessMode.READ),
    "publication": CommandSpec("_cmd_publication", ArtifactPolicy.NONE, ArchiveAccessMode.READ),
    "editorial": CommandSpec("_cmd_editorial", ArtifactPolicy.NONE, ArchiveAccessMode.READ),
    "dedup": CommandSpec("_cmd_dedup", ArtifactPolicy.READ, ArchiveAccessMode.READ),
})


def add_policy_arguments(subparsers: argparse._SubParsersAction) -> None:
    """Add the configured artifact root to commands that inspect artifacts."""
    from bili_asr.cli._shared import _ARTIFACT_ROOT_HELP

    if set(subparsers.choices) != set(COMMANDS):
        raise ValueError("CLI parser commands do not match the command registry")
    for name, parser in subparsers.choices.items():
        spec = COMMANDS[name]
        if spec.artifacts is not ArtifactPolicy.NONE:
            parser.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
