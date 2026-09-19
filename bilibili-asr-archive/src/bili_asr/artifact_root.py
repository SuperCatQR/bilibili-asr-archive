"""Where the pipeline's products live: one configured root, two ordered read bases.

The pipeline's **products** — audio, transcript bundles, harvested subtitle documents —
may live under a root that is not the archive root (``--artifact-root`` /
``BILI_ARTIFACT_ROOT``); its **state** (``manifest/``, ``archive.db``,
``coordinator/``, the sidecars) always stays at the archive root.  This module is the
single place that resolves, validates and carries that split
(``artifact-root-contract.md`` §2–§5, decisions D7–D12).

Resolution (contract §3.2, D9)::

    --artifact-root <value>   (non-blank)  -> use it
    else BILI_ARTIFACT_ROOT   (non-blank)  -> use it
    else                                   -> the archive root (today's behaviour)

A blank or whitespace-only value at either level counts as *unset* and never blocks the
next level, which is :func:`config.resolve_proxy`'s idiom (``config.py:154-175``) and
deliberately not :func:`config.resolve_sessdata`'s (``config.py:128-141``): the
credential's blank-blocks-fallthrough rule exists because it has a security-relevant
anonymous mode, and a path has no such mode.  ``~`` is expanded, and a relative value
is made absolute against the process CWD exactly as ``--archive-root`` behaves today.
The path is kept **lexical** — ``realpath`` is never applied — because
``path_policy.open_audio_directory`` (``path_policy.py:32-57``) opens the root itself
with ``O_NOFOLLOW``: resolving first would silently follow a symlinked root past that
check.  The consequence is stated for the operator: a symlinked artifact root is
refused, so pass the real path.

Validation (contract §3.3, D10) happens once, in :func:`roots_for`, and only for a
**configured** root.  A value lexically equal to the archive root is the **identity
case**: one base, today's code path, not validated further, because an explicit no-op
must be a no-op.  Any other value must already be an existing directory or the command
refuses with its usage/config exit and names the path.  A missing root is **never
created**: an unmounted mount point still exists as an empty directory, and
auto-creating a missing one would publish products to the underlying filesystem
instead of the mount.  A root *inside* the archive root is accepted — a legitimate
layout, and the two bases stay distinct.

Reads (contract §5, D7/D8) never see an absolute recorded path.  The recorded strings
stay artifact-root-relative (``audio/{stem}.m4a``, ``transcripts/srt/{stem}.srt``), so
the manifest's bytes are unchanged by this feature and no reader needs to know which
root a row was written under.  :func:`resolve_audio_path` walks
:meth:`ArtifactRoots.read_bases` in order and returns the first hit, with each
candidate validated at **its own** base by that family's existing guard — never a
cross-root path computation.  A legacy row written before the root was configured
therefore keeps resolving to its existing file (§5, D6), and nothing durable records
the root (D12): a later run with a different root neither rewrites nor invalidates
earlier rows.

Layering: a shared policy leaf beside ``path_policy``, importing stdlib plus
``path_policy`` only — never a manifest, storage or artifact writer — so the
cross-layer rule that only ``cli`` composes the stages is not widened.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .path_policy import confined_audio_path

#: Environment variable carrying the optional configured artifact root.
ARTIFACT_ROOT_ENV_VAR = "BILI_ARTIFACT_ROOT"

#: Environment variable carrying the optional audio retention policy (``1`` keep,
#: ``0`` reclaim); the flag is resolved against it once at the command boundary.
KEEP_AUDIO_ENV_VAR = "BILI_KEEP_AUDIO"

#: Retention default: audio is retained unless a flag or the variable says otherwise.
KEEP_AUDIO_DEFAULT = True


class ArtifactRootError(ValueError):
    """A configured artifact root cannot be used → the command's usage/config exit (1)."""


@dataclass(frozen=True)
class ArtifactRoots:
    """The roots one invocation reads and writes under (D7, D8, D10 in one value).

    ``archive_root`` and ``artifact_root`` are both absolute and lexical; they are
    equal when no root was configured, which is the identity case the libraries
    default to.
    """

    archive_root: Path
    artifact_root: Path

    @classmethod
    def of(
        cls,
        archive_root: str | os.PathLike[str],
        artifact_root: str | os.PathLike[str] | None = None,
    ) -> "ArtifactRoots":
        """Build the value object from raw paths — lexical only, no ``isdir`` check."""
        archive = _lexical(archive_root)
        configured = archive if artifact_root is None else _lexical(artifact_root)
        return cls(archive_root=archive, artifact_root=configured)

    @property
    def configured(self) -> bool:
        """True when a root other than the archive root was configured."""
        return self.artifact_root != self.archive_root

    @property
    def write_base(self) -> Path:
        """The base every artifact write uses — always the configured root."""
        return self.artifact_root

    def read_bases(self) -> tuple[Path, ...]:
        """The ordered bases a recorded artifact path is resolved against (D8)."""
        if self.configured:
            return (self.artifact_root, self.archive_root)
        return (self.archive_root,)


def _lexical(value: str | os.PathLike[str]) -> Path:
    """Expand ``~``, make absolute, and never resolve symlinks (contract §3.2)."""
    return Path(os.path.abspath(os.path.expanduser(os.fspath(value))))


def resolve_artifact_root(value: str | None, environ: Mapping[str, str]) -> str | None:
    """Return the configured artifact root: flag, else environment, else ``None``.

    The flag wins over :data:`ARTIFACT_ROOT_ENV_VAR`; a blank or whitespace-only value
    at either level counts as unset and never blocks the next level.  The value that
    resolves is stripped, ``~`` is expanded and the result is made absolute against the
    process CWD.  ``None`` means unconfigured — the caller then uses the archive root.
    """
    for candidate in (value, environ.get(ARTIFACT_ROOT_ENV_VAR)):
        if candidate is None:
            continue
        stripped = candidate.strip()
        if stripped:
            return str(_lexical(stripped))
    return None


def resolve_keep_audio(flag_value: bool | None, environ: Mapping[str, str]) -> bool:
    """Return the retention policy: the flag, else the variable, else the default.

    The flag wins outright.  Otherwise ``BILI_KEEP_AUDIO == "1"`` retains and ``== "0"``
    reclaims — the two documented values keep the meanings they have today — and
    anything else, including an absent or blank value, falls back to
    :data:`KEEP_AUDIO_DEFAULT` (retain).
    """
    if flag_value is not None:
        return flag_value
    value = environ.get(KEEP_AUDIO_ENV_VAR)
    if value == "1":
        return True
    if value == "0":
        return False
    return KEEP_AUDIO_DEFAULT


def roots_for(
    archive_root: str | os.PathLike[str],
    *,
    flag_value: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ArtifactRoots:
    """Resolve and validate the roots for one command invocation (contract §3.2/§3.3).

    The CLI's one entry point: precedence, the blank rule and the validation of a
    *configured* root live here and nowhere else.  Raises :class:`ArtifactRootError`
    when a configured root does not exist or is not a directory; it is never created.
    The identity case is accepted without touching the filesystem.
    """
    environment: Mapping[str, str] = os.environ if environ is None else environ
    roots = ArtifactRoots.of(archive_root, resolve_artifact_root(flag_value, environment))
    if roots.configured and not roots.artifact_root.is_dir():
        reason = "is not a directory" if roots.artifact_root.exists() else "does not exist"
        raise ArtifactRootError(f"artifact root {reason} ({roots.artifact_root})")
    return roots


def resolve_audio_path(
    roots: ArtifactRoots,
    declared: str | os.PathLike[str] | None,
    *,
    require_exists: bool = True,
) -> Path | None:
    """Resolve one recorded ``audio_path`` over the ordered bases (contract §5).

    Each candidate is validated at its own base by
    ``path_policy.confined_audio_path`` — the same no-follow guard the single-root
    readers use today — and the first hit wins.  ``None`` means the value is missing or
    refused at *every* base: under ``require_exists=True`` the guard returns ``None``
    for both, so the resolver does not try to tell them apart.
    """
    for base in roots.read_bases():
        confined = confined_audio_path(base, declared, require_exists=require_exists)
        if confined is not None:
            return confined
    return None


__all__ = [
    "ARTIFACT_ROOT_ENV_VAR",
    "KEEP_AUDIO_DEFAULT",
    "KEEP_AUDIO_ENV_VAR",
    "ArtifactRootError",
    "ArtifactRoots",
    "resolve_artifact_root",
    "resolve_audio_path",
    "resolve_keep_audio",
    "roots_for",
]
