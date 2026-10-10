"""Independent final release target-generation boundary regressions."""
from __future__ import annotations

import pytest

from bili_asr.services import artifact_transfer as service
from tests.support.artifact_online import archive as online_archive
from tests.test_artifact_transfer import plan


@pytest.fixture
def archive(tmp_path):
    return online_archive.__wrapped__(tmp_path)


def test_target_changed_after_member_read_never_becomes_verified_generation(archive, monkeypatch):
    original = service.copy_package_object

    def corrupt_after_read(package_path, *args, **kwargs):
        result = original(package_path, *args, **kwargs)
        # A concurrent change after the verified read must not become the
        # generation that the final deletion guard treats as verified.
        content = bytearray(package_path.read_bytes())
        content[content.index(archive.data)] ^= 0xFF
        package_path.write_bytes(content)
        return result

    monkeypatch.setattr(service, "copy_package_object", corrupt_after_read)
    with pytest.raises(ValueError, match="generation|changed"):
        service.transfer_artifacts(archive.roots, plan(archive), target_root=archive.target,
                                   mode="offload", external_holds={}, _online=True)
    assert archive.data in [path.read_bytes() for path in (archive.root / "audio").iterdir()
                            if path.is_file()]
