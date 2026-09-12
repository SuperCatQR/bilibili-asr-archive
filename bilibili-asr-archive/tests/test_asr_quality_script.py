"""The automatic quality report: what it must say, and what it must refuse."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "asr_quality.py"


def _write(tmp_path: Path, segments: list[dict], provenance: dict | None = None) -> Path:
    path = tmp_path / "raw.json"
    path.write_text(json.dumps({"segments": segments, "provenance": provenance or {}},
                               ensure_ascii=False), encoding="utf-8")
    return path


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_report_names_confidence_anomalies_and_agreement(tmp_path):
    artifact = _write(
        tmp_path,
        [
            {"start": 0.0, "end": 2.0, "text": "第一句话。", "confidence": 0.9},
            {"start": 2.0, "end": 4.0, "text": "，第二句话。", "confidence": 0.2},
        ],
        {"model_name": "[redacted]", "device": "cpu"},
    )
    reference = tmp_path / "other.txt"
    reference.write_text("第一句话。第二句话。", encoding="utf-8")

    result = _run(str(artifact), "--reference", str(reference))

    assert result.returncode == 0, result.stderr
    assert "confidence : mean 0.550" in result.stdout
    assert "unsure" in result.stdout
    assert "cue opens with a mark=1" in result.stdout
    assert "agreement  :" in result.stdout


def test_report_says_so_when_confidence_was_not_recorded(tmp_path):
    artifact = _write(tmp_path, [{"start": 0.0, "end": 2.0, "text": "一句话。"}])

    result = _run(str(artifact))

    assert result.returncode == 0
    assert "not recorded" in result.stdout


def test_fail_under_turns_low_confidence_into_a_nonzero_exit(tmp_path):
    artifact = _write(tmp_path, [{"start": 0.0, "end": 2.0, "text": "一句话。", "confidence": 0.3}])

    assert _run(str(artifact), "--fail-under", "0.5").returncode == 1
    assert _run(str(artifact), "--fail-under", "0.1").returncode == 0


def test_empty_artifact_is_an_error_not_an_empty_report(tmp_path):
    artifact = _write(tmp_path, [])

    result = _run(str(artifact))

    assert result.returncode == 1
    assert "no cues" in result.stderr
