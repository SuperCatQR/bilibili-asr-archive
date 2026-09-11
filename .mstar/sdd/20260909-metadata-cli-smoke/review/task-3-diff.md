# Task 3 Diff — 20260909-metadata-cli-smoke

Base: `cf490ff`
Head: `c86daa7`

```diff
diff --git a/bilibili-asr-archive/README.md b/bilibili-asr-archive/README.md
index b79e20a..bf05ad1 100644
--- a/bilibili-asr-archive/README.md
+++ b/bilibili-asr-archive/README.md
@@ -99,7 +99,7 @@ in committed files or CI artifacts.
 
 ## Workflow
 
-    bili-asr fetch-meta --mid 23191782 --resume
+    bili-asr fetch-meta --mid 23191782 --archive-root archive
     bili-asr harvest-subs --archive-root archive
     bili-asr download-audio --missing-subs --archive-root archive
     bili-asr asr --pending --archive-root archive
@@ -247,13 +247,15 @@ A completed rerun skips work already `archived`. Missing optional ASR exits
 non-zero with `pip install -e "bilibili-asr-archive/[asr]"` and does not mark
 the row archived.
 
-### Operational run ledger (`run-ledger.jsonl`), `status`, and `runs`
+### Operational run ledger (`run-ledger.jsonl`)
 
-Every `fetch-meta` execution (exit 0 or 2) and every `pilot` / `run` /
-`schedule` run atomically appends an inspectable run record to
-`{archive-root}/run-ledger.jsonl`.
-The ledger is a sidecar file that records execution history and coverage
-without altering manifest row schemas or the transport layer.
+Every `pilot` / `run` / `schedule` run atomically appends an inspectable run
+record to `{archive-root}/run-ledger.jsonl`. The metadata CLI's `fetch-meta`
+records its runs in the fresh SQLite database
+(`{archive-root}/archive.db`, see
+[the fresh-start metadata workflow](#fresh-start-metadata-collection-fetchmeta--status--runs))
+instead. The ledger is a sidecar file that records execution history and
+coverage without altering manifest row schemas or the transport layer.
 
 #### Ledger record schema
 
@@ -262,7 +264,7 @@ Each JSONL line represents one immutable record with the following schema:
 | Field | Type | Description |
 |-------|------|-------------|
 | `run_id` | `str` | Opaque identifier (`run-YYYYMMDDHHMMSS-<token>`). |
-| `command` | `str` | Command executed (`fetch-meta`, `pilot`, `run`, `schedule`). |
+| `command` | `str` | Command executed (`pilot`, `run`, `schedule`). |
 | `started_at` | `str` | ISO-8601 UTC start timestamp. |
 | `finished_at` | `str` | ISO-8601 UTC completion timestamp. |
 | `exit_code` | `int` | Process exit code (`0`, `1`, or `2`). |
@@ -280,11 +282,13 @@ cookies), signed streaming URLs, and raw exception stack traces.
 
 #### Operator inspection
 
-- **`bili-asr status [--archive-root <root>]`** displays current per-status
-  manifest row counts, unresolved legacy identifiers, total run count, and
-  latest run details (run ID, exit code, cursor snapshot, and coverage
-  summary). For `limited` enumeration runs, it reports cursor state honestly
-  without claiming complete enumeration.
+- **`bili-asr status [--archive-root <root>]`** reads the fresh SQLite
+  metadata database (`archive.db`): counts of collected users, videos, and
+  parts, the `processing_status` breakdown, pending work ids from
+  `v_pending_metadata`, and each user's stored enumeration cursor. It exits
+  `1` when the database does not exist (`fetch-meta` creates it) and never
+  reads the legacy manifest sidecar. For `limited` collection runs, it
+  reports the cursor state honestly without claiming complete enumeration.
 - **`bili-asr coverage [--quality]`** is a read-only reconciliation and artifact quality report over fixture/local archive evidence. Use a temporary local root and optional scope; it never performs network traffic, model invocation, audio transcoding, or writes to source sidecars:
 
       bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --scope pending --format json
@@ -478,27 +482,55 @@ The JSONL manifest (`{archive-root}/manifest/manifest.jsonl`) remains the single
 - **Vocabulary**: Consistently uses manifest `status` (never cursor `state`).
 - **Decoupled from search index**: Export operates directly over the JSONL manifest SSOT and does not require, query, or mutate `search.db`.
 
-### `fetch-meta --resume` and exit 2
+### Fresh-start metadata collection (`fetch-meta` / `status` / `runs`)
 
-`bili-asr fetch-meta` writes `{archive-root}/meta-cursor.json` after each
-successful archive-list page merge. The sidecar holds only `mid`, `next_page`,
-`total`, `state`, `last_api_error_code`, and `updated_at` — never cookies,
-`SESSDATA`, signed URLs, or exception text.
+`bili-asr fetch-meta` collects video metadata through the pinned
+`bilibili-api-python==17.4.2` gateway and writes it to a fresh normalized
+SQLite database at `{archive-root}/archive.db`; the layout is described in
+[docs/metadata-storage.md](docs/metadata-storage.md). The metadata commands
+never read or write the legacy `manifest/manifest.jsonl`,
+`meta-cursor.json`, or `run-ledger.jsonl` sidecars, and no command migrates
+old archive data: a new database starts empty. Deleting `archive.db` is the
+only restart path.
+
+    bili-asr fetch-meta --mid 23191782 --archive-root archive
+    bili-asr fetch-meta --mid 23191782 --limit-pages 1 --archive-root archive
+    bili-asr status --archive-root archive
+    bili-asr runs --limit 10 --archive-root archive
+
+- **Resume semantics**: without `--resume` or `--start-page`, a run continues
+  from the stored cursor when one exists and starts at page 1 otherwise.
+  `--resume` requires a stored cursor and exits `1` when there is none;
+  `--start-page` overrides the cursor. A failed page never advances the
+  cursor, so resume is always safe.
+- **Credential boundary**: optional SESSDATA comes from `--sessdata` or the
+  `BILI_SESSDATA` environment variable (cookie **value**, not a file path).
+  It is sent as an API cookie only and is never echoed, logged, persisted,
+  or written to the database; CLI output shows presence only
+  (`sessdata: present|absent`).
 
 | Exit | Meaning |
 |------|---------|
-| 0 | Run finished without risk exhaustion. Cursor `state` is `complete` (full visible archive) or `limited` (intentional `--limit-pages` cap). `--resume` does **not** auto-continue these. |
-| 1 | Usage/config or unexpected error (no traceback). |
-| 2 | Risk budget or terminal API failure. Cursor `state` is `risk_interrupted`; `next_page` is the 1-based `pn` that was **not** merged. Re-run `fetch-meta --resume` with the same `--mid` to start at that page. |
-
-`--resume` auto-continues **only** an exit-2 `risk_interrupted` cursor whose
-`mid` matches. `complete` and `limited` are not auto-resumable. JSONL upsert
-stays last-write-wins per `work_id`; a failed page is never marked complete.
-Without `--resume`, a new run starts at page 1, merges the existing JSONL
-(does not shrink it to a page-1 prefix), and replaces a leftover cursor after
-the first successful page. Mid-run sidecar writes stay `risk_interrupted`
-with `next_page` = last merged `pn+1`; terminal `complete`/`limited` is
-written only when the run finishes without exit 2.
+| 0 | `fetch-meta`: successful collection (empty page reached or explicit `--limit-pages` bound). `status` / `runs`: database read and displayed. |
+| 1 | Usage/configuration error: bad page arguments, `--resume` without a stored cursor, or a missing/unreadable database for the read commands. |
+| 2 | `fetch-meta` only: terminal gateway failure with a bounded scalar code (e.g. `response_error`, `rate_limited`); the cursor remains unchanged — re-run `fetch-meta` to resume. |
+
+#### Opt-in bounded live smoke
+
+`tests/test_live_metadata_smoke.py` drives the real CLI against the real
+upstream: exactly one public metadata page for UID 23191782
+(`--start-page 1 --limit-pages 1`) into a temporary archive root, calling no
+subtitle/playback/audio/ASR code. Default pytest runs skip it:
+
+    cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v
+
+Anonymous (no-credential) access is currently rejected by upstream anti-bot
+control: the smoke then verifies the bounded-failure evidence (terminal run
+row, one scalar page row, no entity growth, no cursor row) and reports the
+case as the expected no-credential behavior rather than a defect.
+Happy-path collection requires a credential from the operator's own
+environment (`--sessdata` or `BILI_SESSDATA`); a bounded failure despite a
+credential is a loud failure.
 
 ### Mixed batch outcomes
 
@@ -523,7 +555,8 @@ selectable by the same command or by `run --scope failed`. Explicit `run
 `already_terminal` and exit 0; they are not duplicated.
 
 `harvest-subs`, `download-audio`, and `asr` do not append `run-ledger.jsonl`
-(that sidecar is `fetch-meta` / `pilot` / `run` / `schedule`). All operator
+(that sidecar is `pilot` / `run` / `schedule`; `fetch-meta` records its runs
+in `archive.db`). All operator
 surfaces carry redacted scalar codes/reasons only.
 
 ### Corpus coverage evidence spine
diff --git a/bilibili-asr-archive/docs/metadata-storage.md b/bilibili-asr-archive/docs/metadata-storage.md
new file mode 100644
index 0000000..124825a
--- /dev/null
+++ b/bilibili-asr-archive/docs/metadata-storage.md
@@ -0,0 +1,127 @@
+# Metadata storage (`archive.db`)
+
+Normalized SQLite storage for the video metadata collected by
+`bili-asr fetch-meta`. This document describes the database the metadata CLI
+creates and reads. The legacy JSONL manifest pipeline
+(`manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`) is a
+separate, untouched state: the metadata commands never read it, and no
+command migrates old data into the new database.
+
+## Fresh-start behavior (no migration)
+
+- `fetch-meta` creates `{archive_root}/archive.db` when it does not exist and
+  initializes the checked-in schema (`src/bili_asr/storage/schema.sql`).
+- `status` and `runs` are read-only. When the database is missing they fail
+  with a clear configuration error and exit `1`; they never create it.
+- There is no migration, import, reset, or rewrite path. Deleting
+  `archive.db` is the only way to restart a collection from page 1; old
+  archive data is never discovered, read, or modified by any command.
+- A failed page never advances the cursor: resume is always safe, and no
+  partially written page payload survives a failure.
+
+## Database layout
+
+One SQLite file at `{archive_root}/archive.db`. Foreign keys are enforced
+(`PRAGMA foreign_keys = ON`).
+
+### Normalized entity tables
+
+| Table | Key | Contents |
+|-------|-----|----------|
+| `bilibili_users` | `mid` | The collected user and its current display label. |
+| `videos` | `bvid` | One row per video: `aid`, owner `mid` (FK to `bilibili_users`), `title`, `pubdate`. |
+| `video_parts` | `(bvid, page_index)` | One row per part: `cid`, part `title`, `duration_ms`, zero-based `page_index` (`{bvid}:p{page_index}` is the derived `work_id`, computed, never stored), `processing_status` (`discovered`, `metadata_collected`, `gone`), FK to `videos`. |
+
+### Ingestion process tables
+
+| Table | Key | Contents |
+|-------|-----|----------|
+| `ingestion_runs` | `run_id` | One row per collection run: target `mid`, source package and version, requested start page and page limit, `started_at` / `finished_at`, terminal `outcome` (`complete`, `limited`, `risk_interrupted`, `failed`). |
+| `ingestion_pages` | `(run_id, page_number)` | One evidence row per requested page: `outcome` (`ok`, `empty`, `risk_interrupted`, `failed`) and a bounded scalar `error_code` on failure. |
+| `ingestion_cursors` | `mid` | The resumable one-based cursor: `next_page`, `state` (`ready`, `complete`, `limited`, `risk_interrupted`), `observed_total`. |
+| `ingestion_discoveries` | `(run_id, page_number, bvid)` | Run-scoped discovery evidence linking a run page to a discovered video. |
+
+### Reserved media boundary (empty in this plan)
+
+`audio_objects`, `part_audio_objects`, `asr_models`, `transcripts`, and
+`transcript_segments` are created now so later media and transcript plans
+attach through these foreign keys instead of reintroducing sidecars. They
+stay empty in this plan; no media bytes or transcripts are written yet.
+
+### Views
+
+| View | Contents |
+|------|----------|
+| `v_video_parts` | Every part with its derived `work_id` and the joined user/video context. |
+| `v_ingestion_run_stats` | Per-run page and video counts (the `runs` command's source). |
+| `v_pending_metadata` | Parts with `processing_status = 'discovered'` (the `status` command's pending work). |
+
+## No-JSONL contract
+
+`fetch-meta`, `status`, and `runs` never read or write `manifest.jsonl`,
+`meta-cursor.json`, or `run-ledger.jsonl`. All persisted run/page evidence
+is scalar: `error_code` values are bounded strings of at most 64 characters
+from a restricted character set. Credentials, signed URLs, raw response
+bodies, and raw exception text never enter CLI output, logs, or any
+persisted row.
+
+## Credential boundary
+
+The optional SESSDATA credential comes from `--sessdata` or the
+`BILI_SESSDATA` environment variable (flag wins). It is passed to the
+gateway's cookie object only: never echoed, logged, persisted, or rendered —
+CLI output shows presence only (`sessdata: present|absent`). Omitting it
+means anonymous access.
+
+## `observed_total` semantics
+
+- `ingestion_cursors.observed_total` records the upstream video total
+  reported by the page response (`page.count`) when it is present; it is
+  provenance about the upstream snapshot, not a completion proof.
+- The fake test gateway reports a per-page count (its scripted responses
+  carry the scripted page size); live runs record the upstream global total.
+- Run completion keys off the empty item list: the first page that returns
+  no videos ends the run `complete` (bounded, spec-defined). An explicit
+  `--limit-pages` bound ends the run `limited` instead — never claimed as
+  complete.
+
+## Exact bounded live smoke command
+
+```
+cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v
+```
+
+- Opt-in only (`BILI_LIVE_SMOKE=1`); default pytest runs skip it without
+  failure. An opted-in run without the pinned `bilibili-api-python==17.4.2`
+  distribution fails loudly with install guidance instead of skipping.
+- Bound: exactly one public metadata page for UID 23191782
+  (`--start-page 1 --limit-pages 1`) into a temporary archive root; no
+  subtitle/playback/audio/ASR code is invoked and nothing outside the
+  temporary root is written.
+- Anonymous (no-credential) access is currently rejected by upstream
+  anti-bot control: the smoke then verifies the bounded-failure evidence
+  (terminal run row, one scalar page row, no entity growth, no cursor row)
+  and reports the case as the expected no-credential behavior — not a
+  defect. Happy-path collection requires a credential from the operator's
+  own environment (`--sessdata` or `BILI_SESSDATA`); a bounded failure
+  despite a credential is a loud failure.
+
+## Exit codes
+
+### `fetch-meta`
+
+| Exit | Meaning |
+|------|---------|
+| 0 | Successful collection: completed on an empty page, or stopped at the explicit `--limit-pages` bound. |
+| 1 | Usage/configuration error: non-positive page arguments, `--resume` with no stored cursor, or an unreadable archive root. |
+| 2 | Terminal gateway failure with a bounded scalar code (for example `response_error`, `rate_limited`); the cursor remains unchanged. |
+
+### `status` / `runs`
+
+| Exit | Meaning |
+|------|---------|
+| 0 | Database read and displayed. An empty database prints `runs: empty`. |
+| 1 | Configuration error: the database does not exist (or a non-positive `runs --limit`). |
+
+`runs` lists runs newest-first and includes non-terminal `running` rows: a
+crash can leave a stale run behind, and hiding it would hide real state.
diff --git a/bilibili-asr-archive/tests/test_live_metadata_smoke.py b/bilibili-asr-archive/tests/test_live_metadata_smoke.py
new file mode 100644
index 0000000..3482ee6
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_live_metadata_smoke.py
@@ -0,0 +1,381 @@
+"""Opt-in bounded live smoke: one real CLI page into a temporary database.
+
+This module holds the only networked metadata test.  It drives the real
+user-facing command path — ``bili_asr.cli.main`` with plain argv, the real
+``BilibiliApiGateway`` adapter over the pinned ``bilibili-api-python``
+distribution, and the fresh SQLite repository — for exactly one public
+metadata page of the archive owner (UID 23191782, ``--start-page 1``,
+``--limit-pages 1``) inside a temporary archive root.  No subtitle, playback,
+audio, or ASR code is invoked, and nothing outside the temporary root is
+written.
+
+Default pytest runs skip the smoke; it executes only when the operator sets
+``BILI_LIVE_SMOKE=1``.  Two documented outcomes are valid:
+
+- the happy path (exit 0) lands the expected normalized rows — user, videos
+  joined to their user through ``mid``, parts joined to their video through
+  ``bvid``, a terminal run row, exactly one page-evidence row, and the
+  advanced fresh cursor — while every persisted surface stays free of
+  credential, signed-URL, and playback markers;
+- the bounded upstream failure (exit 2) is a valid, documented CLI outcome:
+  the failure evidence stays scalar (terminal run row, one bounded page row,
+  no entity or discovery growth, no cursor row), and the smoke verifies it.
+  Anonymous (no-credential) access is currently rejected by upstream
+  anti-bot control, so an anonymous run reports that case as the expected
+  no-credential behavior (a clearly-reasoned skip, after its assertions
+  ran); the same bounded failure with an operator credential in the
+  environment is a loud failure.
+"""
+
+from __future__ import annotations
+
+import importlib.metadata
+import os
+
+import pytest
+
+from bili_asr.cli import main
+from bili_asr.config import SESSDATA_ENV_VAR
+from bili_asr.storage import open_database
+from fixtures.fake_bilibili_gateway import (
+    RAW_JSON_BODY_MARKER,
+    SESSDATA_BOUNDARY_VALUE,
+    SIGNED_URL_MARKER,
+    UPSTREAM_ERROR_TEXT,
+    FakeResponseCodeException,
+    assert_leaks_no_markers,
+    bilibili_api_seam,
+    make_part_item,
+    make_videos_response,
+    make_vlist_item,
+    persisted_row_text,
+)
+
+PINNED_PACKAGE_VERSION = "17.4.2"
+
+#: The archive owner whose public metadata the bounded smoke may collect.
+LIVE_SMOKE_MID = 23191782
+
+LIVE_SMOKE_ENV = "BILI_LIVE_SMOKE"
+
+#: Tokens that must never appear in the live smoke's persisted rows: cookie
+#: names and playback-CDN signature markers indicate credential or playback
+#: leakage rather than ordinary metadata.
+LIVE_HYGIENE_TOKENS = ("sessdata", "pssign", "bilivideo.com")
+
+#: Tokens scanned in CLI output.  The bare ``sessdata`` word is excluded on
+#: purpose: the CLI prints the redacted presence label
+#: ``sessdata: present|absent`` by design, and only the credential VALUE
+#: itself (scanned separately below) must never appear.
+LIVE_OUTPUT_HYGIENE_TOKENS = ("pssign", "bilivideo.com")
+
+LEGACY_SIDECAR_PATHS = (
+    os.path.join("manifest", "manifest.jsonl"),
+    "meta-cursor.json",
+    "run-ledger.jsonl",
+)
+
+
+def _live_smoke_requested() -> bool:
+    """True only when the operator explicitly opts in via the environment."""
+
+    return os.environ.get(LIVE_SMOKE_ENV, "") == "1"
+
+
+def _pinned_package_version() -> str:
+    """Return the installed distribution version, or fail loudly.
+
+    Loud-fail guard (Plan-2 live-smoke precedent): an opted-in smoke in an
+    environment without the pinned distribution fails loudly with install
+    guidance instead of silently skipping.
+    """
+
+    try:
+        return importlib.metadata.version("bilibili-api-python")
+    except importlib.metadata.PackageNotFoundError as error:
+        pytest.fail(
+            "live smoke was requested but bilibili-api-python is not installed"
+            f" in this environment ({error}); install the pinned"
+            f" bilibili-api-python=={PINNED_PACKAGE_VERSION} (uv sync) first"
+        )
+
+
+def _assert_no_credential_or_playback_leaks(
+    surface_text: str, persisted_text: str
+) -> None:
+    """Scan live CLI output and persisted rows for leakage markers.
+
+    The static markers cover cookie names and playback-CDN signature
+    markers; when the operator supplied a credential through the
+    environment, its value is scanned on both surfaces as well and must
+    never appear.
+    """
+
+    lowered_rows = persisted_text.lower()
+    for token in LIVE_HYGIENE_TOKENS:
+        assert token not in lowered_rows, f"live smoke persisted {token!r}"
+    lowered_output = surface_text.lower()
+    for token in LIVE_OUTPUT_HYGIENE_TOKENS:
+        assert token not in lowered_output, f"live smoke output carried {token!r}"
+    credential = os.environ.get(SESSDATA_ENV_VAR)
+    if credential:
+        assert credential not in surface_text, (
+            "live smoke output carried the operator SESSDATA value"
+        )
+        assert credential not in persisted_text, (
+            "live smoke persisted the operator SESSDATA value"
+        )
+
+
+def _assert_collected_page_rows(connection, mid: int) -> None:
+    """Assert the normalized evidence a successful one-page run leaves."""
+
+    run_row = connection.execute(
+        "SELECT outcome, requested_start_page, requested_page_limit, finished_at"
+        " FROM ingestion_runs"
+    ).fetchone()
+    assert run_row is not None, "the run row must exist"
+    assert run_row["outcome"] in ("complete", "limited")
+    assert run_row["requested_start_page"] == 1
+    assert run_row["requested_page_limit"] == 1
+    assert run_row["finished_at"] is not None
+
+    # Exactly one bounded page-evidence row for the one requested page.
+    page_row = connection.execute(
+        "SELECT page_number, outcome, error_code FROM ingestion_pages"
+    ).fetchone()
+    assert page_row is not None and page_row["page_number"] == 1
+
+    assert connection.execute(
+        "SELECT COUNT(*) FROM bilibili_users WHERE mid = ?", (mid,)
+    ).fetchone()[0] == 1
+    # Every video joins its owner user through mid; every part joins its
+    # video through bvid (the normalized foreign-key relationships).
+    assert connection.execute(
+        "SELECT COUNT(*) FROM videos AS v"
+        " LEFT JOIN bilibili_users AS u ON v.mid = u.mid"
+        " WHERE u.mid IS NULL"
+    ).fetchone()[0] == 0
+    assert connection.execute(
+        "SELECT COUNT(*) FROM video_parts AS p"
+        " LEFT JOIN videos AS v ON p.bvid = v.bvid"
+        " WHERE v.bvid IS NULL"
+    ).fetchone()[0] == 0
+    video_count = connection.execute(
+        "SELECT COUNT(*) FROM videos WHERE mid = ?", (mid,)
+    ).fetchone()[0]
+
+    cursor_row = connection.execute(
+        "SELECT next_page, state, observed_total FROM ingestion_cursors"
+        " WHERE mid = ?",
+        (mid,),
+    ).fetchone()
+    assert cursor_row is not None, "a collected page must record the fresh cursor"
+    observed_total = cursor_row["observed_total"]
+    if run_row["outcome"] == "limited":
+        assert video_count >= 1
+        assert tuple(page_row)[:2] == (1, "ok")
+        assert tuple(cursor_row)[:2] == (2, "limited")
+    else:  # complete: the first page came back empty and completed the run
+        assert video_count == 0
+        assert tuple(page_row)[:2] == (1, "empty")
+        assert tuple(cursor_row)[:2] == (1, "complete")
+    if observed_total is not None:
+        assert observed_total >= video_count
+
+
+def _assert_bounded_failure_rows(connection, mid: int) -> str:
+    """Assert the scalar-only evidence a bounded one-page failure leaves."""
+
+    run_row = connection.execute(
+        "SELECT outcome, finished_at FROM ingestion_runs"
+    ).fetchone()
+    assert run_row is not None, "the failed run row must still exist"
+    assert run_row["outcome"] in ("risk_interrupted", "failed")
+    assert run_row["finished_at"] is not None
+    page_row = connection.execute(
+        "SELECT page_number, outcome, error_code FROM ingestion_pages"
+    ).fetchone()
+    assert page_row is not None and page_row["page_number"] == 1
+    assert page_row["outcome"] in ("risk_interrupted", "failed")
+    error_code = page_row["error_code"]
+    assert error_code, "the failed page must carry a bounded scalar error code"
+    # The rolled-back page left no payload and no cursor movement; the user
+    # row was committed with the run start and stays.
+    assert connection.execute(
+        "SELECT COUNT(*) FROM bilibili_users WHERE mid = ?", (mid,)
+    ).fetchone()[0] == 1
+    assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
+    assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 0
+    assert connection.execute(
+        "SELECT COUNT(*) FROM ingestion_discoveries"
+    ).fetchone()[0] == 0
+    assert connection.execute(
+        "SELECT COUNT(*) FROM ingestion_cursors"
+    ).fetchone()[0] == 0
+    return str(error_code)
+
+
+def _bounded_live_argv(tmp_root: str) -> list[str]:
+    """The exact bounded smoke invocation: one explicit page, one limit."""
+
+    return [
+        "fetch-meta",
+        "--mid",
+        str(LIVE_SMOKE_MID),
+        "--start-page",
+        "1",
+        "--limit-pages",
+        "1",
+        "--archive-root",
+        tmp_root,
+    ]
+
+
+def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
+    tmp_root: str,
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """Opt-in live probe: ONE public metadata page through the real CLI.
+
+    Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The probe runs
+    the real ``fetch-meta`` command for UID 23191782 with ``--start-page 1
+    --limit-pages 1`` into a temporary archive root, asserts the normalized
+    table relationships on the happy path, and asserts the scalar-only
+    failure evidence when upstream rejects the page.  It never invokes
+    subtitle, playback, audio, or ASR code.
+    """
+
+    if not _live_smoke_requested():
+        pytest.skip(f"live smoke is opt-in: set {LIVE_SMOKE_ENV}=1 to request it")
+
+    # Loud-fail guard: an opted-in smoke without the pinned distribution
+    # fails loudly with install guidance instead of silently skipping.
+    assert _pinned_package_version() == PINNED_PACKAGE_VERSION
+
+    exit_code = main(_bounded_live_argv(tmp_root))
+    out, err = capsys.readouterr()
+
+    assert os.path.isfile(os.path.join(tmp_root, "archive.db"))
+    for relative in LEGACY_SIDECAR_PATHS:
+        assert not os.path.exists(os.path.join(tmp_root, relative))
+
+    connection = open_database(tmp_root)
+    try:
+        persisted = persisted_row_text(connection)
+        _assert_no_credential_or_playback_leaks(out + err, persisted)
+        if exit_code == 0:
+            assert err == ""
+            assert "sessdata:" in out
+            assert "outcome=" in out
+            _assert_collected_page_rows(connection, LIVE_SMOKE_MID)
+            return
+
+        assert exit_code == 2
+        if "unexpected error" in err:
+            pytest.fail(
+                "live smoke hit an unexpected internal error (exit 2 without"
+                " a bounded run record); rerun to capture the failure shape"
+            )
+        error_code = _assert_bounded_failure_rows(connection, LIVE_SMOKE_MID)
+        assert error_code in err
+        assert "metadata gateway failure" in err
+        if os.environ.get(SESSDATA_ENV_VAR) is None:
+            pytest.skip(
+                "live smoke ended in the documented bounded anonymous"
+                f" rejection (error_code={error_code!r}, exit 2): upstream"
+                " anti-bot control currently rejects no-credential metadata"
+                " access; this is the expected no-credential behavior, not a"
+                " defect. Provide a credential via --sessdata or"
+                f" {SESSDATA_ENV_VAR} for the happy-path run."
+            )
+        pytest.fail(
+            "live smoke ended in a bounded upstream failure despite an"
+            f" operator credential (error_code={error_code!r}); rerun when"
+            " upstream recovers"
+        )
+    finally:
+        connection.close()
+
+
+def test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam(
+    tmp_root: str,
+    bilibili_api_seam,
+    monkeypatch: pytest.MonkeyPatch,
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """Rehearse both live-smoke outcome branches offline through the CLI.
+
+    The live smoke's database assertions are plain SQL over the fresh
+    schema; this rehearsal runs them against the same real CLI path over
+    the fake ``bilibili_api`` seam, so a broken assertion or query is
+    caught by every default (offline) run instead of first failing at the
+    QA gate's live execution.  No live behavior is claimed here.
+    """
+
+    monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)
+    script = bilibili_api_seam
+
+    def videos_response(pn: int, ps: int):
+        # Payload-laden upstream item: the seam sentinels ride the page so
+        # the no-leak assertions scan a surface that really carried them.
+        items = (
+            [
+                make_vlist_item(
+                    bvid="BV1REHEARSE1",
+                    sessdata_note=SESSDATA_BOUNDARY_VALUE,
+                    frame_url=SIGNED_URL_MARKER,
+                    raw_note=RAW_JSON_BODY_MARKER,
+                )
+            ]
+            if pn == 1
+            else []
+        )
+        return make_videos_response(*items, count=len(items))
+
+    script.videos_response = videos_response
+    script.parts_response = [make_part_item(cid=2222)]
+
+    # Branch one: the limited happy path lands every normalized row family.
+    assert main(_bounded_live_argv(tmp_root)) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert "sessdata: absent" in out
+    assert "outcome=limited" in out
+    assert "cursor: next_page=2 state=limited" in out
+    connection = open_database(tmp_root)
+    try:
+        _assert_collected_page_rows(connection, LIVE_SMOKE_MID)
+        # Positive control: a normalized video row really persisted, so the
+        # no-leak scans are not vacuous.
+        persisted = persisted_row_text(connection)
+        assert "BV1REHEARSE1" in persisted
+        assert_leaks_no_markers(out + err, context="rehearsal output")
+        assert_leaks_no_markers(persisted, context="rehearsal persisted rows")
+    finally:
+        connection.close()
+    for relative in LEGACY_SIDECAR_PATHS:
+        assert not os.path.exists(os.path.join(tmp_root, relative))
+
+    # Branch two: a bounded upstream failure on a fresh root stays scalar.
+    failure_root = os.path.join(tmp_root, "failure")
+    script.videos_response = None
+    script.parts_response = None
+    script.videos_error = FakeResponseCodeException(-400, UPSTREAM_ERROR_TEXT)
+    assert main(_bounded_live_argv(failure_root)) == 2
+    out, err = capsys.readouterr()
+    assert "metadata gateway failure" in err
+    connection = open_database(failure_root)
+    try:
+        assert _assert_bounded_failure_rows(connection, LIVE_SMOKE_MID) == (
+            "response_error"
+        )
+        assert_leaks_no_markers(out + err, context="rehearsal failure output")
+        assert_leaks_no_markers(
+            persisted_row_text(connection),
+            context="rehearsal failure persisted rows",
+        )
+    finally:
+        connection.close()
+    for relative in LEGACY_SIDECAR_PATHS:
+        assert not os.path.exists(os.path.join(failure_root, relative))
```
