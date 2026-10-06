"""An audio-only store has no caption publication work."""

from bili_asr.cli import main
from bili_asr.storage import MediaQueueRepository, open_database
from test_cli_publish_transcripts import BARE_BVID, PARTS, _seed_archive


def test_audio_only_store_is_a_reported_zero_candidate_publication(tmp_root, capfd):
    _seed_archive(tmp_root, parts=[part for part in PARTS if part[0] == BARE_BVID])
    connection = open_database(tmp_root)
    try:
        MediaQueueRepository(connection).mark_audio_acquired(
            bvid=BARE_BVID, page_index=0, audio_path="audio/example.m4a",
            sha256="a" * 64, byte_size=11, format="m4a", duration_ms=3000,
            acquisition_source="download-audio", acquired_at=100,
        )
    finally:
        connection.close()
    assert main(["publish-transcripts", "--archive-root", str(tmp_root)]) == 0
    assert "candidates=0 published=0 already_published=0 failed=0" in capfd.readouterr().out
