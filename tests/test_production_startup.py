"""Exercise deployment startup without shell evaluation or secret output."""

import os
import sys

import pytest

from scripts import production


def test_startup_uses_environment_interpreter_and_literal_values(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text('BILI_SESSDATA="private value"\nLITERAL=$(touch unwanted)\n', encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.setenv("BILI_SESSDATA", "inherited")
    calls = []
    monkeypatch.setattr(production.subprocess, "call", lambda command, **kwargs: calls.append((command, kwargs)) or 7)
    monkeypatch.setattr(sys, "argv", ["production.py", "--env-file", str(env_file), "--", "workflow", "status"])
    assert production.main() == 7
    command, kwargs = calls[0]
    assert command == [sys.executable, "-m", "bili_asr", "workflow", "status"]
    assert kwargs["env"]["BILI_SESSDATA"] == "private value"
    assert kwargs["env"]["LITERAL"] == "$(touch unwanted)"
    assert capsys.readouterr() == ("", "")


def test_invalid_env_does_not_expose_secret_or_launch(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text('BILI_SESSDATA="private-unclosed\n', encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.setattr(sys, "argv", ["production.py", "--env-file", str(env_file), "--", "--help"])
    monkeypatch.setattr(production.subprocess, "call", lambda *a, **k: pytest.fail("must not launch"))
    assert production.main() == 2
    assert "private" not in capsys.readouterr().err


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_rejects_world_readable_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BILI_SESSDATA=private\n", encoding="utf-8")
    env_file.chmod(0o644)
    with pytest.raises(ValueError, match="permissions|accessible"):
        production.load_environment(env_file)
