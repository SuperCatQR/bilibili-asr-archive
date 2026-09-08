import itertools
import os
import shutil
import sys
import types

import pytest

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

_TEST_TMP_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".test-tmp"))
_counter = itertools.count()


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
