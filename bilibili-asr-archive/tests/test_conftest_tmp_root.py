"""Pin for conftest's ``tmp_root`` PID-reuse hardening (plan 007).

Before the UUID suffix, the dir name was ``manifest-test-<pid>-<counter>``; a
leftover dir from a killed run could collide on PID reuse and raise
``FileExistsError`` in fixture setup (an intermittent full-suite red). The fix
adds a UUID component, so a stale dir is tolerated instead of colliding.
"""

from __future__ import annotations

import os
import re

import conftest as _conftest
import pytest


def test_tmp_root_reuse_leftover_dir():
    """A stale leftover dir must not make ``tmp_root`` raise FileExistsError."""
    stale = os.path.join(_conftest._TEST_TMP_BASE, "manifest-test-stale-leftover")
    os.makedirs(stale, exist_ok=True)
    try:
        with pytest.raises(FileExistsError):
            os.makedirs(stale)
    finally:
        pass  # stale dir stays in place: the fixture must tolerate it.

    fixture = _conftest.tmp_root.__wrapped__
    os.makedirs(_conftest._TEST_TMP_BASE, exist_ok=True)
    gen = fixture()
    yielded = next(gen)
    try:
        assert yielded != stale
        assert os.path.isdir(yielded)
        assert os.path.commonpath([yielded, _conftest._TEST_TMP_BASE]) == (
            _conftest._TEST_TMP_BASE
        )
        # The deterministic prefix survives; the UUID suffix prevents reuse collisions.
        assert re.match(
            r"^manifest-test-\d+-\d+-[0-9a-f]{32}$", os.path.basename(yielded)
        )
    finally:
        try:
            next(gen)
        except StopIteration:
            pass
    assert not os.path.exists(yielded)  # teardown removes the yielded dir
