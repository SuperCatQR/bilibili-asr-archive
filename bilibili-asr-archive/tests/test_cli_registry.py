"""All CLI entry points obey the shared routing and invocation policy."""

from argparse import Namespace, _SubParsersAction
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from bili_asr import cli, coordinator
from functools import partial
from bili_asr.cli.main import _main
from bili_asr.cli.registry import COMMANDS, ArtifactPolicy, CommandSpec, add_policy_arguments

# These parser/lock/dispatch seams exercise the invocation policy inside the
# publication worker. The supervisor has dedicated real-process tests.
worker_main = partial(_main, _publication_worker=True)


ARTIFACT_READERS = {
    "coverage", "verify", "recover", "derive-audio-inventory",
    "adopt-transcripts", "search", "search-index", "export",
}
ARTIFACT_WRITERS = {
    "asr", "pilot", "download-audio", "run", "campaign", "schedule",
    "publish-transcripts", "proofread", "proofread-merge",
}
ARCHIVE_WRITERS = {
    "fetch-meta", "recover", "asr", "pilot", "derive-manifest",
    "derive-audio-inventory", "adopt-transcripts", "publish-transcripts",
    "harvest-subs", "download-audio", "run", "campaign", "schedule",
}
RETAINERS = {"asr", "pilot", "run", "schedule", "campaign"}


def test_registration_requires_explicit_mutation_and_artifact_policies():
    with pytest.raises(TypeError):
        CommandSpec("_cmd_new")
    with pytest.raises(TypeError):
        CommandSpec("_cmd_new", mutates_archive=False)
    with pytest.raises(TypeError):
        CommandSpec("_cmd_new", artifacts=ArtifactPolicy.NONE)


@pytest.mark.parametrize("mutation,artifacts,retention", [
    ("false", ArtifactPolicy.NONE, False),
    (False, "read", False),
    (False, ArtifactPolicy.NONE, "true"),
])
def test_registration_rejects_ambiguous_policy_types(mutation, artifacts, retention):
    with pytest.raises(TypeError):
        CommandSpec("_cmd_new", mutation, artifacts, retention)


def _command_parsers():
    return next(
        action.choices for action in cli.build_parser()._actions
        if isinstance(action, _SubParsersAction)
    )


def test_registry_covers_parser_and_preserves_policy_contract():
    parsers = _command_parsers()
    assert set(COMMANDS) == set(parsers)
    assert {name for name, spec in COMMANDS.items() if spec.mutates_archive} == ARCHIVE_WRITERS
    assert {name for name, spec in COMMANDS.items() if spec.artifacts is ArtifactPolicy.READ} == ARTIFACT_READERS
    assert {name for name, spec in COMMANDS.items() if spec.artifacts is ArtifactPolicy.WRITE} == ARTIFACT_WRITERS
    assert {name for name, spec in COMMANDS.items() if spec.retains_audio} == RETAINERS
    for name, parser in parsers.items():
        options = parser._option_string_actions
        assert ("--artifact-root" in options) == (name in ARTIFACT_READERS | ARTIFACT_WRITERS)
        assert ("--keep-audio" in options) == (name in RETAINERS)
        assert ("--no-keep-audio" in options) == (name in RETAINERS)
        assert callable(getattr(cli, COMMANDS[name].handler))


def test_policy_setup_refuses_an_unregistered_parser():
    import argparse

    parsers = argparse.ArgumentParser().add_subparsers()
    parsers.add_parser("new-unclassified-command")
    with pytest.raises(ValueError, match="command registry"):
        add_policy_arguments(parsers)


@pytest.mark.parametrize("command", COMMANDS)
def test_dispatch_resolves_package_handler_at_call_time(command, monkeypatch):
    args = Namespace(command=command)
    seen = []
    monkeypatch.setattr(cli, COMMANDS[command].handler, lambda value: seen.append(value) or 37)
    assert cli._dispatch_command(args) == 37
    assert seen == [args]


def test_unknown_dispatch_keeps_named_error():
    with pytest.raises(ValueError, match="command 'unknown' is not implemented"):
        cli._dispatch_command(Namespace(command="unknown"))


def test_unknown_command_from_parser_seam_keeps_named_error(monkeypatch):
    parser = SimpleNamespace(parse_args=lambda argv: Namespace(command="unknown"))
    monkeypatch.setattr(cli, "build_parser", lambda: parser)
    with pytest.raises(ValueError, match="command 'unknown' is not implemented"):
        worker_main([])


def _invocation(monkeypatch, command, archive, artifact=None):
    # Parser-independent invocation boundary; completeness above checks real flags.
    args = Namespace(command=command, archive_root=str(archive))
    if command in ARTIFACT_READERS | ARTIFACT_WRITERS:
        args.artifact_root = None if artifact is None else str(artifact)
    monkeypatch.setattr(cli, "build_parser", lambda: SimpleNamespace(parse_args=lambda argv: args))
    return args


@pytest.mark.parametrize("command", COMMANDS)
def test_busy_archive_refuses_every_state_writer_and_allows_readers(command, tmp_path, monkeypatch, capsys):
    @contextmanager
    def busy_writer(root):
        raise coordinator.ArchiveBusyError()
        yield

    monkeypatch.delenv("BILI_ARTIFACT_ROOT", raising=False)
    monkeypatch.setattr(coordinator, "archive_writer", busy_writer)
    args = _invocation(monkeypatch, command, tmp_path)
    seen = []
    monkeypatch.setattr(cli, "_dispatch_command", lambda value: seen.append(value) or 0)
    result = worker_main([])
    if command in ARCHIVE_WRITERS:
        assert result == 1
        assert seen == []
        assert capsys.readouterr().err == f"{command}: archive_busy\n"
    else:
        assert result == 0
        assert seen == [args]
        assert capsys.readouterr().err == ""


@pytest.mark.parametrize("command", sorted(ARTIFACT_READERS | ARTIFACT_WRITERS))
def test_bad_artifact_root_refuses_before_lock_or_handler(command, tmp_path, monkeypatch, capsys):
    archive = tmp_path / "archive"
    invalid = tmp_path / "not-a-directory"
    invalid.write_text("file")
    _invocation(monkeypatch, command, archive, invalid)

    def unexpected(*args, **kwargs):
        pytest.fail("artifact refusal reached the archive lock or handler")

    monkeypatch.setattr(coordinator, "archive_writer", unexpected)
    monkeypatch.setattr(cli, "_dispatch_command", unexpected)
    assert worker_main([]) == 1
    assert capsys.readouterr().err.startswith(f"{command}: artifact root is not a directory")
    assert not archive.exists()


@pytest.mark.parametrize("command", sorted(ARTIFACT_READERS | ARTIFACT_WRITERS))
def test_artifact_write_probe_only_applies_to_product_writers(command, tmp_path, monkeypatch):
    import importlib

    entrypoint = importlib.import_module("bili_asr.cli.main")
    args = _invocation(monkeypatch, command, tmp_path)
    roots = object()
    probes = []

    def resolve(archive_root, *, flag_value, require_writable):
        probes.append(require_writable)
        return roots

    @contextmanager
    def writer(root):
        yield

    monkeypatch.setattr(entrypoint, "roots_for", resolve)
    monkeypatch.setattr(coordinator, "archive_writer", writer)
    monkeypatch.setattr(cli, "_dispatch_command", lambda value: 0)
    assert worker_main([]) == 0
    assert probes == [command in ARTIFACT_WRITERS]
    assert args.artifact_roots is roots
