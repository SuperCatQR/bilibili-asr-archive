# Plan-3 QC Fix Wave Diff — 20260911-subtitle-cli-cutover

Base: `8373817`
Head: `7e57eb6`
Scope: consolidated F-001 (Warning) + F-002/F-003 + QC2-001/002/003/004/009 + Q3-01/03/04/05

```diff
diff --git a/bilibili-asr-archive/README.md b/bilibili-asr-archive/README.md
index 1593524..7d24b45 100644
--- a/bilibili-asr-archive/README.md
+++ b/bilibili-asr-archive/README.md
@@ -99,6 +99,16 @@ in committed files or CI artifacts.
 
 ## Workflow
 
+⚠️ **The `probe-subs` / `harvest-subs` pair writes to `archive.db`, not to the
+manifest, so it feeds nothing below it.** The ASR/pilot chain
+(`download-audio`, `asr`, `pilot`, `run`, `schedule`, `campaign`) is still driven
+from `manifest/manifest.jsonl`, and the new `harvest-subs` no longer marks rows
+`needs_audio`: `download-audio --missing-subs` gains no entries from the step
+above it, and `asr --pending` does not see the stored transcripts. Run the
+subtitle step for the SQLite archive itself; the legacy chain keeps its own
+harvest (see the boundary bullet under
+[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)).
+
     bili-asr fetch-meta --mid 23191782 --archive-root archive
     bili-asr probe-subs --limit-parts 5 --archive-root archive
     bili-asr harvest-subs --limit-parts 5 --archive-root archive
@@ -619,9 +629,13 @@ observed live run, is in
   remaining_without_transcript=<n>`, carrying all four counts including the
   zeros. Nothing here is a claim about corpus or caption coverage.
 - **Preference rule**: the default keeps the **uploader** caption
-  (`subtitle-cc`) over the machine one (`subtitle-ai`) inside the same language
-  **family**, with families ranked `zh`, then `en`, then the rest in upstream
-  order. The family is derived from the `language` + `is_ai` facts the gateway
+  (`subtitle-cc`) over the machine one (`subtitle-ai`), with families ranked
+  `zh`, then `en`, then the rest in upstream order. That CC-before-AI term is
+  family-blind on purpose: the remaining families share one rank, so between two
+  **different** non-default families the uploader caption wins even when the
+  machine track comes first upstream, and upstream order settles only a tie
+  between tracks of the same family and the same kind. The family is derived
+  from the `language` + `is_ai` facts the gateway
   already guarantees (strip an `ai-` prefix from a machine code, then take the
   primary subtag), so `zh-CN` / `zh-Hans` / `zh-Hant` / `ai-zh` all rank as
   `zh`: upstream uses different exact codes per caption kind, and a fixed code
@@ -637,11 +651,14 @@ observed live run, is in
   its run row, so a part it recorded `no-subtitle` stays interpretable — an
   invisible caption may exist and simply be login-gated.
 - **Schema guard and rebuild**: on a database that predates the transcript
-  schema both commands print `<command>: archive database predates the
-  transcript schema; rebuild it (delete <archive-root>/archive.db and re-run
-  fetch-meta)` and exit `1`, while `fetch-meta` / `status` / `runs` keep working
-  on it. There is no in-place migration: deleting `archive.db` and re-running
-  `fetch-meta` is the rebuild. The database is created from two checked-in
+  schema both commands print one line on stderr — `<command>: archive database
+  predates the transcript schema; rebuild it (delete <archive-root>/archive.db
+  and re-run fetch-meta)` — and exit `1`, while `fetch-meta` / `status` / `runs`
+  keep working on it. There is no in-place migration: deleting `archive.db` and
+  re-running `fetch-meta` is the rebuild, and a bare `fetch-meta` stops at the
+  implicit `--limit-pages` bound (`DEFAULT_PAGE_LIMIT = 10`), so a corpus
+  collected beyond page 10 needs `--limit-pages <n>` (or repeated `--resume`
+  runs). The database is created from two checked-in
   resources, `src/bili_asr/storage/schema.sql` and
   `src/bili_asr/storage/schema-transcripts.sql`.
 - **Legacy manifest boundary**: the ASR/pilot chain is untouched and still reads
@@ -656,7 +673,10 @@ observed live run, is in
   `{archive-root}/coordinator/archive-writer.lock` for the whole run, so a
   second mutating command exits `1` with `harvest-subs: archive_busy`. Apart
   from `archive.db`, that lock is the only file a bounded harvest leaves behind;
-  `probe-subs` deliberately takes none.
+  `probe-subs` deliberately takes none. The lock is taken **before** the
+  command's database check, so even a failed or mistyped harvest — a missing
+  `--archive-root`, say — creates `<root>/coordinator/` and leaves the lock file
+  there while exiting `1`; nothing reaches the database.
 
 #### Opt-in bounded live smokes
 
@@ -684,7 +704,11 @@ run skips all four and makes no network call:
   commands only ever address parts the database already stores. Zero visible
   tracks, a `not_found` listing, and a `rate_limited` refusal are recorded as
   bounded evidence and skipped rather than reading green; every other bounded
-  code fails loudly. Its one count-only evidence line names the seeded part,
+  code fails loudly. Once opted in it **requires a credential**: with no
+  resolvable `BILI_SESSDATA` it fails with source-the-`.env` guidance instead of
+  reporting an anonymous `sessdata=absent tracks=0` run as "nothing visible now"
+  — an ambiguous reading, since a login-gated caption looks the same. Its one
+  count-only evidence line names the seeded part,
   credential presence, both commands' counts, and the stored source
   kind/language/version. Run it from the package directory of the checkout
   under test (the package's `tests/conftest.py` puts that checkout's `src/`
diff --git a/bilibili-asr-archive/docs/metadata-storage.md b/bilibili-asr-archive/docs/metadata-storage.md
index 18c7140..3fc764d 100644
--- a/bilibili-asr-archive/docs/metadata-storage.md
+++ b/bilibili-asr-archive/docs/metadata-storage.md
@@ -150,8 +150,13 @@ bounded run make progress. Each attempted part maps to exactly one outcome:
 | New content, or content differing from every stored version | `stored` | A new version was written; earlier versions stay readable. |
 | `rate_limited`, `transport_error`, `response_error`, `shape_error` | `failed` + the bounded code | Retry later for the first two; the last two need investigation. |
 
-No output carries a credential, a signed URL, a raw body, or upstream message
-text, and no count here is presented as coverage of the corpus.
+The error and evidence paths carry no credential, a signed URL, a raw body, or
+raw upstream message text: a bounded scalar code stands in for whatever upstream
+said. The one upstream **metadata** value any output prints is the track label
+(`lan_doc`) on the `track` lines above — printed as metadata, trimmed, and
+rejected by the gateway as a bounded `shape_error` if it carries a control
+character, so it cannot split the locked one-line-per-track shape. No count here
+is presented as coverage of the corpus.
 
 ### Exit codes
 
@@ -187,6 +192,13 @@ mutating command exits `1` with `harvest-subs: archive_busy` instead of
 partially mutating the archive. That lock file and the database itself are the
 only files a bounded harvest leaves under the archive root.
 
+The lock is taken by the command dispatcher **before** the handler reaches its
+database check, so a harvest pointed at a missing or mistyped `--archive-root`
+still creates `<root>/coordinator/` and leaves the lock file there while exiting
+`1` with the missing-database line. A failed or mistyped harvest is therefore
+not a no-op on the filesystem: nothing reaches the database, but the root and
+its `coordinator/` directory are created.
+
 `probe-subs` is deliberately **not** an archive-writer command: it takes no
 lock and creates no file under the archive root. Its read-only promise is
 structural rather than only documented — no database creation, no transcript
@@ -198,8 +210,13 @@ while another process writes, exactly like `status` and `runs`.
 `harvest-subs` stores exactly one track per part. The default (no `--language`)
 ranks the visible tracks by language **family** — `zh` first, then `en`, then
 every remaining family in upstream order — and prefers an uploader caption
-(`is_ai = false`, printed `cc`) over a machine one inside the same family; the
-first track after that ranking is fetched.
+(`is_ai = false`, printed `cc`) over a machine one; the first track after that
+ranking is fetched. The CC-before-AI term is deliberately **family-blind**: the
+remaining families share one rank, so between two *different* non-default
+families the uploader caption wins even when the machine track comes first
+upstream, and upstream order settles only a tie between tracks of the same
+family and the same kind. That ranking order is the locked key; `--language`
+overrides the whole rule.
 
 The family is derived from the two normalized facts the gateway DTO already
 guarantees — `language` and `is_ai` — by stripping the `ai-` prefix from a
@@ -237,17 +254,21 @@ keeps the machine one reachable.
 
 Both commands require the transcript contract in the database they open. On a
 database that predates it — one whose `transcripts` table lacks `language` /
-`content_sha256` — they print the fixed line and exit `1`:
+`content_sha256` — they print the fixed message below on **stderr** (their part
+and summary output is stdout, and this path prints nothing there) and exit `1`.
+It is one line; the wrap below is the page's, not the command's:
 
 ```text
-<command>: archive database predates the transcript schema; rebuild it
-(delete <archive-root>/archive.db and re-run fetch-meta)
+<command>: archive database predates the transcript schema; rebuild it (delete <archive-root>/archive.db and re-run fetch-meta)
 ```
 
 The metadata commands (`fetch-meta`, `status`, `runs`) keep working on that same
 database unchanged. There is no in-place migration: the rebuild procedure is to
 delete `archive.db`, re-run `fetch-meta` to recreate it from the checked-in
-schemas, and harvest again.
+schemas, and harvest again. A bare `fetch-meta` stops at the implicit
+`--limit-pages` bound (`DEFAULT_PAGE_LIMIT = 10`), so rebuilding a corpus
+collected beyond page 10 needs the bound spelled out (`--limit-pages <n>`) — or
+repeated runs with `--resume`, which continues from the stored cursor.
 
 ### Boundary with the legacy manifest path
 
@@ -495,13 +516,26 @@ exercised is the checkout the test file belongs to.
   is visible). The smoke adds no retry of its own; the shipped gateway is
   fail-fast per call, so a throttled endpoint is answered by waiting and
   re-running, never by bending the call shape.
+- Opt-in requires a resolvable credential: the smoke passes no `--sessdata` and
+  reads the same environment the command reads, so an opted-in run with no
+  `BILI_SESSDATA` (unset or blank) **fails loudly** with source-the-`.env`
+  guidance instead of reporting its anonymous `sessdata=absent tracks=0` reading
+  as a bounded observation. That reading is ambiguous — a login-gated caption
+  and a part with no caption look identical — so a forgotten credential must not
+  read as "nothing visible now". A default (not opted-in) pytest run still
+  skips, credential or not.
 - Asserted when a caption is visible: the printed presence, track, outcome and
   summary line shapes; the normalized transcript row (an allowed
   `source_kind`, its language, version 1, the content hash), its ordered
   segments, the one run row with the operator's selector and the credential
   presence, the one attempt row pointing at the transcript, a part that left
   `v_pending_subtitles`, and an archive root holding nothing but `archive.db`
-  and `coordinator/archive-writer.lock`.
+  and `coordinator/archive-writer.lock`. Every field of the printed evidence
+  line is tied to an assertion: the probe's `with_tracks` and the harvest's
+  `stored` are checked against the part line they summarize, and the printed
+  `run_id` against the persisted run row. Both commands' stdout and stderr are
+  scanned for the seam's secret/payload sentinels — including the probe's, whose
+  `track` lines are the one place an upstream label is printed.
 - Recorded without reading green: zero visible tracks, a `not_found` listing,
   and a `rate_limited` refusal each assert their bounded shapes, print the
   evidence, and skip — a run that stored no transcript is not a subtitle
@@ -511,12 +545,12 @@ exercised is the checkout the test file belongs to.
   exit 0, bounded facts only: `part_source=fixed-sample
   work_id=BV1S8hA6MEvy:p0 sessdata=present probe_exit=0 probed=1 with_tracks=1
   without_tracks=0 probe_failed=0 track_count=1 tracks=ai-zh:ai harvest_exit=0
-  attempted=1 stored=1 unchanged=0 no_subtitle=0 failed=0
-  remaining_without_transcript=0 source_kind=subtitle-ai language=ai-zh
-  version=1 segments=2913 transcripts=1 attempts=1 pending_after=0`. The part
-  exposed one machine caption, the harvest stored it as version 1, and the part
-  left the pending enumeration. Count-only: no credential, no proxy, no signed
-  URL, and no caption text is recorded here.
+  run_id=1de9b7cb7cd141bfa7114112212188db attempted=1 stored=1 unchanged=0
+  no_subtitle=0 failed=0 remaining_without_transcript=0 source_kind=subtitle-ai
+  language=ai-zh version=1 segments=2913 transcripts=1 attempts=1
+  pending_after=0`. The part exposed one machine caption, the harvest stored it
+  as version 1, and the part left the pending enumeration. Count-only: no
+  credential, no proxy, no signed URL, and no caption text is recorded here.
 
 ## Exit codes
 
diff --git a/bilibili-asr-archive/src/bili_asr/cli.py b/bilibili-asr-archive/src/bili_asr/cli.py
index 017a0a5..275aa68 100644
--- a/bilibili-asr-archive/src/bili_asr/cli.py
+++ b/bilibili-asr-archive/src/bili_asr/cli.py
@@ -499,6 +499,23 @@ def _metadata_database_path(archive_root: str) -> str:
     return os.path.join(archive_root, ARCHIVE_DATABASE_NAME)
 
 
+def _archive_database_exists(command: str, archive_root: str) -> bool:
+    """Require an existing ``archive.db`` below the root; print the shipped line when absent.
+
+    Neither subtitle command creates the database and read commands never do, so
+    the file is checked before any connection is opened — the shipped read
+    command's missing-database answer (fixed line, exit 1, nothing created).
+    """
+    if os.path.isfile(_metadata_database_path(archive_root)):
+        return True
+    print(
+        f"{command}: no archive database at {archive_root}; "
+        "run fetch-meta to create it",
+        file=sys.stderr,
+    )
+    return False
+
+
 def _open_read_connection(command: str, archive_root: str):
     """Open the fresh database for a read command; None after printing why not.
 
@@ -509,22 +526,56 @@ def _open_read_connection(command: str, archive_root: str):
     """
     from bili_asr.storage import open_database
 
-    if not os.path.isfile(_metadata_database_path(archive_root)):
+    if not _archive_database_exists(command, archive_root):
+        return None
+    try:
+        return open_database(archive_root)
+    except (OSError, sqlite3.Error) as exc:
         print(
-            f"{command}: no archive database at {archive_root}; "
-            "run fetch-meta to create it",
+            f"{command}: unreadable archive database at {archive_root} "
+            f"({type(exc).__name__})",
             file=sys.stderr,
         )
         return None
+
+
+def _open_read_only_connection(command: str, archive_root: str):
+    """Open an existing archive database strictly read-only; None after printing why not.
+
+    ``probe-subs`` promises that it writes nothing at all, so it deliberately
+    does not go through :func:`~bili_asr.storage.open_database`: that path
+    executes both idempotent schema scripts and commits them even when nothing
+    changes.  This connection is opened through a ``mode=ro`` URI instead, so the
+    promise is structural rather than conventional — a write attempted through it
+    fails inside SQLite instead of reaching the file.  The database existence
+    guard is the shipped one, and an unreadable file is reported bounded exactly
+    as the write-capable read path reports it.  The first read is taken here,
+    inside that bounded handler, because a file that is not a database at all
+    only fails on the first statement, not on connect.
+    """
+    if not _archive_database_exists(command, archive_root):
+        return None
+    connection = None
     try:
-        return open_database(archive_root)
+        resolved = Path(_metadata_database_path(archive_root)).resolve()
+        connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
+        # The repository contract requires both of these of any connection it is
+        # handed, and neither touches the database file: ``sqlite3.Row`` is a
+        # client-side row factory and ``foreign_keys`` is a per-connection
+        # setting.
+        connection.row_factory = sqlite3.Row
+        connection.execute("PRAGMA foreign_keys = ON")
+        connection.execute("PRAGMA schema_version").fetchone()
     except (OSError, sqlite3.Error) as exc:
+        if connection is not None:
+            connection.close()
         print(
             f"{command}: unreadable archive database at {archive_root} "
             f"({type(exc).__name__})",
             file=sys.stderr,
         )
         return None
+    return connection
 
 
 def _open_read_repository(
@@ -556,7 +607,9 @@ def _subtitle_schema_rebuild_line(command: str, archive_root: str) -> str:
     )
 
 
-def _open_subtitle_connection(command: str, archive_root: str):
+def _open_subtitle_connection(
+    command: str, archive_root: str, *, read_only: bool = False
+):
     """Open the archive database for one subtitle command; None after printing.
 
     Neither subtitle command creates ``archive.db`` (``open_database`` does), so
@@ -564,10 +617,19 @@ def _open_subtitle_connection(command: str, archive_root: str):
     and the transcript-schema capability is required immediately after opening:
     a database that predates the contract is answered with the fixed rebuild line
     and exit 1 instead of a raw SQLite error from the first transcript query.
+
+    ``read_only`` is set by ``probe-subs``, whose "writes nothing at all" promise
+    is then structural: its connection is the ``mode=ro`` one from
+    :func:`_open_read_only_connection`, never the schema-initializing
+    ``open_database`` the write commands and the other read commands share.
     """
     from bili_asr.storage import SchemaContractError, require_subtitle_schema
 
-    connection = _open_read_connection(command, archive_root)
+    connection = (
+        _open_read_only_connection(command, archive_root)
+        if read_only
+        else _open_read_connection(command, archive_root)
+    )
     if connection is None:
         return None
     try:
@@ -600,6 +662,23 @@ def _subtitle_selector(value: str | None) -> tuple[str | None, int | None]:
         return value, None
 
 
+def _selector_cannot_name_a_part(bvid: str) -> bool:
+    """Report whether a ``--bvid`` value can never name a stored part.
+
+    The archive stores ``bvid`` values through the storage contract's own
+    identifier rule, which rejects a value that is empty once stripped and one
+    that carries a control character (``\\x00``/``\\r``/``\\n``), so such a
+    selector resolves to zero rows in every database there is.  It is therefore
+    answered as the documented configuration error — the fixed
+    ``unknown --bvid <value>`` line, exit 1 — decided on the argument alone and
+    before the database is opened, instead of being handed to the repository,
+    whose identifier validation would reject it and surface as an unexpected
+    internal error.  A padded-but-addressable value is deliberately *not*
+    rejected here: only a value the storage rule cannot hold is.
+    """
+    return not bvid.strip() or any(mark in bvid for mark in "\x00\r\n")
+
+
 def _cmd_fetch_meta(args: argparse.Namespace) -> int:
     """Collect video metadata into the fresh SQLite archive database.
 
@@ -768,8 +847,16 @@ def _cmd_probe_subs(args: argparse.Namespace) -> int:
         )
         return 1
     bvid, page_index = _subtitle_selector(args.bvid)
+    if bvid is not None and _selector_cannot_name_a_part(bvid):
+        # A blank or control-character selector names no part in any database, so
+        # it is the documented configuration error and is decided before the
+        # database is opened.
+        print(f"probe-subs: unknown --bvid {args.bvid}", file=sys.stderr)
+        return 1
     sessdata = _resolve_sessdata(args)
-    connection = _open_subtitle_connection("probe-subs", args.archive_root)
+    connection = _open_subtitle_connection(
+        "probe-subs", args.archive_root, read_only=True
+    )
     if connection is None:
         return 1
     try:
@@ -855,6 +942,12 @@ def _cmd_harvest_subs(args: argparse.Namespace) -> int:
         )
         return 1
     bvid, page_index = _subtitle_selector(args.bvid)
+    if bvid is not None and _selector_cannot_name_a_part(bvid):
+        # Same configuration error as an unknown bvid, and decided on the
+        # argument alone: a selector the archive cannot store can never resolve to
+        # a part, so no bound would make it selectable.
+        print(f"harvest-subs: unknown --bvid {args.bvid}", file=sys.stderr)
+        return 1
     if args.limit_parts is None and page_index is None:
         # No unbounded runs: only a single named part is bounded by construction.
         print(
diff --git a/bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py b/bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py
index 41a2dc9..64b840d 100644
--- a/bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py
+++ b/bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py
@@ -22,6 +22,9 @@ Outcome mapping (one outcome per attempted part):
   later run, and the attempt row carries ``not_found`` when upstream said so);
 - the body was fetched and stored → ``stored``, or ``unchanged`` when a stored
   version of the same identity already carries that content;
+- a fetched body the storage boundary refuses as unrepresentable (a timeline
+  position above its caption range) → ``failed`` with the bounded
+  ``shape_error`` code, one part's outcome rather than the run's;
 - any other bounded gateway failure → ``failed`` with that scalar error code.
 """
 
@@ -40,6 +43,7 @@ from bili_asr.sources.models import (
     BilibiliGateway,
     GatewayError,
     GatewayNotFound,
+    GatewayShapeError,
     SubtitleSegment,
     SubtitleTrack,
 )
@@ -493,29 +497,45 @@ class SubtitleIngestor:
         with the resulting ``stored``/``unchanged`` outcome, and commits — or
         rolls the whole call back.  The body is converted field for field, and
         the language is stored trimmed, so the reported language is the identity
-        the store holds.
+        the store holds.  A body the storage boundary refuses with its bounded
+        ``ValueError`` (a timeline position it cannot represent) is answered as
+        this part's ``failed``/``shape_error`` outcome rather than an escaping
+        error, so one anomalous part cannot end a bounded run.
         """
 
         finished_at = self._clock()
         source_kind = _caption_source_kind(track.is_ai)
         language = track.language.strip()
-        write = self._repository.record_acquired_transcript(
-            run_id=run_id,
-            video_part_id=item.video_part_id,
-            source_kind=source_kind,
-            language=language,
-            segments=tuple(
-                TranscriptSegmentRecord(
-                    start_ms=segment.start_ms,
-                    end_ms=segment.end_ms,
-                    text=segment.text,
-                )
-                for segment in segments
-            ),
-            started_at=started_at,
-            finished_at=finished_at,
-            created_at=finished_at,
-        )
+        try:
+            write = self._repository.record_acquired_transcript(
+                run_id=run_id,
+                video_part_id=item.video_part_id,
+                source_kind=source_kind,
+                language=language,
+                segments=tuple(
+                    TranscriptSegmentRecord(
+                        start_ms=segment.start_ms,
+                        end_ms=segment.end_ms,
+                        text=segment.text,
+                    )
+                    for segment in segments
+                ),
+                started_at=started_at,
+                finished_at=finished_at,
+                created_at=finished_at,
+            )
+        except ValueError:
+            # The storage boundary re-validates the timeline it is handed and
+            # rejects a body it cannot represent (a position above
+            # ``MAX_TIMELINE_MS``) with a bounded ``ValueError``.  That check runs
+            # in the boundary's canonical-segment step, ahead of its transaction,
+            # so nothing was written and nothing needs rolling back.  It is one
+            # part's data anomaly, not the run's: it is recorded as this part's
+            # bounded ``shape_error`` attempt so the remaining parts of the
+            # bounded run are still attempted, instead of aborting the whole run.
+            return self._record_failed_part(
+                run_id, item, GatewayShapeError(), started_at
+            )
         return SubtitlePartOutcome(
             work_id=item.work_id,
             outcome=write.outcome,
diff --git a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
index d226352..5aac671 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
@@ -175,13 +175,20 @@ def _normalize_video_summary_item(item: object, requested_mid: int) -> VideoSumm
         raise GatewayShapeError(
             detail="video item owner mid does not match the requested user"
         )
-    return VideoSummary(
-        bvid=bvid,
-        aid=_read_optional_aid(item),
-        title=title.strip(),
-        pubdate=_read_pubdate(item),
-        mid=owner_mid,
-    )
+    try:
+        return VideoSummary(
+            bvid=bvid,
+            aid=_read_optional_aid(item),
+            title=title.strip(),
+            pubdate=_read_pubdate(item),
+            mid=owner_mid,
+        )
+    except (TypeError, ValueError) as exc:
+        # The DTO rejects text the storage contract cannot hold either — a title
+        # carrying a control character, for instance — and that is a bounded
+        # shape error at this boundary, like every sibling normalizer's, rather
+        # than a raw validation error escaping the gateway.
+        raise GatewayShapeError(detail="video item is not normalizable") from exc
 
 
 def _normalize_user_video_page(
diff --git a/bilibili-asr-archive/src/bili_asr/sources/models.py b/bilibili-asr-archive/src/bili_asr/sources/models.py
index 1a8d9dd..a7006f8 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/models.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/models.py
@@ -23,6 +23,36 @@ def _integer(value: object, field: str, *, minimum: int | None = None) -> int:
 
 
 def _text(value: object, field: str) -> str:
+    """Validate one printable, non-empty text field of a DTO.
+
+    The rule is the storage contract's own (``storage.models._text``): a
+    non-empty string after stripping that carries no control character.  A
+    control character is rejected rather than kept because these fields are
+    operator-facing — the CLI prints them verbatim, one line per record — so a
+    value carrying ``\\x00``, ``\\r``, or ``\\n`` would split a locked output
+    shape instead of being displayed.  Caption body text is the one documented
+    exception and goes through :func:`_caption_text` instead, mirroring the
+    storage contract's own split.
+    """
+    if not isinstance(value, str):
+        raise TypeError(f"{field} must be a string")
+    if not value.strip():
+        raise ValueError(f"{field} must not be empty")
+    if "\x00" in value or "\r" in value or "\n" in value:
+        raise ValueError(f"{field} contains invalid control characters")
+    return value
+
+
+def _caption_text(value: object, field: str) -> str:
+    """Validate one caption body row: a string non-empty after stripping.
+
+    The mirror of ``storage.models._caption_text``, which the storage contract
+    states explicitly: unlike :func:`_text`, control characters inside a
+    caption body are *kept*, because a stored caption is verbatim apart from
+    trimming.  A cue may legitimately span two lines, so rejecting ``\\n`` here
+    would turn a real caption into a document-level shape error — and the store
+    is the boundary that decides what it can hold, not this DTO.
+    """
     if not isinstance(value, str):
         raise TypeError(f"{field} must be a string")
     if not value.strip():
@@ -129,6 +159,9 @@ class SubtitleSegment:
     ``end_ms > start_ms >= 0`` with ``text`` non-empty after stripping is the
     invariant this DTO enforces on what a call returns.  It is not a filter:
     the adapter drops a row carrying nothing usable before constructing it.
+    ``text`` is validated as caption body text (:func:`_caption_text`), so a
+    cue that legitimately spans two lines stays one row — the store keeps
+    caption text verbatim, control characters included.
     """
 
     start_ms: int
@@ -140,7 +173,7 @@ class SubtitleSegment:
         _integer(self.end_ms, "end_ms", minimum=1)
         if self.end_ms <= self.start_ms:
             raise ValueError("end_ms must be greater than start_ms")
-        _text(self.text, "text")
+        _caption_text(self.text, "text")
 
 
 class BilibiliGateway(Protocol):
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index 4ec0b04..9ca07a2 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -537,6 +537,29 @@ def test_get_user_video_page_rejects_foreign_owner_mid(bilibili_api_seam):
     assert "mid" in str(caught.value)
 
 
+def test_get_user_video_page_rejects_a_title_with_control_characters(
+    bilibili_api_seam,
+):
+    """A title the storage contract cannot hold is a bounded shape error here.
+
+    The DTO applies the same printable-text rule the storage contract applies, so
+    the metadata path stays bounded: an upstream title carrying a control
+    character is rejected as this page's ``shape_error`` instead of escaping as a
+    raw validation error from a later write.
+    """
+
+    bilibili_api_seam.videos_response = make_videos_response(
+        make_vlist_item(title="未明子讲座\n伪造第二行"), count=1
+    )
+    gateway = _load_gateway()
+
+    with pytest.raises(GatewayShapeError) as caught:
+        asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    assert caught.value.code == "shape_error"
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
+
+
 def test_get_user_video_page_rejects_missing_owner_mid(bilibili_api_seam):
     """An item without an owner mid cannot prove ownership."""
 
@@ -1571,6 +1594,17 @@ def test_subtitle_dtos_carry_no_work_id_and_no_url_field():
         {"label": ""},
         {"label": "   "},
         {"label": None},
+        # The label is printed verbatim on the CLI's one-line-per-track shape, so
+        # a value carrying a control character is rejected here (F-003) exactly as
+        # the storage contract rejects one on every text field it holds.
+        {"label": "中文\n伪造第二行"},
+        {"label": "中文\r"},
+        {"label": "中文\x00"},
+        {"language": "zh-CN\n"},
+        {"language": "zh-CN\r"},
+        {"language": "zh-CN\x00"},
+        {"track_id": "track\n1"},
+        {"track_id": "track\x001"},
         {"is_ai": "ai"},
         {"is_ai": 1},
         {"is_ai": None},
@@ -2462,6 +2496,16 @@ def test_get_subtitle_tracks_returns_an_empty_tuple_for_an_empty_inventory(
         # The service derives the language family from the primary subtag, so a
         # vocabulary it could not rank is a shape error, not a silent keep.
         {"subtitle": {"subtitles": [{"lan": "-zh", "lan_doc": "中文"}]}},
+        # A label carrying a control character cannot reach the CLI, whose track
+        # line is locked to one line per track: it is a bounded shape error here
+        # (F-003) rather than a value that splits the printed shape.  The
+        # characters are interior on purpose — the adapter strips the outer
+        # whitespace of ``lan``/``lan_doc`` before constructing the DTO, so only
+        # an interior one survives to the DTO's own rule.
+        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": "中文\n伪造第二行"}]}},
+        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": "中文\r伪造"}]}},
+        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": "中文\x00"}]}},
+        {"subtitle": {"subtitles": [{"lan": "zh\n-CN", "lan_doc": "中文"}]}},
     ],
 )
 def test_get_subtitle_tracks_rejects_an_unreadable_inventory(
@@ -2683,6 +2727,42 @@ def test_fetch_subtitle_segments_normalizes_the_document_and_drops_degenerate_ro
     assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
 
 
+def test_caption_text_keeps_interior_control_characters_as_one_row(
+    bilibili_api_seam,
+):
+    """A multi-line cue is a normal caption row, not a document-level failure.
+
+    The storage contract splits its text rules on purpose: ``_caption_text``
+    keeps control characters inside a caption body (a stored caption is verbatim
+    apart from trimming), while every operator-facing field goes through
+    ``_text``, which rejects them.  The gateway mirrors that split, so a cue
+    spanning two lines survives as ONE row here.  Rejecting it in the DTO would
+    raise a raw ``ValueError`` out of ``fetch_subtitle_segments`` — it is not a
+    bounded ``GatewayError`` — and end a whole harvest run on ordinary upstream
+    data.
+    """
+
+    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(
+            _subtitle_row(0.0, 1.5, "  未明子讲座\n第一讲  "),
+            _subtitle_row(1.5, 3.0, "第二行\r第三行"),
+            _subtitle_row(3.0, 4.0, "末行"),
+        )
+    }
+
+    segments = asyncio.run(
+        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
+    )
+
+    assert segments == (
+        SubtitleSegment(start_ms=0, end_ms=1500, text="未明子讲座\n第一讲"),
+        SubtitleSegment(start_ms=1500, end_ms=3000, text="第二行\r第三行"),
+        SubtitleSegment(start_ms=3000, end_ms=4000, text="末行"),
+    )
+    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
+
+
 def test_caption_seconds_are_floored_rather_than_rounded_to_milliseconds(
     bilibili_api_seam,
 ):
diff --git a/bilibili-asr-archive/tests/test_live_subtitle_cli_smoke.py b/bilibili-asr-archive/tests/test_live_subtitle_cli_smoke.py
index b256504..b72279f 100644
--- a/bilibili-asr-archive/tests/test_live_subtitle_cli_smoke.py
+++ b/bilibili-asr-archive/tests/test_live_subtitle_cli_smoke.py
@@ -105,6 +105,7 @@ from bili_asr.storage.models import (
 )
 from fixtures.fake_bilibili_gateway import (
     SESSDATA_BOUNDARY_VALUE,
+    SIGNED_SUBTITLE_URL_MARKER,
     FakeGateway,
     assert_leaks_no_markers,
     fake_gateway_seam,
@@ -232,6 +233,49 @@ def _credential_expectation() -> bool:
     return resolve_sessdata(None, os.environ.get(SESSDATA_ENV_VAR)) is not None
 
 
+def _require_live_credential() -> None:
+    """Fail loudly when an opted-in smoke has no resolvable credential.
+
+    Reached only after the opt-in gate, so a default pytest run still skips
+    without a credential.  Once the operator has asked for a live run, a
+    forgotten credential must not read as a benign skip: the smoke derives its
+    own expectation from the same environment the command reads, so an
+    anonymous run answers ``sessdata=absent`` with no visible tracks and would
+    report "nothing visible now" — indistinguishable from a login-gated caption
+    and from a part that simply has none.  Failing here costs no upstream call.
+    """
+
+    if _credential_expectation():
+        return
+    pytest.fail(
+        "the live subtitle CLI smoke was requested but no credential resolves:"
+        f" {SESSDATA_ENV_VAR} is unset or blank.  Source the control checkout's"
+        " gitignored .env (set -a; source .env; set +a) or export"
+        f" {SESSDATA_ENV_VAR}, then re-run — an anonymous run cannot tell a"
+        " login-gated caption from a part that has none, so a forgotten"
+        " credential must not read as a benign skip"
+    )
+
+
+def _live_preconditions() -> None:
+    """Apply the smoke's three preconditions, in their documented order.
+
+    Opt in first, so a default pytest run skips without needing a credential or
+    the pinned distribution; then the pin, which fails loudly rather than
+    skipping; then the credential, which fails loudly for the same reason
+    (:func:`_require_live_credential`).  Extracted so the order itself is
+    rehearsable offline, instead of resting on a live run.
+    """
+
+    if not _live_smoke_requested():
+        pytest.skip(
+            f"live subtitle CLI smoke is opt-in: set {LIVE_SMOKE_ENV}=1 to"
+            " request it"
+        )
+    assert _pinned_package_version() == PINNED_PACKAGE_VERSION
+    _require_live_credential()
+
+
 def _probe_argv(tmp_root: str) -> list[str]:
     """The bounded ``probe-subs`` invocation: one part by the enumeration bound."""
 
@@ -383,15 +427,34 @@ def _read_probe_output(out: str, *, expect_credential_present: bool) -> ProbeOut
     assert work_id == SAMPLE_WORK_ID, (
         f"the probe addressed {work_id!r}, not the part the smoke authored"
     )
+    probed = int(summary["probed"])
+    with_tracks = int(summary["with_tracks"])
+    without_tracks = int(summary["without_tracks"])
+    failed = int(summary["failed"])
+    # The summary's counts are tied to the part line they summarize, so the
+    # evidence line's ``with_tracks`` is derived from the probe's own output
+    # rather than re-emitted on trust (QC2-009/Q3-03).
+    assert with_tracks == (1 if track_count else 0), (
+        "with_tracks counts the parts that listed a track"
+    )
+    assert without_tracks == (1 if track_count == 0 else 0), (
+        "without_tracks counts the parts that listed no track"
+    )
+    assert failed == (1 if error_code is not None else 0), (
+        "failed counts the parts whose listing failed"
+    )
+    assert probed == with_tracks + without_tracks + failed, (
+        "the three brackets partition the probed parts"
+    )
     return ProbeOutput(
         work_id=work_id,
         track_count=track_count,
         error_code=error_code,
         tracks=tracks,
-        probed=int(summary["probed"]),
-        with_tracks=int(summary["with_tracks"]),
-        without_tracks=int(summary["without_tracks"]),
-        failed=int(summary["failed"]),
+        probed=probed,
+        with_tracks=with_tracks,
+        without_tracks=without_tracks,
+        failed=failed,
     )
 
 
@@ -433,6 +496,29 @@ def _read_harvest_output(
         f"the harvest addressed {groups['work_id']!r}, not the part the smoke seeded"
     )
 
+    attempted = int(summary["attempted"])
+    stored = int(summary["stored"])
+    unchanged = int(summary["unchanged"])
+    no_subtitle = int(summary["no_subtitle"])
+    failed = int(summary["failed"])
+    # The four outcome counts are tied to the one part line above them: exactly
+    # one of them is 1 and they partition the single attempt, so the evidence
+    # line's ``stored`` is derived from the harvest's own output instead of
+    # being re-emitted on trust (QC2-009/Q3-03).
+    expected_counts = {
+        "stored": (1, 0, 0, 0),
+        "unchanged": (0, 1, 0, 0),
+        "no-subtitle": (0, 0, 1, 0),
+        "failed": (0, 0, 0, 1),
+    }[outcome]
+    assert (stored, unchanged, no_subtitle, failed) == expected_counts, (
+        f"the part line's outcome {outcome!r} disagrees with its counts"
+    )
+    assert stored + unchanged + no_subtitle + failed == attempted, (
+        "the four outcome counts partition the attempted parts"
+    )
+    assert summary["run_id"], "the summary line names the persisted run"
+
     return HarvestOutput(
         run_id=summary["run_id"],
         work_id=groups["work_id"],
@@ -443,11 +529,11 @@ def _read_harvest_output(
         version=(
             int(groups["version"]) if groups.get("version") is not None else None
         ),
-        attempted=int(summary["attempted"]),
-        stored=int(summary["stored"]),
-        unchanged=int(summary["unchanged"]),
-        no_subtitle=int(summary["no_subtitle"]),
-        failed=int(summary["failed"]),
+        attempted=attempted,
+        stored=stored,
+        unchanged=unchanged,
+        no_subtitle=no_subtitle,
+        failed=failed,
         remaining_without_transcript=int(summary["remaining"]),
     )
 
@@ -499,7 +585,10 @@ def _assert_one_pending_part(connection: sqlite3.Connection) -> None:
 
 
 def _assert_stored_rows(
-    connection: sqlite3.Connection, *, expect_credential_present: bool
+    connection: sqlite3.Connection,
+    *,
+    run_id: str,
+    expect_credential_present: bool,
 ) -> str:
     """Assert one bounded harvest stored one transcript version; render evidence.
 
@@ -508,8 +597,10 @@ def _assert_stored_rows(
     its language and version, its ordered segments, the one run row carrying the
     operator's selector and the credential presence, the one attempt row
     pointing at the stored transcript, and a part that left the pending
-    enumeration.  The returned line carries counts only: no segment text, no
-    upstream value, no credential.
+    enumeration.  ``run_id`` is the id the command printed on its summary line,
+    and it is asserted against the persisted row — the evidence line's
+    ``run_id`` is therefore tied to its source (QC2-009/Q3-03).  The returned
+    line carries counts only: no segment text, no upstream value, no credential.
     """
 
     transcripts = list(
@@ -554,6 +645,9 @@ def _assert_stored_rows(
     runs = list(connection.execute("SELECT * FROM acquisition_runs"))
     assert len(runs) == 1, "the bounded run opens exactly one run row"
     run = runs[0]
+    assert run["run_id"] == run_id, (
+        "the printed run id is the persisted run row's own id"
+    )
     assert (
         run["kind"],
         run["selector_kind"],
@@ -595,6 +689,7 @@ def _assert_stored_rows(
 def _assert_no_transcript_rows(
     connection: sqlite3.Connection,
     *,
+    run_id: str,
     outcome: str,
     expect_credential_present: bool,
 ) -> str:
@@ -605,7 +700,9 @@ def _assert_no_transcript_rows(
     row carries).  The transcript tables stay empty, the one part stays in the
     pending enumeration with its timestamped attempt evidence, and the run row is
     terminal with the outcome derived from its attempts — so the run never reads
-    as a success it did not have.
+    as a success it did not have.  ``run_id`` is the id the command printed on
+    its summary line, asserted against the persisted row, so the evidence line's
+    ``run_id`` is tied to its source (QC2-009/Q3-03).
     """
 
     assert outcome in ("no-subtitle", "failed")
@@ -635,6 +732,9 @@ def _assert_no_transcript_rows(
     runs = list(connection.execute("SELECT * FROM acquisition_runs"))
     assert len(runs) == 1
     run = runs[0]
+    assert run["run_id"] == run_id, (
+        "the printed run id is the persisted run row's own id"
+    )
     expected_run_outcome = "failed" if outcome == "failed" else "complete"
     assert (run["outcome"], run["credential_present"]) == (
         expected_run_outcome,
@@ -741,13 +841,9 @@ def test_live_smoke_one_part_through_probe_and_harvest(
     loud.
     """
 
-    if not _live_smoke_requested():
-        pytest.skip(
-            f"live subtitle CLI smoke is opt-in: set {LIVE_SMOKE_ENV}=1 to"
-            " request it"
-        )
-
-    assert _pinned_package_version() == PINNED_PACKAGE_VERSION
+    # Opt in, the pinned distribution, the credential — in that order, and the
+    # credential one is loud (see :func:`_live_preconditions`).
+    _live_preconditions()
 
     credential = os.environ.get(SESSDATA_ENV_VAR)
     expect_credential_present = _credential_expectation()
@@ -767,6 +863,12 @@ def test_live_smoke_one_part_through_probe_and_harvest(
     probe = _read_probe_output(
         probe_out, expect_credential_present=expect_credential_present
     )
+    # The probe's stdout is the one surface that renders an upstream free-text
+    # field (the track label, printed as metadata), so the sentinel scan covers
+    # stdout as well as stderr here — a signed URL or a raw body arriving
+    # through that field fails the smoke instead of passing unnoticed
+    # (QC2-004/Q3-02).
+    assert_leaks_no_markers(probe_out + probe_err, context="live probe output")
     if probe.error_code is not None:
         # Nothing answered the listing, so the harvest's calls would be spent on
         # a part no listing exists for.  The probe's own reading is recorded
@@ -803,8 +905,13 @@ def test_live_smoke_one_part_through_probe_and_harvest(
             assert harvest_exit == 0, harvest_err
             assert (harvest.failed, harvest.no_subtitle) == (0, 0)
             assert harvest.remaining_without_transcript == 0
+            assert (harvest.stored, harvest.unchanged) == (
+                (1, 0) if harvest.outcome == "stored" else (0, 1)
+            ), "the one-part run's stored/unchanged counts follow its outcome"
             evidence = _assert_stored_rows(
-                connection, expect_credential_present=expect_credential_present
+                connection,
+                run_id=harvest.run_id,
+                expect_credential_present=expect_credential_present,
             )
         else:
             if harvest.outcome == "no-subtitle":
@@ -823,6 +930,7 @@ def test_live_smoke_one_part_through_probe_and_harvest(
             assert harvest.remaining_without_transcript == 1
             evidence = _assert_no_transcript_rows(
                 connection,
+                run_id=harvest.run_id,
                 outcome=harvest.outcome,
                 expect_credential_present=expect_credential_present,
             )
@@ -941,6 +1049,48 @@ def test_the_live_smoke_switch_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> Non
     assert _live_smoke_requested() is True
 
 
+def test_the_live_preconditions_gate_in_the_documented_order(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """Default skips; opted in without a credential fails loudly; else it runs.
+
+    The three preconditions are the live smoke's own preamble, so driving them
+    offline is what keeps the live body from resting on a single recorded run.
+    The order matters twice over: the opt-in gate comes first, so a default
+    pytest run skips without a credential *or* the pinned distribution; and past
+    that gate a missing credential is a failure rather than a skip, because the
+    smoke derives its expectation from the same environment the command reads —
+    an anonymous run answers ``sessdata=absent`` with no visible tracks, which is
+    exactly what a login-gated caption looks like (QC2-009/Q3-03).
+    """
+
+    # Default: not opted in, so the skip is decided before anything else — no
+    # credential and no pinned distribution are needed.
+    monkeypatch.delenv(LIVE_SMOKE_ENV, raising=False)
+    monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)
+    with pytest.raises(pytest.skip.Exception) as skipped:
+        _live_preconditions()
+    assert f"{LIVE_SMOKE_ENV}=1" in str(skipped.value)
+
+    # Opted in, no credential: loud, and by a plain ``fail`` rather than a
+    # ``skip`` — a skip here is the hazard this guard exists to remove.
+    monkeypatch.setenv(LIVE_SMOKE_ENV, "1")
+    with pytest.raises(pytest.fail.Exception) as refused:
+        _live_preconditions()
+    assert SESSDATA_ENV_VAR in str(refused.value)
+    assert "benign skip" in str(refused.value)
+
+    # A blank value means anonymous by the shipped rule, so it is refused too.
+    monkeypatch.setenv(SESSDATA_ENV_VAR, "")
+    with pytest.raises(pytest.fail.Exception):
+        _live_preconditions()
+
+    # A resolvable credential is the only shape that gets through.
+    monkeypatch.setenv(SESSDATA_ENV_VAR, SESSDATA_BOUNDARY_VALUE)
+    assert _credential_expectation() is True
+    assert _live_preconditions() is None
+
+
 def test_the_seeded_root_survives_the_probe_with_no_new_file(
     tmp_root: str,
     anonymous_environment,
@@ -986,6 +1136,53 @@ def test_the_seeded_root_survives_the_probe_with_no_new_file(
         )
 
 
+def test_the_probe_surface_scan_catches_a_sentinel_arriving_as_a_track_label(
+    tmp_root: str,
+    anonymous_environment,
+    capsys: pytest.CaptureFixture[str],
+    fake_gateway_seam: FakeGateway,
+) -> None:
+    """The probe's stdout is scanned, and the scan can really fire there.
+
+    The track label is the one upstream free-text value this CLI prints (as
+    metadata, on the documented ``track <lan> <ai|cc> <label>`` line), so the
+    scan that guards every other surface has to be shown to work on this one
+    rather than assumed.  The leak scripted here is the shape that field would
+    produce — a signed document URL echoed as the label, which is what reading
+    the wrong upstream field looks like — and the scan catches it (QC2-004).
+    """
+
+    _seed_probe_part(tmp_root)
+    fake_gateway_seam.script_subtitle_tracks(
+        SAMPLE_CID,
+        (
+            SubtitleTrack(
+                language="ai-zh",
+                label=SIGNED_SUBTITLE_URL_MARKER,
+                is_ai=True,
+                track_id="1",
+            ),
+        ),
+    )
+
+    assert main(_probe_argv(tmp_root)) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    probe = _read_probe_output(out, expect_credential_present=False)
+    assert probe.tracks == (("ai-zh", "ai"),)
+    assert SIGNED_SUBTITLE_URL_MARKER in out, (
+        "the label is printed as metadata, which is why it is scanned"
+    )
+    with pytest.raises(AssertionError):
+        assert_leaks_no_markers(out + err, context="probe rehearsal output")
+    # And the scan stays silent on the benign surface, so it is not a
+    # formality that fires on every run:
+    assert_leaks_no_markers(
+        out.replace(SIGNED_SUBTITLE_URL_MARKER, "自动生成"),
+        context="probe rehearsal output without the sentinel",
+    )
+
+
 def test_the_seam_rehearsal_stores_a_transcript_and_passes_every_row_assertion(
     tmp_root: str,
     anonymous_environment,
@@ -1025,7 +1222,11 @@ def test_the_seam_rehearsal_stores_a_transcript_and_passes_every_row_assertion(
     assert harvest.run_id, "the summary names the persisted run"
 
     with _archive_connection(tmp_root) as connection:
-        evidence = _assert_stored_rows(connection, expect_credential_present=False)
+        evidence = _assert_stored_rows(
+            connection,
+            run_id=harvest.run_id,
+            expect_credential_present=False,
+        )
         persisted = persisted_row_text(connection)
     assert evidence == (
         "source_kind=subtitle-ai language=ai-zh version=1 segments=2"
@@ -1076,6 +1277,7 @@ def test_a_captionless_part_is_recorded_and_never_reads_green(
     with _archive_connection(tmp_root) as connection:
         evidence = _assert_no_transcript_rows(
             connection,
+            run_id=harvest.run_id,
             outcome="no-subtitle",
             expect_credential_present=False,
         )
@@ -1112,7 +1314,10 @@ def test_a_failed_harvest_is_recorded_with_its_bounded_code(
 
     with _archive_connection(tmp_root) as connection:
         evidence = _assert_no_transcript_rows(
-            connection, outcome="failed", expect_credential_present=False
+            connection,
+            run_id=harvest.run_id,
+            outcome="failed",
+            expect_credential_present=False,
         )
     assert evidence == "outcome=failed transcripts=0 attempts=1 pending_after=1"
     assert_leaks_no_markers(out + err, context="rehearsal failed-harvest output")
@@ -1184,7 +1389,10 @@ def test_a_refused_listing_is_read_from_the_probe_and_never_harvested(
     )
     with _archive_connection(refused_root) as connection:
         _assert_no_transcript_rows(
-            connection, outcome="no-subtitle", expect_credential_present=False
+            connection,
+            run_id=harvested.run_id,
+            outcome="no-subtitle",
+            expect_credential_present=False,
         )
 
 
diff --git a/bilibili-asr-archive/tests/test_subtitle_cli.py b/bilibili-asr-archive/tests/test_subtitle_cli.py
index f3eed4a..758c69c 100644
--- a/bilibili-asr-archive/tests/test_subtitle_cli.py
+++ b/bilibili-asr-archive/tests/test_subtitle_cli.py
@@ -21,6 +21,7 @@ from __future__ import annotations
 from contextlib import contextmanager
 import os
 import sqlite3
+from pathlib import Path
 
 import pytest
 
@@ -43,6 +44,7 @@ from bili_asr.storage import MetadataRepository, open_database
 from bili_asr.storage.models import (
     ALLOWED_ACQUISITION_KINDS,
     ALLOWED_CAPTION_SOURCE_KINDS,
+    MAX_TIMELINE_MS,
 )
 from fixtures.fake_bilibili_gateway import (
     SESSDATA_BOUNDARY_VALUE,
@@ -223,8 +225,16 @@ def _exit_code(argv: list[str]) -> int:
         ["probe-subs", "--limit-parts", "0"],
         ["probe-subs", "--limit-parts", "-2"],
         ["probe-subs", "--limit-parts", "not-a-number"],
+        # A selector the archive cannot store names no part in any database, so it
+        # is the documented configuration error (exit 1) exactly like an unknown
+        # bvid — never the unexpected-internal-error exit 2 (F-001).
+        ["probe-subs", "--bvid", ""],
+        ["probe-subs", "--bvid", "   "],
+        ["probe-subs", "--bvid", f"{BVID_A}\x00"],
         ["harvest-subs"],
         ["harvest-subs", "--bvid", BVID_A],
+        ["harvest-subs", "--bvid", "  ", "--limit-parts", "2"],
+        ["harvest-subs", "--bvid", f"{BVID_A}\np0", "--limit-parts", "2"],
         ["harvest-subs", "--limit-parts", "0"],
         ["harvest-subs", "--limit-parts", "2", "--language", "ai-zh,"],
         ["harvest-subs", "--limit-parts", "2", "--language", ""],
@@ -241,6 +251,90 @@ def test_subtitle_usage_errors_exit_one_never_two(
     assert captured.err.strip()
 
 
+@pytest.mark.parametrize(
+    "value",
+    ["", " ", "   ", "\t", f"{BVID_A}\x00", f"{BVID_A}\n", f"  {BVID_A}\x00  "],
+)
+def test_an_unstorable_bvid_is_answered_as_unknown_bvid(
+    tmp_root: str, capsys, install_gateway, value: str
+) -> None:
+    """A blank/control-character selector is ``unknown --bvid <value>``, exit 1.
+
+    The archive stores ``bvid`` values through the storage contract's identifier
+    rule, which rejects a value that is empty once stripped and one carrying a
+    control character, so no database can hold the part such a selector names.
+    Both commands therefore answer it with the documented configuration error —
+    byte for byte, on stderr, with nothing on stdout — instead of reaching the
+    repository, whose own validation would surface as an unexpected internal
+    error with exit 2 (F-001).
+    """
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
+
+    for command, argv in (
+        ("probe-subs", ["probe-subs", "--bvid", value, "--archive-root", tmp_root]),
+        (
+            "harvest-subs",
+            [
+                "harvest-subs",
+                "--bvid",
+                value,
+                "--limit-parts",
+                "2",
+                "--archive-root",
+                tmp_root,
+            ],
+        ),
+    ):
+        assert _exit_code(argv) == 1
+        captured = capsys.readouterr()
+        assert captured.out == ""
+        assert captured.err == f"{command}: unknown --bvid {value}\n"
+        if command == "probe-subs":
+            assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME], (
+                "the read-only probe leaves no file at all"
+            )
+
+    # Configuration, decided before any call and before any run row.  The writer
+    # lock of the failing harvest is the one file this exits-1 path adds: it is
+    # taken by main() before the handler runs, which the docs state.
+    assert gateway.listing_cids == []
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_runs") == 0
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_attempts") == 0
+    assert _archive_files(tmp_root) == sorted(
+        [ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH]
+    )
+
+
+def test_an_unstorable_bvid_outranks_the_missing_database_guard(
+    tmp_root: str, capsys
+) -> None:
+    """The selector check is decided on the argument, before the database guard.
+
+    ``--bvid ""`` names no part in any database, so the operator is told that —
+    even on a root that holds no ``archive.db`` yet — instead of being sent to
+    ``fetch-meta`` for a selector ``fetch-meta`` could never satisfy either.
+    A padded-but-addressable value is deliberately *not* rejected: it reaches the
+    database and is answered as an unknown bvid there, because the storage rule
+    can hold it.
+    """
+
+    root = os.path.join(tmp_root, "absent")
+    assert main(["probe-subs", "--bvid", "", "--archive-root", root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err == "probe-subs: unknown --bvid \n"
+    assert not os.path.exists(root), "still nothing created on a read command"
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    padded = f" {BVID_A} "
+    assert main(["probe-subs", "--bvid", padded, "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err == f"probe-subs: unknown --bvid {padded}\n"
+
+
 def test_probe_subs_requires_exactly_one_selector(tmp_root: str, capsys) -> None:
     """Neither selector, and both selectors, are the same usage error."""
 
@@ -409,6 +503,42 @@ def test_default_preference_ranks_known_families_then_falls_back_to_upstream_ord
     assert select_subtitle_track(()) is None
 
 
+def test_the_cc_before_ai_preference_decides_across_two_rest_families() -> None:
+    """The corner the prose used to mis-state: a CC/AI pair in distinct families.
+
+    ``_family_rank`` collapses every family outside ``zh``/``en`` onto one rank,
+    so the CC-before-AI term is family-blind there: a later French uploader
+    caption beats an earlier Japanese machine one, even though the machine track
+    comes first upstream.  The ranking key is the locked spec's, so this pins the
+    shipped reading; ``test_default_preference_ranks_known_families_then_falls_back_to_upstream_order``
+    covers the equal-kind direction and this covers the cross-family one
+    (Q3-01).  Neither track is ``zh``/``en`` and neither kind repeats, so the
+    family rank and the upstream index each disagree with the outcome on their
+    own — the CC/AI term is the only one that produces it.
+    """
+
+    japanese_ai = SubtitleTrack(
+        language="ai-ja", label="日本語（自動生成）", is_ai=True, track_id="1"
+    )
+    french_cc = SubtitleTrack(
+        language="fr", label="Français", is_ai=False, track_id=None
+    )
+
+    assert select_subtitle_track((japanese_ai, french_cc)) is french_cc, (
+        "across two rest-families the uploader caption wins, wherever it sits"
+    )
+    assert select_subtitle_track((french_cc, japanese_ai)) is french_cc, (
+        "the CC/AI term is family-blind, so upstream order does not move it"
+    )
+
+    other_french = SubtitleTrack(
+        language="fr-CA", label="Français (CA)", is_ai=False, track_id=None
+    )
+    assert (
+        select_subtitle_track((japanese_ai, french_cc, other_french)) is french_cc
+    ), "same family and same kind: upstream order settles that tie"
+
+
 def test_explicit_language_matches_exactly_and_first_preference_wins() -> None:
     """``--language`` order decides; a code nothing matches yields no track."""
 
@@ -933,27 +1063,140 @@ def test_not_found_is_recorded_no_subtitle_with_its_code(
 def test_partial_failure_keeps_exit_zero_and_stays_visible_in_the_counts(
     tmp_root: str, capsys, install_gateway
 ) -> None:
-    """One stored and one failed part is a partial run, not a terminal failure."""
+    """The failing part comes *first*: the loop continues into a later success.
+
+    The order is the point.  With the failure last (the direction the E2E scripts
+    it) a regression that aborted the loop on the first non-stored outcome would
+    still read green here, so this case scripts the failure on the first part and
+    asserts that the part after it was really attempted, really stored, and really
+    counted — one part's failure does not end a bounded run (QC2-001).
+    """
 
     _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
-    install_gateway(
+    gateway = install_gateway(
         tracks={101: (CC_ZH,), 102: (CC_ZH,)},
-        segments={101: BODY},
-        listing_failures={102: GatewayRateLimited()},
+        segments={102: BODY},
+        listing_failures={101: GatewayRateLimited()},
     )
 
     assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0
 
     captured = capsys.readouterr()
-    assert "attempted=2 stored=1 unchanged=0 no-subtitle=0 failed=1" in captured.out
-    assert captured.out.splitlines()[2] == (
-        f"harvest {BVID_A}:p1 failed rate_limited"
+    assert_leaks_no_markers(captured.out + captured.err, context="partial-run output")
+    with _archive_connection(tmp_root) as connection:
+        run = connection.execute(
+            "SELECT run_id, outcome FROM acquisition_runs"
+        ).fetchone()
+        assert captured.out.splitlines() == [
+            "sessdata: absent",
+            f"harvest {BVID_A}:p0 failed rate_limited",
+            f"harvest {BVID_A}:p1 stored subtitle-cc zh-CN v1",
+            f"harvest-subs: run_id={run['run_id']} attempted=2 stored=1"
+            " unchanged=0 no-subtitle=0 failed=1 remaining_without_transcript=1",
+        ]
+        # Both parts were attempted, in selection order, and only the part after
+        # the failure fetched a body.
+        assert gateway.listing_cids == [101, 102]
+        assert gateway.body_cids == [102]
+        # The later part's own evidence: the stored transcript is p1's, and the
+        # two attempts are the failed one and the stored one, in part order.
+        stored = connection.execute(
+            "SELECT vp.cid, vp.page_index, t.source_kind, t.language, t.version"
+            " FROM transcripts AS t JOIN video_parts AS vp"
+            " ON vp.video_part_id = t.video_part_id"
+        ).fetchone()
+        assert (stored["cid"], stored["page_index"]) == (102, 1)
+        assert (
+            stored["source_kind"],
+            stored["language"],
+            stored["version"],
+        ) == ("subtitle-cc", "zh-CN", 1)
+        assert [
+            (row["outcome"], row["error_code"], row["transcript_id"] is not None)
+            for row in connection.execute(
+                "SELECT a.outcome, a.error_code, a.transcript_id"
+                " FROM acquisition_attempts AS a"
+                " JOIN video_parts AS vp ON vp.video_part_id = a.video_part_id"
+                " ORDER BY vp.page_index"
+            )
+        ] == [("failed", "rate_limited", False), ("stored", None, True)]
+        assert run["outcome"] == "partial"
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 1
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcript_segments") == 2
+
+
+def test_a_body_the_storage_boundary_refuses_is_one_parts_bounded_failure(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """A pathological timeline cannot abort the whole bounded run (QC2-002).
+
+    The gateway script is the seam, so the scripted segment is exactly what a
+    finite-but-absurd upstream ``to`` produces: a millisecond position above the
+    storage contract's caption range (``MAX_TIMELINE_MS``).  The storage boundary
+    rejects it with its bounded ``ValueError``, and that rejection is answered as
+    *this part's* ``failed``/``shape_error`` attempt — so the part after it is
+    still attempted and stored, and the run stays exit 0 with the partial counts
+    instead of collapsing into ``<command>: unexpected error`` with exit 2.
+    """
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
+    gateway = install_gateway(
+        tracks={101: (CC_ZH,), 102: (CC_ZH,)},
+        segments={
+            101: (
+                SubtitleSegment(
+                    start_ms=0, end_ms=MAX_TIMELINE_MS + 1, text="越界的一句"
+                ),
+            ),
+            102: BODY,
+        },
     )
+
+    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert captured.err == ""
+    assert_leaks_no_markers(captured.out, context="pathological-timeline output")
     with _archive_connection(tmp_root) as connection:
+        run = connection.execute(
+            "SELECT run_id, outcome FROM acquisition_runs"
+        ).fetchone()
+        assert captured.out.splitlines() == [
+            "sessdata: absent",
+            f"harvest {BVID_A}:p0 failed shape_error",
+            f"harvest {BVID_A}:p1 stored subtitle-cc zh-CN v1",
+            f"harvest-subs: run_id={run['run_id']} attempted=2 stored=1"
+            " unchanged=0 no-subtitle=0 failed=1 remaining_without_transcript=1",
+        ]
+        assert gateway.listing_cids == [101, 102]
+        assert gateway.body_cids == [101, 102]
+        assert [
+            (row["outcome"], row["error_code"], row["transcript_id"] is not None)
+            for row in connection.execute(
+                "SELECT a.outcome, a.error_code, a.transcript_id"
+                " FROM acquisition_attempts AS a"
+                " JOIN video_parts AS vp ON vp.video_part_id = a.video_part_id"
+                " ORDER BY vp.page_index"
+            )
+        ] == [("failed", "shape_error", False), ("stored", None, True)]
+        assert run["outcome"] == "partial"
+        # The refused part stored nothing at all: no transcript, no segment, and
+        # the part stays pending for a later attempt.
+        assert [
+            (row["cid"], row["version"])
+            for row in connection.execute(
+                "SELECT vp.cid, t.version FROM transcripts AS t"
+                " JOIN video_parts AS vp ON vp.video_part_id = t.video_part_id"
+            )
+        ] == [(102, 1)]
+        stored_part = connection.execute(
+            "SELECT video_part_id FROM transcripts"
+        ).fetchone()[0]
         assert connection.execute(
-            "SELECT outcome FROM acquisition_runs"
-        ).fetchone()[0] == "partial"
-    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 1
+            "SELECT COUNT(*) FROM transcript_segments WHERE transcript_id IN"
+            " (SELECT transcript_id FROM transcripts WHERE video_part_id = ?)",
+            (stored_part,),
+        ).fetchone()[0] == len(BODY)
 
 
 def test_unexpected_error_exits_two_finishes_the_run_and_leaks_nothing(
@@ -1020,6 +1263,71 @@ def test_credential_is_reported_as_presence_only(
     assert captured.out.splitlines()[0] == "sessdata: absent"
 
 
+def test_the_probe_opens_the_archive_read_only_and_cannot_write(
+    tmp_root: str, capsys, install_gateway, monkeypatch
+) -> None:
+    """The probe's ``mode=ro`` connection is write-proof, not just well-behaved.
+
+    ``probe-subs`` promises it writes nothing at all, and that promise used to
+    hold only because the probe happened to call no write: it opened the same
+    schema-initializing connection as ``status``/``runs``, and ``open_database``
+    executes both idempotent schema scripts and commits them.  The connection the
+    probe now opens is asserted here (the URI it asks SQLite for) and then used
+    directly, so the "cannot write" claim is functional rather than conventional
+    (QC2-003).
+    """
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    install_gateway(tracks={101: (CC_ZH,)})
+
+    real_connect = sqlite3.connect
+    opened: list[tuple[tuple, dict]] = []
+
+    def recording_connect(*args, **kwargs):
+        opened.append((args, kwargs))
+        return real_connect(*args, **kwargs)
+
+    monkeypatch.setattr(sqlite3, "connect", recording_connect)
+    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+
+    assert len(opened) == 1, "the probe opens exactly one connection"
+    arguments, keywords = opened[0]
+    uri = arguments[0]
+    assert keywords == {"uri": True}
+    assert uri == (
+        Path(os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)).resolve().as_uri()
+        + "?mode=ro"
+    )
+
+    # The URI the probe used is really write-proof: neither DDL nor DML succeeds
+    # through it, so a later edit on the probe path cannot silently write.
+    read_only = real_connect(uri, uri=True)
+    try:
+        for statement in (
+            "CREATE TABLE probe_must_not_create(x INTEGER)",
+            "DELETE FROM transcripts",
+            "INSERT INTO acquisition_runs(run_id, kind, selector_kind,"
+            " selector_target, requested_limit, credential_present, started_at,"
+            " finished_at, outcome) VALUES ('x', 'subtitle', 'pending', NULL, 1,"
+            " 0, 0, NULL, 'running')",
+        ):
+            with pytest.raises(sqlite3.OperationalError):
+                read_only.execute(statement)
+    finally:
+        read_only.close()
+
+    # And every observable of the probe run is unchanged: one file, no rows.
+    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
+    for table in (
+        "acquisition_runs",
+        "acquisition_attempts",
+        "transcripts",
+        "transcript_segments",
+    ):
+        assert _scalar(tmp_root, f"SELECT COUNT(*) FROM {table}") == 0
+
+
 def test_neither_command_writes_a_sidecar_or_a_transcript_projection(
     tmp_root: str, capsys, install_gateway
 ) -> None:
```
