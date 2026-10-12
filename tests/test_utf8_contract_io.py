"""UTF-8 inputs remain exact with Python UTF-8 mode disabled."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_json_fixture_does_not_depend_on_process_default_encoding(tmp_path):
    data = {"title": "\u4fdd\u7559\u539f\u6587 \u2014 \u03b1", "markdown": "\u6b63\u6587\n"}
    path = tmp_path / "fixture.json"
    original = json.dumps(data, ensure_ascii=False).encode("utf-8")
    path.write_bytes(original)
    env = os.environ.copy()
    env.update(PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", LC_ALL="C", PYTHONIOENCODING="utf-8",
               PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    probe = subprocess.run([sys.executable, "-X", "utf8=0", "-c", """
import json, sys
from pathlib import Path
from bili_asr.cli.json_input import _json_object
assert sys.flags.utf8_mode == 0
expected = json.loads(sys.argv[2])
assert _json_object(sys.argv[1]) == expected
assert json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')) == expected
""", str(path), json.dumps(data)], env=env, capture_output=True,
        text=True, encoding="utf-8", timeout=30, check=False)
    assert probe.returncode == 0, probe.stderr
    assert path.read_bytes() == original
