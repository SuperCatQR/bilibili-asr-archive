"""Exercise the real bounded subprocess boundary without network/credentials."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from bili_asr.platform_identity import ContentRef
from bili_asr.sources.models import GatewayError, GatewayShapeError
from bili_asr.sources.youtube_source import YoutubeSource, normalize_json3

REF = ContentRef("youtube", "dQw4w9WgXcQ")


@pytest.fixture
def extractor(tmp_path):
    script = tmp_path / "extractor.py"
    script.write_text('''import json,os,pathlib,subprocess,sys,time
args=sys.argv[1:]
mode=os.environ.get("MOCK_YOUTUBE_MODE", "normal")
evidence=pathlib.Path(os.environ["MOCK_YOUTUBE_EVIDENCE"])
with evidence.open("a") as out: out.write(json.dumps(args)+"\\n")
if mode=="sleep": time.sleep(30)
if mode=="budget":
    sys.stdout.write("x"*(9*1024*1024)); sys.stdout.flush(); time.sleep(30)
if mode=="orphan":
    child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])
    (evidence.parent/"child.pid").write_text(str(child.pid))
    os._exit(1)
if mode=="denied":
    sys.stderr.write("Sign in: cookie=SECRET https://private.test/?signature=SECRET")
    sys.exit(1)
if "--dump-single-json" in args:
    print(json.dumps({"id":"dQw4w9WgXcQ","title":"English lesson","duration":2,"language":"en",
        "channel_id":"UC_creator","channel":"Teacher","upload_date":"20200102","timestamp":1577923200,
        "subtitles":{"en":[{"ext":"json3","name":"English"}]},"automatic_captions":{}}))
elif "--sub-format" in args:
    pathlib.Path("caption.en.json3").write_text(json.dumps({"events":[{"tStartMs":0,"dDurationMs":2000,"segs":[{"utf8":"A complete English sentence."}]}]}))
else:
    pattern=args[args.index("--output")+1]
    target=pathlib.Path(pattern.replace("%(ext)s","webm"))
    target.write_bytes(b"audio"); print(target)
''', encoding="utf-8")
    return script


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    path = tmp_path / "argv.jsonl"
    monkeypatch.setenv("MOCK_YOUTUBE_EVIDENCE", str(path))
    return path


def test_real_subprocess_metadata_caption_audio_and_checkpoint_thread(extractor, evidence, tmp_path):
    owner = threading.get_ident()
    checkpoints = []
    def checkpoint():
        assert threading.get_ident() == owner
        checkpoints.append(True)
    source = YoutubeSource(command=(sys.executable,str(extractor)), checkpoint=checkpoint)
    metadata = source.metadata(REF)
    assert metadata.title == "English lesson" and metadata.duration_ms == 2000
    tracks = asyncio.run(source.list_tracks(REF))
    assert len(tracks) == 1 and not tracks[0].is_ai
    segments = asyncio.run(source.fetch_segments(tracks[0], REF))
    assert segments[0].text == "A complete English sentence."
    audio = source.download_audio(REF,tmp_path / "youtube.digest.p0",staging_root=tmp_path)
    assert audio.name == "youtube.digest.p0.webm" and audio.read_bytes() == b"audio"
    invocations = [json.loads(line) for line in evidence.read_text().splitlines()]
    assert len(invocations) == 3 and checkpoints
    for args in invocations:
        assert "--ignore-config" in args and "--no-playlist" in args
        assert "--no-remote-components" in args and args[-2:] == ["--","https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
        assert "--download-archive" not in args
    assert "--no-simulate" in invocations[-1]


@pytest.mark.parametrize("mode,code", [("sleep","youtube_timeout"),("budget","youtube_output_budget"),("denied","auth_failed")])
def test_real_subprocess_faults_are_bounded_and_redacted(extractor,evidence,monkeypatch,mode,code):
    monkeypatch.setenv("MOCK_YOUTUBE_MODE",mode)
    started = time.monotonic()
    with pytest.raises(GatewayError) as error:
        YoutubeSource(command=(sys.executable,str(extractor)),timeout_seconds=1).metadata(REF)
    assert error.value.code == code and "SECRET" not in str(error.value)
    assert time.monotonic()-started < 8


def test_real_subprocess_cancellation_reaps_process(extractor,evidence,monkeypatch):
    monkeypatch.setenv("MOCK_YOUTUBE_MODE","sleep")
    calls = 0
    def checkpoint():
        nonlocal calls
        calls += 1
        if calls > 3:
            raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError,match="cancelled"):
        YoutubeSource(command=(sys.executable,str(extractor)),checkpoint=checkpoint).metadata(REF)
    assert calls > 3


@pytest.mark.skipif(os.name == "nt",reason="POSIX process-group ownership regression")
def test_exited_extractor_leader_cannot_leave_decoder_descendant(extractor,evidence,monkeypatch):
    monkeypatch.setenv("MOCK_YOUTUBE_MODE","orphan")
    with pytest.raises(GatewayError):
        YoutubeSource(command=(sys.executable,str(extractor))).metadata(REF)
    pid = int((evidence.parent / "child.pid").read_text())
    deadline = time.monotonic()+3
    while time.monotonic() < deadline:
        status = Path(f"/proc/{pid}/stat")
        try:
            dead = status.read_text().split()[2] == "Z"
        except (FileNotFoundError, ProcessLookupError):
            dead = True
        if dead:
            break
        time.sleep(.05)
    else:
        pytest.fail("extractor descendant survived cleanup")


def test_incremental_caption_append_preserves_word_boundary_and_deduplicates_rolling_window():
    result = normalize_json3({"events":[
        {"tStartMs":0,"dDurationMs":1000,"segs":[{"utf8":"Hello"}]},
        {"tStartMs":500,"dDurationMs":1000,"aAppend":1,"segs":[{"utf8":" world"}]},
        {"tStartMs":1000,"dDurationMs":1000,"segs":[{"utf8":"Hello world again"}]},
        {"tStartMs":2500,"dDurationMs":500,"segs":[{"utf8":"Another cue"}]},
    ]})
    assert [item.text for item in result] == ["Hello world again","Another cue"]
    assert result[0].start_ms == 0 and result[0].end_ms == 2000


@pytest.mark.parametrize("release", [None, "invalid", True, -1, float("nan"), float("inf"), 2**64])
def test_invalid_release_timestamp_preserves_precise_upload_timestamp(release):
    source = YoutubeSource()
    source._information[REF] = {"title": "Source", "duration": 2,
                                "release_timestamp": release, "timestamp": 1577923210,
                                "upload_date": "20200102"}
    assert source.metadata(REF).published_at == 1577923210


def test_valid_release_timestamp_has_precedence_over_upload_timestamp():
    source = YoutubeSource()
    source._information[REF] = {"title": "Source", "duration": 2,
                                "release_timestamp": 1577923220, "timestamp": 1577923210}
    assert source.metadata(REF).published_at == 1577923220


def test_date_only_upload_does_not_fabricate_midnight_precision():
    source = YoutubeSource()
    source._information[REF] = {"title": "Source", "duration": 2,
                                "release_timestamp": None, "upload_date": "20200102"}
    assert source.metadata(REF).published_at is None


@pytest.mark.parametrize("field,value", [
    ("title", "x" * 513), ("title", "bad\u0085title"), ("title", "bad\ud800title"),
    ("channel", "x" * 513), ("channel", "bad\u0085creator"),
    ("channel_id", "x" * 513), ("language", "bad\u0085language"),
    ("duration", 2**63), ("timestamp", 2**63),
])
def test_incompatible_provider_metadata_is_rejected_before_source_storage(tmp_path, field, value):
    from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession
    from bili_asr.services.archive_migration import initialize_archive
    from bili_asr.storage.sources import SourceRepository

    root = tmp_path / "archive"
    initialize_archive(root)
    source = YoutubeSource()
    source._information[REF] = {"title": "Source", "duration": 2, field: value}
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        before = "\n".join(session.connection.iterdump())
        with pytest.raises(GatewayShapeError) as error:
            with session.connection:
                SourceRepository(session.connection).upsert_video(source.metadata(REF))
        assert error.value.code == "youtube_metadata_shape"
        assert "\n".join(session.connection.iterdump()) == before
        assert not session.connection.execute("SELECT 1 FROM source_videos").fetchone()
