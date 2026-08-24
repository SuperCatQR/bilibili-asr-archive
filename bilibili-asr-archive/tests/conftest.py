import itertools
import os
import shutil

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
