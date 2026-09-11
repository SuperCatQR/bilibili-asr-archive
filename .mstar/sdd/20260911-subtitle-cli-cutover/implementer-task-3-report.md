# Task 3 report — Bounded live smoke and operator documentation

- Plan: `20260911-subtitle-cli-cutover` (task 3 of 3, final), SDD, leaf implementer (no subagent dispatched)
- Branch: `feature/20260911-subtitle-cli-cutover` @ `8373817` (base `c501d9a`, Task 2 review Approved)
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover` (package root `bilibili-asr-archive/`)
- Test interpreter: `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python` (control venv; the worktree has none)
- **Status: DONE_WITH_CONCERNS** — every brief item and documentation obligation landed, and the
  acceptance-carrying live run produced a real subtitle acquisition through the shipped CLI. The single
  concern is a **disclosed process deviation on the live budget** (three live invocations instead of one plus
  one throttle retry); see "Live evidence → Invocation ledger". No acceptance item is unmet and no run
  contradicts another.

## Implemented (per brief item + the documentation obligations)

| Brief item | Where it landed |
|---|---|
| Opt-in live smoke: temporary archive root, bounded `--limit-parts`, credential and proxy from the documented environment, skip by default, loud-fail when opted in without the pinned distribution, reusing the metadata smoke's bounded structure | **new** `tests/test_live_subtitle_cli_smoke.py` — `test_live_smoke_one_part_through_probe_and_harvest` (skip-by-default gate, `_pinned_package_version()` loud-fail guard, `tmp_root` as the temporary archive root, `--limit-parts 1` on both commands) |
| Run it once and record the outcome (parts attempted, tracks found, transcripts stored, or the explicit bounded blocker including the code), never printing URLs, bodies, or credentials | Ran live; see "Live evidence" below. The smoke's readers parse the locked line shapes and its evidence line carries only counts, codes, and presence tokens; a credential-value scan over the captured log returned **0 occurrences** |
| `docs/metadata-storage.md` + README: the subtitle path on SQLite | `docs/metadata-storage.md` §"Subtitle acquisition (`probe-subs` / `harvest-subs`)" (intro + §"Media and transcript tables"); `README.md` §"Subtitle acquisition on SQLite (`probe-subs` / `harvest-subs`)" |
| … the two commands with bounds, exit codes and output shapes | `docs` §Output + §Exit codes (both command synopses, the exact `probe` / `track` / `probe-subs:` and `harvest` / `harvest-subs:` line grammars); same content condensed in the README bullet list |
| … the preference rule and why it is defined on the language family | `docs` §"Track selection preference" (family derivation from `language` + `is_ai`, the `zh`/`en`/rest order, CC before AI; why a fixed code list and an equivalence table are both rejected) + README bullet |
| … the credential handling | `docs` §"Credential boundary" (extended) + §"Subtitle acquisition → Credential handling" + README bullet: same `--sessdata`/`BILI_SESSDATA` resolution and presence-only redaction, `harvest-subs` records the presence in its run row |
| … the schema guard and rebuild procedure (delete `archive.db`, re-run `fetch-meta`) | `docs` §"Schema guard and rebuild" (the exact printed line and the procedure) + README bullet |
| … the two schema resources | `docs` §"Fresh-start behavior" (`schema.sql` + `schema-transcripts.sql`, including the pre-contract skip behavior) + README bullet |
| … that the legacy ASR/pilot path still reads the manifest | `docs` §"Boundary with the legacy manifest path" + README bullet + a boundary sentence added to the README's `run` four-stage description |
| … that `harvest-subs` no longer produces `needs_audio` | Same three places: the ASR/pilot chain does not see these transcripts, and `download-audio --missing-subs` gains no new entries |
| **M1** — the probe-vs-harvest `not_found` asymmetry, both readings stated | `docs` §"Exit codes → A `not_found` listing is read differently…" (`probe <work_id> failed not_found` with `failed=` and all-failed exit `2`; `harvest` records `no-subtitle`, exit `0`) + README bullet; the asymmetry is also rehearsed offline against both sides |
| **⚠️2** — the writer lock `harvest-subs` takes and that `probe-subs` takes none | `docs` §"Archive writer lock" (what it is, `{archive-root}/coordinator/archive-writer.lock`, the `harvest-subs: archive_busy` exit, "probe-subs is deliberately not an archive-writer command") + README bullet; the README's writer-isolation command list was corrected |
| **⚠️6** — the ASR/pilot chain reads the manifest, so `download-audio --missing-subs` gains nothing | `docs` §"Boundary with the legacy manifest path" + README bullet + the `run` section sentence |
| Folded **`ProbeResult.credential_present`** assertion (Task-2 L2 follow-up) | `test_probe_result_carries_the_credential_presence_the_cli_observed` — the real `SubtitleIngestor.probe` is wrapped so the service-side value is observable from the command path; two CLI runs pin `[False, True]` against the printed `sessdata: absent` / `sessdata: present`, and the value reaching the adapter is pinned too. The live run additionally records `sessdata=present` alongside `part_source`, as the follow-up asked |
| **QC3-003** — `docs/metadata-storage.md`'s now-false "no … transcripts are written yet" sentence | Replaced, not appended. Exact old text removed: heading `### Reserved media boundary (empty in this plan)` and the paragraph "`audio_objects`, `part_audio_objects`, `asr_models`, `transcripts`, and `transcript_segments` are created now so later media and transcript plans attach through these foreign keys instead of reintroducing sidecars. They stay empty in this plan; no media bytes or transcripts are written yet." New text: §"Media and transcript tables" — `transcripts`/`transcript_segments` are written by `harvest-subs` and read through the views; `audio_objects`/`part_audio_objects`/`asr_models` are still empty because the audio/ASR chain records in the manifest |

### Smoke design (why the part is authored, and what each branch does)

Both commands address parts the database already stores (`harvest-subs` never fetches a pagelist), so a
temporary archive root has to contain one part before any live run is expressible. The smoke seeds exactly one
part through the shipped repository and uses the **gateway plan's live-validated sample** for its identity
(`BV1S8hA6MEvy`, cid `41314223900`, page 0 → `BV1S8hA6MEvy:p0`), recorded as `part_source=fixed-sample`. Only
the identity is real and it is used verbatim; the seeded user/video/title/duration rows are inert scaffolding
that no subtitle code path reads (disclosed because a reviewer will see synthetic metadata next to a real
acquisition).

Branch ladder, all rehearsed offline over the shared `fake_gateway_seam`: stored/unchanged (assert the
normalized rows, the run and attempt evidence, the pending count, and the root file set) → no visible track
(record the counts, skip) → `not_found` (record and stop before the harvest) → `rate_limited` (record the
refusal, skip) → every other bounded code (`transport_error`, `response_error`, `shape_error`, unknown) fails
loudly. The probe's refusal stops the smoke before the harvest so a dead listing does not spend the harvest's
calls; the evidence line says `harvest=not_attempted` in that case.

## Live evidence

Command (from the worktree package dir, so `tests/conftest.py`'s `sys.path` insert wins over the control
venv's editable install — the worktree has no `.venv`; credential sourced, never echoed, never copied into the
worktree; proxy required on this host):

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover/bilibili-asr-archive
set -a; source /root/workspace/bilibili-asr-archive/.env; set +a
export BILI_HTTP_PROXY=http://127.0.0.1:7890
BILI_LIVE_SMOKE=1 /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python \
  -m pytest tests/test_live_subtitle_cli_smoke.py -s -v
```

- **Temporary root**: the `tmp_root` fixture, `<worktree package>/.test-tmp/manifest-test-<pid>-<n>`, created
  and removed in-process by the fixture. Nothing outside it was written; `git status` after the runs shows only
  the three committed files.
- **Part**: `part_source=fixed-sample`, `work_id=BV1S8hA6MEvy:p0` (bvid `BV1S8hA6MEvy`, cid `41314223900`,
  page_index `0`) — the sample the gateway plan fetched live (`ai-zh`, 2913 segments).
- **Credential**: `sessdata=present`, resolved by the shipped rule from `BILI_SESSDATA` sourced out of the
  control checkout's `.env`; the smoke builds its own argv and passes no `--sessdata` flag. A value scan over
  the captured pytest log returned **0 occurrences**, and the run's own no-leak scans covered stdout+stderr and
  every persisted row.
- **Parts attempted**: 1 (both commands under `--limit-parts 1`).
- **Tracks found**: probe `probe BV1S8hA6MEvy:p0 tracks=1` with one `track ai-zh ai <label>` line;
  `probe-subs: probed=1 with_tracks=1 without_tracks=0 failed=0`; probe exit **0**.
- **Transcripts stored**: `harvest BV1S8hA6MEvy:p0 stored subtitle-ai ai-zh v1` and
  `harvest-subs: run_id=1de9b7cb7cd141bfa7114112212188db attempted=1 stored=1 unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=0`;
  harvest exit **0**.
- **Overall exit code**: pytest exit 0, `19 passed`.
- **Bounded blocker**: none. No `rate_limited`, no `not_found`, no throttle, no retry needed.
- **Rows asserted live** (by the smoke's own row assertions): one `transcripts` row (`source_kind=subtitle-ai`,
  `language=ai-zh`, `version=1`, 64-char content hash), its **2913** ordered segments with non-empty intervals
  and a non-decreasing start timeline, one `acquisition_runs` row (`kind=subtitle`, `selector_kind=pending`,
  `selector_target=NULL`, `requested_limit=1`, `credential_present=1`, `outcome=complete`, finished), one
  `acquisition_attempts` row (`outcome=stored`, no error code, linked transcript, same run id), and
  `v_pending_subtitles` empty afterwards.
- **Root file set after the run**: `archive.db` + `coordinator/archive-writer.lock` only — the probe left no
  lock and created no file, and no legacy sidecar and no `subtitles/raw/` or `transcripts/srt/` projection
  appeared.
- The single evidence line the run printed (bounded facts only; no URL, body, label, or credential):

```
live subtitle CLI smoke evidence: part_source=fixed-sample work_id=BV1S8hA6MEvy:p0 sessdata=present probe_exit=0 probed=1 with_tracks=1 without_tracks=0 probe_failed=0 track_count=1 tracks=ai-zh:ai harvest_exit=0 run_id=1de9b7cb7cd141bfa7114112212188db attempted=1 stored=1 unchanged=0 no_subtitle=0 failed=0 remaining_without_transcript=0 source_kind=subtitle-ai language=ai-zh version=1 segments=2913 transcripts=1 attempts=1 pending_after=0
```

### Invocation ledger (the disclosed deviation)

Three invocations, because the first two exposed defects in the new smoke itself rather than differing
about upstream:

1. **Attempt 1 — aborted by a smoke-side defect.** The module's autouse anonymous-environment fixture was
   stripping the operator's credential from the live test as well, so the probe ran anonymously and the
   `capsys` capture also picked up the smoke's own preamble, failing the reader. It did complete one live
   listing and its bounded observation was `sessdata=absent tracks=0 tracks=none` — the documented "nothing
   visible now" reading, consistent with machine captions being invisible anonymously. **No evidence is
   claimed from this run**; nothing was retried to change its outcome.
2. **Attempt 2 — passed** (the primary evidence): the identical acquisition recorded above, printed as
   `… probe_exit=0 harvest_exit=0 … stored=1 … segments=2913 …` (probe counts not yet folded into the line).
3. **Attempt 3 — confirming run after a presentation-only change.** The probe counts were folded into the one
   evidence line, and the second `capsys` flush was removed so a future stray print would fail loudly instead
   of being swallowed. No assertion changed. Re-ran once so the recorded line is exactly what the committed
   code prints: same bounded facts (`subtitle-ai`, `ai-zh`, `v1`, 2913 segments, `stored=1`).

Each invocation cost two or three upstream calls (the shipped gateway is fail-fast per call, and the smoke adds
no retry of its own). The deviation is real and is stated here rather than buried: the brief's rule was one live
attempt plus one throttle retry, and I spent three because of two defects in my own test file. No run was
discarded because of an upstream answer, and all three are consistent.

## Tests

- New module offline: `pytest tests/test_live_subtitle_cli_smoke.py -v` → **18 passed, 1 skipped** (the skip is
  the opt-in live gate), 19 collected. Every branch of the smoke's ladder — seeding and its read-only pending
  check, both output readers, all three row assertions, the refusal ladder, the loud-fail guard, the credential
  expectation rule, the leak scan, and the `ProbeResult.credential_present` pin — runs offline over the shared
  fake gateway seam.
- Focused group: `pytest tests/test_live_subtitle_cli_smoke.py tests/test_subtitle_cli.py tests/test_subtitle_e2e.py tests/test_live_metadata_smoke.py tests/test_live_subtitle_smoke.py -q`
  → **116 passed, 3 skipped**.
- Full offline suite: `pytest -q` → **1279 passed, 4 skipped in 46.6s** (pre-change baseline measured in this
  worktree at `c501d9a`: **1261 passed, 3 skipped in 46.6s**; delta = +18 new rehearsals + 1 new opt-in gate,
  and no pre-existing test changed state).
- Live: `BILI_LIVE_SMOKE=1 … -m pytest tests/test_live_subtitle_cli_smoke.py -s -v` → **19 passed**, exit 0,
  evidence line above.
- **TDD triple**: test file `bilibili-asr-archive/tests/test_live_subtitle_cli_smoke.py`; command
  `cd bilibili-asr-archive && <control venv>/bin/python -m pytest tests/test_live_subtitle_cli_smoke.py -v`;
  output `18 passed, 1 skipped` offline and `19 passed` with `BILI_LIVE_SMOKE=1`.
- **The `credential_present` assertion** (folded Task-2 follow-up):
  `test_probe_result_carries_the_credential_presence_the_cli_observed` → PASSED. It wraps the real
  `SubtitleIngestor.probe` (the result object is the only place the service-side value is observable from the
  command path), then asserts `[result.credential_present for result in captured] == [False]` for a run with no
  credential and `== [False, True]` for the `BILI_SESSDATA` run, in both cases against the line the same run
  printed (`sessdata: absent` / `sessdata: present`), with the captured part's `work_id` pinned to the sample and
  the value confirmed to have reached the adapter.

## Files changed

| File | Change |
|---|---|
| `bilibili-asr-archive/tests/test_live_subtitle_cli_smoke.py` | **new**, 1303 lines — the opt-in live CLI smoke plus 18 offline rehearsals |
| `bilibili-asr-archive/docs/metadata-storage.md` | 292 → 560 lines — QC3-003 replacement, the subtitle section, the smoke section, the exit-code index, the schema-resource and credential updates |
| `bilibili-asr-archive/README.md` | 677 → 791 lines — the subtitle subsection, the writer-isolation correction, the four-smoke index, the mixed-outcome scoping, the fresh-start rename |

Commits (working branch only, no push):

```
8373817 docs(subs): document the SQLite subtitle path and the live smoke
d5c0f9e test(subs): add the bounded live CLI smoke with its offline rehearsals
```

Range `c501d9a..HEAD` contains exactly those three paths and nothing else.

## Self-review notes

- `git diff --check c501d9a..HEAD` → clean; working tree clean; `git status --porcelain` empty. The live
  logs were written to `/tmp`, outside the repository. The only file left under the gitignored
  `bilibili-asr-archive/.test-tmp/` is `audio-outside.m4a`, which `tests/test_audio.py:236-242` writes on
  purpose (it proves a download refuses a path outside `audio/`) — pre-existing suite behaviour, not from this
  task; the smoke's own temporary root is removed by the `tmp_root` fixture.
- **No pre-existing assertion was changed.** No existing test file was touched, so there is no altered
  assertion to disclose; the only changed assertions in the range are the new ones. On the production side
  there is no diff at all — the smoke exercises the shipped CLI unchanged.
- **Doc sentences replaced** (the QC3-003 fix is item 4; the rest are claims the cutover made false, tracked so
  the reviewer can check each):
  1. `docs` H1 `# Metadata storage (`archive.db`)` → `# Metadata and subtitle storage (`archive.db`)`.
  2. `docs` intro "the metadata commands never read it" → "none of these commands read it" (the subtitle
     commands also never touch the sidecars).
  3. `docs` fresh-start bullet "initializes the checked-in schema (`src/bili_asr/storage/schema.sql`)" →
     both resources, with the pre-contract skip behavior stated.
  4. `docs` §"Reserved media boundary (empty in this plan)" → §"Media and transcript tables"
     (**QC3-003**, exact text above).
  5. `docs` §"No-JSONL contract": the three-command list → five commands, plus the no-projection sentence.
  6. `docs` §"Credential boundary": last sentence extended with the two commands' presence semantics.
  7. `docs` §"Views": added `v_pending_subtitles`.
  8. `docs`: added §"Subtitle acquisition" (with Output, Exit codes, Archive writer lock, Track selection
     preference, Schema guard and rebuild, Boundary with the legacy manifest path), §"Subtitle CLI smoke", and
     §"`probe-subs` / `harvest-subs`" under the trailing Exit codes.
  9. `README` workflow block: `bili-asr harvest-subs --archive-root archive` →
     `bili-asr harvest-subs --limit-parts 5 --archive-root archive` plus a `probe-subs` line — **the removed
     form is now a usage error**, so this was a factual bug, not a style change.
  10. `README` §"Archive writer isolation": `probe-subs` removed from the archive-mutating list and added to
      the read-only list.
  11. `README` §"Fresh-start metadata collection (`fetch-meta` / `status` / `runs`)" → §"Fresh-start SQLite
      archive (…)" with a pointer to the subtitle subsection (the section now owns both), and the one internal
      anchor reference updated.
  12. `README` §"Operational run ledger": "The metadata CLI's `fetch-meta`" → "The metadata and subtitle CLI
      commands", with the anchor retargeted to the renamed heading.
  13. `README`: added §"Subtitle acquisition on SQLite (`probe-subs` / `harvest-subs`)" (bounds, exit codes,
      output shapes, preference rule, credential, schema guard/rebuild, legacy boundary, writer lock).
  14. `README` §"Opt-in bounded live smoke" → §"Opt-in bounded live smokes": "Three tests" → "Four tests" plus
      the new module's bullet, including why it runs from the checkout under test.
  15. `README` §"Mixed batch outcomes": the command list is now scoped to the legacy manifest path (removed
      `harvest-subs`, which follows its own taxonomy) with a pointer to the new section.
  16. `README` `run` four-stage paragraph: added the manifest-only boundary sentence.
- **Doc claims verified against the implementation** rather than restated: `subtitles._LAN_PREFERENCE ==
  ("ai-zh", "zh-CN", "zh-Hans", "en")`; `_SOURCE_KIND_BY_AI = {True: "subtitle-ai", False: "subtitle-cc"}`;
  `_ARCHIVE_WRITER_COMMANDS` contains `harvest-subs` and not `probe-subs`; the schema guard line is composed in
  `cli._subtitle_schema_rebuild_line`; `initialize_schema` runs `schema.sql` and then `schema-transcripts.sql`
  only when the contract is present; the probe requires exactly one selector; an all-failed probe exits 2; a
  failed harvest exits 2; `main()` prints `<command>: archive_busy`.
- **Defects found and fixed during the task** (all by running the thing, not by inspection): the autouse
  anonymous-environment fixture silently stripping the operator credential (would have made every live run
  anonymous and only ever `tracks=0`); the `capsys` preamble contaminating the command-output readers; pytest's
  assertion introspection being able to render the credential value on a leak-check failure (replaced with an
  explicit `if`/`raise AssertionError(fixed message)`); and the row assertion assuming `no-subtitle` never
  carries an error code, when a `not_found` listing records `error_code='not_found'` (the existing
  `test_not_found_is_recorded_no_subtitle_with_its_code` pins the other side) — each caught by the offline
  rehearsals or the first live run before it could mislead.
- **STOP conditions checked, none triggered**: the cutover touches no manifest for any command; the bounded run
  needs no retry or loop (the shipped gateway is fail-fast and the smoke adds none); no output or row carries a
  signed URL, raw body, cookie, or traceback (scanned live, 0 credential-value occurrences in the log); no
  second executable and no second metadata source of truth; and `probe-subs` is genuinely read-only — the live
  run left exactly `archive.db` with no lock, no run row, and no file.
- No `simplify:` or `temporary` marker was introduced, so no removal path needed recording.
- Line lengths and naming follow the sibling smokes; the new module was checked for unused imports and
  duplicate definitions (none).

## Hand-off

- PM: this is the plan's last task; the branch review package / QC tri / QA gate come next. The live evidence
  line above is the iteration's operator-visible acceptance-carrying result.
- Reviewer attention requested on two deliberate choices: the authored sample part (`part_source=fixed-sample`
  into a temporary root, because both commands only address stored parts and this host has no archive), and the
  three-invocation live ledger.
- Carried, unchanged and out of this plan: plan 1's residual R1 (whole-`user`-module import) still targets the
  next plan whose file list includes `src/bili_asr/sources/bilibili_api_gateway.py`; the archive-db branch of
  the *gateway* probe stays unreachable on this host (documented there, re-established by attempt 1's snapshot
  of the anonymous bracket); and the deferred work named in the plan (SRT/TXT/MD projections from SQLite, the
  SQLite audio work queue, promoting the storage/transport contract out of the iteration package) remains owned
  by `project-manager` with the trigger "this iteration delivered".
