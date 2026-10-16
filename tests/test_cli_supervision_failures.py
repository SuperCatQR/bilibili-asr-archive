"""CLI refuses unsafe collection options and preserves supervisor failures."""
import pytest

from bili_asr.cli.main import main
from bili_asr import release_identity
from bili_asr.services.metadata_supervision import MetadataSupervisor
from bili_asr.services.retry_maintenance_io import MaintenanceBusyError
from bili_asr.sources.models import GatewayAuthenticationError
from tests.fixtures.fake_bilibili_gateway import fake_gateway_seam  # noqa: F401


def test_release_failure_stops_before_command_parser(monkeypatch, capsys):
    def reject():
        raise release_identity.ReleaseIdentityError("release verification failed: disk_drift")
    monkeypatch.setattr(release_identity, "require_expected_build", reject)
    assert main(["unknown-command"]) == 2
    assert capsys.readouterr().err.strip() == "release verification failed: disk_drift"


@pytest.mark.parametrize("options,diagnostic", [
    (["--supervision-state", "state.json"], "requires --supervised"),
    (["--supervised", "--start-page", "1"], "cannot rewind or skip"),
    (["--supervision-status"], "requires an existing archive database"),
    (["--bvid", "BV1AbCdEfGhJ", "--supervised"], "applies only to paginated collection"),
])
def test_supervision_options_fail_before_any_request(tmp_path, fake_gateway_seam, capsys, options, diagnostic):
    assert main(["fetch-meta", "--archive-root", str(tmp_path / "archive"), *options]) == 1
    assert diagnostic in capsys.readouterr().err
    assert fake_gateway_seam.page_calls == []


@pytest.mark.parametrize("error,exit_code,diagnostic", [
    (MaintenanceBusyError("private lock details"), 3, "already active"),
    (ValueError("private invalid state"), 1, "preserve state and investigate"),
])
def test_supervisor_refusal_has_safe_exit_and_no_gateway_request(
        tmp_path, fake_gateway_seam, monkeypatch, capsys, error, exit_code, diagnostic):
    def reject(*_args, **_kwargs):
        raise error
    monkeypatch.setattr(MetadataSupervisor, "collect", reject)
    assert main(["fetch-meta", "--archive-root", str(tmp_path / "archive"), "--supervised"]) == exit_code
    output = capsys.readouterr()
    assert diagnostic in output.err and "private" not in output.err
    assert fake_gateway_seam.page_calls == []


def test_authentication_stop_is_attention_not_automatic_retry(tmp_path, fake_gateway_seam, capsys):
    fake_gateway_seam.script_page(1, GatewayAuthenticationError())
    arguments = ["fetch-meta", "--archive-root", str(tmp_path / "archive"), "--supervised"]
    assert main(arguments) == 4
    assert "supervision needs_attention" in capsys.readouterr().err
    assert main(arguments) == 4
    assert len(fake_gateway_seam.page_calls) == 1
