"""Durable single-file replacement handles incomplete writes and ownership failures."""
import os

import pytest

from bili_asr import file_ops


class PartialWriter:
    def __init__(self, stream, *, zero_after_first=False):
        self.stream = stream
        self.zero_after_first = zero_after_first
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def write(self, content):
        self.calls += 1
        if self.zero_after_first and self.calls > 1:
            return 0
        return self.stream.write(content[:3])


def test_atomic_replace_completes_short_writes_before_publishing(tmp_path, monkeypatch):
    destination = tmp_path / "value.json"
    content = '{"original":"中文 synthetic data"}\n'.encode("utf-8")
    original = os.fdopen
    monkeypatch.setattr(file_ops.os, "fdopen", lambda *args: PartialWriter(original(*args)))
    file_ops.atomic_replace_file(destination, content)
    assert destination.read_bytes() == content
    assert list(tmp_path.iterdir()) == [destination]


def test_zero_write_preserves_destination_and_removes_private_partial_file(tmp_path, monkeypatch):
    destination = tmp_path / "value.json"
    destination.write_bytes(b"original bytes")
    original = os.fdopen
    monkeypatch.setattr(file_ops.os, "fdopen", lambda *args: PartialWriter(original(*args), zero_after_first=True))
    with pytest.raises(OSError, match="cannot complete file write"):
        file_ops.atomic_replace_file(destination, b"replacement bytes")
    assert destination.read_bytes() == b"original bytes"
    assert list(tmp_path.iterdir()) == [destination]


def test_stream_initialization_failure_closes_descriptor_and_preserves_destination(tmp_path, monkeypatch):
    destination = tmp_path / "value.json"
    destination.write_bytes(b"original bytes")
    opened = []

    def fail_open(descriptor, mode):
        opened.append(descriptor)
        raise OSError("synthetic stream initialization failure")

    monkeypatch.setattr(file_ops.os, "fdopen", fail_open)
    with pytest.raises(OSError, match="stream initialization failure"):
        file_ops.atomic_replace_file(destination, b"replacement bytes")
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])
    assert destination.read_bytes() == b"original bytes"
    assert list(tmp_path.iterdir()) == [destination]
