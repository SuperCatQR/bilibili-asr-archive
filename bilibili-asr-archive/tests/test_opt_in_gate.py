"""Exercise the real opt-in fixture through a separate pytest invocation."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("marker_name,env_var", [
    ("live_smoke", "BILI_LIVE_SMOKE"),
    ("scale", "BILI_SCALE"),
])
@pytest.mark.parametrize("opt_in_value", [None, "0", "true", "1"])
@pytest.mark.parametrize("custom_reason", [None, "caller-specific opt-in reason"])
def test_fixture_alone_enforces_opt_in(
    tmp_path: Path, marker_name: str, env_var: str,
    opt_in_value: str | None, custom_reason: str | None,
) -> None:
    source_fixture = Path(__file__).with_name("conftest.py")
    # Import the shipped fixture, without registering the source suite's other
    # hooks or fixtures in the nested run. The body below never calls skip.
    (tmp_path / "conftest.py").write_text(
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('source_gate', {str(source_fixture)!r})\n"
        "source = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(source)\n"
        "opt_in_gate = source.opt_in_gate\n",
        encoding="utf-8",
    )
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n"
        "    live_smoke: live gate\n"
        "    scale: scale gate\n",
        encoding="utf-8",
    )
    marker_args = "" if custom_reason is None else f"(skip_reason={custom_reason!r})"
    (tmp_path / "test_consumer.py").write_text(
        "from pathlib import Path\nimport pytest\n"
        f"@pytest.mark.{marker_name}{marker_args}\n"
        "def test_fixture_only_consumer(opt_in_gate):\n"
        f"    assert opt_in_gate[0] == {env_var!r}\n"
        "    Path('body-executed').write_text('ran', encoding='utf-8')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("BILI_LIVE_SMOKE", None)
    env.pop("BILI_SCALE", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    if opt_in_value is not None:
        env[env_var] = opt_in_value
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "test_consumer.py"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if opt_in_value == "1":
        assert "1 passed" in result.stdout
        assert (tmp_path / "body-executed").read_text(encoding="utf-8") == "ran"
    else:
        assert "1 skipped" in result.stdout
        assert not (tmp_path / "body-executed").exists()
        expected_reason = custom_reason or (
            f"{marker_name} test is opt-in: set {env_var}=1 to run it"
        )
        assert expected_reason in result.stdout
