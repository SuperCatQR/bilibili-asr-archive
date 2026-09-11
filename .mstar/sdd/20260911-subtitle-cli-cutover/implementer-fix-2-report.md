# Implementer Fix Wave 2 — `20260911-subtitle-cli-cutover`

Assignment: `fullstack-dev`, `Task category: backend / CLI`, `Execution mode: sdd (fix round)`,
`Delegation: forbidden`, leaf executor (no subagents). Defect to fix: **`F-QA-001`** (Warning) from the
L4 QA gate at `7e57eb6`.

Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover`
(package root `bilibili-asr-archive/`) · branch `feature/20260911-subtitle-cli-cutover` · **no push**.

## Status

**Complete.** One commit on the working branch, worktree clean, `git diff --check` clean.

| Item | Value |
|---|---|
| Pre-fix HEAD | `7e57eb62d35d33b8effee6b21bac8b0b8f4d70c1` |
| Commit | `0e0ea812bb9f8e28c8ca036a298c61e7730f3201` — `fix(subs): bound the probe's damaged-database answer (F-QA-001)` |
| Files | `src/bili_asr/cli.py` (+19), `tests/test_subtitle_cli.py` (+117), `docs/metadata-storage.md` (+15) — 3 files, +151/−0 |
| Offline suite | **1314 passed, 4 skipped**, exit 0 (baseline 1311/4 + the 3 new cases) |
| Module under fix | `tests/test_subtitle_cli.py` → **84 passed** (was 81 cases) |
| Live network | **none** — `BILI_LIVE_SMOKE` never set; the 4 skips are exactly the opt-in live gates |

Everything the assignment asked for is delivered: the bound, the pinned regression case on both commands,
the doc sentence, and the secondary note's disposition. No `BILI_LIVE_SMOKE`, no credentials read, no
control-checkout write, no push.

## 1. Root cause of `F-QA-001` (reproduced before touching anything)

Reproduced first, in scratch outside both checkouts (`/root/scratch/fix2/`), against the pre-fix HEAD with
module provenance pinned (`bili_asr.cli.__file__` asserted to be the worktree copy; the control venv carries
an editable install of the *control* checkout, so `PYTHONPATH=<worktree>/src` is not optional):

```
$ /root/scratch/fix2/repro.sh <worktree package root>
== provenance ==
/root/workspace/…/.worktrees/20260911-subtitle-cli-cutover/bilibili-asr-archive/src/bili_asr/cli.py
== probe-subs (expect bounded line, exit 1) ==
  File "…/src/bili_asr/storage/database.py", line 116, in _transcripts_columns
    row[1] for row in connection.execute("PRAGMA table_info(transcripts)")
sqlite3.DatabaseError: database disk image is malformed
probe_exit=1
probe_exit=1 stdout_bytes=0 stderr_lines=23
== harvest-subs (control: already correct) ==
harvest-subs: unreadable archive database at …/root.JpzmpP (DatabaseError)
harvest_exit=1
== status (shipped write-capable read path) ==
status: unreadable archive database at …/root.JpzmpP (DatabaseError)
status_exit=1
```

That is the QA gate's measurement reproduced exactly: **23 stderr lines, stdout empty, exit 1** for
`probe-subs`, while `harvest-subs` and the shipped `status` answer the same file with the bounded line.

**The chain.** A damaged-but-openable `archive.db` (intact SQLite header, page 1 body zeroed) passes
`_archive_database_exists`, passes `sqlite3.connect(…?mode=ro)`, and passes
`PRAGMA schema_version` — that pragma is a **header read** (`cli.py:565`), so the read-only open helper's
`except (OSError, sqlite3.Error)` handler (`cli.py:569`) never fires. The damage only surfaces on the next
statement, `require_subtitle_schema(connection)` (`cli.py:643`), whose first read is
`PRAGMA table_info(transcripts)` → `_transcripts_columns` (`storage/database.py:116`) → `sqlite3.DatabaseError`.
Inside `_open_subtitle_connection` only `SchemaContractError` was handled, so the `DatabaseError` escaped the
helper, escaped `_cmd_probe_subs` (whose `try:` starts *after* the open call), and reached the interpreter as a
raw traceback. `harvest-subs` is unaffected because its `open_database` reads `sqlite_master` **inside** the
write-capable helper's bounded handler.

**Blast radius (unchanged from the gate's):** one command, output surface only — the exit code happened to be 1
already because an uncaught exception exits 1; no secret, URL, body or cookie appears in the 23 lines.

## 2. The fix (exact anchors)

`src/bili_asr/cli.py`, inside `_open_subtitle_connection` — a second handler beside the existing
`SchemaContractError` one:

```python
    except (OSError, sqlite3.Error) as exc:          # cli.py:651
        # The guard executes SQL against the file, so a malformed image surfaces
        # on its first read rather than on ``connect``: answer it exactly as
        # both open helpers answer their own statements (F-QA-001).
        connection.close()                            # cli.py:654
        print(
            f"{command}: unreadable archive database at {archive_root} "
            f"({type(exc).__name__})",
            file=sys.stderr,
        )
        return None
```

- **`cli.py:651-660`** — the new handler. It prints the byte-identical line both open helpers print
  (`cli.py:535` for the write-capable path, `cli.py:573` for the read-only path) and returns `None`, which the
  handlers turn into exit 1 (`_cmd_probe_subs` `if connection is None: return 1`).
- **`cli.py:626-632`** — the function docstring gains the paragraph that makes the promise explicit: the guard
  is a *reading* statement, its failure is storage-side, and it is bounded with the same line **and the same
  `(OSError, sqlite3.Error)` class** the two open helpers use.
- The `SchemaContractError` branch is untouched, so a pre-iteration database still answers with the composed
  rebuild line and exit 1.

**Why `(OSError, sqlite3.Error)` and not `sqlite3.Error` alone:** the assignment asks for "the same
`sqlite3.Error` handling the write-capable read path uses", and that path catches `(OSError, sqlite3.Error)`
(`cli.py:533`). Matching the tuple makes the three bounded answers mechanically identical, which is exactly the
parity `_open_read_only_connection`'s docstring claims. Within the guard the practically reachable class is
`sqlite3.Error` (it only executes SQL); the `OSError` term is there for parity, not because I found a path to it.

**Boundary discipline:** `sqlite3.ProgrammingError` is a subclass of `sqlite3.Error`, so my first docstring draft
("a programming error still escapes") was **wrong** and I corrected it before committing to "anything outside
that class escapes as the unexpected internal error the command handlers report" — which is the true statement,
and matches the shipped write path's own bound. This is deliberate: the defect being fixed *was* a documented
promise that was false at runtime, so the new prose is written to the letter of what the code does.

**Completeness of the bound (the "any other statement" clause):** the read-only open's remaining statements
(`connect`, `row_factory`, `PRAGMA foreign_keys`, `PRAGMA schema_version`) are all inside
`_open_read_only_connection`'s handler; the guard was the only statement outside it; and everything after the
open call in both handlers (`repository.list_selected_parts`, `SubtitleIngestor.probe/harvest`) is already
inside their `try/except Exception` → bounded `unexpected error`, exit 2. So there is no second hole of this
class on either command's open path.

## 3. The pinned regression case and its revert-proof

`tests/test_subtitle_cli.py:1385-1499`, new section `# ---- damaged and empty databases`:

- `_damage_page_one` (`:1387`) — zeroes page 1's body from offset 64, leaving the 100-byte SQLite header intact:
  the canonical "database disk image is malformed" state.
- `_overwrite_with_text` (`:1401`) — replaces the file with bytes carrying no SQLite magic.
- `test_an_unreadable_archive_database_is_one_bounded_line_on_both_commands[damaged-page-1 | not-a-database]`
  (`:1415`) — a real seeded archive, damaged, then driven through **both** commands end to end via
  `bili_asr.cli.main`.

Per case it asserts: **byte-exact** stderr
(`probe-subs: unreadable archive database at <root> (DatabaseError)\n` and the same with `harvest-subs:`), empty
stdout, exit 1, the exact file set under the root (`archive.db` alone for the probe — no lock; `archive.db` plus
`coordinator/archive-writer.lock`, the documented writer lock, for the harvest), and that the damaged file's
bytes are **unchanged** afterwards (no repair, rewrite or replacement by either command).

This pins **all three** `unreadable archive database` handlers, which had no test anywhere before
(`grep -rn "unreadable archive database" tests/ docs/ README.md` previously matched nothing): the two open
helpers through the `not-a-database` recipe, and the transcript-schema guard through the `damaged-page-1`
recipe, for both commands. That closes seat 1's observation recorded in the plan (`20260911-subtitle-cli-cutover.md`:
"the two `<command>: unreadable archive database at …` branches … have neither a test nor a doc sentence").

### Revert-proof (non-vacuity), executed and restored

The fix was stashed (`git stash push -- src/bili_asr/cli.py`), the new tests re-run against the pre-fix code,
then the fix restored and byte-compared against a scratch backup (`diff -q` → identical; `git stash list`
shows no leftover of mine):

```
$ pytest tests/test_subtitle_cli.py -q -k unreadable          # with the fix stashed (pre-fix HEAD code)
src/bili_asr/storage/database.py:116: in _transcripts_columns
    row[1] for row in connection.execute("PRAGMA table_info(transcripts)")
E   sqlite3.DatabaseError: database disk image is malformed
FAILED tests/test_subtitle_cli.py::test_an_unreadable_archive_database_is_one_bounded_line_on_both_commands[damaged-page-1]
1 failed, 1 passed, 81 deselected in 0.64s
```

**Named failing case (reverted):**
`test_an_unreadable_archive_database_is_one_bounded_line_on_both_commands[damaged-page-1]` — the raw
`sqlite3.DatabaseError` escapes `main` exactly as the QA gate measured. The `not-a-database` parametrization
passes pre-fix **as expected**: that branch (`_open_read_only_connection`'s own handler) was already correct —
this test pins it rather than pretending it was broken.

**Green with the fix:**

```
$ pytest tests/test_subtitle_cli.py -v -k "unreadable or zero_byte"
tests/test_subtitle_cli.py::test_an_unreadable_archive_database_is_one_bounded_line_on_both_commands[damaged-page-1] PASSED
tests/test_subtitle_cli.py::test_an_unreadable_archive_database_is_one_bounded_line_on_both_commands[not-a-database] PASSED
tests/test_subtitle_cli.py::test_a_zero_byte_database_is_initialized_by_harvest_and_refused_by_probe PASSED
3 passed, 81 deselected in 0.56s
```

## 4. Secondary note — the empty-file asymmetry: **documented, not aligned**

First reproduced at runtime (probe on a 0-byte `archive.db` → rebuild line, exit 1, file still 0 bytes;
harvest on the same file → initializes it to 139264 bytes, `attempted=0`, exit 0):

```
$ probe-subs   --limit-parts 1 --archive-root <0-byte root>   # probe_exit=1 size=0
probe-subs: archive database predates the transcript schema; rebuild it (delete …/archive.db and re-run fetch-meta)
$ harvest-subs --limit-parts 1 --archive-root <same root>     # harvest_exit=0 size=139264
harvest-subs: run_id=… attempted=0 stored=0 unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=0
```

**Disposition: documented.** Aligning was rejected because both sides are *locked* promises and neither can move
inside a fix wave:

- `open_database` initializing both idempotent schema scripts into an existing file is the shipped semantics
  `fetch-meta`, `status`, `runs` and `harvest-subs` share; changing it for the empty-file case is a storage-contract
  change, not a CLI bound.
- Making the probe initialize the file instead would break its structural "writes nothing at all, creates no file"
  promise, which `test_the_probe_opens_the_archive_read_only_and_cannot_write` pins (and the plan's QC2-003 fixed).

So the asymmetry is the honest consequence of two locked rules, and it is now (a) documented and (b) pinned:

- `docs/metadata-storage.md:272` — a paragraph in "Schema guard and rebuild" naming the zero-byte state, why
  `harvest-subs` initializes it and runs `attempted=0`/exit 0, and why the probe refuses it with the rebuild line
  and exit 1.
- `tests/test_subtitle_cli.py:1461` — `test_a_zero_byte_database_is_initialized_by_harvest_and_refused_by_probe`
  pins exactly that, including that the probe leaves the file at 0 bytes and creates nothing, and that the harvest
  really created the transcript contract (`SELECT COUNT(*) FROM transcripts` = 0 reads, i.e. the table exists).

**(Disclosure: this test is one case beyond the letter of the assignment.)** I added it because the note asked for
*either* documentation *or* alignment, and a documented behaviour with no runnable check is precisely the shape of
gap that produced `F-QA-001` (a docstring promise nothing verified). It is 30 lines, offline, and in the same
"database state" section as the required case.

## 5. Every other case is semantically identical — runtime matrix

Both commands against four archive states, post-fix, at the committed HEAD (offline; the healthy/empty selections
make no gateway call):

| `archive.db` state | `probe-subs` | `harvest-subs` |
|---|---|---|
| healthy (both schemas) | exit 0, `probe-subs: probed=0 with_tracks=0 without_tracks=0 failed=0` | exit 0, `attempted=0 stored=0 unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=0` |
| missing | exit 1, `no archive database at <root>; run fetch-meta to create it` | exit 1, same line with `harvest-subs:` |
| pre-iteration schema | exit 1, `archive database predates the transcript schema; rebuild it (delete <root>/archive.db and re-run fetch-meta)` | exit 1, same rebuilt line |
| damaged-but-openable | exit 1, `unreadable archive database at <root> (DatabaseError)` — **the fix** | exit 1, same line (was already correct) |

Only the last row changed; the first three rows are byte-identical to the gate's measurements. The matrix ran in
scratch (`/root/scratch/fix2/matrix.py`), importing the worktree's `bili_asr` and `test_storage_schema` explicitly.

## 6. Tests — commands and outputs

TDD triple (test file, command, output) for this fix wave:

- **Test file:** `bilibili-asr-archive/tests/test_subtitle_cli.py`
- **Commands and outputs** (control interpreter, per the assignment; the worktree has no `.venv`):

```
$ cd /root/workspace/…/.worktrees/20260911-subtitle-cli-cutover/bilibili-asr-archive
$ /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_subtitle_cli.py -q
84 passed in 3.01s

$ /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q -rs
SKIPPED [1] tests/test_bilibili_api_gateway.py:3380: live smoke is opt-in: set BILI_LIVE_SMOKE=1 to request it
SKIPPED [1] tests/test_live_metadata_smoke.py:329: live smoke is opt-in: set BILI_LIVE_SMOKE=1 to request it
SKIPPED [1] tests/test_live_subtitle_cli_smoke.py:271: live subtitle CLI smoke is opt-in: set BILI_LIVE_SMOKE=1 to request it
SKIPPED [1] tests/test_live_subtitle_smoke.py:438: live subtitle probe is opt-in: set BILI_LIVE_SMOKE=1 to request it
1314 passed, 4 skipped in 49.27s
```

**1314 = the plan's 1311 baseline + the 3 new cases**, run twice on the frozen final state, both exit 0. The
pre-existing green baseline was never red during this wave.

## 7. Disclosure — every assertion and doc sentence added or changed

**No existing assertion was changed, weakened, or deleted** (the diff is insertions only: `+151/−0`). Added:

Tests (`tests/test_subtitle_cli.py`):

1. `test_an_unreadable_archive_database_is_one_bounded_line_on_both_commands[damaged-page-1]` — byte-exact
   `probe-subs: unreadable archive database at {tmp_root} (DatabaseError)\n` and `harvest-subs: …` line; empty
   stdout; exit 1 for both; file set `["archive.db"]` after the probe and
   `sorted(["archive.db", "coordinator/archive-writer.lock"])` after the harvest; database bytes unchanged.
2. `…[not-a-database]` — the same eight assertions through the other recipe.
3. `test_a_zero_byte_database_is_initialized_by_harvest_and_refused_by_probe` — probe: byte-exact rebuild line,
   empty stdout, exit 1, `os.path.getsize == 0`, file set `["archive.db"]`; harvest: exit 0, `sessdata: absent` +
   `attempted=0 stored=0 … remaining_without_transcript=0` summary, `SELECT COUNT(*) FROM transcripts` readable,
   file set with the lock.
4. Helpers `_damage_page_one`, `_overwrite_with_text`, section comment — no assertions, but disclosed for
   completeness.

Docs (`docs/metadata-storage.md`):

5. `:169` — new paragraph (one sentence) in the subtitle **Exit codes** section: an existing-but-unreadable
   `archive.db` (not a SQLite file / truncated / damaged-but-openable) is answered by both commands on **stderr**
   with the single bounded line `<command>: unreadable archive database at <archive-root> (<ErrorType>)` and exit
   `1`, the same line `status`/`runs` print, and no command repairs or rewrites it.
6. `:272` — new paragraph in **Schema guard and rebuild**: the zero-byte asymmetry (item 4 above).

I considered but did **not** change the exit-1 row of the acquisition exit-code table, nor the pointer summary at
`:589+` ("`1` usage/configuration or the transcript-schema guard"): the new paragraph sits directly under that
table and states the exit code, so both remain accurate without an extra edit. No other doc, README, or comment
was touched.

## 8. Files changed

| File | Change |
|---|---|
| `bilibili-asr-archive/src/bili_asr/cli.py` | `_open_subtitle_connection`: new `except (OSError, sqlite3.Error)` handler (`:651-660`) + docstring paragraph (`:626-632`) |
| `bilibili-asr-archive/tests/test_subtitle_cli.py` | 2 damage recipes + parametrized bounded-line test (both commands) + zero-byte asymmetry test (`:1385-1499`, +117) |
| `bilibili-asr-archive/docs/metadata-storage.md` | bounded-line sentence (`:169`) + zero-byte asymmetry paragraph (`:272`, +15 total) |

## 9. Mutation hygiene and no-network confirmation

- **No live network:** `BILI_LIVE_SMOKE` was never set (the suite's 4 skips are the opt-in live gates); no
  credential was read, echoed, or sourced; only `--limit-parts` selections that resolve to zero parts were run
  outside pytest, and those make no gateway call. Credentials: presence-only, nothing inspected. No `--sessdata`,
  no `BILI_SESSDATA` in any command I ran.
- **Scratch outside both checkouts:** `/root/scratch/fix2/` (reproduction script, damage roots, `matrix.py`,
  `cli.py.fixed` backup). Nothing was written under the control checkout
  (`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/`) except this report's sanctioned harness path
  (`.mstar/sdd/<plan-id>/`, gitignored). The control checkout does show three modified harness files —
  `specs/subtitle-cli-contract.md` (mtime 17:32), `plans/20260911-subtitle-cli-cutover.md` (18:30, the QA gate's
  `## QA Gate Summary`) and `workflows/…/snapshot.json` (16:20) — all of them **predate this wave** (my session
  began ~18:31) and are the PM's/QA's own edits; none is mine. The only file I wrote outside the worktree is
  this report (18:38).
- **Worktree:** `git status --porcelain` is empty at `0e0ea81`; `git diff --check` was clean before the commit;
  the only harness file written is this report. No push, no merge, no touch of `main` or the integration branch.
- The pre-existing stash entry `stash@{0}` ("preserve pre-existing control edits before ASR integration") belongs
  to the iteration branch's history, not to this wave; my temporary stash was popped and verified gone.

## 10. Self-review notes

1. **Root cause fixed at the narrowest point that covers all callers.** `require_subtitle_schema` has exactly two
   callers: the CLI guard (fixed here) and `TranscriptRepository` construction in storage
   (`storage/database.py:754`), which is not on this path and whose contract is to raise. The CLI guard is where
   the operator-facing bound belongs, and the fix is in the shared helper both subtitle commands go through — not
   in each handler.
2. **No duplication introduced in behaviour:** the three `unreadable archive database` prints are now three
   literal copies of the same message. I deliberately did **not** extract a helper: that would have re-written two
   already-verified, already-reviewed lines of the shipped read path for a cosmetics win, against the wave's
   surgical-scope rule. Recorded as a nit, not implemented — a future plan touching those helpers may fold the
   three into one `_print_unreadable_database(command, root, exc)`.
3. **The bound is on storage-side classes only.** `except (OSError, sqlite3.Error)` around a call that executes
   SQL; no `except BaseException`, no blanket `except Exception` added, and no change to the exit taxonomy
   (exit 1 for configuration/unreadable, exit 2 for unexpected/internal — both unchanged and still covered by the
   existing parametrizations).
4. **Locked shapes untouched:** no printed line, count, order, or exit code other than the damaged-database
   surface changes; the full suite (including the locked-line and no-leak scans) is green and the runtime matrix
   above re-checks the four states end to end.
5. **The regression test would have caught the gate's finding**: it drives `main` (not the helper) with a real
   damaged database, so it fails on the *output surface* — the exact thing the gate measured — and not merely on
   an internal return value.
6. **Weakness, stated honestly:** the SQLite failure modes other than "malformed image" and "not a database"
   (locked database, permission denied, I/O error mid-query) are still not enumerated by tests; the `OSError`
   half of the handler remains parity-by-inspection, exactly as the gate described the write path's own bound.
   Also, `_damage_page_one`'s byte offsets assume the default 4096-byte page size, which holds for the
   archive's own schema at this size.
7. **Nothing was marked Done, no harness artifact other than this report was edited**, and the plan's acceptance
   boxes remain the PM's/QA's to tick — `F-QA-001` is answered here and awaits the QA re-verify the gate's
   "Recommended owners" table asks for.
