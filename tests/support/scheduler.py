from __future__ import annotations
import json
import os
import pytest
from bili_asr import asr as asr_mod
from bili_asr import bili_client as bc
from bili_asr.cli.main import main
from bili_asr.pipeline.attempts import AttemptLedger
from bili_asr.pipeline.models import RowResult
from bili_asr.manifest import ManifestStore
from bili_asr.meta_cursor import MetaCursorStore, utc_now_iso
from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.run_ledger import LEDGER_FILENAME, RunLedger
from bili_asr.scheduler import (
    SCHEDULER_FILENAME,
    SchedulerStore,
    classify_batch_state,
    settled_processed_ids,
    terminal_resume_ids,
)
from tests.support.audio import (
    AUDIO_BYTES,
    SPI_OK,
    STREAM_HOST,
    RouterTransport,
    nav_response,
    playurl_ok,
)
from tests.support.subtitles import SAMPLE_DOC, nav_ok, player_ok, sub_entry
import tests.support.asr_fakes as asr_fakes
from tests.support.archive_database import _seed_archive_database


SECRET = "SECRET-SESS"


_NO_SECRET_MARKERS = (
    SECRET,
    "SESSDATA",
    "Traceback",
    "upos-sz-",
    "bilivideo.com",
    "deadline=",
    "model failed",
    "FunASR support is not installed",
)


def _row(identity, *, status="meta_ok", duration_s=5, title="clip", **extra):
    row = {
        "bvid": identity.bvid,
        "work_id": identity.work_id,
        "page_index": identity.page_index,
        "cid": identity.cid,
        "page_label": identity.page_label,
        "status": status,
        "title": title,
        "duration_s": duration_s,
        "pubdate": 1,
        "pubdate_str": "2026-01-02",
    }
    row.update(extra)
    return row


def _patch_cli(monkeypatch, transport):
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: (lambda _s: None))
    monkeypatch.setattr('bili_asr.cli.pilot.time.sleep', lambda _s: None)
    monkeypatch.setattr("bili_asr.coordinator.time.sleep", lambda _s: None)


def _stub_asr(monkeypatch):
    return asr_fakes.install(monkeypatch, text="asr-text")


def _assert_no_secrets(captured, root):
    blob = captured.out + captured.err
    for marker in _NO_SECRET_MARKERS:
        assert marker not in blob
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith((".jsonl", ".json", ".md", ".txt", ".srt")):
                continue
            text = open(os.path.join(dirpath, name), encoding="utf-8").read()
            for marker in _NO_SECRET_MARKERS:
                assert marker not in text


def _write_subtitle_raw(root, identity):
    path = os.path.join(root, "subtitles", "raw", f"{artifact_stem(identity)}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(SAMPLE_DOC, fh)


def _scheduler(root):
    return SchedulerStore(root=root).load()


def _base_routes():
    return {
        "finger/spi": [SPI_OK] * 16,
        "nav": [nav_ok(), nav_response()],
        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
    }


class CidRouterTransport(RouterTransport):
    def __init__(self, player_by_cid, playurl_by_cid=None, routes=None,
                 stream_routes=None):
        routes = dict(routes or {})
        routes.pop("player/wbi/v2", None)
        routes.pop("playurl", None)
        super().__init__(routes, stream_routes)
        self.player_by_cid = dict(player_by_cid)
        self.playurl_by_cid = dict(playurl_by_cid or {})

    def get_json(self, url, params=None, headers=None, cookies=None, timeout=None):
        self.calls.append({
            "url": url,
            "params": dict(params or {}),
            "headers": dict(headers or {}),
            "cookies": dict(cookies or {}),
        })
        cid = dict(params or {}).get("cid")
        if "player/wbi/v2" in url:
            if cid not in self.player_by_cid:
                raise AssertionError(f"no player route for cid={cid}")
            return self.player_by_cid[cid]
        if "/x/player/wbi/playurl" in url:
            if cid not in self.playurl_by_cid:
                raise AssertionError(f"no playurl route for cid={cid}")
            return self.playurl_by_cid[cid]
        self.calls.pop()
        return super().get_json(url, params=params, headers=headers,
                                cookies=cookies, timeout=timeout)
