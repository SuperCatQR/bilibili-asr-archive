# Plan-3 QA Fix Wave Diff — 20260911-subtitle-cli-cutover

Base: `7e57eb6`
Head: `0e0ea81`
Scope: F-QA-001 (bound the probe's damaged-database answer) + the pinned cases + the docs sentence

```diff
diff --git a/bilibili-asr-archive/docs/metadata-storage.md b/bilibili-asr-archive/docs/metadata-storage.md
index 3fc764d..e134b6c 100644
--- a/bilibili-asr-archive/docs/metadata-storage.md
+++ b/bilibili-asr-archive/docs/metadata-storage.md
@@ -166,6 +166,13 @@ is presented as coverage of the corpus.
 | 1 | Usage/configuration: a missing `archive.db`, an unknown `--bvid`, a missing or non-positive bound, neither or both `probe-subs` selectors, an empty `--language` entry, or the transcript-schema guard below. |
 | 2 | The run failed on **every** attempted part, or an unexpected internal error (the fixed line `<command>: unexpected error`, no traceback). |
 
+An `archive.db` that exists but cannot be read — a file that is not a SQLite
+database at all, a truncated one, or a damaged image whose header still opens —
+is answered by both commands on **stderr** with the single bounded line
+`<command>: unreadable archive database at <archive-root> (<ErrorType>)` and
+exit `1`, the same line `status` and `runs` print for that file, which no
+command repairs or rewrites.
+
 Partial failure stays visible in the counts and does not by itself decide the
 exit code: a harvest that stored one part and failed another exits `0` with
 `failed=1` on its summary line. In both exit-2 variants the run row is finished
@@ -262,6 +269,14 @@ It is one line; the wrap below is the page's, not the command's:
 <command>: archive database predates the transcript schema; rebuild it (delete <archive-root>/archive.db and re-run fetch-meta)
 ```
 
+A zero-byte `archive.db` — a file that exists but was never initialized — is the
+one state the two commands read differently, and the difference is the point:
+`harvest-subs` opens through the schema-initializing `open_database`, so it
+creates both schemas in that file and runs normally (a selection resolving to no
+part reports `attempted=0`, exit `0`), while `probe-subs` writes nothing at all,
+so its read-only open finds no transcript contract and answers with the rebuild
+line above (exit `1`).
+
 The metadata commands (`fetch-meta`, `status`, `runs`) keep working on that same
 database unchanged. There is no in-place migration: the rebuild procedure is to
 delete `archive.db`, re-run `fetch-meta` to recreate it from the checked-in
diff --git a/bilibili-asr-archive/src/bili_asr/cli.py b/bilibili-asr-archive/src/bili_asr/cli.py
index 275aa68..d6452b0 100644
--- a/bilibili-asr-archive/src/bili_asr/cli.py
+++ b/bilibili-asr-archive/src/bili_asr/cli.py
@@ -622,6 +622,14 @@ def _open_subtitle_connection(
     is then structural: its connection is the ``mode=ro`` one from
     :func:`_open_read_only_connection`, never the schema-initializing
     ``open_database`` the write commands and the other read commands share.
+
+    The capability guard reads the database, so a damaged-but-openable file
+    (intact header, corrupted page) fails here rather than when the connection
+    is opened.  That failure is storage-side — the guard only executes SQL — and
+    it is bounded with the same fixed ``unreadable archive database`` line, and
+    the same ``(OSError, sqlite3.Error)`` class, both open helpers use for their
+    own statements; anything outside that class escapes as the unexpected
+    internal error the command handlers report.
     """
     from bili_asr.storage import SchemaContractError, require_subtitle_schema
 
@@ -640,6 +648,17 @@ def _open_subtitle_connection(
             _subtitle_schema_rebuild_line(command, archive_root), file=sys.stderr
         )
         return None
+    except (OSError, sqlite3.Error) as exc:
+        # The guard executes SQL against the file, so a malformed image surfaces
+        # on its first read rather than on ``connect``: answer it exactly as
+        # both open helpers answer their own statements (F-QA-001).
+        connection.close()
+        print(
+            f"{command}: unreadable archive database at {archive_root} "
+            f"({type(exc).__name__})",
+            file=sys.stderr,
+        )
+        return None
     return connection
 
 
diff --git a/bilibili-asr-archive/tests/test_subtitle_cli.py b/bilibili-asr-archive/tests/test_subtitle_cli.py
index 758c69c..8c57576 100644
--- a/bilibili-asr-archive/tests/test_subtitle_cli.py
+++ b/bilibili-asr-archive/tests/test_subtitle_cli.py
@@ -1380,3 +1380,120 @@ def test_both_commands_print_the_fixed_rebuild_line_for_a_legacy_database(
 
     assert main(["status", "--archive-root", tmp_root]) == 0
     assert capsys.readouterr().out.startswith("users: 1")
+
+
+# ------------------------------------------- damaged and empty databases
+
+def _damage_page_one(database_path: str) -> None:
+    """Corrupt page 1's body and leave the SQLite header intact.
+
+    The canonical "database disk image is malformed" state an unclean
+    shutdown, a full disk, or a partial copy leaves behind: the header still
+    answers a ``PRAGMA schema_version``, so the damage surfaces only on the
+    first statement that reads ``sqlite_master``.
+    """
+
+    with open(database_path, "r+b") as handle:
+        handle.seek(64)
+        handle.write(b"\x00" * 4096)
+
+
+def _overwrite_with_text(database_path: str) -> None:
+    """Leave a file carrying no SQLite magic at all in the database's place."""
+
+    with open(database_path, "wb") as handle:
+        handle.write(b"not a database\n")
+
+
+@pytest.mark.parametrize(
+    "damage",
+    [
+        pytest.param(_damage_page_one, id="damaged-page-1"),
+        pytest.param(_overwrite_with_text, id="not-a-database"),
+    ],
+)
+def test_an_unreadable_archive_database_is_one_bounded_line_on_both_commands(
+    tmp_root: str, capsys, damage
+) -> None:
+    """An existing but unreadable database: one bounded line, exit 1, no repair.
+
+    Every ``unreadable archive database`` handler is pinned here: the two open
+    helpers (``_open_read_connection`` for ``harvest-subs``,
+    ``_open_read_only_connection`` for ``probe-subs``) through the
+    not-a-database recipe, and the transcript-schema guard inside
+    ``_open_subtitle_connection`` through the damaged-but-openable one, whose
+    intact header passes the helper's ``PRAGMA schema_version``.  Before
+    F-QA-001 that guard sat outside the bounded handler, so the probe printed a
+    raw SQLite traceback instead of the line its own docstring promised.
+    Neither command repairs, rewrites, or replaces the damaged database, and a
+    harvest leaves only the documented writer lock beside it.
+    """
+
+    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    damage(database_path)
+    damaged_bytes = Path(database_path).read_bytes()
+
+    assert main(["probe-subs", "--bvid", BVID_A, "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err == (
+        f"probe-subs: unreadable archive database at {tmp_root} (DatabaseError)\n"
+    )
+    # The probe is not an archive-writer command: no lock, no other file.
+    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
+    assert Path(database_path).read_bytes() == damaged_bytes
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err == (
+        f"harvest-subs: unreadable archive database at {tmp_root} (DatabaseError)\n"
+    )
+    # A harvest is an archive-writer command, so the documented writer lock is
+    # the only other file it leaves.
+    assert _archive_files(tmp_root) == sorted(
+        [ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH]
+    )
+    assert Path(database_path).read_bytes() == damaged_bytes
+
+
+def test_a_zero_byte_database_is_initialized_by_harvest_and_refused_by_probe(
+    tmp_root: str, capsys
+) -> None:
+    """The documented empty-file asymmetry: the harvest initializes, the probe refuses.
+
+    ``open_database`` initializes both schema scripts into an existing zero-byte
+    file, and that is the shipped semantics ``fetch-meta``, ``status``, ``runs``,
+    and ``harvest-subs`` share.  ``probe-subs`` promises to write nothing at all,
+    so it refuses the same file with the rebuild line rather than creating the
+    transcript contract in it.  Documented in ``docs/metadata-storage.md``
+    ("Schema guard and rebuild").
+    """
+
+    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
+    with open(database_path, "wb"):
+        pass
+
+    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err == (
+        f"probe-subs: archive database predates the transcript schema; "
+        f"rebuild it (delete {database_path} and re-run fetch-meta)\n"
+    )
+    # The read-only promise holds structurally: the file is still empty.
+    assert os.path.getsize(database_path) == 0
+    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    captured = capsys.readouterr()
+    lines = captured.out.splitlines()
+    assert lines[0] == "sessdata: absent"
+    assert "attempted=0 stored=0 unchanged=0 no-subtitle=0 failed=0" in lines[1]
+    assert lines[1].endswith("remaining_without_transcript=0")
+    # Initialized for real: the transcript contract is in the file now.
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 0
+    assert _archive_files(tmp_root) == sorted(
+        [ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH]
+    )
```
