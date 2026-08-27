import json
from pathlib import Path

import pytest

from scripts.verify_baseline import SNAPSHOT_SCHEMA, PrerequisiteError, load_snapshot


def test_snapshot_schema_and_digest_are_validated(tmp_path: Path):
    path = tmp_path / "advisories.json"
    path.write_text(json.dumps({"schema": SNAPSHOT_SCHEMA, "advisories": []}), encoding="utf-8")
    data, digest = load_snapshot(path)
    assert data["schema"] == SNAPSHOT_SCHEMA
    assert len(digest) == 16


def test_arbitrary_snapshot_is_rejected(tmp_path: Path):
    path = tmp_path / "not-a-snapshot.json"
    path.write_text(json.dumps({"name": "anything"}), encoding="utf-8")
    with pytest.raises(PrerequisiteError, match="schema"):
        load_snapshot(path)
