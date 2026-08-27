from pathlib import Path
import json
from bili_asr.coverage_report import CoverageReport


def test_stable_json_csv_and_read_only(tmp_path: Path):
    p = tmp_path / "manifest" / "manifest.jsonl"
    p.parent.mkdir()
    p.write_text(json.dumps({"work_id":"BVx:p0","bvid":"BVx","status":"pending"})+"\n")
    before = p.read_bytes(), p.stat().st_mtime_ns
    report = CoverageReport.build(tmp_path)
    assert report.to_json() == report.to_json()
    assert report.to_csv() == report.to_csv()
    assert report.data["denominator"]["count"] == 1
    assert p.read_bytes() == before[0] and p.stat().st_mtime_ns == before[1]




def test_cli_coverage_json_csv_and_status_dispatch(tmp_path, monkeypatch, capsys):
    from bili_asr import cli
    (tmp_path / "manifest").mkdir()
    (tmp_path / "manifest" / "manifest.jsonl").write_text(json.dumps({"work_id": "w1", "status": "gone"}) + "\n")
    assert cli.main(["coverage", "--archive-root", str(tmp_path), "--format", "json"]) == 0
    assert '"schema_version"' in capsys.readouterr().out
    assert cli.main(["coverage", "--archive-root", str(tmp_path), "--format", "csv"]) == 0
    assert "schema_version" in capsys.readouterr().out
    monkeypatch.setattr(cli, "_cmd_status", lambda args: 7)
    assert cli.main(["status", "--archive-root", str(tmp_path)]) == 7


def test_missing_denominator_is_named(tmp_path: Path):
    report = CoverageReport.build(tmp_path)
    assert report.data["diagnostics"][0]["code"] == "denominator_unavailable"
