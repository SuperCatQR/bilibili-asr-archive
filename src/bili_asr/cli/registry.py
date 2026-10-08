"""Registered CLI handlers and their artifact access policy."""

from __future__ import annotations

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
    artifacts: ArtifactPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts, ArtifactPolicy):
            raise TypeError("command artifact policy must be ArtifactPolicy")


COMMANDS = MappingProxyType({
    "workflow": CommandSpec("_cmd_workflow", ArtifactPolicy.NONE),
    "snapshot": CommandSpec("_cmd_snapshot", ArtifactPolicy.NONE),
    "fetch-meta": CommandSpec("_cmd_fetch_meta", ArtifactPolicy.NONE),
    "status": CommandSpec("_cmd_status", ArtifactPolicy.NONE),
    "runs": CommandSpec("_cmd_runs", ArtifactPolicy.NONE),
    "coverage": CommandSpec("_cmd_coverage", ArtifactPolicy.READ),
    "verify": CommandSpec("_cmd_verify", ArtifactPolicy.READ),
    "search": CommandSpec("_cmd_search", ArtifactPolicy.READ),
    "search-index": CommandSpec("_cmd_search_index", ArtifactPolicy.READ),
    "check-asr-env": CommandSpec("_cmd_check_asr_env", ArtifactPolicy.NONE),
    "export": CommandSpec("_cmd_export", ArtifactPolicy.READ),
    "publication": CommandSpec("_cmd_publication", ArtifactPolicy.NONE),
    "editorial": CommandSpec("_cmd_editorial", ArtifactPolicy.NONE),
    "dedup": CommandSpec("_cmd_dedup", ArtifactPolicy.READ),
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
