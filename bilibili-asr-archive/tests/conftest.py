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

# Setup-failure forensics. The full suite has been observed red in some runs and
# green in others on an unchanged tree (recorded 261 / 0 / 196 / 0 setup errors),
# and the red runs left nothing behind: pytest's default report goes to the
# terminal, so the cause died with the scrollback. These constants pin the
# evidence to a stable, gitignored path (.tb/ is already an ignored convention)
# so the *next* red is diagnosable instead of merely counted.
_TRACEBACK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tb"))
_TRACEBACK_PATH = os.path.join(_TRACEBACK_DIR, "setup-failures.log")


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
    """Persist the traceback of any setup failure to a stable path.

    Only the ``setup`` phase is recorded: that is the phase the recorded
    cross-file, large-and-varying-count red hit, and it is the phase whose
    failures are otherwise indistinguishable from "the fixture never ran".
    Reporting must never itself fail the run, so every step is guarded.
    """
    outcome = yield
    if call.when != "setup":
        return
    report = outcome.get_result()
    if not report.failed:
        return
    try:
        os.makedirs(_TRACEBACK_DIR, exist_ok=True)
        with open(_TRACEBACK_PATH, "a", encoding="utf-8") as handle:
            handle.write(f"{'=' * 78}\n")
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} SETUP FAILURE\n")
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


@pytest.fixture(autouse=True)
def mock_torch(monkeypatch):
    """Mock torch module to report CUDA is available for all tests.
    
    This prevents PyTorch import errors in ASR tests that use mocked models.
    """
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True)
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
