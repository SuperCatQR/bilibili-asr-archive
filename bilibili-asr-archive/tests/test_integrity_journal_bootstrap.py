"""A valid ledger is authoritative before its first snapshot compaction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bili_asr.archive import write_archive
from bili_asr.cli import main
from bili_asr.integrity import IntegrityVerifier, RECOVERY_NOT_AUTHORITATIVE
from bili_asr.manifest import JOURNAL_NAME, ManifestStore


def _fresh_archive(tmp_root, *, publish=True) -> tuple[Path, dict]:
    root = Path(tmp_root)
    entry = {
        "work_id": "BV1journal:p0", "bvid": "BV1journal", "page_index": 0,
        "cid": 7, "title": "Journal bootstrap", "pubdate_str": "2026-01-02",
        "status": "archived", "source": "cc",
    }
    if publish:
        entry.update(write_archive(root, entry, [{"start": 0, "end": 1, "text": "ok"}], source="cc"))
    ManifestStore(root).upsert(entry)
    assert (root / "manifest" / JOURNAL_NAME).is_file()
    assert not (root / "manifest" / "manifest.jsonl").exists()
    coordinator = root / "coordinator"
    coordinator.mkdir(exist_ok=True)
    (coordinator / "attempts.jsonl").write_text("", encoding="utf-8")
    return root, entry


def test_verify_accepts_a_fresh_valid_journal_only_archive(tmp_root, capsys) -> None:
    root, _ = _fresh_archive(tmp_root)
    journal = root / "manifest" / JOURNAL_NAME
    original = journal.read_bytes()

    assert main(["verify", "--archive-root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["authoritative"] is True
    assert payload["checked"] == 1
    assert payload["diagnostics"] == []
    assert payload["defect_count"] == 0
    assert journal.read_bytes() == original
    assert not (root / "manifest" / "manifest.jsonl").exists()


def test_recover_can_select_a_defect_from_a_fresh_journal_only_archive(tmp_root, capsys) -> None:
    root, entry = _fresh_archive(tmp_root, publish=False)
    assert main(["recover", "--archive-root", str(root), "--work-id", entry["work_id"]]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["selected"] == [entry["work_id"]]
    audit = root / "coordinator" / "recovery-audit.jsonl"
    record = json.loads(audit.read_text(encoding="utf-8"))
    assert record["work_ids"] == [entry["work_id"]]
    assert record["action"] == "audit"


@pytest.mark.parametrize("damage", ["malformed", "identity", "symlink"])
def test_a_present_but_invalid_journal_does_not_authorize_recovery(tmp_root, damage) -> None:
    root, entry = _fresh_archive(tmp_root, publish=False)
    journal = root / "manifest" / JOURNAL_NAME
    if damage == "malformed":
        journal.write_text("{broken\n", encoding="utf-8")
    elif damage == "identity":
        journal.write_text(json.dumps({**entry, "bvid": "BVother"}) + "\n", encoding="utf-8")
    else:
        outside = root / "outside.jsonl"
        outside.write_bytes(journal.read_bytes())
        journal.unlink()
        journal.symlink_to(outside)

    report = IntegrityVerifier().verify(root)
    assert report.authoritative is False
    assert report.diagnostics
    refusal = IntegrityVerifier.recover(root, work_ids=[entry["work_id"]])
    assert refusal["code"] == RECOVERY_NOT_AUTHORITATIVE
    assert not (root / "coordinator" / "recovery-audit.jsonl").exists()
