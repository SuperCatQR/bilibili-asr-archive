"""Contract tests for the queue-gap read repository.

``MediaQueueRepository`` reads the three gap views one work queue each and owns
the order the views do not declare.  These tests pin that order, the membership
each view defines, the narrowing each filter performs, and the attempt evidence
the typed entry carries.

The store is built through the repositories' own writers wherever one exists.
The audio rows are the exception: the ``audio_objects`` / ``part_audio_objects``
evidence pair and the audio route's failed-attempt row are written here as SQL,
so what a gap view probes is pinned against the declared schema shape rather
than against the writer ``test_storage_queue_writes.py`` owns.
"""

from __future__ import annotations

import sqlite3
from typing import get_args

import pytest

from bili_asr.storage import (
    ALLOWED_QUEUE_GAPS,
    AcquisitionRunRecord,
    MediaQueueRepository,
    MetadataRepository,
    QueueGap,
    QueueGapItem,
    SchemaContractError,
    TranscriptRepository,
    TranscriptSegmentRecord,
    UserRecord,
    VideoPartRecord,
    VideoRecord,
    open_database,
)


_MID = 23191782
# ``pubdate`` values chosen so the four queued videos separate: two share one
# publication second (the bvid/page tie-break), and the rest order by date.
_VIDEOS = (
    ("BV1AAA", 3_000, "三秒的视频"),
    ("BV1BBB", 2_000, "两秒的视频"),
    ("BV1CCC", 1_000, "一秒的视频"),
    ("BV1DDD", 500, "下架的视频"),
    ("BV1EEE", 3_000, "另一个三秒的视频"),
    ("BV1FFF", 1_500, "一秒半的视频"),
)
# Every part the fixture stores: one captionless never-attempted part, one whose
# newest subtitle attempt found nothing, one with archived audio and no
# transcript, one holding a transcript, one gone part with archived audio, and
# one whose subtitle attempt failed and whose audio download failed too.
_PARTS = (
    ("BV1AAA", 0, "discovered"),
    ("BV1AAA", 1, "discovered"),
    ("BV1BBB", 0, "discovered"),
    ("BV1CCC", 0, "discovered"),
    ("BV1DDD", 0, "gone"),
    ("BV1EEE", 0, "discovered"),
    ("BV1FFF", 0, "discovered"),
)


def _open_run(
    transcripts: TranscriptRepository, run_id: str, kind: str
) -> None:
    """Open one parent run of ``kind`` so attempt rows have their foreign key."""
    transcripts.start_acquisition_run(
        AcquisitionRunRecord(
            run_id=run_id,
            kind=kind,
            selector_kind="pending",
            selector_target=None,
            requested_limit=None,
            credential_present=False,
            started_at=200,
        )
    )


def _audio_attempt(
    connection: sqlite3.Connection, run_id: str, video_part_id: int
) -> None:
    """Insert one failed audio attempt row directly.

    This is *not* audio evidence: the attempt contract's ``kind='audio'`` shape
    is a ``'failed'`` outcome with a bounded ``error_code`` and no transcript
    (``stored`` / ``unchanged`` require a ``transcript_id`` an audio download
    never produces), so a row here records a download that produced nothing.
    """
    connection.execute(
        """
        INSERT INTO acquisition_attempts(
            run_id, video_part_id, outcome, error_code, transcript_id,
            started_at, finished_at
        ) VALUES (?, ?, 'failed', 'audio_unavailable', NULL, 700, 800)
        """,
        (run_id, video_part_id),
    )
    connection.commit()


def _archive_audio(
    connection: sqlite3.Connection,
    *,
    audio_id: int,
    video_part_id: int,
    sha256: str,
    storage_key: str,
) -> None:
    """Insert the positive audio evidence: one object row and its part link."""
    connection.execute(
        """
        INSERT INTO audio_objects(
            audio_id, sha256, byte_size, format, duration_ms, storage_key, created_at
        ) VALUES (?, ?, 4096, 'm4a', 1234, ?, 650)
        """,
        (audio_id, sha256, storage_key),
    )
    connection.execute(
        """
        INSERT INTO part_audio_objects(
            video_part_id, audio_id, acquired_at, acquisition_source
        ) VALUES (?, ?, 650, 'download')
        """,
        (video_part_id, audio_id),
    )
    connection.commit()


def _seed(
    connection: sqlite3.Connection,
) -> tuple[dict[tuple[str, int], int], MediaQueueRepository]:
    """Store the fixture's videos, parts, runs and attempts; return the ids."""
    metadata = MetadataRepository(connection)
    transcripts = TranscriptRepository(connection)
    with metadata.transaction():
        metadata.upsert_user(
            UserRecord(mid=_MID, display_name="未明子", created_at=100, updated_at=100)
        )
        for bvid, pubdate, title in _VIDEOS:
            metadata.upsert_video(
                VideoRecord(
                    bvid=bvid,
                    aid=None,
                    mid=_MID,
                    title=title,
                    pubdate=pubdate,
                    created_at=101,
                    updated_at=101,
                )
            )
        parts = {
            (bvid, page_index): metadata.upsert_part(
                VideoPartRecord(
                    bvid=bvid,
                    page_index=page_index,
                    cid=2_000 + index,
                    title=f"{bvid} 第 {page_index} 段",
                    duration_ms=1_000 + index,
                    processing_status=status,
                    created_at=102,
                    updated_at=102,
                )
            )
            for index, (bvid, page_index, status) in enumerate(_PARTS, start=1)
        }

    # BV1AAA:p1 — three subtitle attempts; the two newest independently listed
    # nothing.  Exhaustion is attested, not inferred from one look: an empty
    # inventory carrying no error code is an *indefinite* negative (this
    # credential may simply not have seen the part), so it admits only once two
    # distinct runs have observed it empty.  Hence two runs here, not one.
    _open_run(transcripts, "run-sub-old", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-sub-old",
        video_part_id=parts[("BV1AAA", 1)],
        outcome="failed",
        error_code="upstream_timeout",
        started_at=300,
        finished_at=400,
    )
    _open_run(transcripts, "run-sub-new", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-sub-new",
        video_part_id=parts[("BV1AAA", 1)],
        outcome="no-subtitle",
        error_code=None,
        started_at=500,
        finished_at=600,
    )
    _open_run(transcripts, "run-sub-confirm", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-sub-confirm",
        video_part_id=parts[("BV1AAA", 1)],
        outcome="no-subtitle",
        error_code=None,
        started_at=700,
        finished_at=800,
    )

    # BV1BBB:p0 — audio was attempted (and the attempt failed), then archived:
    # the object link is the evidence, the attempt row is history.
    _open_run(transcripts, "run-audio-bbb", "audio")
    _audio_attempt(connection, "run-audio-bbb", parts[("BV1BBB", 0)])
    _archive_audio(
        connection,
        audio_id=1,
        video_part_id=parts[("BV1BBB", 0)],
        sha256="a" * 64,
        storage_key="audio/BV1BBB-p0.m4a",
    )

    # BV1CCC:p0 — a stored transcript leaves every queue.
    _open_run(transcripts, "run-sub-ccc", "subtitle")
    transcripts.record_acquired_transcript(
        run_id="run-sub-ccc",
        video_part_id=parts[("BV1CCC", 0)],
        source_kind="subtitle-ai",
        language="zh-CN",
        segments=(TranscriptSegmentRecord(start_ms=0, end_ms=1_000, text="第一句"),),
        started_at=900,
        finished_at=1_000,
        created_at=1_001,
    )

    # BV1DDD:p0 — gone, so only the view that does not filter status holds it.
    # Its audio attempt also failed; only the archived object counts.
    _open_run(transcripts, "run-audio-ddd", "audio")
    _audio_attempt(connection, "run-audio-ddd", parts[("BV1DDD", 0)])
    _archive_audio(
        connection,
        audio_id=2,
        video_part_id=parts[("BV1DDD", 0)],
        sha256="b" * 64,
        storage_key="audio/BV1DDD-p0.m4a",
    )

    # BV1FFF:p0 — one failed subtitle attempt: the outcome the audio queue also
    # accepts, so the newest evidence carries an error code.  Its audio download
    # also failed and archived nothing, so the part must *stay* in the audio
    # queue: the attempt row is rotation history, never a claim that bytes
    # exist.  (Pre-fix this row read as audio evidence and pushed the part into
    # the transcript queue with no audio on disk.)
    _open_run(transcripts, "run-sub-fff", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-sub-fff",
        video_part_id=parts[("BV1FFF", 0)],
        outcome="failed",
        error_code="risk_control",
        started_at=1_100,
        finished_at=1_200,
    )
    _open_run(transcripts, "run-audio-fff", "audio")
    _audio_attempt(connection, "run-audio-fff", parts[("BV1FFF", 0)])
    return parts, MediaQueueRepository(connection)


@pytest.fixture
def queue_store(tmp_root):
    """A seeded store with its queue repository; the connection is closed last."""
    connection = open_database(tmp_root)
    try:
        yield connection, *_seed(connection)
    finally:
        connection.close()


def test_queue_gap_literal_matches_its_validation_set():
    """The three queue names and their enumeration set are one contract."""
    assert sorted(get_args(QueueGap)) == [
        "missing_audio",
        "missing_subtitle",
        "missing_transcript",
    ]
    assert sorted(ALLOWED_QUEUE_GAPS) == sorted(get_args(QueueGap))


def test_each_gap_holds_exactly_the_parts_its_view_defines(queue_store):
    """Membership comes from the view; the repository adds no predicate."""
    _connection, parts, repository = queue_store
    assert len(parts) == len(_PARTS)

    members = {
        gap: [item.work_id for item in repository.list_queue_gaps(gap=gap)]
        for gap in sorted(ALLOWED_QUEUE_GAPS)
    }
    # BV1AAA:p0 and BV1EEE:p0 have no evidence at all, BV1AAA:p1 was attempted
    # and listed nothing, BV1BBB:p0 was reached on the audio route; BV1CCC:p0
    # holds a transcript and belongs to no queue.
    assert members["missing_subtitle"] == [
        "BV1AAA:p0",
        "BV1AAA:p1",
        "BV1EEE:p0",
        "BV1BBB:p0",
        "BV1FFF:p0",
    ]
    # Only the parts whose newest subtitle attempt is a terminal "no caption"
    # outcome are queued for audio.  BV1FFF:p0 stays here although its audio
    # download was already attempted and failed: a failed attempt is not
    # acquired bytes, and the queue admits it exactly because no object exists.
    assert members["missing_audio"] == ["BV1AAA:p1", "BV1FFF:p0"]
    # Audio evidence is the archived object, so the two parts holding one — the
    # gone part and the one whose download also failed — are here together.
    # This view does not filter status.
    assert members["missing_transcript"] == ["BV1BBB:p0", "BV1DDD:p0"]

    assert all(
        isinstance(item, QueueGapItem)
        for item in repository.list_queue_gaps(gap="missing_subtitle")
    )



def test_one_empty_inventory_is_not_exhaustion(queue_store):
    """A single empty look must not admit a part: exhaustion is attested.

    Measured 2026-10-03 (``I-000187``): ``probe-subs`` reported ``tracks=0`` /
    "(no subtitles visible)" for two parts, and minutes later ``harvest-subs``
    stored ``subtitle-ai`` for both — the inventory had simply not been visible
    to the credential in effect.  The gateway contract says as much: "An
    inventory the credential in effect could not see is an empty tuple".

    So an empty inventory (``outcome='no-subtitle'`` with no error code) is an
    *indefinite* negative.  One such observation is not exhaustion, and the part
    must stay out of the audio queue.
    """
    connection, parts, repository = queue_store
    transcripts = TranscriptRepository(connection)

    # BV1EEE:p0 carries no evidence at all in the fixture; give it exactly one
    # empty observation, from a single run.  (BV1DDD:p0 is unusable: it is
    # processing_status='gone', which the view excludes.)
    _open_run(transcripts, "run-emptied-once", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-emptied-once",
        video_part_id=parts[("BV1EEE", 0)],
        outcome="no-subtitle",
        error_code=None,
        started_at=900,
        finished_at=1_000,
    )

    assert "BV1EEE:p0" not in [
        item.work_id for item in repository.list_queue_gaps(gap="missing_audio")
    ]

    # A second, independent observation (distinct run) is what admits it.
    _open_run(transcripts, "run-emptied-twice", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-emptied-twice",
        video_part_id=parts[("BV1EEE", 0)],
        outcome="no-subtitle",
        error_code=None,
        started_at=1_100,
        finished_at=1_200,
    )

    assert "BV1EEE:p0" in [
        item.work_id for item in repository.list_queue_gaps(gap="missing_audio")
    ]


def test_a_definite_not_found_admits_at_once(queue_store):
    """A gateway ``not_found`` is a claim about the part, so one look suffices.

    It must not be made to wait for corroboration: "this video has no subtitle
    resource" is definite evidence, unlike "I could not see an inventory".
    """
    connection, parts, repository = queue_store
    transcripts = TranscriptRepository(connection)

    _open_run(transcripts, "run-not-found", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-not-found",
        video_part_id=parts[("BV1EEE", 0)],
        outcome="no-subtitle",
        error_code="not_found",
        started_at=900,
        finished_at=1_000,
    )

    assert "BV1EEE:p0" in [
        item.work_id for item in repository.list_queue_gaps(gap="missing_audio")
    ]


def test_two_empty_looks_in_one_run_are_one_observation(queue_store):
    """``COUNT(DISTINCT run_id)`` is load-bearing, so a retry cannot inflate it.

    The attempt table's primary key is ``(run_id, video_part_id)``, so a second
    empty observation inside one run is not merely counted once — it cannot be
    written at all.  This asserts that, which is what makes the corroboration
    rule resistant to a retry loop.
    """
    import sqlite3 as _sqlite3

    connection, parts, repository = queue_store
    transcripts = TranscriptRepository(connection)

    _open_run(transcripts, "run-one-only", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-one-only",
        video_part_id=parts[("BV1EEE", 0)],
        outcome="no-subtitle",
        error_code=None,
        started_at=900,
        finished_at=1_000,
    )

    with pytest.raises(_sqlite3.IntegrityError):
        transcripts.record_subtitle_attempt(
            run_id="run-one-only",
            video_part_id=parts[("BV1EEE", 0)],
            outcome="no-subtitle",
            error_code=None,
            started_at=1_100,
            finished_at=1_200,
        )

    assert "BV1EEE:p0" not in [
        item.work_id for item in repository.list_queue_gaps(gap="missing_audio")
    ]


def test_only_indefinite_observations_confirm_an_empty_inventory(queue_store):
    """Only *indefinite* observations corroborate: the counter's filter is load-bearing.

    ``empty_inventory_confirmations`` counts ``outcome = 'no-subtitle'`` rows
    whose ``error_code IS NULL``.  Dropping that filter would let a ``not_found``
    row (a definite negative) or a ``failed`` row (which observed nothing about
    the inventory at all) supply the second "confirmation" — admitting a part on
    one empty look plus one unrelated row, which is the conflation this whole
    fix exists to remove.

    The *newest* attempt decides admission, and the corroboration count is
    independent of recency, so each case below keeps the indefinite observation
    newest (later ``finished_at``) and checks the count alone.
    """
    connection, parts, repository = queue_store
    transcripts = TranscriptRepository(connection)

    # One indefinite observation, made NEWEST by using the latest timestamps.
    _open_run(transcripts, "run-definite", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-definite",
        video_part_id=parts[("BV1EEE", 0)],
        outcome="no-subtitle",
        error_code="not_found",
        started_at=100,
        finished_at=200,
    )
    _open_run(transcripts, "run-failed", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-failed",
        video_part_id=parts[("BV1EEE", 0)],
        outcome="failed",
        error_code="upstream_timeout",
        started_at=300,
        finished_at=400,
    )
    _open_run(transcripts, "run-indefinite", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-indefinite",
        video_part_id=parts[("BV1EEE", 0)],
        outcome="no-subtitle",
        error_code=None,
        started_at=500,
        finished_at=600,
    )

    # The newest attempt is indefinite, and no *other indefinite* row exists, so
    # the not_found and failed rows above must not have contributed a second
    # confirmation.
    assert "BV1EEE:p0" not in [
        item.work_id for item in repository.list_queue_gaps(gap="missing_audio")
    ]

    # A second INDEFINITE observation admits it.
    _open_run(transcripts, "run-indefinite-2", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-indefinite-2",
        video_part_id=parts[("BV1EEE", 0)],
        outcome="no-subtitle",
        error_code=None,
        started_at=700,
        finished_at=800,
    )
    assert "BV1EEE:p0" in [
        item.work_id for item in repository.list_queue_gaps(gap="missing_audio")
    ]


def test_v_part_pipeline_agrees_with_v_missing_audio(queue_store):
    """The two views must not contradict each other on the same row.

    ``v_part_pipeline`` documents ``audio_pending`` as meaning the part is in
    ``v_missing_audio``.  If the pipeline view kept the old one-look predicate
    while the queue view gained corroboration, a part with a single empty
    observation would render ``audio_pending`` while being absent from the audio
    queue — the two views disagreeing about one row.  This pins them together.
    """
    connection, parts, repository = queue_store
    transcripts = TranscriptRepository(connection)

    # The fixture's caption-exhausted part has TWO independent observations, so
    # both views agree on it trivially.  A part with exactly ONE is what tells
    # the predicates apart, so add one.
    _open_run(transcripts, "run-one-look", "subtitle")
    transcripts.record_subtitle_attempt(
        run_id="run-one-look",
        video_part_id=parts[("BV1EEE", 0)],
        outcome="no-subtitle",
        error_code=None,
        started_at=900,
        finished_at=1_000,
    )

    states = {
        str(row["work_id"]): str(row["pipeline_state"])
        for row in connection.execute("select work_id, pipeline_state from v_part_pipeline")
    }
    in_queue = {
        item.work_id
        for item in repository.list_queue_gaps(gap="missing_audio")
    }
    for work_id, state in states.items():
        assert (state == "audio_pending") == (work_id in in_queue), (
            f"{work_id}: pipeline_state={state!r} but in v_missing_audio={work_id in in_queue}"
        )

def test_a_failed_audio_attempt_is_not_audio_evidence(queue_store):
    """The fixture's BV1FFF:p0 has *only* a failed audio attempt.

    Contract §4d: ``acquisition_attempts`` cannot express a successful audio
    acquisition — its CHECK matrix admits ``stored`` / ``unchanged`` only with a
    ``transcript_id`` an audio download never produces — so probing it is an
    inversion.  Pre-fix, that part read as audio evidence: it left
    ``missing_audio``, entered ``missing_transcript``, and rendered
    ``audio_ok`` — queued for transcription with no audio on disk and no
    attempt left that could move it back out.
    """
    connection, _parts, repository = queue_store

    # The failed attempt leaves the part in the audio queue...
    assert [
        item.work_id for item in repository.list_queue_gaps(gap="missing_audio")
    ] == ["BV1AAA:p1", "BV1FFF:p0"]
    # ...and does not promote it into the transcription queue, which holds only
    # the parts that really have archived bytes.
    assert [
        item.work_id for item in repository.list_queue_gaps(gap="missing_transcript")
    ] == ["BV1BBB:p0", "BV1DDD:p0"]
    # The converged state is "still waiting for audio", not "has audio".
    assert dict(
        connection.execute("SELECT work_id, pipeline_state FROM v_part_pipeline")
    )["BV1FFF:p0"] == "audio_pending"


def test_gap_entries_carry_the_part_cid(queue_store):
    """``cid`` rides the projection: the audio route needs it per part.

    Contract §4d added it before the views froze, so no caller has to re-fetch a
    page for a value the store already holds.  The stored cids are the fixture's
    own, pinned here per part so an entry carrying another part's cid fails.
    """
    _connection, _parts, repository = queue_store
    cids = {
        item.work_id: item.cid
        for gap in ALLOWED_QUEUE_GAPS
        for item in repository.list_queue_gaps(gap=gap)
    }
    # Every queued part, each with the fixture's own stored cid; the part that
    # holds a transcript is in no queue and so appears in no entry.
    assert cids == {
        "BV1AAA:p0": 2_001,
        "BV1AAA:p1": 2_002,
        "BV1BBB:p0": 2_003,
        "BV1DDD:p0": 2_005,
        "BV1EEE:p0": 2_006,
        "BV1FFF:p0": 2_007,
    }


def test_ordering_is_pubdate_desc_then_bvid_then_page(queue_store):
    """The repository, not the view, imposes the locked work order."""
    _connection, _parts, repository = queue_store
    for gap, expected in (
        ("missing_subtitle", ["BV1AAA:p0", "BV1AAA:p1", "BV1EEE:p0", "BV1BBB:p0", "BV1FFF:p0"]),
        ("missing_transcript", ["BV1BBB:p0", "BV1DDD:p0"]),
    ):
        items = repository.list_queue_gaps(gap=gap)
        keys = [(item.pubdate, item.bvid, item.page_index) for item in items]
        assert keys == sorted(keys, key=lambda key: (-key[0], key[1], key[2]))
        assert [item.work_id for item in items] == expected

    # The tie inside one publication second is broken by bvid first.
    assert [
        (item.bvid, item.page_index)
        for item in repository.list_queue_gaps(gap="missing_subtitle")
    ][:3] == [("BV1AAA", 0), ("BV1AAA", 1), ("BV1EEE", 0)]


def test_bvid_and_page_filters_narrow_the_read(queue_store):
    """Each filter adds one predicate and never widens the queue."""
    _connection, _parts, repository = queue_store

    assert [
        item.work_id
        for item in repository.list_queue_gaps(gap="missing_subtitle", bvid="BV1AAA")
    ] == ["BV1AAA:p0", "BV1AAA:p1"]
    assert [
        item.work_id
        for item in repository.list_queue_gaps(gap="missing_subtitle", page=1)
    ] == ["BV1AAA:p1"]
    assert [
        item.work_id
        for item in repository.list_queue_gaps(
            gap="missing_subtitle", bvid="BV1AAA", page=1
        )
    ] == ["BV1AAA:p1"]
    # A video the queue does not hold — here one whose part has a transcript —
    # answers an empty list rather than an invented row.
    assert repository.list_queue_gaps(gap="missing_subtitle", bvid="BV1CCC") == []
    assert [
        item.work_id
        for item in repository.list_queue_gaps(gap="missing_audio", page=1)
    ] == ["BV1AAA:p1"]
    assert repository.list_queue_gaps(gap="missing_audio", page=4) == []


def test_limit_bounds_the_ordered_page(queue_store):
    """``limit`` takes the head of the locked order, never a fresh sample."""
    _connection, _parts, repository = queue_store
    assert [
        item.work_id
        for item in repository.list_queue_gaps(gap="missing_subtitle", limit=2)
    ] == ["BV1AAA:p0", "BV1AAA:p1"]
    assert [
        item.work_id
        for item in repository.list_queue_gaps(gap="missing_subtitle", limit=1)
    ] == ["BV1AAA:p0"]
    assert len(repository.list_queue_gaps(gap="missing_subtitle")) == 5


def test_gap_and_limit_validation_follow_the_module_rule(queue_store):
    """A wrong type is a ``TypeError``; a wrong value is a ``ValueError``."""
    _connection, _parts, repository = queue_store

    with pytest.raises(ValueError, match="gap must be one of"):
        repository.list_queue_gaps(gap="missing_asr")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="gap must be a string"):
        repository.list_queue_gaps(gap=None)  # type: ignore[arg-type]

    for bad in (0, -1):
        with pytest.raises(ValueError, match="limit must be a positive integer"):
            repository.list_queue_gaps(gap="missing_subtitle", limit=bad)
    # ``bool`` is an ``int`` in Python; it is still not a limit.
    for bad in (True, False, "2", 1.5):
        with pytest.raises(TypeError, match="limit must be an integer or None"):
            repository.list_queue_gaps(gap="missing_subtitle", limit=bad)


def test_count_queue_gaps_reports_all_three_queues(queue_store):
    """Every queue answers a size, a drained one included."""
    _connection, _parts, repository = queue_store
    counts = repository.count_queue_gaps()
    assert counts == {
        "missing_subtitle": 5,
        "missing_audio": 2,
        "missing_transcript": 2,
    }
    assert sorted(counts) == sorted(ALLOWED_QUEUE_GAPS)
    # The counts agree with the unfiltered reads, key for key.
    for gap in ALLOWED_QUEUE_GAPS:
        assert counts[gap] == len(repository.list_queue_gaps(gap=gap))


def test_count_queue_gaps_reports_zero_for_a_drained_store(tmp_root):
    """An empty queue is a size, not a missing key."""
    connection = open_database(tmp_root)
    try:
        repository = MediaQueueRepository(connection)
        assert repository.count_queue_gaps() == {
            "missing_subtitle": 0,
            "missing_audio": 0,
            "missing_transcript": 0,
        }
        assert sorted(repository.count_queue_gaps()) == sorted(ALLOWED_QUEUE_GAPS)
        assert repository.list_queue_gaps(gap="missing_subtitle") == []
        assert repository.list_queue_gaps(gap="missing_audio", limit=1) == []
    finally:
        connection.close()


def test_constructor_requires_a_validated_connection_and_the_schema(tmp_root):
    """The constructor enforces the same preconditions as its siblings."""
    connection = open_database(tmp_root)
    try:
        # A connection without the row factory is rejected before any query.
        raw = sqlite3.connect(":memory:")
        try:
            with pytest.raises(TypeError, match="row_factory"):
                MediaQueueRepository(raw)
        finally:
            raw.close()

        # A store without the transcript-schema contract fails closed with the
        # bounded rebuild error, not a raw OperationalError.
        connection.execute("DROP VIEW v_pending_subtitles")
        with pytest.raises(SchemaContractError):
            MediaQueueRepository(connection)
    finally:
        connection.close()


def test_attempt_count_follows_the_gap_route_and_evidence_only_where_held(queue_store):
    """Each entry counts its own route's attempts and reports the view's evidence."""
    _connection, _parts, repository = queue_store

    subtitle_entries = {
        item.work_id: item
        for item in repository.list_queue_gaps(gap="missing_subtitle")
    }
    # Three subtitle attempts on BV1AAA:p1; one on BV1FFF:p0; none elsewhere.
    assert {work_id: item.attempt_count for work_id, item in subtitle_entries.items()} == {
        "BV1AAA:p0": 0,
        "BV1AAA:p1": 3,
        "BV1EEE:p0": 0,
        "BV1BBB:p0": 0,
        "BV1FFF:p0": 1,
    }
    # The subtitle view exposes no attempt evidence column: absence, not zero.
    assert all(
        item.newest_outcome is None and item.newest_error_code is None
        for item in subtitle_entries.values()
    )

    audio_entries = {
        item.work_id: item
        for item in repository.list_queue_gaps(gap="missing_audio")
    }
    # The audio queue counts audio attempts: the three subtitle attempts on
    # BV1AAA:p1 are not this queue's evidence, while BV1FFF:p0 carries one
    # failed audio attempt and still holds the queue (a failed attempt is not
    # acquired bytes).
    assert {work_id: item.attempt_count for work_id, item in audio_entries.items()} == {
        "BV1AAA:p1": 0,
        "BV1FFF:p0": 1,
    }
    assert (
        audio_entries["BV1AAA:p1"].newest_outcome,
        audio_entries["BV1AAA:p1"].newest_error_code,
    ) == ("no-subtitle", None)
    assert (
        audio_entries["BV1FFF:p0"].newest_outcome,
        audio_entries["BV1FFF:p0"].newest_error_code,
    ) == ("failed", "risk_control")

    transcript_entries = {
        item.work_id: item
        for item in repository.list_queue_gaps(gap="missing_transcript")
    }
    # One audio attempt per part on that route; no evidence columns here either.
    assert {
        work_id: item.attempt_count for work_id, item in transcript_entries.items()
    } == {"BV1BBB:p0": 1, "BV1DDD:p0": 1}
    assert all(
        item.newest_outcome is None and item.newest_error_code is None
        for item in transcript_entries.values()
    )
    assert all(
        isinstance(item.gap, str) and item.gap == "missing_transcript"
        for item in transcript_entries.values()
    )
