import itertools
import os
import shutil
import sys
import tempfile
import time
import traceback
import types

import pytest

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

_TEST_TMP_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".test-tmp"))
_counter = itertools.count()

# Error-report forensics. The full suite has been observed red in some runs and
# green in others on an unchanged tree (recorded 261 / 0 / 196 / 0 errors), and
# the red runs left nothing behind: pytest's default report goes to the
# terminal, so the cause died with the scrollback. These constants pin the
# evidence to a stable, gitignored path (.tb/ is already an ignored convention)
# so the *next* red is diagnosable instead of merely counted.
#
# The phases the hook below *cannot* see: a **collection** error arrives as
# `pytest_collectreport(report)`, and that report carries no `item`, so it can
# never reach a `pytest_runtest_makereport` hook no matter how the guard reads.
# A collection red therefore still writes nothing here; catching one needs a
# collector-report hook, not a wider phase guard.
_TRACEBACK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tb"))
_TRACEBACK_PATH = os.path.join(_TRACEBACK_DIR, "errors.log")


def _environment_facts() -> str:
    """One block of the facts that discriminate environment from repo causes."""
    facts = [
        f"cwd={os.getcwd()}",
        f"sys.executable={sys.executable}",
        f"tmpdir={tempfile.gettempdir()}",
    ]
    try:
        import bili_asr

        # Resolving outside this worktree is the known invocation trap: a red
        # that comes from the wrong tree is a false lead.
        facts.append(f"bili_asr={bili_asr.__file__}")
    except Exception as exc:  # pragma: no cover - diagnostic path only
        facts.append(f"bili_asr=<unimportable: {type(exc).__name__}: {exc}>")
    for label, path in (("tmp", tempfile.gettempdir()), ("cwd", os.getcwd())):
        try:
            usage = shutil.disk_usage(path)
            facts.append(
                f"disk[{label}]={usage.free} free / {usage.total} total bytes"
            )
        except OSError as exc:  # pragma: no cover - diagnostic path only
            facts.append(f"disk[{label}]=<unavailable: {exc}>")
    return "\n".join(facts)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Persist the traceback of any setup or teardown error to a stable path.

    Only the ``setup`` and ``teardown`` phases are recorded — the phases whose
    reports count into pytest's ``errors`` total. Setup is the phase the
    recorded cross-file, large-and-varying-count red hit, and teardown errors
    are indistinguishable from "the fixture never ran" for the same reason.
    A **collection** error carries no ``item`` and is therefore invisible to
    this hook; see the module-level note above. Reporting must never itself
    fail the run, so every step is guarded.
    """
    outcome = yield
    if call.when not in ("setup", "teardown"):
        return
    report = outcome.get_result()
    if not report.failed:
        return
    try:
        os.makedirs(_TRACEBACK_DIR, exist_ok=True)
        # A new on-disk artifact follows the repo's own write discipline
        # (manifest.py:204-209): O_CREAT with O_NOFOLLOW, and mode 0600, so the
        # file is not world-readable although the block carries environment
        # facts. Scope, stated exactly: O_NOFOLLOW refuses a symlink as the
        # *final* path component — a pre-existing `errors.log` symlink is
        # rejected rather than written through. Its parent `.tb/` is created by
        # makedirs, which follows a pre-existing directory symlink; refusing
        # that needs O_DIRECTORY|O_NOFOLLOW walking, and the fallback is the
        # guarded failure anyway (worst case: no log, with the reason in every
        # run's message).
        try:
            fd = os.open(
                _TRACEBACK_PATH,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
                0o600,
            )
        except OSError as exc:  # pragma: no cover - diagnostic path only
            print(f"conftest: {call.when} error not persisted: {exc}",
                  file=sys.stderr)
            return
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(f"{'=' * 78}\n")
            handle.write(
                f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {call.when.upper()} ERROR\n"
            )
            handle.write(f"nodeid: {item.nodeid}\n")
            handle.write(f"fixture info: {getattr(item, 'fixturenames', None)}\n")
            handle.write(f"location: {item.location}\n")
            handle.write(f"{_environment_facts()}\n")
            if report.longrepr is not None:
                handle.write(f"{report.longrepr}\n")
            else:  # pragma: no cover - pytest always populates longrepr for failures
                handle.write(f"{traceback.format_exc()}\n")
    except Exception:  # pragma: no cover - never mask the original failure
        pass


@pytest.fixture
def tmp_root():
    """Temp dir for ManifestStore tests.

    Notes on this environment: the sandbox denies directory creation under
    %TEMP% from Python and breaks pytest's tmpdir plugin cleanup, so we use a
    self-managed workspace-local temp dir created and removed in-process.
    """
    os.makedirs(_TEST_TMP_BASE, exist_ok=True)
    path = os.path.join(_TEST_TMP_BASE, f"manifest-test-{os.getpid()}-{next(_counter)}")
    os.makedirs(path)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class _NoOpContext:
    """A context manager that does nothing, standing in for a torch grad mode."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc_info: object) -> bool:
        return False


@pytest.fixture(autouse=True)
def mock_torch(monkeypatch):
    """A torch stand-in that reports CUDA is available and no-ops the grad modes.

    Every test that drives the ASR path with mocked models needs torch to be importable but does
    not need it to be real.  The boundary runs its decodes and its alignment inside
    ``torch.inference_mode()``, so the stand-in has to carry that context manager as well as
    ``cuda.is_available`` — without it every ASR row fails at the first decode with an
    ``AttributeError`` that the coordinator records as a per-row failure.
    """

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True),
        inference_mode=lambda *args, **kwargs: _NoOpContext(),
        no_grad=lambda *args, **kwargs: _NoOpContext(),
        # A ``Tensor`` class so third-party probes answer False instead of raising.  The boundary
        # never reads it; ``scipy`` does, through ``librosa``'s resampler, asking a module named
        # ``torch`` whether some class *is* ``torch.Tensor``.  A stand-in missing the attribute
        # turns that probe into an ``AttributeError``, which fails a test for a reason unrelated to
        # the code under test.
        Tensor=type("Tensor", (), {}),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)


def reuse_line(captured, command):
    """The one ``model constructions=`` line, or a failure explaining its absence.

    Shared by the CLI tests that drive the in-process loops (``asr``,
    ``pilot``): the printed line's shape is one contract (D2.6), so the
    assertion that reads it back is one helper rather than a copy per file.
    """
    lines = [
        line for line in captured.err.splitlines() if "model constructions=" in line
    ]
    assert len(lines) == 1, (
        f"{command} printed {len(lines)} reuse line(s), expected exactly one: "
        f"{captured.err!r}"
    )
    assert lines[0].startswith(f"{command}: "), lines[0]
    return lines[0]
