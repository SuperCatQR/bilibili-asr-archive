# Plan-1 Fix Wave 1 Diff — 20260911-subtitle-gateway

Base: `c3d362c`
Head: `6002f99`
Scope: Task-3 review Minors 2-4 (probe module only)

```diff
diff --git a/bilibili-asr-archive/tests/test_live_subtitle_smoke.py b/bilibili-asr-archive/tests/test_live_subtitle_smoke.py
index 3b9bcb3..5274bb2 100644
--- a/bilibili-asr-archive/tests/test_live_subtitle_smoke.py
+++ b/bilibili-asr-archive/tests/test_live_subtitle_smoke.py
@@ -14,8 +14,12 @@ Where the probed part comes from:
 - the operator's archive database is preferred, read through a read-only
   SQLite URI (``mode=ro``): ``BILI_LIVE_ARCHIVE_DB`` when set, else
   ``archive/archive.db`` below the package directory — the root the
-  ``fetch-meta`` command defaults to.  A missing, unreadable, or part-less
-  database is not a probe failure;
+  ``fetch-meta`` command defaults to.  The newest part row (highest
+  ``video_part_id``) is the deterministic one probed, provided the archive has
+  not already marked it ``gone`` and its ``bvid`` is a BV id — two checks that
+  keep a part the archive has itself written off, or a foreign row, from
+  spending the probe's one live call or reaching the adapter's ``ValueError``.
+  A missing, unreadable, or part-less database is not a probe failure;
 - when no archived part is readable — a fresh checkout has no ``archive/``
   root at all — the probe falls back to the fixed public sample instead
   (:data:`SAMPLE_BVID` / :data:`SAMPLE_CID`): one part of the archive owner's
@@ -34,6 +38,13 @@ distribution is missing.  Its documented bounded outcomes are:
 - the part exposes no track (``track_count=0``): a legitimate observation,
   recorded together with the credential presence — never "this video has no
   captions";
+- the listing itself answers the bounded ``not_found`` code
+  (``track_count=not_found``): the part is one upstream no longer serves, or one
+  the credential in effect cannot see — this boundary deliberately collapses
+  both into the one code the caller records as ``no-subtitle``.  The outcome is
+  recorded with the part that produced it and the probe skips, because a run
+  that obtained no listing at all must not read green; a sample upstream has
+  since removed lands here;
 - upstream risk control refuses the locked call shape (``rate_limited``): the
   plan's recorded bounded blocker, reported as a skip carrying the bounded code
   and the stage, because the locked shape must not be bent to make the call
@@ -45,6 +56,11 @@ distribution is missing.  Its documented bounded outcomes are:
   ``response_error``, ``shape_error`` — fails loudly, because those mean the
   environment or the adapter regressed rather than upstream refusing.
 
+Every branch of that ladder is rehearsed offline in this module — part
+selection, the two loud-fail guards, both evidence renderers, and all four
+record-and-skip branches — so a default (offline, non-opted-in) run exercises
+the whole control flow; only the two boundary calls themselves are live.
+
 Run it with::
 
     cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 \\
@@ -61,7 +77,9 @@ import asyncio
 import importlib.metadata
 import os
 import pathlib
+import re
 import sqlite3
+import sys
 from typing import NoReturn
 
 import pytest
@@ -75,12 +93,14 @@ from bili_asr.config import (
     resolve_sessdata,
 )
 from bili_asr.sources.models import (
+    BilibiliGateway,
     GatewayNotFound,
     GatewayRateLimited,
     SubtitleSegment,
     SubtitleTrack,
 )
 from bili_asr.storage.database import MetadataRepository, open_database
+from bili_asr.storage.models import ProcessingStatus, VideoPartRecord
 from fixtures.fake_bilibili_gateway import (
     BVID,
     RAW_JSON_BODY_MARKER,
@@ -103,6 +123,16 @@ LIVE_SMOKE_ENV = "BILI_LIVE_SMOKE"
 #: The part cid the offline rehearsals seed and select.
 REHEARSAL_CID = 2222
 
+#: The part cid the offline rehearsals seed as already ``gone``.
+REHEARSAL_GONE_CID = 3333
+
+#: The BV-id shape the adapter requires before it issues a call
+#: (``^BV[a-zA-Z0-9]{10}$``).  Mirrored here rather than imported from the
+#: adapter, which imports the pinned distribution at module scope: this module
+#: must stay importable, and its rehearsals runnable, in an environment without
+#: that distribution.
+BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")
+
 #: The fixed public sample the probe probes when no archived part is readable:
 #: one part of the archive owner's own collection, discovered once through the
 #: delivered metadata gateway while this probe was authored (2026-09-11; first
@@ -172,10 +202,15 @@ def _read_archive_part(database_path: str) -> tuple[str, int] | None:
 
     The database is opened through a ``mode=ro`` SQLite URI, so the probe can
     neither create, migrate, nor write anything; the newest part row (highest
-    ``video_part_id``) is the deterministic one probed.  A database that does
-    not exist, a file that is not a readable SQLite database, and a database
-    without a part row all answer ``None`` and hand the probe to its documented
-    sample fallback.
+    ``video_part_id``) is the deterministic one probed, provided the archive has
+    not already marked it ``gone`` — a part upstream no longer serves is exactly
+    the one the player endpoint answers ``not_found`` for, and the probe has one
+    live call to spend — and provided its ``bvid`` has the BV shape the adapter
+    requires, so a foreign or hand-edited row cannot turn into an adapter
+    ``ValueError``.  A database that does not exist, a file that is not a
+    readable SQLite database, a database without a usable part row, and a row
+    the adapter would reject all answer ``None`` and hand the probe to its
+    documented sample fallback.
     """
 
     path = pathlib.Path(database_path)
@@ -188,7 +223,8 @@ def _read_archive_part(database_path: str) -> tuple[str, int] | None:
     try:
         row = connection.execute(
             "SELECT bvid, cid FROM video_parts"
-            " WHERE cid > 0 ORDER BY video_part_id DESC LIMIT 1"
+            " WHERE cid > 0 AND processing_status != 'gone'"
+            " ORDER BY video_part_id DESC LIMIT 1"
         ).fetchone()
     except sqlite3.Error:
         return None
@@ -197,7 +233,9 @@ def _read_archive_part(database_path: str) -> tuple[str, int] | None:
     if row is None:
         return None
     bvid, cid = row
-    if not isinstance(bvid, str) or isinstance(cid, bool) or not isinstance(cid, int):
+    if not isinstance(bvid, str) or BVID_PATTERN.fullmatch(bvid) is None:
+        return None
+    if isinstance(cid, bool) or not isinstance(cid, int):
         return None
     return bvid, cid
 
@@ -292,45 +330,44 @@ def _record_risk_control_refusal(
     )
 
 
-def test_live_subtitle_probe_reports_one_real_part_inventory():
-    """Opt-in live probe: ONE real part's subtitle inventory and body.
+def _probe_one_part(
+    gateway: BilibiliGateway, bvid: str, cid: int, part_source: str
+) -> None:
+    """Run the probe's two boundary calls for one part and record the evidence.
 
-    Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The probe resolves
-    one part (the operator's archive first, the bounded sample fallback
-    second), lists its subtitle inventory through the real adapter in the
-    locked call shape, and — when a track is visible — fetches that track's
-    body and checks the document-level timeline.  It asserts and prints the
-    bounded facts only: counts, language codes, AI versus CC, segment count,
-    and milliseconds.
+    The listing is issued first, and the body only when a track is visible.  The
+    evidence lines and every record-and-skip branch live here rather than inline
+    in the live test so a default (offline) pytest run can drive all of them
+    through a scripted gateway: a branch only a live run can enter is a branch no
+    offline run has ever verified.
     """
 
-    if not _live_smoke_requested():
-        pytest.skip(
-            f"live subtitle probe is opt-in: set {LIVE_SMOKE_ENV}=1 to request it"
-        )
-
-    assert _pinned_package_version() == PINNED_PACKAGE_VERSION
-
-    sessdata = resolve_sessdata(None, os.environ.get(SESSDATA_ENV_VAR))
-    gateway = _load_gateway(sessdata)
-    proxy = resolve_proxy(None, os.environ)
-    print(
-        "live subtitle probe environment:"
-        f" sessdata={redact_sessdata(sessdata)}"
-        f" proxy={'present' if proxy else 'absent'}"
-    )
-
-    bvid, cid, part_source = _resolve_probe_part()
-    print(
-        f"live subtitle probe part: source={part_source} bvid={bvid} cid={cid}"
-    )
-
     try:
         tracks = asyncio.run(gateway.get_subtitle_tracks(bvid, cid))
     except GatewayRateLimited as refusal:
         _record_risk_control_refusal(
             refusal, stage="track-listing", part_source=part_source
         )
+    except GatewayNotFound:
+        # The part is not visible upstream: an inventory nothing answered for,
+        # which is what a sample upstream has since removed looks like — and
+        # what the boundary reports when the credential in effect cannot see
+        # the part at all (its ``-101`` signal).  Both are bounded outcomes the
+        # caller records as ``no-subtitle``, so the probe records them instead
+        # of dying with a traceback and no evidence line.
+        print(
+            "live subtitle probe evidence: part_source="
+            f"{part_source} stage=track-listing track_count=not_found"
+        )
+        pytest.skip(
+            "the player endpoint answered the bounded not_found code for this"
+            " part: upstream no longer serves it, or the credential in effect"
+            " cannot see it — the boundary collapses both into the code the"
+            " caller records as no-subtitle.  No listing evidence was obtained,"
+            " so the run must not read as green: probe another part, or refresh"
+            " the archive metadata when the part came from the archive"
+            " database."
+        )
     print(
         "live subtitle probe evidence: stage=track-listing"
         f" {_track_evidence(tracks)}"
@@ -369,17 +406,61 @@ def test_live_subtitle_probe_reports_one_real_part_inventory():
     )
 
 
+def test_live_subtitle_probe_reports_one_real_part_inventory():
+    """Opt-in live probe: ONE real part's subtitle inventory and body.
+
+    Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The probe resolves
+    one part (the operator's archive first, the bounded sample fallback
+    second), lists its subtitle inventory through the real adapter in the
+    locked call shape, and — when a track is visible — fetches that track's
+    body and checks the document-level timeline.  It asserts and prints the
+    bounded facts only: counts, language codes, AI versus CC, segment count,
+    and milliseconds.
+    """
+
+    if not _live_smoke_requested():
+        pytest.skip(
+            f"live subtitle probe is opt-in: set {LIVE_SMOKE_ENV}=1 to request it"
+        )
+
+    assert _pinned_package_version() == PINNED_PACKAGE_VERSION
+
+    sessdata = resolve_sessdata(None, os.environ.get(SESSDATA_ENV_VAR))
+    gateway = _load_gateway(sessdata)
+    proxy = resolve_proxy(None, os.environ)
+    print(
+        "live subtitle probe environment:"
+        f" sessdata={redact_sessdata(sessdata)}"
+        f" proxy={'present' if proxy else 'absent'}"
+    )
+
+    bvid, cid, part_source = _resolve_probe_part()
+    print(
+        f"live subtitle probe part: source={part_source} bvid={bvid} cid={cid}"
+    )
+
+    _probe_one_part(gateway, bvid, cid, part_source)
+
+
 # ------------------------------------------------------------- rehearsals
 #
 # The rehearsals below run in every default (offline) pytest run and cover the
-# probe's own logic — part selection, the read-only archive query, the loud-fail
-# guard, and the bounded evidence renderers — so a broken query or a loosened
-# assertion fails offline instead of first surfacing during a live run.  No
-# live behaviour is claimed here, and no network call is made.
-
-
-def _seed_archive(database_path: str, *, bvid: str, cid: int) -> None:
-    """Seed one user, video, and part into a real archive database."""
+# probe's own logic — part selection, the read-only archive query, both loud-fail
+# guards, the bounded evidence renderers, and every record-and-skip branch — so a
+# broken query or a loosened assertion fails offline instead of first surfacing
+# during a live run.  No live behaviour is claimed here, and no network call is
+# made: the live flow's two calls are driven through a scripted gateway.
+
+
+def _seed_archive(
+    database_path: str,
+    *,
+    bvid: str,
+    cid: int,
+    processing_status: ProcessingStatus = "discovered",
+    extra_parts: tuple[VideoPartRecord, ...] = (),
+) -> None:
+    """Seed one user, one video, and the given part rows into a real archive."""
 
     connection = open_database(database_path)
     repository = MetadataRepository(connection)
@@ -387,7 +468,11 @@ def _seed_archive(database_path: str, *, bvid: str, cid: int) -> None:
         with repository.transaction():
             repository.upsert_user(make_user_record())
             repository.upsert_video(make_video_record(bvid))
-            repository.upsert_part(make_part_record(bvid, cid=cid))
+            repository.upsert_part(
+                make_part_record(bvid, cid=cid, processing_status=processing_status)
+            )
+            for part in extra_parts:
+                repository.upsert_part(part)
     finally:
         connection.close()
 
@@ -468,6 +553,86 @@ def test_probe_part_selection_ignores_an_archive_without_a_part(
     assert _resolve_probe_part() == (SAMPLE_BVID, SAMPLE_CID, "fixed-sample")
 
 
+def test_probe_part_selection_skips_a_part_the_archive_marked_gone(
+    tmp_root: str, monkeypatch: pytest.MonkeyPatch
+):
+    """A part the archive knows is gone is never probed, even as the newest row.
+
+    ``gone`` is a first-class shipped part status, and a part upstream no longer
+    serves is exactly the one the player endpoint answers ``not_found`` for, so
+    selecting it would spend the probe's one live call on a bounded blocker its
+    own database could have predicted.  An archive whose every part is gone
+    lands on the sample fallback the way an empty one does.
+    """
+
+    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
+    _seed_archive(
+        database_path,
+        bvid=BVID,
+        cid=REHEARSAL_CID,
+        extra_parts=(
+            make_part_record(
+                BVID,
+                page_index=1,
+                cid=REHEARSAL_GONE_CID,
+                processing_status="gone",
+            ),
+        ),
+    )
+    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, database_path)
+
+    # The gone part carries the higher ``video_part_id``, so the ordering alone
+    # would select exactly the row the archive has already written off.
+    assert _read_archive_part(database_path) == (BVID, REHEARSAL_CID)
+    assert _resolve_probe_part() == (BVID, REHEARSAL_CID, "archive-db")
+
+    gone_only_path = os.path.join(tmp_root, "gone-only", ARCHIVE_DATABASE_NAME)
+    os.makedirs(os.path.dirname(gone_only_path), exist_ok=True)
+    _seed_archive(
+        gone_only_path,
+        bvid=BVID,
+        cid=REHEARSAL_GONE_CID,
+        processing_status="gone",
+    )
+    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, gone_only_path)
+
+    assert _read_archive_part(gone_only_path) is None
+    assert _resolve_probe_part() == (SAMPLE_BVID, SAMPLE_CID, "fixed-sample")
+
+
+def test_probe_part_selection_ignores_a_row_that_is_not_a_bv_id(
+    tmp_root: str, monkeypatch: pytest.MonkeyPatch
+):
+    """A newest row the adapter would reject hands the probe to the sample.
+
+    The row is written with raw SQL rather than through the repository, which
+    validates the shape: this guard exists for the case the repository cannot
+    produce — a foreign or hand-edited row — whose ``bvid`` the adapter would
+    refuse with ``ValueError`` instead of the probe falling back to its sample.
+    """
+
+    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
+    _seed_archive(database_path, bvid=BVID, cid=REHEARSAL_CID)
+    connection = sqlite3.connect(database_path)
+    try:
+        connection.execute(
+            "INSERT INTO video_parts("
+            " bvid, page_index, cid, title, duration_ms, processing_status,"
+            " created_at, updated_at"
+            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
+            ("not-a-bv-id", 9, 4444, "foreign row", 1_000, "discovered", 1, 1),
+        )
+        connection.commit()
+    finally:
+        connection.close()
+    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, database_path)
+
+    # The foreign row is the newest one, so the shape check — not the ordering —
+    # is what keeps the adapter's ``ValueError`` out of the probe.
+    assert _read_archive_part(database_path) is None
+    assert _resolve_probe_part() == (SAMPLE_BVID, SAMPLE_CID, "fixed-sample")
+
+
 def test_missing_pinned_distribution_fails_loudly(monkeypatch: pytest.MonkeyPatch):
     """An opted-in probe without the pin fails with guidance, not a skip."""
 
@@ -480,6 +645,25 @@ def test_missing_pinned_distribution_fails_loudly(monkeypatch: pytest.MonkeyPatc
         _pinned_package_version()
 
 
+def test_unimportable_pinned_module_fails_loudly(monkeypatch: pytest.MonkeyPatch):
+    """An opted-in probe that cannot import the adapter fails with guidance.
+
+    A module replaced by ``None`` on ``sys.modules`` is what an unimportable
+    adapter looks like to an ``import`` statement, so the guard is driven
+    offline rather than first by a live run in a half-installed environment.
+    """
+
+    monkeypatch.setitem(sys.modules, "bili_asr.sources.bilibili_api_gateway", None)
+
+    with pytest.raises(pytest.fail.Exception) as failure:
+        _load_gateway(None)
+
+    message = str(failure.value)
+    assert PINNED_PACKAGE_DISTRIBUTION_NAME in message
+    assert PINNED_PACKAGE_VERSION in message
+    assert "uv sync" in message
+
+
 def test_live_smoke_switch_is_opt_in(monkeypatch: pytest.MonkeyPatch):
     """Only the documented ``1`` opts the probe in."""
 
@@ -533,3 +717,166 @@ def test_segment_evidence_requires_a_non_decreasing_timeline():
         _assert_bounded_segment_facts(tuple(reversed(forward)))
     with pytest.raises(AssertionError):
         _assert_bounded_segment_facts(())
+
+
+class _ScriptedGateway:
+    """The probe's two boundary calls, scripted, with no network at all.
+
+    ``_probe_one_part`` is driven through this double so the live flow's control
+    flow — every record-and-skip branch included — is entered by a default
+    (offline, non-opted-in) pytest run.  ``calls`` records which of the two calls
+    were made, in order, so a rehearsal can pin that a listing which never
+    answered is not followed by a body fetch.
+    """
+
+    def __init__(
+        self,
+        *,
+        tracks: tuple[SubtitleTrack, ...] = (),
+        segments: tuple[SubtitleSegment, ...] = (),
+        listing_failure: Exception | None = None,
+        body_failure: Exception | None = None,
+    ) -> None:
+        self._tracks = tracks
+        self._segments = segments
+        self._listing_failure = listing_failure
+        self._body_failure = body_failure
+        self.calls: list[str] = []
+
+    async def get_subtitle_tracks(
+        self, bvid: str, cid: int
+    ) -> tuple[SubtitleTrack, ...]:
+        self.calls.append("get_subtitle_tracks")
+        if self._listing_failure is not None:
+            raise self._listing_failure
+        return self._tracks
+
+    async def fetch_subtitle_segments(
+        self, track: SubtitleTrack, bvid: str, cid: int
+    ) -> tuple[SubtitleSegment, ...]:
+        self.calls.append("fetch_subtitle_segments")
+        if self._body_failure is not None:
+            raise self._body_failure
+        return self._segments
+
+
+def _rehearsal_track() -> SubtitleTrack:
+    """One track DTO whose display label carries both leak sentinels."""
+
+    return SubtitleTrack(
+        language="ai-zh",
+        label=f"自动生成 {SIGNED_SUBTITLE_URL_MARKER} {RAW_JSON_BODY_MARKER}",
+        is_ai=True,
+        track_id="1",
+    )
+
+
+def test_probe_records_an_empty_listing_and_stops_before_the_body(capsys):
+    """No visible track is a recorded observation, and the body is not fetched."""
+
+    gateway = _ScriptedGateway()
+
+    _probe_one_part(gateway, SAMPLE_BVID, SAMPLE_CID, "fixed-sample")
+
+    evidence = capsys.readouterr().out
+    assert "stage=track-listing track_count=0 tracks=none" in evidence
+    assert "no usable track was visible" in evidence
+    assert gateway.calls == ["get_subtitle_tracks"]
+
+
+@pytest.mark.parametrize(
+    (
+        "listing_failure",
+        "body_failure",
+        "expected_evidence",
+        "expected_skip",
+        "expected_calls",
+    ),
+    [
+        pytest.param(
+            GatewayRateLimited(detail="get_subtitle_tracks"),
+            None,
+            "part_source=fixed-sample stage=track-listing refusal_code=rate_limited",
+            "STOP condition",
+            ["get_subtitle_tracks"],
+            id="listing-risk-control-refusal",
+        ),
+        pytest.param(
+            GatewayNotFound(detail="get_subtitle_tracks"),
+            None,
+            "part_source=fixed-sample stage=track-listing track_count=not_found",
+            "must not read as green",
+            ["get_subtitle_tracks"],
+            id="listing-not-found",
+        ),
+        pytest.param(
+            None,
+            GatewayRateLimited(detail="fetch_subtitle_segments"),
+            "stage=subtitle-body refusal_code=rate_limited",
+            "STOP condition",
+            ["get_subtitle_tracks", "fetch_subtitle_segments"],
+            id="body-risk-control-refusal",
+        ),
+        pytest.param(
+            None,
+            GatewayNotFound(detail="fetch_subtitle_segments"),
+            "stage=subtitle-body segments=not_found",
+            "must not read as green",
+            ["get_subtitle_tracks", "fetch_subtitle_segments"],
+            id="body-not-found",
+        ),
+    ],
+)
+def test_probe_records_each_bounded_blocker_and_never_reads_green(
+    capsys,
+    listing_failure: Exception | None,
+    body_failure: Exception | None,
+    expected_evidence: str,
+    expected_skip: str,
+    expected_calls: list[str],
+):
+    """All four record-and-skip branches are rehearsed, and none of them passes.
+
+    Each line names the bounded code and the stage — the listing-side lines also
+    name the part that produced them; each branch skips instead of passing, which
+    is what keeps a run without evidence from reading green; and a listing that
+    never answered is never followed by a body fetch.
+    """
+
+    gateway = _ScriptedGateway(
+        tracks=(_rehearsal_track(),),
+        listing_failure=listing_failure,
+        body_failure=body_failure,
+    )
+
+    with pytest.raises(pytest.skip.Exception) as skipped:
+        _probe_one_part(gateway, SAMPLE_BVID, SAMPLE_CID, "fixed-sample")
+
+    evidence = capsys.readouterr().out
+    assert expected_evidence in evidence
+    assert expected_skip in str(skipped.value)
+    assert gateway.calls == expected_calls
+
+
+def test_probe_records_the_whole_evidence_chain_without_leaking_a_label(capsys):
+    """The visible-track path prints both bounded lines and no upstream text."""
+
+    gateway = _ScriptedGateway(
+        tracks=(_rehearsal_track(),),
+        segments=(
+            SubtitleSegment(start_ms=0, end_ms=1500, text="未明子"),
+            SubtitleSegment(start_ms=1500, end_ms=2600, text="讲座"),
+        ),
+    )
+
+    _probe_one_part(gateway, SAMPLE_BVID, SAMPLE_CID, "archive-db")
+
+    evidence = capsys.readouterr().out
+    assert "stage=track-listing track_count=1 tracks=ai-zh:ai" in evidence
+    assert (
+        "stage=subtitle-body track=ai-zh:ai segments=2 first_start_ms=0"
+        " last_end_ms=2600 timeline=non-decreasing"
+    ) in evidence
+    assert_leaks_no_markers(evidence, context="live subtitle probe rehearsal")
+    assert RAW_JSON_BODY_MARKER not in evidence
+    assert gateway.calls == ["get_subtitle_tracks", "fetch_subtitle_segments"]
```
