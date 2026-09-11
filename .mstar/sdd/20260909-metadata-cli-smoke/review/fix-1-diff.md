# QC Fix Wave Diff — 20260909-metadata-cli-smoke

Plan: `20260909-metadata-cli-smoke` (SDD)
Range: `c86daa7..1a99751`
Base: `c86daa7` (QC-reviewed implementation head)
Head: `1a99751 docs(cli): document exit-2 variants and default page bound for metadata CLI`
Working branch: `feature/20260909-metadata-cli-smoke`
Scope: targeted re-validation of consolidated findings W1 + W2 + S-fix-1..7 (see review/qc-consolidated.md)
Note: the PM separately edited the frozen spec exit-code section (harness artifact, not in this diff)

```diff
diff --git a/bilibili-asr-archive/README.md b/bilibili-asr-archive/README.md
index bf05ad1..62a5ac9 100644
--- a/bilibili-asr-archive/README.md
+++ b/bilibili-asr-archive/README.md
@@ -253,7 +253,7 @@ Every `pilot` / `run` / `schedule` run atomically appends an inspectable run
 record to `{archive-root}/run-ledger.jsonl`. The metadata CLI's `fetch-meta`
 records its runs in the fresh SQLite database
 (`{archive-root}/archive.db`, see
-[the fresh-start metadata workflow](#fresh-start-metadata-collection-fetchmeta--status--runs))
+[the fresh-start metadata workflow](#fresh-start-metadata-collection-fetch-meta--status--runs))
 instead. The ledger is a sidecar file that records execution history and
 coverage without altering manifest row schemas or the transport layer.
 
@@ -498,6 +498,13 @@ only restart path.
     bili-asr status --archive-root archive
     bili-asr runs --limit 10 --archive-root archive
 
+- **Default page bound**: `--limit-pages` is optional and defaults to
+  `DEFAULT_PAGE_LIMIT = 10`. The canonical command above therefore stops
+  after 10 pages (the ingestor's page size is 100), ends the run `limited`,
+  and still exits 0 — a limited run is never claimed as complete. A full
+  archive walk is a series of resumable runs: re-run the same command to
+  continue from the stored cursor, or pass an explicit `--limit-pages` for
+  a longer slice.
 - **Resume semantics**: without `--resume` or `--start-page`, a run continues
   from the stored cursor when one exists and starts at page 1 otherwise.
   `--resume` requires a stored cursor and exits `1` when there is none;
@@ -507,13 +514,27 @@ only restart path.
   `BILI_SESSDATA` environment variable (cookie **value**, not a file path).
   It is sent as an API cookie only and is never echoed, logged, persisted,
   or written to the database; CLI output shows presence only
-  (`sessdata: present|absent`).
+  (`sessdata: present|absent`). Passing `--sessdata ""` explicitly forces
+  anonymous access even when `BILI_SESSDATA` is set; a blank environment
+  value likewise means anonymous.
 
 | Exit | Meaning |
 |------|---------|
-| 0 | `fetch-meta`: successful collection (empty page reached or explicit `--limit-pages` bound). `status` / `runs`: database read and displayed. |
-| 1 | Usage/configuration error: bad page arguments, `--resume` without a stored cursor, or a missing/unreadable database for the read commands. |
-| 2 | `fetch-meta` only: terminal gateway failure with a bounded scalar code (e.g. `response_error`, `rate_limited`); the cursor remains unchanged — re-run `fetch-meta` to resume. |
+| 0 | `fetch-meta`: successful collection — the empty page was reached, or the run stopped at a page bound (the explicit `--limit-pages` or the implicit default of 10 pages); the run row records `complete` or `limited` accordingly. `status` / `runs`: database read and displayed. |
+| 1 | Usage/configuration error: bad page arguments, `--resume` without a stored cursor, or a missing/unreadable database for the read commands. Unexpected internal errors exit 2 (see below), not 1. |
+| 2 | `fetch-meta` only: terminal failure — two variants, distinguishable by the failure line (see below). |
+
+Exit 2 variants:
+
+- **Gateway failure** (bounded scalar code, e.g. `response_error`,
+  `rate_limited`): the gateway is fail-fast per page — one attempt per
+  page, no retry. The failed page records its bounded scalar code, the
+  cursor remains unchanged, and re-running `fetch-meta` resumes safely.
+- **Unexpected internal error** (the fixed line `fetch-meta: unexpected
+  error`, no scalar code, no traceback): the cursor may already hold the
+  last committed page of the run and the run row may remain `running` —
+  check `status` / `runs` before re-running. Re-running is safe: it
+  resumes from the stored cursor.
 
 #### Opt-in bounded live smoke
 
diff --git a/bilibili-asr-archive/docs/metadata-storage.md b/bilibili-asr-archive/docs/metadata-storage.md
index 124825a..c75e1ef 100644
--- a/bilibili-asr-archive/docs/metadata-storage.md
+++ b/bilibili-asr-archive/docs/metadata-storage.md
@@ -11,6 +11,9 @@ command migrates old data into the new database.
 
 - `fetch-meta` creates `{archive_root}/archive.db` when it does not exist and
   initializes the checked-in schema (`src/bili_asr/storage/schema.sql`).
+  Opening the database — for a write or a read command — always runs that
+  schema script, which is an idempotent no-op on a current-version database;
+  no schema upgrade happens in this iteration.
 - `status` and `runs` are read-only. When the database is missing they fail
   with a clear configuration error and exit `1`; they never create it.
 - There is no migration, import, reset, or rewrite path. Deleting
@@ -18,6 +21,10 @@ command migrates old data into the new database.
   archive data is never discovered, read, or modified by any command.
 - A failed page never advances the cursor: resume is always safe, and no
   partially written page payload survives a failure.
+- `--limit-pages` is optional and defaults to `DEFAULT_PAGE_LIMIT = 10`: a
+  run without the flag stops after 10 pages, ends the run `limited` (exit
+  0, never claimed complete), and re-running the command resumes from the
+  stored cursor.
 
 ## Database layout
 
@@ -71,7 +78,9 @@ The optional SESSDATA credential comes from `--sessdata` or the
 `BILI_SESSDATA` environment variable (flag wins). It is passed to the
 gateway's cookie object only: never echoed, logged, persisted, or rendered —
 CLI output shows presence only (`sessdata: present|absent`). Omitting it
-means anonymous access.
+means anonymous access, and so does passing `--sessdata ""` explicitly
+(which never falls through to `BILI_SESSDATA`); a blank environment value
+likewise means anonymous.
 
 ## `observed_total` semantics
 
@@ -83,7 +92,8 @@ means anonymous access.
 - Run completion keys off the empty item list: the first page that returns
   no videos ends the run `complete` (bounded, spec-defined). An explicit
   `--limit-pages` bound ends the run `limited` instead — never claimed as
-  complete.
+  complete — and the same applies to the implicit default bound
+  (`DEFAULT_PAGE_LIMIT = 10`) applied when the flag is omitted.
 
 ## Exact bounded live smoke command
 
@@ -112,9 +122,21 @@ cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/te
 
 | Exit | Meaning |
 |------|---------|
-| 0 | Successful collection: completed on an empty page, or stopped at the explicit `--limit-pages` bound. |
-| 1 | Usage/configuration error: non-positive page arguments, `--resume` with no stored cursor, or an unreadable archive root. |
-| 2 | Terminal gateway failure with a bounded scalar code (for example `response_error`, `rate_limited`); the cursor remains unchanged. |
+| 0 | Successful collection: completed on an empty page, stopped at the explicit `--limit-pages` bound, or stopped at the implicit default bound (`DEFAULT_PAGE_LIMIT = 10` when the flag is omitted); the run row records `complete` or `limited` accordingly. |
+| 1 | Usage/configuration error: non-positive page arguments, `--resume` with no stored cursor, or an unreadable archive root. Unexpected internal errors exit 2 (see below), not 1. |
+| 2 | Terminal failure — two variants, distinguishable by the failure line (see below). |
+
+Exit 2 variants:
+
+- **Gateway failure** (bounded scalar code, e.g. `response_error`,
+  `rate_limited`): the gateway is fail-fast per page — one attempt per
+  page, no retry. The failed page records its bounded scalar code, the
+  cursor remains unchanged, and re-running `fetch-meta` resumes safely.
+- **Unexpected internal error** (the fixed line `fetch-meta: unexpected
+  error`, no scalar code, no traceback): the cursor may already hold the
+  last committed page of the run and the run row may remain `running` —
+  check `status` / `runs` before re-running. Re-running is safe: it
+  resumes from the stored cursor.
 
 ### `status` / `runs`
 
@@ -123,5 +145,7 @@ cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/te
 | 0 | Database read and displayed. An empty database prints `runs: empty`. |
 | 1 | Configuration error: the database does not exist (or a non-positive `runs --limit`). |
 
-`runs` lists runs newest-first and includes non-terminal `running` rows: a
-crash can leave a stale run behind, and hiding it would hide real state.
+`runs` lists runs newest-first — ordered by `started_at` descending, with
+same-second runs tie-broken deterministically by `run_id` descending — and
+includes non-terminal `running` rows: a crash can leave a stale run behind,
+and hiding it would hide real state.
diff --git a/bilibili-asr-archive/src/bili_asr/cli.py b/bilibili-asr-archive/src/bili_asr/cli.py
index bcb9f56..e11885f 100644
--- a/bilibili-asr-archive/src/bili_asr/cli.py
+++ b/bilibili-asr-archive/src/bili_asr/cli.py
@@ -74,11 +74,15 @@ def build_parser() -> argparse.ArgumentParser:
         help=f"Stop after collecting N pages (default: {DEFAULT_PAGE_LIMIT})",
     )
 
-    status = subparsers.add_parser("status", help="Print manifest status summary")
+    status = subparsers.add_parser(
+        "status",
+        help="Print collected metadata status from the SQLite archive database",
+    )
     status.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
 
     runs = subparsers.add_parser(
-        "runs", help="List recent operational runs from the ledger"
+        "runs",
+        help="List recent metadata collection runs from the SQLite archive database",
     )
     runs.add_argument(
         "--limit", type=int, default=None,
@@ -488,7 +492,8 @@ def _open_read_repository(
 
     Read commands never create the database: a missing file is the
     documented configuration error (exit 1), and an unreadable file is
-    reported bounded without raw SQLite text.
+    reported bounded without raw SQLite text.  The caller owns the open
+    connection and closes it when the command finishes.
     """
     from bili_asr.storage import MetadataRepository, open_database
 
@@ -515,8 +520,14 @@ def _cmd_fetch_meta(args: argparse.Namespace) -> int:
     """Collect video metadata into the fresh SQLite archive database.
 
     Exit taxonomy (metadata-cli-contract spec): 0 successful collection
-    (reached end or explicit --limit-pages); 1 usage/configuration error;
-    2 terminal gateway failure with the cursor unchanged.  This handler
+    (reached the end, the explicit --limit-pages bound, or the implicit
+    DEFAULT_PAGE_LIMIT bound); 1 usage/configuration error; 2 terminal
+    failure in one of two variants — a bounded gateway failure (the
+    fail-fast gateway: one attempt per page, a bounded scalar code, cursor
+    unchanged, resume safe) or an unexpected internal error (the fixed
+    "fetch-meta: unexpected error" message with no scalar code; the cursor
+    may hold the last committed page of the run and the run row may remain
+    `running`, so consult status/runs before re-running).  This handler
     never reads or writes the legacy manifest/cursor/ledger sidecars.
     """
     from bili_asr.services import MetadataIngestor
@@ -598,15 +609,25 @@ def _cmd_fetch_meta(args: argparse.Namespace) -> int:
     return 0
 
 
-def _run_error_codes(repository: "MetadataRepository") -> dict[str, str]:
-    """Collect one bounded error code per run from recorded page evidence."""
+def _run_error_codes(
+    repository: "MetadataRepository", run_ids: list[str]
+) -> dict[str, str]:
+    """Collect one bounded error code per rendered run from page evidence.
+
+    Only the runs the listing renders are queried and each query takes at
+    most one row (LIMIT 1), so the scan never grows with page history.
+    """
     codes: dict[str, str] = {}
-    rows = repository.connection.execute(
-        "SELECT run_id, error_code FROM ingestion_pages"
-        " WHERE error_code IS NOT NULL ORDER BY run_id, page_number"
-    ).fetchall()
-    for row in rows:
-        codes.setdefault(str(row["run_id"]), str(row["error_code"]))
+    for run_id in run_ids:
+        # Composition-root exception (adjudicated): this raw SQL read stays at the CLI seam.
+        row = repository.connection.execute(
+            "SELECT error_code FROM ingestion_pages"
+            " WHERE run_id = ? AND error_code IS NOT NULL"
+            " ORDER BY page_number LIMIT 1",
+            (run_id,),
+        ).fetchone()
+        if row is not None:
+            codes[run_id] = str(row["error_code"])
     return codes
 
 
@@ -628,7 +649,7 @@ def _format_run_line(stats: sqlite3.Row, error_code: str | None) -> str:
 
 
 def _resolve_sessdata(args: argparse.Namespace) -> str | None:
-    """SESSDATA from --sessdata or env BILI_SESSDATA; never echoed."""
+    """SESSDATA from --sessdata or env BILI_SESSDATA; blank forces anonymous."""
     return resolve_sessdata(args.sessdata, os.environ.get(SESSDATA_ENV_VAR))
 
 
@@ -900,42 +921,47 @@ def _cmd_status(args: argparse.Namespace) -> int:
     repository = _open_read_repository("status", args.archive_root)
     if repository is None:
         return 1
-    connection = repository.connection
-    counts = connection.execute(
-        "SELECT (SELECT COUNT(*) FROM bilibili_users) AS users,"
-        " (SELECT COUNT(*) FROM videos) AS videos,"
-        " (SELECT COUNT(*) FROM video_parts) AS parts"
-    ).fetchone()
-    print(f"users: {counts['users']}")
-    print(f"videos: {counts['videos']}")
-    print(f"parts: {counts['parts']}")
-    processing = connection.execute(
-        "SELECT processing_status, COUNT(*) AS count FROM video_parts"
-        " GROUP BY processing_status ORDER BY processing_status"
-    ).fetchall()
-    if processing:
-        summary = ", ".join(
-            f"{row['processing_status']}={row['count']}" for row in processing
-        )
-        print(f"processing: {summary}")
-    pending = repository.list_pending_parts()
-    print(f"pending: {len(pending)}")
-    for row in pending[:_MAX_DISPLAYED_PENDING_PARTS]:
-        print(f"  {row['work_id']}")
-    hidden = len(pending) - _MAX_DISPLAYED_PENDING_PARTS
-    if hidden > 0:
-        print(f"  + {hidden} more pending part(s)")
-    # The cursor row is reported exactly as stored: a failed or
-    # risk-interrupted run leaves it untouched, so this line never implies
-    # the cursor advanced past a failed page (C3).
-    for user_row in connection.execute("SELECT mid FROM bilibili_users ORDER BY mid"):
-        cursor = repository.read_cursor(int(user_row["mid"]))
-        if cursor is not None:
-            print(
-                f"cursor: mid={cursor.mid} next_page={cursor.next_page} "
-                f"state={cursor.state}"
+    try:
+        connection = repository.connection
+        counts = connection.execute(
+            "SELECT (SELECT COUNT(*) FROM bilibili_users) AS users,"
+            " (SELECT COUNT(*) FROM videos) AS videos,"
+            " (SELECT COUNT(*) FROM video_parts) AS parts"
+        ).fetchone()
+        print(f"users: {counts['users']}")
+        print(f"videos: {counts['videos']}")
+        print(f"parts: {counts['parts']}")
+        processing = connection.execute(
+            "SELECT processing_status, COUNT(*) AS count FROM video_parts"
+            " GROUP BY processing_status ORDER BY processing_status"
+        ).fetchall()
+        if processing:
+            summary = ", ".join(
+                f"{row['processing_status']}={row['count']}" for row in processing
             )
-    return 0
+            print(f"processing: {summary}")
+        pending = repository.list_pending_parts()
+        print(f"pending: {len(pending)}")
+        for row in pending[:_MAX_DISPLAYED_PENDING_PARTS]:
+            print(f"  {row['work_id']}")
+        hidden = len(pending) - _MAX_DISPLAYED_PENDING_PARTS
+        if hidden > 0:
+            print(f"  + {hidden} more pending part(s)")
+        # The cursor row is reported exactly as stored: a failed or
+        # risk-interrupted run leaves it untouched, so this line never implies
+        # the cursor advanced past a failed page (C3).
+        for user_row in connection.execute(
+            "SELECT mid FROM bilibili_users ORDER BY mid"
+        ):
+            cursor = repository.read_cursor(int(user_row["mid"]))
+            if cursor is not None:
+                print(
+                    f"cursor: mid={cursor.mid} next_page={cursor.next_page} "
+                    f"state={cursor.state}"
+                )
+        return 0
+    finally:
+        repository.connection.close()
 
 
 def _cmd_coverage_quality(args: argparse.Namespace) -> int:
@@ -1128,27 +1154,36 @@ def _cmd_runs(args: argparse.Namespace) -> int:
 
     Non-terminal ``running`` rows are rendered too: abnormal termination
     can leave a stale run behind and hiding it would hide real state (C2).
+    Ordering is deterministic: ``started_at`` descending, with same-second
+    runs tie-broken by ``run_id`` descending.
     """
     repository = _open_read_repository("runs", args.archive_root)
     if repository is None:
         return 1
-    if args.limit is not None and args.limit < 1:
-        print("runs: --limit must be a positive integer", file=sys.stderr)
-        return 1
-    stats_rows = repository.run_stats()
-    if not stats_rows:
-        print("runs: empty")
+    try:
+        if args.limit is not None and args.limit < 1:
+            print("runs: --limit must be a positive integer", file=sys.stderr)
+            return 1
+        stats_rows = repository.run_stats()
+        if not stats_rows:
+            print("runs: empty")
+            return 0
+        # Newest first; two runs sharing the second-resolution started_at
+        # order deterministically on the opaque run_id (run_id descending).
+        ordered = sorted(
+            stats_rows,
+            key=lambda row: (row["started_at"], row["run_id"]),
+            reverse=True,
+        )
+        selected = ordered if args.limit is None else ordered[: args.limit]
+        error_codes = _run_error_codes(
+            repository, [str(row["run_id"]) for row in selected]
+        )
+        for row in selected:
+            print(_format_run_line(row, error_codes.get(str(row["run_id"]))))
         return 0
-    error_codes = _run_error_codes(repository)
-    ordered = sorted(
-        stats_rows,
-        key=lambda row: (row["started_at"], row["run_id"]),
-        reverse=True,
-    )
-    selected = ordered if args.limit is None else ordered[: args.limit]
-    for row in selected:
-        print(_format_run_line(row, error_codes.get(str(row["run_id"]))))
-    return 0
+    finally:
+        repository.connection.close()
 
 
 _PILOT_PROCESSABLE = frozenset(
diff --git a/bilibili-asr-archive/src/bili_asr/config.py b/bilibili-asr-archive/src/bili_asr/config.py
index 6c5c73d..d1c4168 100644
--- a/bilibili-asr-archive/src/bili_asr/config.py
+++ b/bilibili-asr-archive/src/bili_asr/config.py
@@ -111,10 +111,14 @@ def resolve_sessdata(
     """Return the credential from the flag, else the environment, else None.
 
     The value is resolved for gateway construction only and is never
-    echoed; blank values mean public (anonymous) access.
+    echoed.  An explicitly blank flag (``""``) forces anonymous access and
+    never falls through to the environment; a blank environment value
+    likewise resolves to no credential.
     """
 
-    return flag_value or environment_value or None
+    if flag_value is not None:
+        return flag_value or None
+    return environment_value or None
 
 
 def redact_sessdata(sessdata: str | None) -> str:
diff --git a/bilibili-asr-archive/tests/test_live_metadata_smoke.py b/bilibili-asr-archive/tests/test_live_metadata_smoke.py
index 3482ee6..fc9823d 100644
--- a/bilibili-asr-archive/tests/test_live_metadata_smoke.py
+++ b/bilibili-asr-archive/tests/test_live_metadata_smoke.py
@@ -280,7 +280,9 @@ def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
         error_code = _assert_bounded_failure_rows(connection, LIVE_SMOKE_MID)
         assert error_code in err
         assert "metadata gateway failure" in err
-        if os.environ.get(SESSDATA_ENV_VAR) is None:
+        # Same resolution rule as ``resolve_sessdata``: a missing or blank
+        # BILI_SESSDATA means no credential was in play.
+        if not os.environ.get(SESSDATA_ENV_VAR):
             pytest.skip(
                 "live smoke ended in the documented bounded anonymous"
                 f" rejection (error_code={error_code!r}, exit 2): upstream"
@@ -304,13 +306,16 @@ def test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam(
     monkeypatch: pytest.MonkeyPatch,
     capsys: pytest.CaptureFixture[str],
 ) -> None:
-    """Rehearse both live-smoke outcome branches offline through the CLI.
+    """Rehearse the live-smoke outcome branches offline through the CLI.
 
     The live smoke's database assertions are plain SQL over the fresh
     schema; this rehearsal runs them against the same real CLI path over
     the fake ``bilibili_api`` seam, so a broken assertion or query is
     caught by every default (offline) run instead of first failing at the
-    QA gate's live execution.  No live behavior is claimed here.
+    QA gate's live execution.  The scripted branches cover the limited
+    happy path, the ``complete`` happy-path sub-branch (an empty first
+    page — practically unreachable live for this UID), and the bounded
+    upstream failure.  No live behavior is claimed here.
     """
 
     monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)
@@ -357,7 +362,27 @@ def test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam(
     for relative in LEGACY_SIDECAR_PATHS:
         assert not os.path.exists(os.path.join(tmp_root, relative))
 
-    # Branch two: a bounded upstream failure on a fresh root stays scalar.
+    # Branch two: the complete happy-path sub-branch over the seam — an
+    # empty first page completes the run without any collected video, a
+    # shape a live run for this UID practically never sees.
+    complete_root = os.path.join(tmp_root, "complete")
+    script.videos_response = lambda pn, ps: make_videos_response(count=0)
+    script.parts_response = None
+    assert main(_bounded_live_argv(complete_root)) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert "outcome=complete" in out
+    assert "cursor: next_page=1 state=complete" in out
+    connection = open_database(complete_root)
+    try:
+        _assert_collected_page_rows(connection, LIVE_SMOKE_MID)
+        assert_leaks_no_markers(out + err, context="rehearsal complete output")
+    finally:
+        connection.close()
+    for relative in LEGACY_SIDECAR_PATHS:
+        assert not os.path.exists(os.path.join(complete_root, relative))
+
+    # Branch three: a bounded upstream failure on a fresh root stays scalar.
     failure_root = os.path.join(tmp_root, "failure")
     script.videos_response = None
     script.parts_response = None
diff --git a/bilibili-asr-archive/tests/test_metadata_cli.py b/bilibili-asr-archive/tests/test_metadata_cli.py
index 5c36f37..854fc5c 100644
--- a/bilibili-asr-archive/tests/test_metadata_cli.py
+++ b/bilibili-asr-archive/tests/test_metadata_cli.py
@@ -12,8 +12,10 @@ contract:
   ``run-ledger.jsonl``.
 - ``status``/``runs`` fail clearly with exit 1 when that database is
   missing, and read only the fresh database.
-- Exit taxonomy: 0 success, 1 usage/configuration error, 2 terminal gateway
-  failure with the cursor unchanged.
+- Exit taxonomy: 0 success, 1 usage/configuration error, 2 terminal
+  failure — a bounded gateway failure (cursor unchanged) or an unexpected
+  internal error (the fixed ``fetch-meta: unexpected error`` message with
+  no scalar code).
 """
 
 from __future__ import annotations
@@ -30,9 +32,10 @@ from bili_asr.config import (
     DEFAULT_PAGE_LIMIT,
     load_metadata_config,
     redact_sessdata,
+    resolve_sessdata,
 )
 from bili_asr.storage import MetadataRepository, open_database
-from bili_asr.storage.models import IngestionRunRecord
+from bili_asr.storage.models import IngestionRunRecord, UserRecord
 from fixtures.fake_bilibili_gateway import (
     MID,
     SESSDATA_BOUNDARY_VALUE,
@@ -230,6 +233,26 @@ def test_sessdata_resolves_flag_over_environment(
     assert load_metadata_config(parser.parse_args(["fetch-meta"])).sessdata is None
 
 
+def test_blank_sessdata_flag_forces_anonymous(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """--sessdata "" is explicit-anonymous and never adopts BILI_SESSDATA."""
+
+    parser = build_parser()
+    monkeypatch.setenv("BILI_SESSDATA", "env-cookie")
+    blank_flag_config = load_metadata_config(
+        parser.parse_args(["fetch-meta", "--sessdata", ""])
+    )
+    assert blank_flag_config.sessdata is None
+    # The resolution rule itself: an explicitly blank flag forces anonymous
+    # access even when the environment carries a credential, while a blank
+    # environment also resolves to no credential.
+    assert resolve_sessdata("", "env-cookie") is None
+    assert resolve_sessdata(None, "env-cookie") == "env-cookie"
+    assert resolve_sessdata(None, "") is None
+    assert resolve_sessdata("flag-cookie", "env-cookie") == "flag-cookie"
+
+
 def test_sessdata_display_path_is_redacted() -> None:
     """Display/debug helpers show presence only, never the credential value."""
 
@@ -251,11 +274,18 @@ def test_metadata_config_repr_hides_sessdata(
     assert SESSDATA_BOUNDARY_VALUE not in repr(config)
 
 
-def test_default_page_bound_is_bounded_not_unbounded() -> None:
-    """Full-collection runs are bounded by the documented default (C1)."""
+def test_default_page_bound_applies_when_limit_pages_omitted() -> None:
+    """Omitting --limit-pages applies the documented default bound (C1)."""
 
+    config = load_metadata_config(build_parser().parse_args(["fetch-meta"]))
+    assert config.page_limit == DEFAULT_PAGE_LIMIT
     assert isinstance(DEFAULT_PAGE_LIMIT, int)
     assert DEFAULT_PAGE_LIMIT >= 1
+
+
+def test_default_mid_is_the_archive_owner() -> None:
+    """The documented default --mid is the archive owner's UID."""
+
     assert DEFAULT_MID == 23191782
 
 
@@ -704,6 +734,47 @@ def test_runs_lists_newest_first_and_renders_running_rows(
     assert {first_run_id, second_run_id} <= set(run_ids)
 
 
+def test_runs_orders_same_second_runs_by_run_id_desc(
+    tmp_root: str, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """Two runs sharing a started_at second render in run_id-descending order."""
+
+    same_second = 1_000
+    connection = open_database(tmp_root)
+    try:
+        repository = MetadataRepository(connection)
+        # The runs' mid foreign key needs its owner row first.
+        repository.upsert_user(
+            UserRecord(
+                mid=MID,
+                display_name=str(MID),
+                created_at=same_second,
+                updated_at=same_second,
+            )
+        )
+        for run_id in ("stub-same-second-aaa", "stub-same-second-bbb"):
+            repository.start_run(
+                IngestionRunRecord(
+                    run_id=run_id,
+                    mid=MID,
+                    source_package="bilibili-api-python",
+                    source_version="17.4.2",
+                    requested_start_page=1,
+                    requested_page_limit=DEFAULT_PAGE_LIMIT,
+                    started_at=same_second,
+                    outcome="running",
+                )
+            )
+    finally:
+        connection.close()
+
+    assert main(["runs", "--archive-root", tmp_root]) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    run_ids = [line.split()[1] for line in _run_lines(out)]
+    assert run_ids == ["stub-same-second-bbb", "stub-same-second-aaa"]
+
+
 def test_runs_limit_shows_only_recent_rows(
     tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str], _ingest_clock
 ) -> None:
diff --git a/bilibili-asr-archive/tests/test_metadata_e2e.py b/bilibili-asr-archive/tests/test_metadata_e2e.py
index 8bde7f7..781263a 100644
--- a/bilibili-asr-archive/tests/test_metadata_e2e.py
+++ b/bilibili-asr-archive/tests/test_metadata_e2e.py
@@ -285,6 +285,7 @@ def test_fetch_meta_normalizes_single_part_and_multipart_videos_end_to_end(
     assert "pending: 3" in status_out
     assert f"{SINGLE_PART_BVID}:p0" in status_out
     assert "cursor: mid=23191782 next_page=2 state=complete" in status_out
+    assert_leaks_no_markers(status_out + status_err, context="status output")
 
     assert main(["runs", "--archive-root", tmp_root]) == 0
     runs_out, runs_err = capsys.readouterr()
@@ -424,14 +425,19 @@ def test_fetch_meta_rerun_of_same_page_stores_no_duplicate_rows(
         cursor_row = _cursor_row(connection)
         assert tuple(cursor_row)[:5] == (MID, 2, 0, "complete", None)
 
-        assert_leaks_no_markers(
-            persisted_row_text(connection), context="re-run persisted rows"
-        )
+        # Positive control: a normalized video row really persisted, so the
+        # re-run's no-leak scan is not vacuous.
+        persisted = persisted_row_text(connection)
+        assert SINGLE_PART_BVID in persisted
+        assert_leaks_no_markers(persisted, context="re-run persisted rows")
     finally:
         connection.close()
 
     out, err = capsys.readouterr()
     assert err == ""
+    # Positive control: the credential really flowed through this run's
+    # flag path, so the re-run's output no-leak scan is not vacuous.
+    assert "sessdata: present" in out
     assert_leaks_no_markers(out + err, context="fetch-meta re-run output")
     # Page 1 was fetched exactly twice: once per run.
     assert script.calls.count("user.get_videos(pn=1, ps=100)") == 2
```
