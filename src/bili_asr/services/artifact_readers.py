"""Preserve explicit restore semantics at manuscript/publication read boundaries."""
from __future__ import annotations

from bili_asr.manuscript_files import read_artifact


def read_retained_text(connection, relative_path, sha256, roots):
    """Read current local bytes, or identify the exact immutable group to restore."""
    try:
        return read_artifact(relative_path, sha256, roots)
    except ValueError as error:
        if "artifact is missing:" not in str(error):
            raise
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='artifact_group_paths'").fetchone():
            raise
        groups = [row[0] for row in connection.execute(
            "SELECT p.group_id FROM artifact_group_paths p JOIN artifact_group_members m USING(group_id,role) "
            "WHERE p.relative_key=? AND m.object_id=? ORDER BY p.group_id", (relative_path, sha256))]
        if not groups:
            raise
        raise ValueError(f"artifact_restore_required: retained object {sha256}; "
                         f"run artifacts restore-group --group-id {groups[0]} with its storage target binding") from error
