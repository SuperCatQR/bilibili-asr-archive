"""Processing paths implementation."""

from __future__ import annotations

from pathlib import Path
import json
import os


def _subtitle_segments(
    roots: ArtifactRoots, entry: dict[str, object]
) -> tuple[list[dict[str, object]], object] | None:
    """Read one row's harvested caption document over the ordered bases (contract §5).

    The document is a **read**, and the recorded path is root-relative (D7), so the
    first base that holds it wins: a row harvested before the artifact root was
    configured keeps resolving at the archive root.
    """
    import json
    from bili_asr.archive import archive_stem

    stem = archive_stem(entry)
    relative = os.path.join("subtitles", "raw", f"{stem}.json")
    for base in roots.read_bases():
        raw_path = os.path.join(os.fspath(base), relative)
        if not os.path.isfile(raw_path):
            continue
        with open(raw_path, encoding="utf-8") as fh:
            doc = json.load(fh)
        segments = [{"start": item.get("from", 0), "end": item.get("to", 0), "text": item.get("content", "")}
                    for item in doc.get("body", [])]
        return segments, doc
    return None


def _audio_base_holding(roots: ArtifactRoots, declared: str) -> Path:
    """The first base that holds one recorded ``audio_path`` (contract §5, D8).

    A recorded value stays root-relative, so the base it is resolved against is decided
    by which one holds the file — the row's audio may predate the configured root.  A
    value no base holds is a failure of the read, reported as the guard's own
    ``OSError`` so the row's ``archive failed`` line keeps naming the same class.
    """
    from bili_asr.path_policy import confined_audio_path

    for base in roots.read_bases():
        if confined_audio_path(base, declared, require_exists=True) is not None:
            return base
    raise OSError("invalid audio path")


def _audio_base_for_path(roots: ArtifactRoots, path: str | os.PathLike[str]) -> Path:
    """The first base that holds one on-disk audio path (contract §5, D6).

    ``audio.download_audio`` hands back what its own resolver found over ``read_bases()``
    when the bytes are already there, so the return may live under the **archive root**
    for a row that predates the configured root — while ``write_base`` only ever names
    where a write goes.  Same rule as :func:`_audio_base_holding`, on an absolute path
    instead of the recorded root-relative one.
    """
    from bili_asr.path_policy import confined_audio_path

    target = os.fspath(path)
    for base in roots.read_bases():
        try:
            declared = os.path.relpath(target, base).replace(os.sep, "/")
        except ValueError:  # Windows across drives
            continue
        if confined_audio_path(base, declared, require_exists=True) is not None:
            return base
    raise OSError("invalid audio path")


def _reclaim_after_archive(
    roots: ArtifactRoots, entry: dict[str, object], *, keep: bool
) -> None:
    """Best-effort audio reclaim once a row is archived (plan: audio-reclaim).

    ``keep`` is the retention policy the command boundary resolved (contract §7, D15);
    the library never reads the environment.  ``roots`` carries both bases, because "do
    not keep this row's audio" means the copy, wherever it is.
    """
    from bili_asr.audio_reclaim import reclaim_audio

    try:
        reclaim_audio(
            roots.archive_root, entry, artifact_roots=roots, keep=keep
        )
    except (OSError, ValueError):
        pass  # per-item non-fatal: transcripts exist; row stays archived
