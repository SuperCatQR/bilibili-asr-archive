# Implementer Fix-3 Report — `F-QA-002` (docstring accuracy, comment-only)

**plan_id**: `20260911-subtitle-cli-cutover`
**Worktree**: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover` (package root `bilibili-asr-archive/`)
**Branch**: `feature/20260911-subtitle-cli-cutover` (base `0e0ea81`; no push, integration branch untouched)
**Execute as**: `fullstack-dev` · **Delegation**: forbidden (leaf — no subagents started)
**Task category**: backend / CLI — one-line documentation correction
**Execution mode**: sdd (fix round)

## Status

**COMPLETE.** One commit, one file, docstring text only.

| Item | Value |
|---|---|
| Commit | `d742fc2` — `docs(subs): state how an out-of-class guard failure really escapes` |
| Parent | `0e0ea81` (the `F-QA-001` fix-wave head the Assignment names) |
| Files changed | `bilibili-asr-archive/src/bili_asr/cli.py` — **+4 / −2**, one file |
| Executable lines changed | **none** (proof in §4) |
| `git diff --check` | clean (before and after the commit; working tree clean at HEAD) |
| Focused suite | `tests/test_subtitle_cli.py` — **84 passed** |
| Full offline suite | **1314 passed, 4 skipped** |
| Live network run | not performed (out of scope: `F-QA-002` is a comment on an offline path; no `BILI_LIVE_SMOKE`, no credential file sourced) |

## 1. The finding, re-verified before changing anything

`F-QA-002` (`review/qa-gate.md` §R7) says the docstring sentence added by the previous fix wave is false at
runtime. I re-checked the three code facts it rests on rather than taking them on trust:

- `_open_subtitle_connection` is called at `src/bili_asr/cli.py:876` (`_cmd_probe_subs`) and
  `src/bili_asr/cli.py:979` (`_cmd_harvest_subs`), and both calls sit **before** their handler's
  `try:` (the `try` opens at `:878` and `:981` respectively; each is preceded by
  `if connection is None: return 1`). Confirmed by reading both call sites.
- `_dispatch_command` ends in `raise ValueError(...)` for an unimplemented command and wraps the
  handlers in no `try` of its own; `main` (`cli.py:2600-2613`) catches **only** `ArchiveBusyError`.
  There is no broad catch anywhere on this path.
- Therefore a non-`(OSError, sqlite3.Error)` exception raised by the capability guard is uncaught and
  reaches the interpreter as a traceback with exit `1` — never the bounded
  `<command>: unexpected error` line, which is printed by the handlers' own `except Exception:` blocks
  at `cli.py:902` and `cli.py:1005` (exit `2`).

**Injection re-measurement (local, offline, no repo writes).** Healthy `archive.db` built through the
shipped `open_database` in a `/tmp` root, then the CLI driven in a subprocess with
`bili_asr.storage.require_subtitle_schema` replaced by a stub raising
`TypeError("guard programming error")` (the function-level import inside the guard makes the module
attribute patch effective):

```
exit: 1
stdout: ''
stderr lines: 18
stderr head: Traceback (most recent call last):
               File "/tmp/guard_runner.py", line 8, in <module> ...
               File ".../src/bili_asr/cli.py", line 2613, in main
has traceback: True
bounded unexpected-error line: False
```

18-line raw traceback, no bounded line, exit `1` — the finding reproduces exactly as the QA gate
described it. (This is a guard-level injection, not a user-reachable input; the QA gate's own
Suggestion severity stands, and I did not re-litigate it.)

## 2. The exact line, before and after

File: `bilibili-asr-archive/src/bili_asr/cli.py`, inside `_open_subtitle_connection`'s docstring.

**Before** — `cli.py:631-632`:

```
    own statements; anything outside that class escapes as the unexpected
    internal error the command handlers report.
```

**After** — `cli.py:631-634`:

```
    own statements.  Anything outside that class is a programming error and is
    not bounded here: this function runs before the command handlers' ``try``
    blocks, so it reaches the interpreter as an uncaught traceback and exit 1,
    never their ``unexpected error`` line.
```

The clause now states the observable behaviour (programming error → uncaught traceback → exit 1) and
names why (this function runs before the handlers' `try` blocks). The rest of the paragraph — the
storage-side half asserting that a damaged-but-openable file's `sqlite3.Error`/`OSError` is bounded with
the same fixed `unreadable archive database` line both open helpers use — is runtime-verified by the QA
gate (`qa-gate.md` §R3) and is deliberately left intact. Lines 628 and 630 of the paragraph exceed 79
**bytes** only because of their em dashes; they are unchanged pre-existing lines, and every line I
touched is ≤ 78 characters.

Full diff of the commit:

```diff
@@ -628,8 +628,10 @@ def _open_subtitle_connection(
     is opened.  That failure is storage-side — the guard only executes SQL — and
     it is bounded with the same fixed ``unreadable archive database`` line, and
     the same ``(OSError, sqlite3.Error)`` class, both open helpers use for their
-    own statements; anything outside that class escapes as the unexpected
-    internal error the command handlers report.
+    own statements.  Anything outside that class is a programming error and is
+    not bounded here: this function runs before the command handlers' ``try``
+    blocks, so it reaches the interpreter as an uncaught traceback and exit 1,
+    never their ``unexpected error`` line.
     """
     from bili_asr.storage import SchemaContractError, require_subtitle_schema
```

## 3. Step 2 of the Assignment — was the docs claim checked?

Yes, checked before assuming, and **no correction was needed**, so `docs/metadata-storage.md` is
**unchanged** by this commit. Evidence:

- The two paragraphs that commit `0e0ea81` added to that file are (a) the `unreadable archive database`
  bounded-line paragraph in the exit-code taxonomy and (b) the zero-byte asymmetry paragraph. Both
  describe behaviour the QA gate verified against a real damaged/not-a-database/truncated file at this
  HEAD (§R3, §R8) — neither repeats the guard's out-of-class claim.
- The sentence that *does* mention an unexpected internal error, the pre-existing table row
  `docs/metadata-storage.md:167` (`| 2 | The run failed on every attempted part, or an unexpected
  internal error (the fixed line <command>: unexpected error, no traceback). |`), is about the
  **run** — the handlers' own `try`, which is exactly where that bounded line is real. It predates this
  iteration's fix waves (it is context in the diff, not an added line) and it is **true**; correcting it
  would introduce a new falsehood and would also exceed a comment-only correction of the reported
  finding. Same reading for the summary line at `docs/metadata-storage.md:608`.
- Cross-checked by grep for `unexpected error` / `traceback` / `escapes` across `docs/`: no other
  passage claims the guard's out-of-class exceptions are bounded.

## 4. Confirmation that no executable line changed

Two independent checks:

1. **Diff shape** — the commit is +4 / −2 across a single contiguous hunk, and every changed line lies
   between the docstring's opening `"""` and its closing `"""` (`cli.py:613-635`). No import, no
   statement, no handler and no print call is touched; `git show --stat HEAD` is one file,
   `src/bili_asr/cli.py`.
2. **AST equality** — parse `HEAD~1:…cli.py` and the working file, strip every module/class/function
   docstring recursively, and compare `ast.dump`:

   ```
   executable AST identical after docstring strip: True
   ```

   So the compiled program is unchanged, not merely "looks" unchanged. This matches the Assignment's
   premise that a comment-only change cannot move any count.

## 5. Verification runs

Focused, exactly the Assignment's command:

```
$ cd .../.worktrees/20260911-subtitle-cli-cutover/bilibili-asr-archive && \
  /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_subtitle_cli.py -q
........................................................................ [ 85%]
............                                                             [100%]
84 passed in 2.72s
```

Full offline suite, immediately after (same interpreter, same worktree, nothing else changed):

```
$ …/python -m pytest -q
........................................................................ [ 71%]
…
1314 passed, 4 skipped in 47.86s
```

Both match the expected counts (**84 passed** / **1314 passed, 4 skipped**), so the correction moved no
count — as required for a comment-only edit. `git diff --check` was clean before the commit and the
working tree is clean at `d742fc2`.

## 6. Files changed

| File | Change |
|---|---|
| `bilibili-asr-archive/src/bili_asr/cli.py` | docstring sentence inside `_open_subtitle_connection` corrected (+4 / −2); no executable line |
| `.mstar/sdd/20260911-subtitle-cli-cutover/implementer-fix-3-report.md` | this report (harness file; the only harness path written) |

`docs/metadata-storage.md` deliberately **not** changed (§3). No plan, snapshot, status, spec or compass
file was touched; nothing was pushed; the integration branch and `main` were not touched.

## 7. Residual / follow-up

None raised by this wave. `F-QA-002` has no defect state to track (the QA gate's own §R9 re-confirmed
that the register should stay as it is), and no new behaviour was introduced, so I registered no
residual and left `{PROJECT_DIR}/_default/residuals.json` untouched. Whether `F-QA-002` is now closed is
the PM's/QA's call on re-verification of `d742fc2`.
