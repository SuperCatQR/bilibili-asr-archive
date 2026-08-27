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


def test_missing_denominator_is_named(tmp_path: Path):
    report = CoverageReport.build(tmp_path)
    assert report.data["diagnostics"][0]["code"] == "denominator_unavailable"
