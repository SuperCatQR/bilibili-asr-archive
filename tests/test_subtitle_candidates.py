"""Real acquisition transactions for empty documents and alternate candidates."""
import asyncio
import json

import pytest

from bili_asr.services.subtitle_ingest import SubtitleIngestor, SubtitleSelection
from bili_asr.sources.models import (
    GatewayAuthenticationError, GatewayRateLimited, GatewayTransportError,
    GatewayShapeError, SubtitleBodyRead, SubtitleSegment, SubtitleTrack,
)
from bili_asr.sources.protocols import SourceAccessObservation
from bili_asr.storage import TranscriptRepository, open_database
from bili_asr.subtitle_policy import rank_candidates
from tests.test_workflow_control_plane import _seed_part
from bili_asr.storage.workflow import WorkflowRepository, AsrPolicy, AsrProfile, JobKind
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from bili_asr.workflow import WorkflowExecutor


CC = SubtitleTrack("zh-CN", "中文", False, "1")
AI = SubtitleTrack("ai-zh", "自动", True, "2")
EN = SubtitleTrack("en", "English", False, "3")
GOOD = SubtitleBodyRead((SubtitleSegment(0, 1000, "真实字幕"),), 1)
EMPTY = SubtitleBodyRead((), 1, "empty_text")


class Source:
    def __init__(self, answers, *, tracks=(CC, AI)):
        self.answers, self.tracks, self.calls = answers, tracks, []

    async def list_tracks(self, ref):
        return self.tracks

    async def read_body(self, track, ref):
        self.calls.append(track)
        answer = self.answers[track]
        if isinstance(answer, Exception):
            raise answer
        if answer == "wait":
            await asyncio.sleep(60)
        return answer

    async def verify_access(self, ref):
        return SourceAccessObservation("credentialed", True)


@pytest.fixture
def database(tmp_path):
    connection = open_database(tmp_path)
    _seed_part(connection)
    yield connection
    connection.close()


def acquire(database, source, **options):
    return SubtitleIngestor(None, TranscriptRepository(database), source=source,
                            credential_present=True, **options).harvest(
                                SubtitleSelection("BVtest", 0, 1))


def test_first_empty_second_valid_records_one_attempt_and_real_transcript(database):
    source = Source({CC: EMPTY, AI: GOOD})
    result = acquire(database, source)
    assert result.stored == 1 and source.calls == [CC, AI]
    assert result.parts[0].language == "ai-zh"
    assert [candidate.outcome for candidate in result.parts[0].candidates] == ["empty_text", "valid"]
    assert database.execute("SELECT COUNT(*) FROM acquisition_attempts").fetchone()[0] == 1
    assert database.execute("SELECT text FROM transcript_segments").fetchone()[0] == "真实字幕"


def test_all_legal_empty_is_success_with_no_legacy_audio_absence_authority(database):
    result = acquire(database, Source({CC: EMPTY, AI: SubtitleBodyRead((), 0, "empty_body")}))
    assert result.no_subtitle == 1 and result.failed == 0
    assert result.parts[0].availability == "visible_candidates_exhausted"
    row = database.execute("SELECT error_code, credential_verified, absence_verified FROM acquisition_attempts").fetchone()
    assert tuple(row) == (None, 0, 0)
    assert database.execute("SELECT COUNT(*) FROM v_missing_audio").fetchone()[0] == 0
    assert database.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0


@pytest.mark.parametrize("error", [GatewayTransportError(), GatewayShapeError()])
def test_uncertain_candidate_prevents_empty_success_but_valid_alternative_wins(database, error):
    result = acquire(database, Source({CC: error, AI: EMPTY}))
    assert result.failed == 1 and result.parts[0].error_code == error.code
    assert acquire(database, Source({CC: error, AI: GOOD})).stored == 1


@pytest.mark.parametrize("error", [GatewayAuthenticationError(), GatewayRateLimited(),
                                    GatewayTransportError(code="request_budget_exhausted")])
def test_authentication_and_risk_stop_without_probing_more_candidates(database, error):
    source = Source({CC: error, AI: GOOD})
    result = acquire(database, source)
    assert result.parts[0].error_code == error.code and source.calls == [CC]


def test_candidate_and_time_budgets_never_attest_exhaustion(database):
    assert acquire(database, Source({CC: EMPTY, AI: EMPTY}), max_candidates=1).parts[0].error_code == "subtitle_candidate_budget_exhausted"
    source = Source({CC: "wait", AI: GOOD})
    assert acquire(database, source, body_budget_seconds=0.01).parts[0].error_code == "subtitle_candidate_timeout"
    assert source.calls == [CC]


def test_requested_languages_never_fall_back_to_unrequested_language():
    assert rank_candidates((EN, AI, CC), ("en", "zh-CN")) == (EN, CC)
    assert rank_candidates((AI, EN, CC)) == (CC, AI, EN)


@pytest.mark.parametrize("body, reason", [([], "empty_body"), ([{"from": 1, "to": 2, "content": "  "}], "empty_text")])
def test_gateway_reads_actual_legal_empty_document(body, reason, monkeypatch):
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    gateway = BilibiliApiGateway()
    async def fetch(*args):
        return {"body": body}
    monkeypatch.setattr(gateway, "_fetch_caption_document", fetch)
    result = asyncio.run(gateway.read_subtitle_body(CC, "BV18L4y1E7qs", 471977032))
    assert result.empty_kind == reason and result.row_count == len(body)


@pytest.mark.parametrize("row", [
    {"from": -1, "to": 2, "content": ""}, {"from": 2, "to": 1, "content": ""},
    {"from": float("nan"), "to": 2, "content": ""}, {"from": 1, "content": ""},
])
def test_malformed_timeline_never_becomes_verified_empty(row, monkeypatch):
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    gateway = BilibiliApiGateway()
    async def fetch(*args):
        return {"body": [row]}
    monkeypatch.setattr(gateway, "_fetch_caption_document", fetch)
    with pytest.raises(GatewayShapeError):
        asyncio.run(gateway.read_subtitle_body(CC, "BV18L4y1E7qs", 471977032))


def test_real_executor_preserves_four_failures_and_safe_actionable_candidate_diagnostics(database, tmp_path):
    class Gateway:
        async def get_subtitle_tracks(self, bvid, cid):
            return (CC,)
        async def read_subtitle_body(self, track, bvid, cid):
            raise GatewayTransportError(detail="https://private.invalid/?cookie=credential")
    repository = WorkflowRepository(database)
    profile_id = repository.register_profile(AsrProfile("candidate", "offline", device="cpu"))
    repository.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=profile_id)
    handlers = ArchiveWorkflowHandlers(database, repository, archive_root=tmp_path, sessdata=None,
                                       gateway_factory=lambda **kwargs: Gateway())
    executor = WorkflowExecutor(repository, worker_id="candidate-test", handlers=handlers.handlers(),
                                kinds=(JobKind.SUBTITLE,))
    for attempt in range(4):
        assert executor.run(limit=1).failed == 1
        if attempt < 3:
            assert repository.requeue_failed(kinds=(JobKind.SUBTITLE,)) == 1
    rows = list(database.execute("SELECT error_code,result_json FROM workflow_attempts ORDER BY rowid"))
    assert len(rows) == 4
    for row in rows:
        assert row[0] == "transport_error"
        details = json.loads(row[1])["diagnostic"]
        assert details["availability"] == "uncertain"
        assert details["candidates"][0]["error_code"] == "transport_error"
        assert "credential" not in row[1] and "https" not in row[1]
    assert repository.claim("candidate-test", kinds=(JobKind.AUDIO,)) is not None
    handlers.close()


def test_real_executor_all_empty_succeeds_without_fabricating_transcript(database, tmp_path):
    class Gateway:
        async def get_subtitle_tracks(self, bvid, cid):
            return (CC, AI)
        async def read_subtitle_body(self, track, bvid, cid):
            return EMPTY
    repository = WorkflowRepository(database)
    profile_id = repository.register_profile(AsrProfile("empty", "offline", device="cpu"))
    repository.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=profile_id)
    handlers = ArchiveWorkflowHandlers(database, repository, archive_root=tmp_path, sessdata=None,
                                       gateway_factory=lambda **kwargs: Gateway())
    assert WorkflowExecutor(repository, worker_id="empty-test", handlers=handlers.handlers(),
                            kinds=(JobKind.SUBTITLE,)).run(limit=1).succeeded == 1
    result = json.loads(database.execute("SELECT result_json FROM workflow_attempts").fetchone()[0])
    assert result["availability"] == "visible_candidates_exhausted"
    assert database.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
    audio_job = repository.claim("empty-test", kinds=(JobKind.AUDIO,))
    repository.finish(audio_job.job_id, worker_id="empty-test", result={"storage_key": "audio/existing.m4a"})
    assert repository.claim("empty-test", kinds=(JobKind.ASR,)) is not None
    handlers.close()
