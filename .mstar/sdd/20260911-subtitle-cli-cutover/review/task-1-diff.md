# Task 1 Diff — 20260911-subtitle-cli-cutover

Base: `c5a9b82`
Head: `8ec992b`

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/cli.py b/bilibili-asr-archive/src/bili_asr/cli.py
index e11885f..017a0a5 100644
--- a/bilibili-asr-archive/src/bili_asr/cli.py
+++ b/bilibili-asr-archive/src/bili_asr/cli.py
@@ -119,25 +119,43 @@ def build_parser() -> argparse.ArgumentParser:
     )
 
     probe = subparsers.add_parser(
-        "probe-subs", help="Probe the subtitle list for one video (no download)"
+        "probe-subs",
+        help="List the subtitle tracks the selected archive parts expose (read-only)",
+    )
+    probe.add_argument(
+        "--bvid", default=None,
+        help="Bvid, or bvid:pN for one part, already in the archive database",
+    )
+    probe.add_argument(
+        "--limit-parts", type=int, default=None,
+        help="Probe the first N parts of the pending enumeration",
     )
-    probe.add_argument("--bvid", required=True, help="Bvid to probe")
     probe.add_argument(
         "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
         help="Archive root directory (default: ./archive)",
     )
     probe.add_argument(
         "--sessdata", default=None,
-        help="SESSDATA cookie for Path B (or env BILI_SESSDATA); not stored",
+        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
     )
 
     harvest = subparsers.add_parser(
-        "harvest-subs", help="Probe + download subtitles for pending manifest videos"
+        "harvest-subs",
+        help="Acquire subtitles for the selected archive parts as transcripts",
     )
     harvest.add_argument(
         "--bvid", default=None,
-        help="Restrict to a bvid or work_id (bvid:pN); STOP if unresolved "
-             "or multi-part without an explicit page",
+        help="Bvid, or bvid:pN for one part, already in the archive database "
+             "(parts that already have a transcript included)",
+    )
+    harvest.add_argument(
+        "--limit-parts", type=int, default=None,
+        help="Bound the run to N parts (required unless a single bvid:pN is named)",
+    )
+    harvest.add_argument(
+        "--language", default=None,
+        help="Comma-separated upstream language codes, first match wins "
+             "(default: the zh family, then en, CC before AI)",
     )
     harvest.add_argument(
         "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
@@ -145,11 +163,7 @@ def build_parser() -> argparse.ArgumentParser:
     )
     harvest.add_argument(
         "--sessdata", default=None,
-        help="SESSDATA cookie for Path B (or env BILI_SESSDATA); not stored",
-    )
-    harvest.add_argument(
-        "--limit", type=int, default=None,
-        help="Stop after N videos (smoke runs)",
+        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
     )
 
     dl = subparsers.add_parser(
@@ -485,17 +499,15 @@ def _metadata_database_path(archive_root: str) -> str:
     return os.path.join(archive_root, ARCHIVE_DATABASE_NAME)
 
 
-def _open_read_repository(
-    command: str, archive_root: str
-) -> "MetadataRepository | None":
+def _open_read_connection(command: str, archive_root: str):
     """Open the fresh database for a read command; None after printing why not.
 
-    Read commands never create the database: a missing file is the
-    documented configuration error (exit 1), and an unreadable file is
-    reported bounded without raw SQLite text.  The caller owns the open
-    connection and closes it when the command finishes.
+    Read commands never create the database: a missing file is the documented
+    configuration error (exit 1), and an unreadable file is reported bounded
+    without raw SQLite text.  The caller owns the returned connection and closes
+    it when the command finishes.
     """
-    from bili_asr.storage import MetadataRepository, open_database
+    from bili_asr.storage import open_database
 
     if not os.path.isfile(_metadata_database_path(archive_root)):
         print(
@@ -505,7 +517,7 @@ def _open_read_repository(
         )
         return None
     try:
-        connection = open_database(archive_root)
+        return open_database(archive_root)
     except (OSError, sqlite3.Error) as exc:
         print(
             f"{command}: unreadable archive database at {archive_root} "
@@ -513,9 +525,81 @@ def _open_read_repository(
             file=sys.stderr,
         )
         return None
+
+
+def _open_read_repository(
+    command: str, archive_root: str
+) -> "MetadataRepository | None":
+    """Open the fresh database for a read command and wrap it in the repository.
+
+    ``None`` means :func:`_open_read_connection` already reported the reason.
+    """
+    from bili_asr.storage import MetadataRepository
+
+    connection = _open_read_connection(command, archive_root)
+    if connection is None:
+        return None
     return MetadataRepository(connection)
 
 
+def _subtitle_schema_rebuild_line(command: str, archive_root: str) -> str:
+    """Compose the fixed rebuild line for a pre-iteration archive database.
+
+    ``SchemaContractError`` carries the reason and the procedure only — it holds
+    a connection, never an archive root — so the command prefix and the actual
+    database path are composed here, and the printed line carries both.
+    """
+    return (
+        f"{command}: archive database predates the transcript schema; "
+        f"rebuild it (delete {_metadata_database_path(archive_root)} "
+        "and re-run fetch-meta)"
+    )
+
+
+def _open_subtitle_connection(command: str, archive_root: str):
+    """Open the archive database for one subtitle command; None after printing.
+
+    Neither subtitle command creates ``archive.db`` (``open_database`` does), so
+    the file is checked before opening through the shipped read-command guard,
+    and the transcript-schema capability is required immediately after opening:
+    a database that predates the contract is answered with the fixed rebuild line
+    and exit 1 instead of a raw SQLite error from the first transcript query.
+    """
+    from bili_asr.storage import SchemaContractError, require_subtitle_schema
+
+    connection = _open_read_connection(command, archive_root)
+    if connection is None:
+        return None
+    try:
+        require_subtitle_schema(connection)
+    except SchemaContractError:
+        connection.close()
+        print(
+            _subtitle_schema_rebuild_line(command, archive_root), file=sys.stderr
+        )
+        return None
+    return connection
+
+
+def _subtitle_selector(value: str | None) -> tuple[str | None, int | None]:
+    """Split an optional ``--bvid`` value into ``(bvid, page_index)``.
+
+    The archive's own part vocabulary is accepted: a bare ``bvid`` selects every
+    stored part of that video and ``bvid:pN`` (``page_identity.parse_work_id``)
+    selects exactly that part.  A value the parser cannot read is kept verbatim
+    as a bare bvid, so the database answers no row for it and the caller reports
+    the documented ``unknown --bvid`` configuration error rather than a crash.
+    """
+    from .page_identity import parse_work_id
+
+    if value is None:
+        return None, None
+    try:
+        return parse_work_id(value)
+    except ValueError:
+        return value, None
+
+
 def _cmd_fetch_meta(args: argparse.Namespace) -> int:
     """Collect video metadata into the fresh SQLite archive database.
 
@@ -654,131 +738,183 @@ def _resolve_sessdata(args: argparse.Namespace) -> str | None:
 
 
 def _cmd_probe_subs(args: argparse.Namespace) -> int:
-    from . import bili_client, subtitles
-    from .manifest import ManifestStore
+    """List the subtitle tracks the selected parts expose, writing nothing.
+
+    Read-only by construction: ``probe-subs`` is not an archive-writer command,
+    so it takes no writer lock, creates no file below the archive root, and never
+    creates a missing database.  Exit taxonomy: 0 the probe ran (zero-track parts
+    included); 1 usage/configuration (neither or both selectors, a non-positive
+    bound, a missing database, an unknown --bvid, the schema guard); 2 the probe
+    failed on every selected part, or an unexpected internal error.  A partial
+    per-part failure stays visible in the printed ``failed=`` count.
+    """
+    from bili_asr.services.subtitle_ingest import (
+        SubtitleIngestor,
+        SubtitleSelection,
+    )
+    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
+    from bili_asr.storage import TranscriptRepository
 
+    if (args.bvid is None) == (args.limit_parts is None):
+        print(
+            "probe-subs: exactly one of --bvid / --limit-parts is required",
+            file=sys.stderr,
+        )
+        return 1
+    if args.limit_parts is not None and args.limit_parts < 1:
+        print(
+            "probe-subs: --limit-parts must be a positive integer",
+            file=sys.stderr,
+        )
+        return 1
+    bvid, page_index = _subtitle_selector(args.bvid)
     sessdata = _resolve_sessdata(args)
-    client = bili_client.BiliClient(sessdata=sessdata)
-    try:
-        entries = client.probe_subs(args.bvid)
-    except bili_client.RiskBudgetExhausted as exc:
-        print(f"probe-subs: risk-control ceiling for {args.bvid} "
-              f"(last code {exc.last_code}); retry later.", file=sys.stderr)
-        return 2
-    except bili_client.APIResponseError as exc:
-        store = ManifestStore(root=args.archive_root)
-        _record_api_error(store, args.bvid, exc.code)
-        print(f"probe-subs: API response error (code {exc.code}) for "
-              f"{args.bvid}; retry later.", file=sys.stderr)
+    connection = _open_subtitle_connection("probe-subs", args.archive_root)
+    if connection is None:
         return 1
-    except bili_client.GoneResponse as exc:
-        print(f"probe-subs: terminal API response (code {exc.code}) "
-              f"for {args.bvid}.", file=sys.stderr)
-        return 2
+    try:
+        repository = TranscriptRepository(connection)
+        if bvid is not None and not repository.list_selected_parts(bvid, page_index):
+            # A selector that resolves to no stored part is configuration, not an
+            # empty result, so the probe never reports a part-less run as a
+            # completed read.
+            print(f"probe-subs: unknown --bvid {args.bvid}", file=sys.stderr)
+            return 1
+        ingestor = SubtitleIngestor(
+            BilibiliApiGateway(sessdata=sessdata),
+            repository,
+            credential_present=sessdata is not None,
+        )
+        result = ingestor.probe(
+            SubtitleSelection(
+                bvid=bvid, page_index=page_index, limit=args.limit_parts
+            )
+        )
     except Exception:
+        # Expected gateway failures are resolved inside the service, so anything
+        # escaping is unexpected: the bounded terminal code, never a traceback.
         print("probe-subs: unexpected error", file=sys.stderr)
-        return 1
+        return 2
+    finally:
+        connection.close()
 
-    if not entries:
-        print(f"{args.bvid}: no subtitles visible at this auth tier -> "
-              f"needs_audio (run harvest-subs to record it)")
-        return 0
-    for e in entries:
-        print(f"{args.bvid}: {e.get('lan')} — {e.get('lan_doc')}")
+    print(f"sessdata: {redact_sessdata(sessdata)}")
+    for part in result.parts:
+        if part.error_code is not None:
+            print(f"probe {part.work_id} failed {part.error_code}")
+            continue
+        print(f"probe {part.work_id} tracks={len(part.tracks)}")
+        if not part.tracks:
+            print("  (no subtitles visible)")
+            continue
+        for track in part.tracks:
+            kind = "ai" if track.is_ai else "cc"
+            print(f"  track {track.language} {kind} {track.label}")
+    with_tracks = sum(1 for part in result.parts if part.tracks)
+    failed = sum(1 for part in result.parts if part.error_code is not None)
+    print(
+        f"probe-subs: probed={len(result.parts)} with_tracks={with_tracks} "
+        f"without_tracks={len(result.parts) - with_tracks - failed} "
+        f"failed={failed}"
+    )
+    if failed and failed == len(result.parts):
+        return 2
     return 0
 
 
 def _cmd_harvest_subs(args: argparse.Namespace) -> int:
-    from . import bili_client, subtitles
-    from .manifest import ManifestStore
+    """Acquire the selected parts into normalized transcripts with run evidence.
+
+    Exit taxonomy: 0 the bounded run completed — including a run whose every
+    attempted part had no visible caption, and a selection that resolved to no
+    part; 1 usage/configuration (a missing database, an unknown --bvid, a missing
+    bound, an empty --language entry, the schema guard); 2 the run failed on every
+    attempted part, or an unexpected internal error.  Partial per-part failure
+    stays visible in the printed counts rather than in the exit code.
+    """
+    from bili_asr.services.subtitle_ingest import (
+        SubtitleIngestor,
+        SubtitleSelection,
+    )
+    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
+    from bili_asr.storage import TranscriptRepository
 
-    store = ManifestStore(root=args.archive_root)
-    entries = store.load()
-    sessdata = _resolve_sessdata(args)
-    client = bili_client.BiliClient(sessdata=sessdata)
-    if args.bvid:
-        todo = _todo_for_bvid(store, args.bvid, entries)
-        if todo is None:
-            print(f"{args.bvid}: multi-part video needs an explicit page",
-                  file=sys.stderr)
-            return 1
-        if not todo:
+    languages: tuple[str, ...] = ()
+    if args.language is not None:
+        languages = tuple(entry.strip() for entry in args.language.split(","))
+        if any(not entry for entry in languages):
             print(
-                f"{args.bvid}: unresolved; not assigned to a page",
+                "harvest-subs: --language entries must not be empty",
                 file=sys.stderr,
             )
             return 1
-    else:
-        todo = [
-            (key, e) for key, e in entries.items()
-            if e.get("status") == "meta_ok" and not _is_excluded(e)
-        ]
-    if args.limit is not None:
-        todo = todo[: args.limit]
-
-    done = needs_audio = failed = 0
-    risk_interrupted = False
-    for key, entry in todo:
-        target = _identity_from_entry(entry, key)
-        label = (
-            target.work_id if hasattr(target, "work_id") else str(key)
+    if args.limit_parts is not None and args.limit_parts < 1:
+        print(
+            "harvest-subs: --limit-parts must be a positive integer",
+            file=sys.stderr,
         )
-        try:
-            status = subtitles.harvest_subtitle(
-                client, target, store, args.archive_root
+        return 1
+    bvid, page_index = _subtitle_selector(args.bvid)
+    if args.limit_parts is None and page_index is None:
+        # No unbounded runs: only a single named part is bounded by construction.
+        print(
+            "harvest-subs: --limit-parts is required unless a single bvid:pN "
+            "part is selected",
+            file=sys.stderr,
+        )
+        return 1
+    sessdata = _resolve_sessdata(args)
+    connection = _open_subtitle_connection("harvest-subs", args.archive_root)
+    if connection is None:
+        return 1
+    try:
+        repository = TranscriptRepository(connection)
+        if bvid is not None and not repository.list_selected_parts(bvid, page_index):
+            # Decided before the run is opened: an unknown selector is
+            # configuration and must not leave an empty run row behind.
+            print(f"harvest-subs: unknown --bvid {args.bvid}", file=sys.stderr)
+            return 1
+        ingestor = SubtitleIngestor(
+            BilibiliApiGateway(sessdata=sessdata),
+            repository,
+            credential_present=sessdata is not None,
+        )
+        result = ingestor.harvest(
+            SubtitleSelection(
+                bvid=bvid,
+                page_index=page_index,
+                limit=args.limit_parts,
+                languages=languages,
             )
-        except bili_client.AmbiguousPageError:
-            failed += 1
-            print(f"{label}: multi-part video needs an explicit page",
-                  file=sys.stderr)
-            continue
-        except bili_client.RiskBudgetExhausted as exc:
-            failed += 1
-            print(f"{label}: risk-control ceiling (last code {exc.last_code}); "
-                  f"stopping — re-run to resume.", file=sys.stderr)
-            risk_interrupted = True
-            break
-        except bili_client.APIResponseError as exc:
-            failed += 1
-            _record_api_error(store, key, exc.code)
-            print(f"{label}: API response error (code {exc.code}); "
-                  f"continuing.", file=sys.stderr)
-            continue
-        except bili_client.GoneResponse as exc:
-            failed += 1
-            e = dict(store.get(key) or store.get_compatible(key) or {})
-            if e.get("work_id"):
-                e["status"] = "gone"
-                store.upsert(e)
-            print(f"{label}: terminal API response (code {exc.code}); "
-                  f"marked gone.", file=sys.stderr)
-            continue
-        except ValueError as exc:
-            failed += 1
-            msg = str(exc)
-            if "missing cid" in msg or "unresolved" in msg:
-                print(f"{label}: {msg}", file=sys.stderr)
-            else:
-                print(f"{label}: unexpected error", file=sys.stderr)
-            continue
-        except Exception:
-            failed += 1
-            print(f"{label}: unexpected error", file=sys.stderr)
-            continue
-        if status == "subtitle_done":
-            done += 1
-            print(f"{label}: subtitle downloaded -> subtitle_done")
-        else:
-            needs_audio += 1
-            print(f"{label}: no subtitles -> needs_audio")
-        if key != todo[-1][0]:
-            time.sleep(3.0)
+        )
+    except Exception:
+        # The service finishes an interrupted run as failed before anything
+        # escapes, so this is the bounded terminal code with no traceback.
+        print("harvest-subs: unexpected error", file=sys.stderr)
+        return 2
+    finally:
+        connection.close()
 
-    print(f"harvest-subs: {done} subtitle_done, {needs_audio} needs_audio"
-          + (f", {failed} failed" if failed else ""))
-    if risk_interrupted:
+    print(f"sessdata: {redact_sessdata(sessdata)}")
+    for outcome in result.parts:
+        if outcome.outcome == "failed":
+            print(f"harvest {outcome.work_id} failed {outcome.error_code}")
+        elif outcome.outcome == "no-subtitle":
+            print(f"harvest {outcome.work_id} no-subtitle")
+        else:
+            print(
+                f"harvest {outcome.work_id} {outcome.outcome} "
+                f"{outcome.source_kind} {outcome.language} v{outcome.version}"
+            )
+    print(
+        f"harvest-subs: run_id={result.run_id} attempted={result.attempted} "
+        f"stored={result.stored} unchanged={result.unchanged} "
+        f"no-subtitle={result.no_subtitle} failed={result.failed} "
+        f"remaining_without_transcript={result.remaining_without_transcript}"
+    )
+    if result.attempted and result.failed == result.attempted:
         return 2
-    return 1 if failed else 0
+    return 0
 
 
 def _cmd_download_audio(args: argparse.Namespace) -> int:
@@ -2301,7 +2437,6 @@ _ARCHIVE_WRITER_COMMANDS = frozenset({
     "recover",
     "asr",
     "pilot",
-    "probe-subs",
     "harvest-subs",
     "download-audio",
     "run",
diff --git a/bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py b/bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py
new file mode 100644
index 0000000..41a2dc9
--- /dev/null
+++ b/bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py
@@ -0,0 +1,595 @@
+"""Bounded subtitle acquisition between the typed gateway and transcript storage.
+
+:class:`SubtitleIngestor` owns everything between "which parts?" and "what was
+written?": the candidate enumeration order, the track-selection preference, the
+per-part transaction boundary, the run-record lifecycle, and the outcome
+mapping.  It depends on the :class:`~bili_asr.sources.models.BilibiliGateway`
+protocol and the :class:`~bili_asr.storage.database.TranscriptRepository` only —
+never on the concrete adapter or on an upstream response dictionary.
+
+The surface is synchronous, like :class:`~bili_asr.services.metadata_ingest.MetadataIngestor`'s,
+and runs the gateway's async calls on one event loop per operation.
+
+``probe`` writes nothing at all: no run, no attempt, no transcript, no file.
+``harvest`` opens exactly one ``acquisition_runs`` row, records exactly one
+attempt row per attempted part through one repository call (one transaction per
+part), and finishes the run with the outcome derived from those attempts.
+
+Outcome mapping (one outcome per attempted part):
+
+- the listing was empty, or upstream answered ``not_found`` for the listing or
+  the body → ``no-subtitle`` (the part is not a failure; it stays eligible for a
+  later run, and the attempt row carries ``not_found`` when upstream said so);
+- the body was fetched and stored → ``stored``, or ``unchanged`` when a stored
+  version of the same identity already carries that content;
+- any other bounded gateway failure → ``failed`` with that scalar error code.
+"""
+
+from __future__ import annotations
+
+import asyncio
+from collections import Counter
+from dataclasses import dataclass
+import sqlite3
+import time
+from typing import Callable
+import uuid
+
+from bili_asr.page_identity import format_work_id
+from bili_asr.sources.models import (
+    BilibiliGateway,
+    GatewayError,
+    GatewayNotFound,
+    SubtitleSegment,
+    SubtitleTrack,
+)
+from bili_asr.storage.database import TranscriptRepository
+from bili_asr.storage.models import (
+    ALLOWED_ACQUISITION_KINDS,
+    ALLOWED_CAPTION_SOURCE_KINDS,
+    AcquisitionRunRecord,
+    TranscriptSegmentRecord,
+)
+
+#: The acquisition kind every run of this service records.
+_ACQUISITION_KIND = "subtitle"
+#: The stored source kind of one selected track, by its machine-generated flag.
+_SOURCE_KIND_BY_AI = {True: "subtitle-ai", False: "subtitle-cc"}
+#: The attempt outcomes this service records, as the storage vocabulary spells
+#: them.  ``stored``/``unchanged`` come back from the transcript write; the other
+#: two are the outcomes of an attempt that produced no transcript, and ``failed``
+#: is also the outcome a run unfinished by an unexpected error is closed with.
+_OUTCOME_STORED = "stored"
+_OUTCOME_UNCHANGED = "unchanged"
+_OUTCOME_NO_SUBTITLE = "no-subtitle"
+_OUTCOME_FAILED = "failed"
+#: The default language family order the selection preference ranks by.
+_DEFAULT_LANGUAGE_FAMILY_ORDER = ("zh", "en")
+
+
+def _now() -> int:
+    """Return the current Unix second used for all persisted clocks."""
+
+    return int(time.time())
+
+
+def _choice(value: str, field: str, allowed: frozenset[str]) -> str:
+    """Return ``value`` when the published storage vocabulary admits it.
+
+    The service derives the two vocabulary values it writes — the caption
+    ``source_kind`` of one selected track and the acquisition ``kind`` of one
+    run — instead of passing storage literals through, and validates each of them
+    against the enum the storage contract publishes.  A drift between the two
+    vocabularies therefore fails here with a bounded message instead of
+    surfacing as a SQLite ``CHECK`` violation in the middle of a run.
+    """
+
+    if value not in allowed:
+        raise ValueError(f"{field} is not part of the storage vocabulary: {value}")
+    return value
+
+
+def _caption_source_kind(is_ai: bool) -> str:
+    """Return the stored source kind of one selected track, validated."""
+
+    return _choice(
+        _SOURCE_KIND_BY_AI[is_ai], "source_kind", ALLOWED_CAPTION_SOURCE_KINDS
+    )
+
+
+def language_family(language: str, is_ai: bool) -> str:
+    """Return the language family one listed track belongs to.
+
+    Total by construction, because the gateway rejects a ``lan`` without a
+    non-empty primary subtag: an AI caption's ``ai-`` prefix is stripped and the
+    lowercase primary subtag — everything before the first ``-`` — is the
+    family.  The family is derived from the two normalized facts the track DTO
+    already guarantees (``language`` and ``is_ai``) because upstream spells the
+    same spoken language differently per caption kind (``zh-CN``, ``zh-Hans``
+    and ``zh-Hant`` for uploader captions against ``ai-zh`` for the machine
+    one), so a fixed list of codes would silently mis-rank a code upstream adds.
+    """
+
+    code = language.strip().lower()
+    if is_ai and code.startswith("ai-"):
+        code = code[3:]
+    return code.split("-", 1)[0]
+
+
+def _family_rank(family: str) -> int:
+    """Return one family's rank in the default order; the rest share the last."""
+
+    try:
+        return _DEFAULT_LANGUAGE_FAMILY_ORDER.index(family)
+    except ValueError:
+        return len(_DEFAULT_LANGUAGE_FAMILY_ORDER)
+
+
+def select_subtitle_track(
+    tracks: tuple[SubtitleTrack, ...], languages: tuple[str, ...] = ()
+) -> SubtitleTrack | None:
+    """Select exactly one track of a part, or ``None`` when none is usable.
+
+    Without ``languages`` the default preference applies: the default language
+    family order first (``zh``, then ``en``, then every other family in upstream
+    order), and inside one family an uploader caption before a machine-generated
+    one.  That is the total order ``(family rank, is_ai, upstream index)`` taken
+    at its minimum — the first track a stable sort on the same key would yield —
+    so the shipped legacy preference (AI first) is deliberately replaced and the
+    uploader caption wins whenever both are visible.
+
+    With ``languages`` each entry is matched exactly against a track's
+    ``language`` code — the code ``probe-subs`` prints — the first preference
+    that matches anything wins, and the tracks it matches are ranked the same
+    way (CC before AI, then upstream order).  ``None`` then means nothing usable
+    for any requested language was visible, never a failure.
+    """
+
+    if not tracks:
+        return None
+    if languages:
+        for preference in languages:
+            matching = [
+                (index, track)
+                for index, track in enumerate(tracks)
+                if track.language == preference
+            ]
+            if matching:
+                return min(matching, key=lambda pair: (pair[1].is_ai, pair[0]))[1]
+        return None
+    return min(
+        enumerate(tracks),
+        key=lambda pair: (
+            _family_rank(language_family(pair[1].language, pair[1].is_ai)),
+            pair[1].is_ai,
+            pair[0],
+        ),
+    )[1]
+
+
+@dataclass(frozen=True, slots=True)
+class SubtitleSelection:
+    """One bounded selection of archive parts to inspect or acquire.
+
+    ``bvid`` alone selects every part of that video already in the database
+    (including parts that already hold a transcript — that is how a caption
+    upstream has since added or revised is re-checked); ``bvid`` together with
+    ``page_index`` selects exactly that part, using the archive's own
+    ``bvid:pN`` vocabulary; ``bvid=None`` selects the pending enumeration.
+    ``limit`` bounds the selection and is required unless ``page_index`` names
+    one part, which is bounded by construction.  ``languages`` is empty for the
+    default preference and otherwise the exact preference order.
+    """
+
+    bvid: str | None = None
+    page_index: int | None = None
+    limit: int | None = None
+    languages: tuple[str, ...] = ()
+
+
+@dataclass(frozen=True, slots=True)
+class SubtitleProbePart:
+    """What one probed part exposed: its tracks, or the bounded failure code."""
+
+    work_id: str
+    tracks: tuple[SubtitleTrack, ...]
+    error_code: str | None = None
+
+
+@dataclass(frozen=True, slots=True)
+class ProbeResult:
+    """The read-only probe's evidence: credential presence and one entry per part."""
+
+    credential_present: bool
+    parts: tuple[SubtitleProbePart, ...]
+
+
+@dataclass(frozen=True, slots=True)
+class SubtitlePartOutcome:
+    """The one outcome one attempted part produced, with its bounded evidence."""
+
+    work_id: str
+    outcome: str
+    error_code: str | None
+    source_kind: str | None
+    language: str | None
+    version: int | None
+
+
+@dataclass(frozen=True, slots=True)
+class HarvestResult:
+    """One run's counting evidence: every number the summary line prints."""
+
+    run_id: str
+    attempted: int
+    stored: int
+    unchanged: int
+    no_subtitle: int
+    failed: int
+    credential_present: bool
+    remaining_without_transcript: int
+    parts: tuple[SubtitlePartOutcome, ...]
+
+
+@dataclass(frozen=True, slots=True)
+class _SubtitleWorkItem:
+    """One normalized unit of subtitle work.
+
+    The two repository selections answer two different row shapes — the pending
+    view carries ``bvid`` and ``cid``, the selected-parts view carries neither
+    ``bvid`` — so the service normalizes both into this one shape before any
+    gateway call: the gateway needs ``(bvid, cid)``, the transcript write needs
+    ``video_part_id``, and ``work_id`` is the identity every printed line uses.
+    """
+
+    work_id: str
+    bvid: str
+    cid: int
+    video_part_id: int
+
+
+def _pending_work_item(row: sqlite3.Row) -> _SubtitleWorkItem:
+    """Normalize one ``v_pending_subtitles`` row, which carries ``bvid``/``cid``."""
+
+    return _SubtitleWorkItem(
+        work_id=str(row["work_id"]),
+        bvid=str(row["bvid"]),
+        cid=int(row["cid"]),
+        video_part_id=int(row["video_part_id"]),
+    )
+
+
+def _selected_work_item(row: sqlite3.Row, bvid: str) -> _SubtitleWorkItem:
+    """Normalize one ``v_video_parts`` row of an explicit selection.
+
+    The selected-parts view carries no ``bvid`` column, so the caller's own
+    selector supplies it; the ``work_id`` the view carries is the identity the
+    row is already addressed by.
+    """
+
+    return _SubtitleWorkItem(
+        work_id=str(row["work_id"]),
+        bvid=bvid,
+        cid=int(row["cid"]),
+        video_part_id=int(row["video_part_id"]),
+    )
+
+
+def _selector(selection: SubtitleSelection) -> tuple[str, str | None]:
+    """Return the run's ``(selector_kind, selector_target)`` as selected.
+
+    The pending enumeration carries no target; an explicit selection records the
+    operator's own selector — the bare ``bvid``, or the ``bvid:pN`` part that was
+    named — so the run row says what was asked for, never more.
+    """
+
+    if selection.bvid is None:
+        return "pending", None
+    if selection.page_index is None:
+        return "bvid", selection.bvid
+    return "bvid", format_work_id(selection.bvid, selection.page_index)
+
+
+class SubtitleIngestor:
+    """Inspect and acquire one bounded selection of archive subtitle work.
+
+    ``credential_present`` is the composition root's own observation that a
+    SESSDATA was in effect for this run.  It is configuration, not a gateway
+    dependency: the run row records it so an attempt recorded without a caption
+    stays interpretable afterwards, and no display path ever carries the value.
+    ``clock`` is the run/attempt timestamp source, in Unix seconds.
+    """
+
+    def __init__(
+        self,
+        gateway: BilibiliGateway,
+        repository: TranscriptRepository,
+        *,
+        credential_present: bool = False,
+        clock: Callable[[], int] = _now,
+    ) -> None:
+        self._gateway = gateway
+        self._repository = repository
+        self._credential_present = bool(credential_present)
+        self._clock = clock
+
+    def probe(self, selection: SubtitleSelection) -> ProbeResult:
+        """List what each selected part exposes, writing nothing at all."""
+
+        parts = asyncio.run(self._probe_parts(self._candidate_items(selection)))
+        return ProbeResult(
+            credential_present=self._credential_present,
+            parts=parts,
+        )
+
+    def harvest(self, selection: SubtitleSelection) -> HarvestResult:
+        """Acquire the selected parts and record one run with its per-part evidence.
+
+        The run row is opened before the first part is attempted and finished
+        with the outcome derived from the attempts (``complete`` when nothing
+        failed, ``partial`` when failed and non-failed attempts coexist,
+        ``failed`` when every attempt failed) — including a selection that
+        resolved to no part at all, which is complete because nothing failed.  An
+        unexpected error escaping a part finishes the opened run as ``failed``
+        before it propagates, so a run is never left ``running``.
+        """
+
+        items = self._candidate_items(selection)
+        selector_kind, selector_target = _selector(selection)
+        run_id = uuid.uuid4().hex
+        self._repository.start_acquisition_run(
+            AcquisitionRunRecord(
+                run_id=run_id,
+                kind=_choice(_ACQUISITION_KIND, "kind", ALLOWED_ACQUISITION_KINDS),
+                selector_kind=selector_kind,
+                selector_target=selector_target,
+                requested_limit=selection.limit,
+                credential_present=self._credential_present,
+                started_at=self._clock(),
+            )
+        )
+        try:
+            outcomes = asyncio.run(
+                self._acquire_parts(run_id, items, selection.languages)
+            )
+        except BaseException:
+            self._finish_failed_run(run_id)
+            raise
+        self._repository.finish_acquisition_run(run_id, self._clock())
+        counts = Counter(outcome.outcome for outcome in outcomes)
+        return HarvestResult(
+            run_id=run_id,
+            attempted=len(outcomes),
+            stored=counts[_OUTCOME_STORED],
+            unchanged=counts[_OUTCOME_UNCHANGED],
+            no_subtitle=counts[_OUTCOME_NO_SUBTITLE],
+            failed=counts[_OUTCOME_FAILED],
+            credential_present=self._credential_present,
+            remaining_without_transcript=(
+                self._repository.count_pending_subtitle_parts()
+            ),
+            parts=outcomes,
+        )
+
+    def _finish_failed_run(self, run_id: str) -> None:
+        """Finish a run an unexpected error escaped, without masking that error.
+
+        The run row must never be left ``running``, and the escaping exception is
+        the bounded evidence the caller reports, so a failure to finish the row
+        is deliberately not raised over it.
+        """
+
+        try:
+            self._repository.finish_acquisition_run(
+                run_id, self._clock(), outcome=_OUTCOME_FAILED
+            )
+        except Exception:
+            pass
+
+    def _candidate_items(
+        self, selection: SubtitleSelection
+    ) -> list[_SubtitleWorkItem]:
+        """Return the selected parts in the locked enumeration order.
+
+        An explicit ``bvid`` reads ``list_selected_parts`` and keeps every stored
+        part of that video, already-transcribed ones included, bounded by
+        ``limit`` when one was given.  The pending selection reads
+        ``list_pending_subtitle_parts``: never-attempted parts before previously
+        attempted ones, oldest attempt first, so successive bounded runs advance
+        through the captionless backlog instead of re-attempting its head.
+        """
+
+        if selection.bvid is None:
+            return [
+                _pending_work_item(row)
+                for row in self._repository.list_pending_subtitle_parts(
+                    selection.limit
+                )
+            ]
+        rows = self._repository.list_selected_parts(
+            selection.bvid, selection.page_index
+        )
+        if selection.limit is not None:
+            rows = rows[: selection.limit]
+        return [_selected_work_item(row, selection.bvid) for row in rows]
+
+    async def _probe_parts(
+        self, items: list[_SubtitleWorkItem]
+    ) -> tuple[SubtitleProbePart, ...]:
+        """Probe every selected part in selection order."""
+
+        return tuple([await self._probe_part(item) for item in items])
+
+    async def _probe_part(self, item: _SubtitleWorkItem) -> SubtitleProbePart:
+        """List one part's inventory; a bounded failure keeps its code on the part."""
+
+        try:
+            tracks = await self._gateway.get_subtitle_tracks(item.bvid, item.cid)
+        except GatewayError as error:
+            return SubtitleProbePart(
+                work_id=item.work_id, tracks=(), error_code=error.code
+            )
+        return SubtitleProbePart(work_id=item.work_id, tracks=tuple(tracks))
+
+    async def _acquire_parts(
+        self,
+        run_id: str,
+        items: list[_SubtitleWorkItem],
+        languages: tuple[str, ...],
+    ) -> tuple[SubtitlePartOutcome, ...]:
+        """Acquire every selected part in selection order, one transaction each."""
+
+        return tuple(
+            [await self._acquire_part(run_id, item, languages) for item in items]
+        )
+
+    async def _acquire_part(
+        self,
+        run_id: str,
+        item: _SubtitleWorkItem,
+        languages: tuple[str, ...],
+    ) -> SubtitlePartOutcome:
+        """Acquire one part: list, select, fetch, store, record the attempt."""
+
+        started_at = self._clock()
+        try:
+            tracks = await self._gateway.get_subtitle_tracks(item.bvid, item.cid)
+        except GatewayNotFound:
+            return self._record_captionless_part(
+                run_id, item, "not_found", started_at
+            )
+        except GatewayError as error:
+            return self._record_failed_part(run_id, item, error, started_at)
+        track = select_subtitle_track(tracks, languages)
+        if track is None:
+            # Either nothing was visible or nothing matched the requested
+            # languages: no usable track for this attempt, which is never a
+            # failure and leaves the part pending for a later run.
+            return self._record_captionless_part(run_id, item, None, started_at)
+        try:
+            segments = await self._gateway.fetch_subtitle_segments(
+                track, item.bvid, item.cid
+            )
+        except GatewayNotFound:
+            return self._record_captionless_part(
+                run_id, item, "not_found", started_at
+            )
+        except GatewayError as error:
+            return self._record_failed_part(run_id, item, error, started_at)
+        return self._record_caption(run_id, item, track, segments, started_at)
+
+    def _record_caption(
+        self,
+        run_id: str,
+        item: _SubtitleWorkItem,
+        track: SubtitleTrack,
+        segments: tuple[SubtitleSegment, ...],
+        started_at: int,
+    ) -> SubtitlePartOutcome:
+        """Store one selected track's body with its attempt evidence, atomically.
+
+        The repository call is the whole per-part transaction: it appends a
+        version with its segments when the content is new, records the attempt
+        with the resulting ``stored``/``unchanged`` outcome, and commits — or
+        rolls the whole call back.  The body is converted field for field, and
+        the language is stored trimmed, so the reported language is the identity
+        the store holds.
+        """
+
+        finished_at = self._clock()
+        source_kind = _caption_source_kind(track.is_ai)
+        language = track.language.strip()
+        write = self._repository.record_acquired_transcript(
+            run_id=run_id,
+            video_part_id=item.video_part_id,
+            source_kind=source_kind,
+            language=language,
+            segments=tuple(
+                TranscriptSegmentRecord(
+                    start_ms=segment.start_ms,
+                    end_ms=segment.end_ms,
+                    text=segment.text,
+                )
+                for segment in segments
+            ),
+            started_at=started_at,
+            finished_at=finished_at,
+            created_at=finished_at,
+        )
+        return SubtitlePartOutcome(
+            work_id=item.work_id,
+            outcome=write.outcome,
+            error_code=None,
+            source_kind=source_kind,
+            language=language,
+            version=write.version,
+        )
+
+    def _record_captionless_part(
+        self,
+        run_id: str,
+        item: _SubtitleWorkItem,
+        error_code: str | None,
+        started_at: int,
+    ) -> SubtitlePartOutcome:
+        """Record one attempt that found no usable caption — never a failure.
+
+        An empty listing and a ``not_found`` answer both mean no usable caption
+        was visible for this part at this attempt; the attempt row is the whole
+        evidence (no transcript), and the part stays eligible for a later run.
+        """
+
+        self._repository.record_subtitle_attempt(
+            run_id=run_id,
+            video_part_id=item.video_part_id,
+            outcome=_OUTCOME_NO_SUBTITLE,
+            error_code=error_code,
+            started_at=started_at,
+            finished_at=self._clock(),
+        )
+        return SubtitlePartOutcome(
+            work_id=item.work_id,
+            outcome=_OUTCOME_NO_SUBTITLE,
+            error_code=error_code,
+            source_kind=None,
+            language=None,
+            version=None,
+        )
+
+    def _record_failed_part(
+        self,
+        run_id: str,
+        item: _SubtitleWorkItem,
+        error: GatewayError,
+        started_at: int,
+    ) -> SubtitlePartOutcome:
+        """Record one bounded gateway failure, with its scalar code as evidence."""
+
+        self._repository.record_subtitle_attempt(
+            run_id=run_id,
+            video_part_id=item.video_part_id,
+            outcome=_OUTCOME_FAILED,
+            error_code=error.code,
+            started_at=started_at,
+            finished_at=self._clock(),
+        )
+        return SubtitlePartOutcome(
+            work_id=item.work_id,
+            outcome=_OUTCOME_FAILED,
+            error_code=error.code,
+            source_kind=None,
+            language=None,
+            version=None,
+        )
+
+
+__all__ = [
+    "HarvestResult",
+    "ProbeResult",
+    "SubtitleIngestor",
+    "SubtitlePartOutcome",
+    "SubtitleProbePart",
+    "SubtitleSelection",
+    "language_family",
+    "select_subtitle_track",
+]
diff --git a/bilibili-asr-archive/tests/test_cli_asr.py b/bilibili-asr-archive/tests/test_cli_asr.py
index 010222f..4879c58 100644
--- a/bilibili-asr-archive/tests/test_cli_asr.py
+++ b/bilibili-asr-archive/tests/test_cli_asr.py
@@ -1,4 +1,11 @@
-"""Command-level frozen status transitions through harvest / download / asr."""
+"""Command-level frozen status transitions through download / asr.
+
+The legacy manifest states these commands start from (``needs_audio``,
+``subtitle_done``) are produced by the legacy subtitle producer
+(``subtitles.harvest_subtitle``) directly: ``harvest-subs`` moved to the SQLite
+transcript path and no longer writes the manifest, so these tests drive the
+ASR/audio path from the state a pre-cutover archive already holds.
+"""
 
 from __future__ import annotations
 
@@ -85,6 +92,26 @@ def _subtitle_transport():
     )
 
 
+def _legacy_subtitle_state(root, identity, transport) -> str:
+    """Produce the legacy manifest state the ASR/audio path still reads.
+
+    ``harvest-subs`` no longer writes the manifest — it stores normalized
+    transcripts in ``archive.db`` — so the legacy producer the pilot and
+    coordinator paths still call is driven directly here: the resulting row and
+    its raw/srt artifacts are exactly what a pre-cutover archive holds.
+    """
+    from bili_asr import subtitles
+
+    store = ManifestStore(root=root)
+    client = bc.BiliClient(
+        transport=transport,
+        sleeper=lambda _seconds: None,
+        jitter=lambda: 0.0,
+        sessdata=None,
+    )
+    return subtitles.harvest_subtitle(client, identity, store, root)
+
+
 def test_download_audio_rejects_escaped_downloader_result(tmp_root, monkeypatch, capsys):
     from bili_asr import audio
     identity = page_identity("BVescape", 0, 333, "p0")
@@ -97,7 +124,7 @@ def test_download_audio_rejects_escaped_downloader_result(tmp_root, monkeypatch,
     assert rc == 1
     assert "0 audio_ok" in captured.out
     assert ManifestStore(root=tmp_root).get(identity.work_id)["status"] == "needs_audio"
-def test_cli_audio_branch_meta_ok_needs_audio_audio_ok_archived(
+def test_cli_audio_branch_needs_audio_audio_ok_archived(
     tmp_root, monkeypatch, capsys
 ):
     identity = page_identity("BVaud", 0, 222, "p0")
@@ -112,11 +139,9 @@ def test_cli_audio_branch_meta_ok_needs_audio_audio_ok_archived(
     _patch_cli(monkeypatch)
     monkeypatch.setattr(bc, "build_default_transport", _audio_transport)
 
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
+    assert _legacy_subtitle_state(tmp_root, identity, _audio_transport()) == "needs_audio"
     captured = capsys.readouterr()
-    assert rc == 0, captured.err
-    after_harvest = ManifestStore(root=tmp_root).get(identity.work_id)
-    assert after_harvest["status"] == "needs_audio"
+    assert ManifestStore(root=tmp_root).get(identity.work_id)["status"] == "needs_audio"
 
     rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
     captured = capsys.readouterr()
@@ -136,7 +161,7 @@ def test_cli_audio_branch_meta_ok_needs_audio_audio_ok_archived(
     assert transcribe_calls == [audio_abs]
 
 
-def test_cli_subtitle_branch_meta_ok_subtitle_done_archived_skips_asr(
+def test_cli_subtitle_branch_subtitle_done_archived_skips_asr(
     tmp_root, monkeypatch, capsys
 ):
     identity = page_identity("BVsub", 0, 111, "p0")
@@ -150,9 +175,11 @@ def test_cli_subtitle_branch_meta_ok_subtitle_done_archived_skips_asr(
     monkeypatch.setattr(asr_mod, "transcribe", fake_transcribe)
     _patch_cli(monkeypatch, _subtitle_transport())
 
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    captured = capsys.readouterr()
-    assert rc == 0, captured.err
+    assert (
+        _legacy_subtitle_state(tmp_root, identity, _subtitle_transport())
+        == "subtitle_done"
+    )
+    capsys.readouterr()
     after_harvest = ManifestStore(root=tmp_root).get(identity.work_id)
     assert after_harvest["status"] == "subtitle_done"
     assert os.path.isfile(os.path.join(tmp_root, after_harvest["srt_path"]))
@@ -166,37 +193,6 @@ def test_cli_subtitle_branch_meta_ok_subtitle_done_archived_skips_asr(
     assert transcribe_calls == []
 
 
-def test_cli_harvest_risk_exhaustion_preserves_last_stable_status(
-    tmp_root, monkeypatch, capsys
-):
-    first = page_identity("BVok", 0, 111, "p0")
-    second = page_identity("BVrisk", 0, 222, "p0")
-    store = ManifestStore(root=tmp_root)
-    store.upsert(_row(first, title="stable"))
-    store.upsert(_row(second, title="risk"))
-
-    risk = (412, {"code": -412, "message": "request too frequent"})
-    transport = RouterTransport(
-        {
-            "finger/spi": [SPI_OK] * 8,
-            "nav": [nav_ok()],
-            "player/wbi/v2": [player_ok([sub_entry()])] + [risk] * 8,
-            "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
-        }
-    )
-    monkeypatch.setattr(asr_mod, "transcribe", lambda *a, **k: [])
-    _patch_cli(monkeypatch, transport)
-
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    captured = capsys.readouterr()
-    assert rc == 2
-    assert "risk-control ceiling" in captured.err
-    assert "re-run to resume" in captured.err
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[first.work_id]["status"] == "subtitle_done"
-    assert loaded[second.work_id]["status"] == "meta_ok"
-
-
 def test_cli_asr_missing_optional_asr_exits_1_non_archived(
     tmp_root, monkeypatch, capsys
 ):
@@ -215,7 +211,7 @@ def test_cli_asr_missing_optional_asr_exits_1_non_archived(
     _patch_cli(monkeypatch)
     monkeypatch.setattr(bc, "build_default_transport", _audio_transport)
 
-    assert main(["harvest-subs", "--archive-root", tmp_root]) == 0
+    assert _legacy_subtitle_state(tmp_root, identity, _audio_transport()) == "needs_audio"
     capsys.readouterr()
     assert main(["download-audio", "--missing-subs", "--archive-root", tmp_root]) == 0
     capsys.readouterr()
@@ -250,7 +246,10 @@ def test_cli_asr_rerun_idempotent_leaves_unrelated_rows(
     )
     _patch_cli(monkeypatch, _subtitle_transport())
 
-    assert main(["harvest-subs", "--archive-root", tmp_root]) == 0
+    assert (
+        _legacy_subtitle_state(tmp_root, target, _subtitle_transport())
+        == "subtitle_done"
+    )
     capsys.readouterr()
     assert main(["asr", "--pending", "--archive-root", tmp_root]) == 0
     capsys.readouterr()
diff --git a/bilibili-asr-archive/tests/test_mixed_outcome_contract.py b/bilibili-asr-archive/tests/test_mixed_outcome_contract.py
index 574d0c6..9ec1a30 100644
--- a/bilibili-asr-archive/tests/test_mixed_outcome_contract.py
+++ b/bilibili-asr-archive/tests/test_mixed_outcome_contract.py
@@ -206,78 +206,6 @@ def test_run_summary_locks_terminal_selectors_and_risk_precedence():
     assert risk_after_fail.fully_processed is False
 
 
-# ------------------------------------------------------------ harvest-subs
-
-def test_harvest_subs_mixed_success_and_api_failure_is_retryable(
-    tmp_root, monkeypatch, capsys,
-):
-    ok_id = page_identity("BVhOk", 0, 111, "p0")
-    fail_id = page_identity("BVhFail", 0, 222, "p0")
-    store = ManifestStore(root=tmp_root)
-    store.upsert(_row(fail_id, title="fail-first"))
-    store.upsert(_row(ok_id, title="then-ok"))
-    transport = CidRouterTransport(
-        {fail_id.cid: API_FAIL, ok_id.cid: player_ok([sub_entry()])},
-        routes=_base_routes(),
-    )
-    _patch_cli(monkeypatch, transport)
-
-    rc = main([
-        "harvest-subs", "--archive-root", tmp_root, "--sessdata", SECRET,
-    ])
-    captured = capsys.readouterr()
-    assert rc == 1
-    assert "1 subtitle_done" in captured.out
-    assert "1 failed" in captured.out
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[ok_id.work_id]["status"] == "subtitle_done"
-    assert os.path.isfile(os.path.join(tmp_root, loaded[ok_id.work_id]["srt_path"]))
-    assert loaded[fail_id.work_id]["status"] == "meta_ok"
-    assert loaded[fail_id.work_id]["last_api_error_code"] == -400
-    assert _ledger_records(tmp_root) == []
-    assert not os.path.exists(os.path.join(tmp_root, "coordinator", "attempts.jsonl"))
-    _assert_no_secrets(captured, tmp_root)
-
-    before = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    captured = capsys.readouterr()
-    assert rc == 1
-    after = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
-    assert len(after) == len(before) + 1
-    assert after[-1]["params"]["cid"] == fail_id.cid
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[ok_id.work_id]["status"] == "subtitle_done"
-    assert loaded[fail_id.work_id]["status"] == "meta_ok"
-
-
-def test_harvest_subs_success_then_risk_exit_2_keeps_success(
-    tmp_root, monkeypatch, capsys,
-):
-    # harvest-subs walks ManifestStore insertion order (JSONL). work_id
-    # names also keep success first if todo is later sorted by work_id.
-    ok_id = page_identity("BVhAOk", 0, 111, "p0")
-    risk_id = page_identity("BVhZRisk", 0, 222, "p0")
-    store = ManifestStore(root=tmp_root)
-    store.upsert(_row(ok_id))
-    store.upsert(_row(risk_id))
-    transport = CidRouterTransport(
-        {ok_id.cid: player_ok([sub_entry()]), risk_id.cid: RISK},
-        routes=_base_routes(),
-    )
-    _patch_cli(monkeypatch, transport)
-
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    captured = capsys.readouterr()
-    assert rc == 2
-    assert "risk-control ceiling" in captured.err
-    assert "harvest-subs:" in captured.out
-    assert "1 subtitle_done" in captured.out
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[ok_id.work_id]["status"] == "subtitle_done"
-    assert loaded[risk_id.work_id]["status"] == "meta_ok"
-    _assert_no_secrets(captured, tmp_root)
-
-
 # ------------------------------------------------------------ download-audio
 
 def test_download_audio_mixed_success_and_api_failure_is_retryable(
diff --git a/bilibili-asr-archive/tests/test_page_pipeline.py b/bilibili-asr-archive/tests/test_page_pipeline.py
index 4a54e1a..37da69e 100644
--- a/bilibili-asr-archive/tests/test_page_pipeline.py
+++ b/bilibili-asr-archive/tests/test_page_pipeline.py
@@ -171,41 +171,6 @@ def test_download_pages_independent_status(tmp_root):
     assert play_cids == [111, 222]
 
 
-def test_cli_harvest_skips_unresolved_and_processes_other_page(
-    tmp_root, monkeypatch
-):
-    store = ManifestStore(root=tmp_root)
-    store.upsert({
-        "bvid": BVID, "status": "meta_ok", "title": "legacy",
-        "duration_s": 1, "pubdate": 1, "unresolved": True,
-        "unresolved_reason": "ambiguous_bare_bvid",
-        "excluded_from_page_processing": True,
-    })
-    ok = page_identity("BV1ok", 0, 333)
-    store.upsert({
-        "bvid": "BV1ok", "work_id": ok.work_id, "page_index": 0, "cid": 333,
-        "status": "meta_ok", "title": "ok", "duration_s": 1, "pubdate": 1,
-    })
-    transport = SubRouter({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "player/wbi/v2": [player_ok([])],
-    })
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda _s=None: None)
-    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _seconds: None)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 0
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[BVID]["unresolved"] is True
-    assert loaded[BVID]["status"] == "meta_ok"
-    assert "work_id" not in loaded[BVID]
-    assert loaded[ok.work_id]["status"] == "needs_audio"
-    player = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
-    assert len(player) == 1
-    assert player[0]["params"]["cid"] == 333
-
-
 def test_cli_download_skips_unresolved_and_processes_other_page(
     tmp_root, monkeypatch
 ):
@@ -265,25 +230,6 @@ def test_cli_download_audio_bvid_unresolved_stops(tmp_root, monkeypatch, capsys)
     assert not os.path.exists(os.path.join(tmp_root, "audio", f"{BVID}.p0.m4a"))
 
 
-def test_cli_harvest_subs_bvid_unresolved_stops(tmp_root, monkeypatch, capsys):
-    store = ManifestStore(root=tmp_root)
-    store.upsert({
-        "bvid": BVID, "status": "meta_ok", "title": "legacy",
-        "duration_s": 1, "pubdate": 1, "unresolved": True,
-        "unresolved_reason": "ambiguous_bare_bvid",
-        "excluded_from_page_processing": True,
-    })
-    monkeypatch.setattr(bc, "build_default_transport", lambda: SubRouter({}))
-    monkeypatch.setattr(bc, "default_sleeper", lambda _s=None: None)
-    rc = main(["harvest-subs", "--bvid", BVID, "--archive-root", tmp_root])
-    assert rc == 1
-    err = capsys.readouterr().err
-    assert "unresolved" in err
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[BVID]["unresolved"] is True
-    assert "work_id" not in loaded[BVID]
-
-
 def test_harvest_subtitle_str_skips_unresolved(tmp_root):
     store = ManifestStore(root=tmp_root)
     store.upsert({
diff --git a/bilibili-asr-archive/tests/test_persistence_scale.py b/bilibili-asr-archive/tests/test_persistence_scale.py
index c9186e0..65cdc4e 100644
--- a/bilibili-asr-archive/tests/test_persistence_scale.py
+++ b/bilibili-asr-archive/tests/test_persistence_scale.py
@@ -426,13 +426,15 @@ def test_cli_dispatch_locks_every_archive_mutation(
         "recover",
         "asr",
         "pilot",
-        "probe-subs",
         "harvest-subs",
         "download-audio",
         "run",
         "campaign",
         "schedule",
     }
+    # ``probe-subs`` reads the SQLite transcript path and writes nothing, so it
+    # is a reader like ``status``: no writer lock, no file, no new database.
+    assert "probe-subs" not in cli._ARCHIVE_WRITER_COMMANDS
 
     @contextmanager
     def busy_writer(_root):
diff --git a/bilibili-asr-archive/tests/test_subtitle_cli.py b/bilibili-asr-archive/tests/test_subtitle_cli.py
new file mode 100644
index 0000000..3a82251
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_subtitle_cli.py
@@ -0,0 +1,1118 @@
+"""Offline contract tests for the subtitle CLI (``probe-subs`` / ``harvest-subs``).
+
+Everything here is offline.  Both commands are driven end to end through
+``bili_asr.cli.main`` — argparse, the read-command database guard, the
+transcript-schema guard, ``TranscriptRepository``, the service, and the printed
+lines — against a temporary archive database and a scripted gateway double
+installed in place of the concrete adapter, so no network call and no package
+call is made.
+
+What is pinned: the locked ``probe`` / ``harvest`` / summary line shapes and the
+exit taxonomy (0 ran / 1 usage or configuration / 2 terminal), the selection
+preference (CC before AI inside a language family, exact ``--language`` match),
+the outcome mapping, the enumeration advancing across bounded runs, and the
+boundaries — neither command reads or writes a legacy sidecar or a transcript
+projection, ``probe-subs`` writes nothing at all and never creates the database,
+and no display path or stored row carries the credential.
+"""
+
+from __future__ import annotations
+
+from contextlib import contextmanager
+import importlib
+import os
+import sqlite3
+
+import pytest
+
+from bili_asr.cli import main
+from bili_asr.config import ARCHIVE_DATABASE_NAME
+from bili_asr.services.subtitle_ingest import (
+    language_family,
+    select_subtitle_track,
+)
+from bili_asr.sources.models import (
+    GatewayNotFound,
+    GatewayRateLimited,
+    GatewayResponseError,
+    GatewayShapeError,
+    GatewayTransportError,
+    SubtitleSegment,
+    SubtitleTrack,
+)
+from bili_asr.storage import MetadataRepository, open_database
+from bili_asr.storage.models import (
+    ALLOWED_ACQUISITION_KINDS,
+    ALLOWED_CAPTION_SOURCE_KINDS,
+)
+from fixtures.fake_bilibili_gateway import (
+    SESSDATA_BOUNDARY_VALUE,
+    UPSTREAM_ERROR_TEXT,
+    assert_leaks_no_markers,
+    persisted_row_text,
+)
+from fixtures.metadata_records import (
+    make_part_record,
+    make_user_record,
+    make_video_record,
+)
+from test_storage_schema import _write_pre_iteration_database
+
+BVID_A = "BV1SubA"
+BVID_B = "BV1SubB"
+
+#: One caption body of two segments, and a revised body of the same identity.
+BODY = (
+    SubtitleSegment(start_ms=0, end_ms=1_200, text="第一句"),
+    SubtitleSegment(start_ms=1_200, end_ms=2_400, text="第二句"),
+)
+CHANGED_BODY = (
+    SubtitleSegment(start_ms=0, end_ms=1_200, text="第一句"),
+    SubtitleSegment(start_ms=1_200, end_ms=2_400, text="改写后的第二句"),
+)
+
+#: The realistic caption inventory: the uploader track and the machine one for
+#: the same spoken language, plus one English uploader track.
+CC_ZH = SubtitleTrack(
+    language="zh-CN", label="中文（简体）", is_ai=False, track_id=None
+)
+AI_ZH = SubtitleTrack(
+    language="ai-zh", label="中文（自动生成）", is_ai=True, track_id="1"
+)
+CC_EN = SubtitleTrack(
+    language="en-US", label="English", is_ai=False, track_id=None
+)
+
+#: The legacy sidecars and the transcript projections the subtitle path owns.
+LEGACY_SIDE_CAR_PATHS = (
+    "manifest/manifest.jsonl",
+    "meta-cursor.json",
+    "run-ledger.jsonl",
+    "coordinator/attempts.jsonl",
+)
+PROJECTION_PREFIXES = ("subtitles/raw/", "transcripts/srt/")
+#: ``harvest-subs`` is an archive-writer command, so the shipped lock is the one
+#: file besides the database it is expected to leave behind.
+ARCHIVE_WRITER_LOCK_PATH = "coordinator/archive-writer.lock"
+
+
+@pytest.fixture(autouse=True)
+def _anonymous_environment(monkeypatch: pytest.MonkeyPatch):
+    """No credential in the environment unless a test sets one explicitly."""
+
+    monkeypatch.delenv("BILI_SESSDATA", raising=False)
+
+
+class _ScriptedSubtitleGateway:
+    """The gateway protocol's two subtitle calls, scripted per part, offline.
+
+    A part is addressed by its ``cid``: ``tracks_by_cid`` scripts one inventory,
+    ``segments_by_cid`` one body, and the two failure maps raise instead of
+    answering.  A call the test did not script fails loudly rather than silently
+    answering an empty inventory, and every call is recorded — ``listing_cids``
+    and ``body_cids`` in issue order — so the enumeration order and "the body was
+    never fetched" are assertable.
+    """
+
+    def __init__(
+        self,
+        *,
+        tracks: dict[int, tuple[SubtitleTrack, ...]] | None = None,
+        segments: dict[int, tuple[SubtitleSegment, ...]] | None = None,
+        listing_failures: dict[int, Exception] | None = None,
+        body_failures: dict[int, Exception] | None = None,
+    ) -> None:
+        self.tracks_by_cid = dict(tracks or {})
+        self.segments_by_cid = dict(segments or {})
+        self.listing_failures_by_cid = dict(listing_failures or {})
+        self.body_failures_by_cid = dict(body_failures or {})
+        self.sessdata: str | None = None
+        self.listing_cids: list[int] = []
+        self.body_cids: list[int] = []
+
+    async def get_subtitle_tracks(
+        self, bvid: str, cid: int
+    ) -> tuple[SubtitleTrack, ...]:
+        self.listing_cids.append(cid)
+        failure = self.listing_failures_by_cid.get(cid)
+        if failure is not None:
+            raise failure
+        if cid not in self.tracks_by_cid:
+            raise AssertionError(f"the test did not script a listing for cid {cid}")
+        return self.tracks_by_cid[cid]
+
+    async def fetch_subtitle_segments(
+        self, track: SubtitleTrack, bvid: str, cid: int
+    ) -> tuple[SubtitleSegment, ...]:
+        self.body_cids.append(cid)
+        failure = self.body_failures_by_cid.get(cid)
+        if failure is not None:
+            raise failure
+        if cid not in self.segments_by_cid:
+            raise AssertionError(f"the test did not script a body for cid {cid}")
+        return self.segments_by_cid[cid]
+
+
+@pytest.fixture
+def install_gateway(monkeypatch: pytest.MonkeyPatch):
+    """Install one scripted gateway as the CLI's concrete adapter.
+
+    The composition root imports ``BilibiliApiGateway`` inside each handler, so
+    replacing the class in its own module keeps the whole command path under test
+    with no network and no package seam.  The double records the credential the
+    composition root handed it, which the credential test pins.
+
+    The module is reached through ``importlib`` deliberately: the adapter is
+    dropped from ``sys.modules`` by the package-seam fixtures of the other test
+    modules, and a plain ``import ... as`` would then bind the parent package's
+    stale attribute instead of the module the handler imports from.
+    """
+
+    def install(**script) -> _ScriptedSubtitleGateway:
+        gateway_module = importlib.import_module(
+            "bili_asr.sources.bilibili_api_gateway"
+        )
+        gateway = _ScriptedSubtitleGateway(**script)
+
+        def factory(sessdata: str | None = None, proxy: str | None = None):
+            del proxy
+            gateway.sessdata = sessdata
+            return gateway
+
+        monkeypatch.setattr(gateway_module, "BilibiliApiGateway", factory)
+        return gateway
+
+    return install
+
+
+def _seed_parts(root: str, parts: tuple[tuple[str, int, int], ...]) -> None:
+    """Create ``archive.db`` with one user, one video per bvid, and these parts.
+
+    ``parts`` is ``(bvid, page_index, cid)`` triples, so a test scripts its
+    answers by the part it means.
+    """
+
+    connection = open_database(root)
+    repository = MetadataRepository(connection)
+    try:
+        with repository.transaction():
+            repository.upsert_user(make_user_record())
+            for bvid in dict.fromkeys(bvid for bvid, _page, _cid in parts):
+                repository.upsert_video(
+                    make_video_record(bvid, aid=None, title="字幕测试视频")
+                )
+            for bvid, page_index, cid in parts:
+                repository.upsert_part(
+                    make_part_record(
+                        bvid,
+                        page_index=page_index,
+                        cid=cid,
+                        processing_status="metadata_collected",
+                    )
+                )
+    finally:
+        connection.close()
+
+
+@contextmanager
+def _archive_connection(root: str):
+    """Read the archive database directly, without creating or migrating it."""
+
+    connection = sqlite3.connect(os.path.join(root, ARCHIVE_DATABASE_NAME))
+    connection.row_factory = sqlite3.Row
+    try:
+        yield connection
+    finally:
+        connection.close()
+
+
+def _archive_files(root: str) -> list[str]:
+    """Every file below the archive root, as sorted relative POSIX paths."""
+
+    return sorted(
+        os.path.relpath(os.path.join(directory, name), root).replace(os.sep, "/")
+        for directory, _directories, names in os.walk(root)
+        for name in names
+    )
+
+
+def _scalar(root: str, sql: str, parameters: tuple = ()):
+    """Read one scalar straight from the archive database."""
+
+    with _archive_connection(root) as connection:
+        return connection.execute(sql, parameters).fetchone()[0]
+
+
+def _exit_code(argv: list[str]) -> int:
+    """Return the command's exit code, argparse usage errors included.
+
+    ``_UsageErrorArgumentParser`` maps argparse's ``2`` onto ``1`` (and keeps
+    ``--help`` at ``0``) but still raises ``SystemExit`` for a malformed value,
+    which is the same process exit code an operator sees.
+    """
+
+    try:
+        return main(argv)
+    except SystemExit as exit_signal:
+        return int(exit_signal.code)
+
+
+# ------------------------------------------------------------------ usage
+
+@pytest.mark.parametrize(
+    "argv",
+    [
+        ["probe-subs"],
+        ["probe-subs", "--bvid", BVID_A, "--limit-parts", "1"],
+        ["probe-subs", "--limit-parts", "0"],
+        ["probe-subs", "--limit-parts", "-2"],
+        ["probe-subs", "--limit-parts", "not-a-number"],
+        ["harvest-subs"],
+        ["harvest-subs", "--bvid", BVID_A],
+        ["harvest-subs", "--limit-parts", "0"],
+        ["harvest-subs", "--limit-parts", "2", "--language", "ai-zh,"],
+        ["harvest-subs", "--limit-parts", "2", "--language", ""],
+    ],
+)
+def test_subtitle_usage_errors_exit_one_never_two(
+    tmp_root: str, capsys, argv: list[str]
+) -> None:
+    """Every usage/configuration error is exit 1 with nothing on stdout."""
+
+    assert _exit_code([*argv, "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err.strip()
+
+
+def test_probe_subs_requires_exactly_one_selector(tmp_root: str, capsys) -> None:
+    """Neither selector, and both selectors, are the same usage error."""
+
+    assert main(["probe-subs", "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert "exactly one of --bvid / --limit-parts" in captured.err
+
+    assert (
+        main(
+            [
+                "probe-subs",
+                "--bvid",
+                BVID_A,
+                "--limit-parts",
+                "1",
+                "--archive-root",
+                tmp_root,
+            ]
+        )
+        == 1
+    )
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert "exactly one of --bvid / --limit-parts" in captured.err
+
+
+def test_missing_database_on_both_commands_prints_the_shipped_line(
+    tmp_root: str, capsys
+) -> None:
+    """A missing database is the shipped read-command line, and nothing appears."""
+
+    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err == (
+        f"probe-subs: no archive database at {tmp_root}; "
+        "run fetch-meta to create it\n"
+    )
+    # Read-only for real: no database, no writer lock, no file at all.
+    assert _archive_files(tmp_root) == []
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err == (
+        f"harvest-subs: no archive database at {tmp_root}; "
+        "run fetch-meta to create it\n"
+    )
+    assert not os.path.exists(os.path.join(tmp_root, ARCHIVE_DATABASE_NAME))
+
+
+def test_probe_subs_creates_nothing_when_the_archive_root_is_absent(
+    tmp_root: str, capsys
+) -> None:
+    """A missing root is not created by a read command."""
+
+    root = os.path.join(tmp_root, "absent")
+    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert "no archive database" in captured.err
+    assert not os.path.exists(root)
+
+
+def test_unknown_bvid_is_configuration_and_opens_no_run(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """A selector naming no stored part exits 1 before any upstream call."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH,)})
+
+    assert (
+        main(
+            [
+                "harvest-subs",
+                "--bvid",
+                "BV1Unknown",
+                "--limit-parts",
+                "5",
+                "--archive-root",
+                tmp_root,
+            ]
+        )
+        == 1
+    )
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert "unknown --bvid BV1Unknown" in captured.err
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_runs") == 0
+
+    assert main(["probe-subs", "--bvid", "BV1Unknown:p7", "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert "unknown --bvid BV1Unknown:p7" in captured.err
+    assert gateway.listing_cids == []
+
+
+# ------------------------------------------------- selection preference
+
+@pytest.mark.parametrize(
+    ("language", "is_ai", "expected"),
+    [
+        ("zh-CN", False, "zh"),
+        ("zh-Hans", False, "zh"),
+        ("zh-Hant", False, "zh"),
+        ("ai-zh", True, "zh"),
+        ("AI-ZH", True, "zh"),
+        ("ai-en", True, "en"),
+        ("en-US", False, "en"),
+        ("ja", False, "ja"),
+        (" pt-BR ", False, "pt"),
+    ],
+)
+def test_language_family_derivation(
+    language: str, is_ai: bool, expected: str
+) -> None:
+    """The family is the lowercase primary subtag, ``ai-`` stripped for AI."""
+
+    assert language_family(language, is_ai) == expected
+
+
+@pytest.mark.parametrize("cc_language", ["zh-CN", "zh-Hans", "zh-Hant", "zh"])
+@pytest.mark.parametrize("ai_language", ["ai-zh", "ai-ZH"])
+@pytest.mark.parametrize("ai_first", [True, False])
+def test_default_preference_picks_the_uploader_caption_for_chinese_pairs(
+    cc_language: str, ai_language: str, ai_first: bool
+) -> None:
+    """For any Chinese CC/AI code pair, in either upstream order, CC wins."""
+
+    uploader = SubtitleTrack(
+        language=cc_language, label="中文（简体）", is_ai=False, track_id=None
+    )
+    machine = SubtitleTrack(
+        language=ai_language, label="中文（自动生成）", is_ai=True, track_id="1"
+    )
+    tracks = (machine, uploader) if ai_first else (uploader, machine)
+
+    assert select_subtitle_track(tracks) is uploader
+
+
+def test_default_preference_ranks_known_families_then_falls_back_to_upstream_order() -> None:
+    """``zh`` outranks ``en``, both outrank the rest, and order settles ties."""
+
+    french = SubtitleTrack(language="fr", label="Français", is_ai=False, track_id=None)
+    english_ai = SubtitleTrack(
+        language="ai-en", label="English (auto)", is_ai=True, track_id="2"
+    )
+    chinese_ai = SubtitleTrack(
+        language="ai-zh", label="中文（自动生成）", is_ai=True, track_id="1"
+    )
+    tr_chinese = SubtitleTrack(
+        language="zh-Hant", label="中文（繁體）", is_ai=False, track_id=None
+    )
+
+    assert select_subtitle_track((english_ai, french, chinese_ai)) is chinese_ai
+    assert select_subtitle_track((french, english_ai)) is english_ai
+    assert select_subtitle_track((french, tr_chinese)) is tr_chinese
+    # the family rank decides before the CC/AI split: zh still wins over en
+    assert select_subtitle_track((AI_ZH, CC_EN)) is AI_ZH
+    first_chinese = SubtitleTrack(
+        language="zh-CN", label="中文（简体）", is_ai=False, track_id=None
+    )
+    assert select_subtitle_track((first_chinese, tr_chinese)) is first_chinese
+    assert select_subtitle_track(()) is None
+
+
+def test_explicit_language_matches_exactly_and_first_preference_wins() -> None:
+    """``--language`` order decides; a code nothing matches yields no track."""
+
+    assert select_subtitle_track((CC_ZH, AI_ZH), ("ai-zh",)) is AI_ZH
+    assert select_subtitle_track((AI_ZH, CC_ZH), ("zh-CN", "ai-zh")) is CC_ZH
+    assert select_subtitle_track((CC_ZH, AI_ZH), ("zh",)) is None
+    assert select_subtitle_track((), ("zh-CN",)) is None
+
+    ai_spelled_cc = SubtitleTrack(
+        language="zh-CN", label="中文（自动生成）", is_ai=True, track_id="1"
+    )
+    assert (
+        select_subtitle_track((ai_spelled_cc, CC_ZH), ("zh-CN",)) is CC_ZH
+    ), "inside one preference the uploader caption still wins"
+
+
+# ------------------------------------------------------- probe-subs output
+
+def test_probe_subs_prints_track_lines_the_zero_track_marker_and_the_summary(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """One ``probe`` line per selected part, in selection order, then the summary."""
+
+    _seed_parts(
+        tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201))
+    )
+    gateway = install_gateway(
+        tracks={101: (CC_ZH, AI_ZH), 102: ()},
+        listing_failures={201: GatewayResponseError(detail=UPSTREAM_ERROR_TEXT)},
+    )
+
+    assert main(["probe-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines() == [
+        "sessdata: absent",
+        f"probe {BVID_A}:p0 tracks=2",
+        "  track zh-CN cc 中文（简体）",
+        "  track ai-zh ai 中文（自动生成）",
+        f"probe {BVID_A}:p1 tracks=0",
+        "  (no subtitles visible)",
+        f"probe {BVID_B}:p0 failed response_error",
+        "probe-subs: probed=3 with_tracks=1 without_tracks=1 failed=1",
+    ]
+    assert_leaks_no_markers(captured.out + captured.err, context="probe output")
+
+    # Nothing was written and no body was fetched: a probe lists tracks only.
+    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
+    assert gateway.body_cids == []
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_runs") == 0
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_attempts") == 0
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 0
+
+
+def test_probe_subs_exits_two_when_every_selected_part_failed(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """A whole-probe failure is the terminal code, with the count still printed."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    install_gateway(listing_failures={101: GatewayRateLimited()})
+
+    assert main(["probe-subs", "--bvid", BVID_A, "--archive-root", tmp_root]) == 2
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines() == [
+        "sessdata: absent",
+        f"probe {BVID_A}:p0 failed rate_limited",
+        "probe-subs: probed=1 with_tracks=0 without_tracks=0 failed=1",
+    ]
+
+
+def test_probe_subs_reports_an_empty_selection_as_zero_probed(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """No pending part is a completed read, not an error and not a stall."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+
+    assert main(["probe-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0
+    captured = capsys.readouterr()
+    assert captured.out.splitlines() == [
+        "sessdata: absent",
+        "probe-subs: probed=0 with_tracks=0 without_tracks=0 failed=0",
+    ]
+    assert gateway.listing_cids == [101]
+
+
+# ----------------------------------------------------- harvest-subs output
+
+def test_harvest_subs_prints_every_outcome_and_the_complete_summary(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """One ``harvest`` line per attempted part, then all four counts and the run."""
+
+    _seed_parts(
+        tmp_root,
+        ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201), (BVID_B, 1, 202)),
+    )
+    install_gateway(
+        tracks={101: (CC_ZH, AI_ZH), 102: (CC_ZH,), 201: (), 202: (CC_ZH,)},
+        segments={101: BODY, 102: BODY},
+        body_failures={202: GatewayNotFound()},
+    )
+
+    assert main(["harvest-subs", "--limit-parts", "4", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert_leaks_no_markers(captured.out + captured.err, context="harvest output")
+    lines = captured.out.splitlines()
+    assert lines[:5] == [
+        "sessdata: absent",
+        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v1",
+        f"harvest {BVID_A}:p1 stored subtitle-cc zh-CN v1",
+        f"harvest {BVID_B}:p0 no-subtitle",
+        f"harvest {BVID_B}:p1 no-subtitle",
+    ]
+    summary = lines[5]
+    assert summary.startswith("harvest-subs: run_id=")
+    assert "attempted=4 stored=2 unchanged=0 no-subtitle=2 failed=0" in summary
+    assert summary.endswith("remaining_without_transcript=2")
+    assert len(lines) == 6
+
+    with _archive_connection(tmp_root) as connection:
+        run = connection.execute(
+            "SELECT kind, selector_kind, selector_target, requested_limit,"
+            " credential_present, outcome, finished_at FROM acquisition_runs"
+        ).fetchone()
+        assert (
+            run["kind"],
+            run["selector_kind"],
+            run["selector_target"],
+            run["requested_limit"],
+        ) == ("subtitle", "pending", None, 4)
+        assert run["kind"] in ALLOWED_ACQUISITION_KINDS
+        assert run["credential_present"] == 0
+        assert run["outcome"] == "complete"
+        assert run["finished_at"] is not None
+        assert [
+            (row["outcome"], row["error_code"])
+            for row in connection.execute(
+                "SELECT outcome, error_code FROM acquisition_attempts"
+                " ORDER BY video_part_id"
+            )
+        ] == [
+            ("stored", None),
+            ("stored", None),
+            ("no-subtitle", None),
+            ("no-subtitle", "not_found"),
+        ]
+        stored = connection.execute(
+            "SELECT source_kind, language, version FROM transcripts"
+            " ORDER BY transcript_id"
+        ).fetchall()
+        assert [(row["source_kind"], row["language"], row["version"]) for row in stored] == [
+            ("subtitle-cc", "zh-CN", 1),
+            ("subtitle-cc", "zh-CN", 1),
+        ]
+        assert {row["source_kind"] for row in stored} <= ALLOWED_CAPTION_SOURCE_KINDS
+        assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcript_segments") == 4
+        # every attempt carries its own timestamps, so a captionless part is
+        # timestamped evidence and never a success with empty content
+        assert connection.execute(
+            "SELECT COUNT(*) FROM acquisition_attempts"
+            " WHERE outcome = 'no-subtitle'"
+            " AND started_at IS NOT NULL AND finished_at IS NOT NULL"
+        ).fetchone()[0] == 2
+
+
+def test_default_preference_stores_the_uploader_caption_when_both_are_visible(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """The AI track is visible first upstream and the CC track is still selected."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    install_gateway(tracks={101: (AI_ZH, CC_ZH)}, segments={101: BODY})
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v1"
+    )
+
+
+def test_language_preference_reaches_the_ai_track(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """``--language`` overrides the default order by exact upstream code."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    install_gateway(tracks={101: (CC_ZH, AI_ZH)}, segments={101: BODY})
+
+    assert (
+        main(
+            [
+                "harvest-subs",
+                "--limit-parts",
+                "1",
+                "--language",
+                "ai-zh, zh-CN",
+                "--archive-root",
+                tmp_root,
+            ]
+        )
+        == 0
+    )
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p0 stored subtitle-ai ai-zh v1"
+    )
+    with _archive_connection(tmp_root) as connection:
+        row = connection.execute(
+            "SELECT source_kind, language FROM transcripts"
+        ).fetchone()
+    assert (row["source_kind"], row["language"]) == ("subtitle-ai", "ai-zh")
+
+
+def test_unmatched_language_preference_is_no_subtitle_with_no_fetch(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """Nothing usable *for the requested language* is no-subtitle, never failed."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH, AI_ZH)})
+
+    assert (
+        main(
+            [
+                "harvest-subs",
+                "--limit-parts",
+                "1",
+                "--language",
+                "ja",
+                "--archive-root",
+                tmp_root,
+            ]
+        )
+        == 0
+    )
+
+    captured = capsys.readouterr()
+    lines = captured.out.splitlines()
+    assert lines[1] == f"harvest {BVID_A}:p0 no-subtitle"
+    assert "attempted=1 stored=0 unchanged=0 no-subtitle=1 failed=0" in lines[2]
+    assert gateway.body_cids == []
+    with _archive_connection(tmp_root) as connection:
+        attempt = connection.execute(
+            "SELECT outcome, error_code, transcript_id FROM acquisition_attempts"
+        ).fetchone()
+        assert (attempt["outcome"], attempt["error_code"]) == ("no-subtitle", None)
+        assert attempt["transcript_id"] is None
+        assert connection.execute(
+            "SELECT outcome FROM acquisition_runs"
+        ).fetchone()[0] == "complete"
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 0
+
+
+def test_harvest_subs_reports_an_empty_pending_selection_as_complete(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """``attempted=0`` is a completed bounded run, still with every count printed."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+
+    assert main(["harvest-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0
+    captured = capsys.readouterr()
+    lines = captured.out.splitlines()
+    assert lines[0] == "sessdata: absent"
+    assert "attempted=0 stored=0 unchanged=0 no-subtitle=0 failed=0" in lines[1]
+    assert lines[1].endswith("remaining_without_transcript=0")
+    assert gateway.listing_cids == [101]
+    with _archive_connection(tmp_root) as connection:
+        assert [
+            row["outcome"]
+            for row in connection.execute(
+                "SELECT outcome FROM acquisition_runs ORDER BY started_at"
+            )
+        ] == ["complete", "complete"]
+
+
+# -------------------------------------------- enumeration and re-acquisition
+
+def test_explicit_bvid_selects_every_stored_part_including_a_stored_one(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """An explicit video selection re-checks stored parts and reports ``unchanged``."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201)))
+    gateway = install_gateway(
+        tracks={101: (CC_ZH,), 102: (CC_ZH,), 201: (CC_ZH,)},
+        segments={101: BODY, 102: BODY, 201: BODY},
+    )
+
+    assert (
+        main(
+            ["harvest-subs", "--bvid", BVID_A, "--limit-parts", "5",
+             "--archive-root", tmp_root]
+        )
+        == 0
+    )
+    capsys.readouterr()
+    assert gateway.listing_cids == [101, 102], "only that video's stored parts"
+
+    assert (
+        main(
+            ["harvest-subs", "--bvid", BVID_A, "--limit-parts", "5",
+             "--archive-root", tmp_root]
+        )
+        == 0
+    )
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1:3] == [
+        f"harvest {BVID_A}:p0 unchanged subtitle-cc zh-CN v1",
+        f"harvest {BVID_A}:p1 unchanged subtitle-cc zh-CN v1",
+    ]
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 2
+    with _archive_connection(tmp_root) as connection:
+        assert connection.execute(
+            "SELECT outcome FROM acquisition_runs ORDER BY started_at DESC LIMIT 1"
+        ).fetchone()[0] == "complete"
+
+
+def test_a_single_named_part_needs_no_bound_and_records_its_selector(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """``bvid:pN`` is bounded by construction; the run records what was named."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
+    gateway = install_gateway(tracks={102: (CC_ZH,)}, segments={102: BODY})
+
+    assert (
+        main(["harvest-subs", "--bvid", f"{BVID_A}:p1", "--archive-root", tmp_root])
+        == 0
+    )
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p1 stored subtitle-cc zh-CN v1"
+    )
+    assert gateway.listing_cids == [102]
+    with _archive_connection(tmp_root) as connection:
+        run = connection.execute(
+            "SELECT selector_kind, selector_target, requested_limit"
+            " FROM acquisition_runs"
+        ).fetchone()
+    assert (
+        run["selector_kind"],
+        run["selector_target"],
+        run["requested_limit"],
+    ) == ("bvid", f"{BVID_A}:p1", None)
+
+
+def test_bounded_pending_runs_advance_through_the_captionless_backlog(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """Never-attempted parts come first; repeated runs rotate, never stall."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201)))
+    gateway = install_gateway(tracks={101: (), 102: (), 201: ()})
+
+    attempted = []
+    for _run in range(4):
+        assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+        captured = capsys.readouterr()
+        assert "attempted=1 stored=0 unchanged=0 no-subtitle=1 failed=0" in captured.out
+        attempted.append(gateway.listing_cids[-1])
+
+    assert attempted == [101, 102, 201, 101], (
+        "never-attempted parts first, then the oldest attempt"
+    )
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_attempts") == 4
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 0
+
+
+def test_unchanged_content_adds_no_version_and_changed_content_appends_one(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """Re-acquisition is idempotent, and a revised body becomes the next version."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+
+    assert (
+        main(["harvest-subs", "--bvid", f"{BVID_A}:p0", "--archive-root", tmp_root])
+        == 0
+    )
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p0 unchanged subtitle-cc zh-CN v1"
+    )
+
+    gateway.segments_by_cid[101] = CHANGED_BODY
+    assert (
+        main(["harvest-subs", "--bvid", f"{BVID_A}:p0", "--archive-root", tmp_root])
+        == 0
+    )
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v2"
+    )
+
+    with _archive_connection(tmp_root) as connection:
+        assert [
+            row["version"]
+            for row in connection.execute(
+                "SELECT version FROM transcripts ORDER BY version"
+            )
+        ] == [1, 2]
+        assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcript_segments") == 4
+
+
+def test_a_part_without_a_caption_can_store_one_in_a_later_run(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """``no-subtitle`` is an observation at one attempt, never a terminal state."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: ()})
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == f"harvest {BVID_A}:p0 no-subtitle"
+    assert "remaining_without_transcript=1" in captured.out
+
+    # the caption appears upstream and the part is still part of the work set
+    gateway.tracks_by_cid[101] = (CC_ZH,)
+    gateway.segments_by_cid[101] = BODY
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v1"
+    )
+    assert "stored=1" in captured.out
+    assert "remaining_without_transcript=0" in captured.out
+    with _archive_connection(tmp_root) as connection:
+        assert [
+            (row["outcome"], row["transcript_id"] is not None)
+            for row in connection.execute(
+                "SELECT outcome, transcript_id FROM acquisition_attempts"
+                " ORDER BY started_at, rowid"
+            )
+        ] == [("no-subtitle", False), ("stored", True)]
+
+
+# ------------------------------------------------------ outcome mapping
+
+@pytest.mark.parametrize(
+    "failure",
+    [
+        GatewayRateLimited(),
+        GatewayTransportError(),
+        GatewayResponseError(),
+        GatewayShapeError(),
+    ],
+    ids=lambda failure: failure.code,
+)
+def test_bounded_gateway_failures_map_to_failed_with_their_code(
+    tmp_root: str, capsys, install_gateway, failure: Exception
+) -> None:
+    """Every non-``not_found`` gateway failure is a bounded ``failed`` part."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
+    install_gateway(listing_failures={101: failure, 102: failure})
+
+    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 2
+
+    captured = capsys.readouterr()
+    assert (
+        f"harvest {BVID_A}:p0 failed {failure.code}"
+        in captured.out
+    )
+    assert "attempted=2 stored=0 unchanged=0 no-subtitle=0 failed=2" in captured.out
+    assert_leaks_no_markers(captured.out + captured.err, context="failed-part output")
+    with _archive_connection(tmp_root) as connection:
+        assert [
+            (row["outcome"], row["error_code"], row["transcript_id"])
+            for row in connection.execute(
+                "SELECT outcome, error_code, transcript_id"
+                " FROM acquisition_attempts ORDER BY video_part_id"
+            )
+        ] == [("failed", failure.code, None), ("failed", failure.code, None)]
+        assert connection.execute(
+            "SELECT outcome FROM acquisition_runs"
+        ).fetchone()[0] == "failed"
+
+
+@pytest.mark.parametrize("stage", ["listing", "body"])
+def test_not_found_is_recorded_no_subtitle_with_its_code(
+    tmp_root: str, capsys, install_gateway, stage: str
+) -> None:
+    """Upstream ``not_found`` is evidence without a caption, never a failure."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    script: dict = {"tracks": {101: (CC_ZH,)}, "segments": {101: BODY}}
+    script[f"{stage}_failures"] = {101: GatewayNotFound()}
+    install_gateway(**script)
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == f"harvest {BVID_A}:p0 no-subtitle"
+    assert "stored=0 unchanged=0 no-subtitle=1 failed=0" in captured.out
+    with _archive_connection(tmp_root) as connection:
+        attempt = connection.execute(
+            "SELECT outcome, error_code, transcript_id FROM acquisition_attempts"
+        ).fetchone()
+    assert (attempt["outcome"], attempt["error_code"]) == ("no-subtitle", "not_found")
+    assert attempt["transcript_id"] is None
+
+
+def test_partial_failure_keeps_exit_zero_and_stays_visible_in_the_counts(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """One stored and one failed part is a partial run, not a terminal failure."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
+    install_gateway(
+        tracks={101: (CC_ZH,), 102: (CC_ZH,)},
+        segments={101: BODY},
+        listing_failures={102: GatewayRateLimited()},
+    )
+
+    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert "attempted=2 stored=1 unchanged=0 no-subtitle=0 failed=1" in captured.out
+    assert captured.out.splitlines()[2] == (
+        f"harvest {BVID_A}:p1 failed rate_limited"
+    )
+    with _archive_connection(tmp_root) as connection:
+        assert connection.execute(
+            "SELECT outcome FROM acquisition_runs"
+        ).fetchone()[0] == "partial"
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 1
+
+
+def test_unexpected_error_exits_two_finishes_the_run_and_leaks_nothing(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """Anything escaping the service is the fixed line, with the run closed."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    install_gateway(listing_failures={101: RuntimeError(UPSTREAM_ERROR_TEXT)})
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 2
+
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err == "harvest-subs: unexpected error\n"
+    assert_leaks_no_markers(
+        captured.out + captured.err, context="unexpected-error output"
+    )
+    with _archive_connection(tmp_root) as connection:
+        run = connection.execute(
+            "SELECT outcome, finished_at FROM acquisition_runs"
+        ).fetchone()
+    assert run["outcome"] == "failed"
+    assert run["finished_at"] is not None
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_attempts") == 0
+
+
+# --------------------------------------------------------- boundaries
+
+def test_credential_is_reported_as_presence_only(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """The value reaches the adapter and no output path or row ever shows it."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
+
+    assert (
+        main(
+            [
+                "harvest-subs",
+                "--limit-parts",
+                "1",
+                "--sessdata",
+                SESSDATA_BOUNDARY_VALUE,
+                "--archive-root",
+                tmp_root,
+            ]
+        )
+        == 0
+    )
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[0] == "sessdata: present"
+    assert SESSDATA_BOUNDARY_VALUE not in captured.out + captured.err
+    assert gateway.sessdata == SESSDATA_BOUNDARY_VALUE
+    with _archive_connection(tmp_root) as connection:
+        assert connection.execute(
+            "SELECT credential_present FROM acquisition_runs"
+        ).fetchone()[0] == 1
+        assert SESSDATA_BOUNDARY_VALUE not in persisted_row_text(connection)
+
+    assert main(["probe-subs", "--bvid", BVID_A, "--archive-root", tmp_root]) == 0
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[0] == "sessdata: absent"
+
+
+def test_neither_command_writes_a_sidecar_or_a_transcript_projection(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """Only ``archive.db`` (and the writer lock) appears under the archive root."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
+
+    assert main(["probe-subs", "--bvid", BVID_A, "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME], (
+        "a probe takes no writer lock and creates no file"
+    )
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+    files = _archive_files(tmp_root)
+    assert files == sorted([ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH])
+    for sidecar in LEGACY_SIDE_CAR_PATHS:
+        assert sidecar not in files
+    for path in files:
+        assert not path.startswith(PROJECTION_PREFIXES)
+
+
+def test_both_commands_print_the_fixed_rebuild_line_for_a_legacy_database(
+    tmp_root: str, capsys
+) -> None:
+    """A pre-iteration database: both commands exit 1, the metadata path keeps working."""
+
+    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
+    _write_pre_iteration_database(database_path)
+
+    for command, argv in (
+        (
+            "probe-subs",
+            ["probe-subs", "--bvid", "BV1Legacy", "--archive-root", tmp_root],
+        ),
+        (
+            "harvest-subs",
+            ["harvest-subs", "--bvid", "BV1Legacy:p0", "--archive-root", tmp_root],
+        ),
+    ):
+        assert main(argv) == 1
+        captured = capsys.readouterr()
+        assert captured.out == ""
+        assert captured.err == (
+            f"{command}: archive database predates the transcript schema; "
+            f"rebuild it (delete {database_path} and re-run fetch-meta)\n"
+        )
+
+    assert main(["status", "--archive-root", tmp_root]) == 0
+    assert capsys.readouterr().out.startswith("users: 1")
diff --git a/bilibili-asr-archive/tests/test_subtitles.py b/bilibili-asr-archive/tests/test_subtitles.py
index d127213..8994408 100644
--- a/bilibili-asr-archive/tests/test_subtitles.py
+++ b/bilibili-asr-archive/tests/test_subtitles.py
@@ -1,15 +1,18 @@
-"""Unit tests for subtitle probe/harvest: mocked transport only, no network."""
+"""Unit tests for subtitle probe/harvest: mocked transport only, no network.
+
+The ``probe-subs`` / ``harvest-subs`` command surface moved to the SQLite
+transcript path and is covered by ``tests/test_subtitle_cli.py``; what stays
+here is the legacy client and harvest-helper layer that the untouched ASR,
+pilot, run, and coordinator paths still call.
+"""
 
 from __future__ import annotations
 
 import json
 import os
 
-import pytest
-
 from bili_asr import bili_client as bc
 from bili_asr import subtitles
-from bili_asr.cli import main
 from bili_asr.manifest import ManifestStore
 
 API = "https://api.bilibili.com"
@@ -259,235 +262,3 @@ def test_harvest_downloads_shortlived_url_same_run(tmp_root):
     manifest_text = open(store.path, encoding="utf-8").read()
     assert "hdslb" not in manifest_text
     assert "subtitle_url" not in manifest_text
-
-
-# ---------------------------------------------------------------- CLI
-
-def _cli_routes(monkeypatch, transport):
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: FastSleeper())
-
-
-def test_cli_probe_subs_empty(tmp_root, monkeypatch, capsys):
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([])],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["probe-subs", "--bvid", "BV1mk8W6dEyx",
-               "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "no subtitles" in out
-    assert "needs_audio" in out
-
-
-def test_cli_probe_subs_unknown_bvid_api_error_does_not_create_row(
-    tmp_root, monkeypatch, capsys
-):
-    sentinel_cookie = "PROBE-SESSDATA-SECRET"
-    monkeypatch.setenv("BILI_SESSDATA", sentinel_cookie)
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "pagelist": [(200, {"code": -99999})],
-    })
-    _cli_routes(monkeypatch, transport)
-
-    rc = main([
-        "probe-subs", "--bvid", "BV1unknown",
-        "--archive-root", tmp_root,
-    ])
-
-    assert rc == 1
-    assert ManifestStore(root=tmp_root).get("BV1unknown") is None
-    assert not os.path.exists(ManifestStore(root=tmp_root).path)
-    captured = capsys.readouterr()
-    output = captured.out + captured.err
-    assert sentinel_cookie not in output
-    assert "http" not in output.lower()
-
-
-def test_cli_probe_subs_transport_error_redacts_exception_message(
-    tmp_root, monkeypatch, capsys
-):
-    sentinel = "SESSDATA=PROBE-SECRET https://cdn.example/sub.json?token=SIGNED"
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "pagelist": [RuntimeError(sentinel)] * 5,
-    })
-    _cli_routes(monkeypatch, transport)
-
-    rc = main([
-        "probe-subs", "--bvid", "BV1transport",
-        "--archive-root", tmp_root,
-    ])
-
-    assert rc == 2
-    captured = capsys.readouterr()
-    output = captured.out + captured.err
-    assert "RuntimeError" in output
-    assert "PROBE-SECRET" not in output
-    assert "SIGNED" not in output
-    assert not os.path.exists(ManifestStore(root=tmp_root).path)
-
-
-def test_cli_probe_subs_lists_entries(tmp_root, monkeypatch, capsys):
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([sub_entry()])],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["probe-subs", "--bvid", "BV1mk8W6dEyx",
-               "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "ai-zh" in out
-
-
-def test_cli_harvest_subs_marks_needs_audio(tmp_root, monkeypatch, capsys):
-    manifest_with(tmp_root)
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([])],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 0
-    store = ManifestStore(root=tmp_root)
-    assert store.get("BV1test00:p0")["status"] == "needs_audio"
-    out = capsys.readouterr().out
-    assert "needs_audio" in out
-
-
-def test_cli_harvest_subs_downloads_and_marks_done(tmp_root, monkeypatch):
-    manifest_with(tmp_root)
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([sub_entry()])],
-        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 0
-    store = ManifestStore(root=tmp_root)
-    assert store.get("BV1test00:p0")["status"] == "subtitle_done"
-    assert os.path.exists(
-        os.path.join(tmp_root, "transcripts", "srt", "BV1test00.p0.srt"))
-
-
-def test_cli_harvest_sessdata_env_not_echoed(tmp_root, monkeypatch, capsys):
-    """BILI_SESSDATA is used but never echoed in output, errors, or files."""
-    manifest_with(tmp_root)
-    monkeypatch.setenv("BILI_SESSDATA", "TOPSECRET123")
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([sub_entry()])],
-        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 0
-    captured = capsys.readouterr()
-    assert "TOPSECRET123" not in captured.out + captured.err
-    text = open(ManifestStore(root=tmp_root).path, encoding="utf-8").read()
-    assert "TOPSECRET123" not in text
-    # ...but it was actually sent to the API
-    player_call = [c for c in transport.calls
-                   if "player/wbi/v2" in c["url"]][0]
-    assert player_call["cookies"].get("SESSDATA") == "TOPSECRET123"
-
-
-def test_cli_harvest_api_error_preserves_status_and_mixed_batch_fails(
-    tmp_root, monkeypatch, capsys
-):
-    store = manifest_with(tmp_root, statuses=("meta_ok", "meta_ok"))
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [
-            (200, {"code": -400}),
-            pagelist_ok(),
-        ],
-        "player/wbi/v2": [player_ok([])],
-    })
-    _cli_routes(monkeypatch, transport)
-    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _seconds: None)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 1
-    entries = ManifestStore(root=tmp_root).load()
-    failed = entries.get("BV1test00") or entries["BV1test00:p0"]
-    assert failed["status"] == "meta_ok"
-    assert failed["last_api_error_code"] == -400
-    assert entries["BV1test01:p0"]["status"] == "needs_audio"
-    assert all(entry.get("status") != "gone" for entry in entries.values())
-    captured = capsys.readouterr()
-    output = captured.out + captured.err
-    assert "SECRET" not in output
-    assert "http" not in output.lower()
-
-
-def test_cli_harvest_budget_exhausted_exit_2(tmp_root, monkeypatch, capsys):
-    manifest_with(tmp_root)
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [(412, None)] * 5,
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 2
-    assert "risk-control" in capsys.readouterr().err
-
-
-def test_cli_harvest_skips_done_and_needs_audio(tmp_root, monkeypatch):
-    store = ManifestStore(root=tmp_root)
-    seed_legacy(
-        store,
-        {"bvid": "BV1done", "status": "subtitle_done", "title": "d",
-         "duration_s": 1, "pubdate": 1},
-        {"bvid": "BV1audio", "status": "needs_audio", "title": "a",
-         "duration_s": 1, "pubdate": 1},
-        {"bvid": "BV1todo", "status": "meta_ok", "title": "t",
-         "duration_s": 1, "pubdate": 1},
-    )
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([sub_entry()])],
-        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 0
-    player_calls = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
-    assert len(player_calls) == 1  # only BV1todo probed
-    assert store.get("BV1done")["status"] == "subtitle_done"
-
-
-def test_cli_harvest_bvid_filter(tmp_root, monkeypatch):
-    manifest_with(tmp_root, statuses=("meta_ok", "meta_ok"))
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([])],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--bvid", "BV1test01",
-               "--archive-root", tmp_root])
-    assert rc == 0
-    store = ManifestStore(root=tmp_root)
-    assert store.get("BV1test00")["status"] == "meta_ok"  # untouched
-    assert store.get("BV1test01:p0")["status"] == "needs_audio"
```
