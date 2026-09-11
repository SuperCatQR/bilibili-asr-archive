# Task 3 L2 Review — Bounded live subtitle probe + tightenings M1/M2/M4

- Plan: `20260911-subtitle-gateway` · Task 3 of 3 (final) · iteration `iter-2026-09-subtitle-transcript-sqlite`
- Review mode: Mode A, L2, diff-first · seat `code-reviewer` (read-only; no dispatch, no worktree mutation)
- Review range: `7f7156a..c3d362c` (`review/task-3-diff.md`, 3 files, +619/−34)
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway` @ `c3d362c`
- Inputs read: brief (full), primary spec (full), plan (full), implementer report (full), task diff (full),
  the three changed files in the worktree, `tests/fixtures/fake_bilibili_gateway.py`,
  `tests/conftest.py`, `storage/schema.sql`, `storage/database.py`, `config.py`, and the installed pin
  (`bilibili_api/video.py`, `bilibili_api/user.py`)
- Writes: this file only. `git status --porcelain` on the worktree is empty after the review.

## Verdict

| Field | Value |
|---|---|
| Spec compliance | ✅ Compliant (no Critical, no Important) |
| Task quality | **Approved** |
| Findings | 0 Critical · 0 Important · 6 Minor |
| ⚠️ Cannot verify from diff | 7 (listed below; none blocks) |
| Item 6 (`user` module acceptance) | Acceptance sound as a **scope** decision; **the stated reason is wrong** — treated as Minor 5/§6, not a blocker |

Independently reproduced / re-derived evidence (this review):

- **Sanctioned focused command re-run** (`env -u BILI_LIVE_SMOKE … pytest tests/test_live_subtitle_smoke.py tests/test_bilibili_api_gateway.py -q`)
  → **`315 passed, 2 skipped in 1.17s`** = the claimed `308 passed, 1 skipped` + `7 passed, 1 skipped`.
  No `BILI_LIVE_SMOKE` was set, no credential was sourced, no network was touched.
- **The live gate is real and collected**: `--collect-only` → 8 tests in the probe module (7 rehearsals
  + 1 live); default-run skip reason is verbatim
  `tests/test_live_subtitle_smoke.py:308: live subtitle probe is opt-in: set BILI_LIVE_SMOKE=1 to request it`.
  The gate is the test's first statement (`test_live_subtitle_smoke.py:307-310`), before the version guard
  (`:312`), before the credential/proxy resolution (`:314`, `:316`) and before the gateway is built
  (`:315`) — so a default run cannot touch the environment or the network.
- **M2 re-derived statically**: 42 distinct `ast.Attribute` names in the adapter; **0 hits** against
  `playback, playurl, play_url, download, danmaku, audio, asr, export`; both positive controls hold
  (`{get_access_id, update_params, get_pages, get_info}` and the three `AUTHORIZED_SUBTITLE_ATTRIBUTES`;
  each carries `subtitle`, which is still in `AUTHORIZED_SEAM_METHOD_TOKENS`).
- **M1 re-derived statically**: the AST import map of the adapter is exactly
  `{bilibili_api: {Credential, request_settings, user}, bilibili_api.video: {API, Video},
  bilibili_api.utils.network: {Api}, bilibili_api.exceptions: {5 names}}` == `ALLOWED_PACKAGE_IMPORTS`.
  The test records `alias.name`, so the local alias `VIDEO_API` correctly does not appear in the set;
  `import bilibili_api.video` and `from bilibili_api import video` both still fail the exact equality
  (`{"bilibili_api.video"}` / a root set that gains `video`). No stale `video.` reference survives in the
  adapter (`grep`: only `VIDEO_API`, `Video`, and prose).
- **M1's premise is factual in the pin**: `bilibili_api/video.py` exposes `Episode` (`:1833`),
  `VideoOnlineMonitor` (`:1836`), `get_api` (imported `:26`), `get_cid_info` (`:41`) and `get_client`
  (imported `:30`) at module level; none of those attribute names carries a forbidden token, so binding
  the module was indeed the only reason they were unflagged.
- **M4's pin is load-bearing by construction**: the seam records the player call *before* raising
  (`fixture:571-578`: `self._record(...)` then `raise script.player_error`), and `player_error` is never
  cleared — so the mutation "initial listing moved inside the re-list `try`" must record a **second**
  `player.track_list(...)` and fail `assert bilibili_api_seam.calls == [_listing_call()]`, exactly as the
  recorded red transcript shows. The mapping is `FakeNetworkException(503)` → not in the rate-limited or
  not-found status sets → `GatewayTransportError`; `RuntimeError` → `except Exception` → same code; the
  `detail` is the operation string the *initial* listing passes (`"fetch_subtitle_segments"`,
  adapter `:607-609`).
- **The read-only archive read holds**: `path.is_file()` guard, then
  `sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)` (`test_live_subtitle_smoke.py:178-190`);
  the live path never calls `open_database`/`MetadataRepository` (those appear only in the rehearsal seeder
  `_seed_archive`, `:381-391`); the shipped app never enables WAL (`grep journal_mode` → 0 hits), so
  `mode=ro` cannot be defeated by `-shm` semantics; and the query matches the shipped DDL
  (`schema.sql:21-35`: `video_part_id INTEGER PRIMARY KEY`, `bvid`, `cid INTEGER CHECK (cid > 0)`).
- **"The archive is empty on this host" is independently confirmed**: `find` for `archive.db` / `*.sqlite*`
  over the whole repo returns nothing and `bilibili-asr-archive/archive/` does not exist — so the recorded
  live run necessarily came from the `fixed-sample` branch, as the report states.
- **Live-run import provenance** (the report leaves this implicit): the sanctioned interpreter is the
  *control* checkout's venv, whose editable `.pth` points at the control `src` — but `tests/conftest.py`
  prepends `<package>/../src` at `sys.path[0]` before any test module imports `bili_asr`, so a run rooted
  in the worktree imports the **worktree** adapter. This also has to be true for the run to have passed at
  all: the control `src` does not carry Task 1/2's subtitle methods. The live evidence is therefore about
  the code under review, not about a stale checkout.
- **Both tightenings restore the pre-plan baseline** (read from the control checkout, which carries no
  subtitle code): its adapter already imports `from bilibili_api.video import Video` with
  `ALLOWED_PACKAGE_IMPORTS["bilibili_api.video"] == {"Video"}` and the root set
  `{Credential, request_settings, user}`, and its `FORBIDDEN_SEAM_METHOD_TOKENS` already contains
  `subtitle`, `player` **and** `download`. Task 2 widened the import (to reach `video.API[...]`) and
  removed the three tokens; M1/M2 put the baseline back, M1 adding exactly one name (`API`). At plan level
  the two guards are therefore a restoration plus one named addition — not a net loosening.
- **Whitespace**: no added line in the diff carries trailing whitespace or space-before-tab (proxy for the
  claimed `git diff --check` clean; the git command itself was not re-run).

---

## 1. Probe contract (target 1)

| Brief / spec clause | Verdict | Evidence |
|---|---|---|
| Opt-in via `BILI_LIVE_SMOKE=1`, skip by default | ✅ | `:129-132` gate predicate; `:307-310` skip at the test's first statement; `:483-492` pins that only the literal `1` opts in (`""`, `0`, `true`, `yes`, `2` do not) — reproduced green in the focused run |
| Loud-fail when opted in without the pinned distribution | ✅ | `:135-152` `_pinned_package_version()` → `pytest.fail` with install guidance; `:155-167` `_load_gateway` does the same for an unimportable adapter; `:312` asserts the version equals the pin. Rehearsed at `:471-477` |
| Bounded assertions only (track count / languages / `ai|cc`) | ✅ | `:224-241`: type-checks the tuple and each DTO, renders `track_count=… tracks=<lang>:<ai|cc>,…`; labels are deliberately excluded, and `:495-505` proves it with a signed-URL marker *inside* a label plus `assert_leaks_no_markers` |
| Bounded assertions only (segment count + monotonic ms) | ✅ | `:244-266`: non-empty, non-decreasing `start_ms`, renders only `segments`, `first_start_ms`, `last_end_ms`; negative cases pinned at `:521-535` |
| No signed URL, body, or credential printed or persisted | ✅ | The probe never holds a URL (resolution stays inside the adapter); the only credential output is `redact_sessdata(...)` (presence label, `config.py:144-151`); the proxy is printed as `present/absent`, never its value (a proxy URL can embed credentials — correctly avoided); no write path exists in the module |
| Archive DB read is read-only (`mode=ro`); the probe never creates one | ✅ | `:170-190`; the rehearsal records the connect URI and asserts it `startswith("file://")` / `endswith("?mode=ro")` (`:395-419`), and both unreadable cases (absent file, empty directory) degrade to the fallback. No `mode=rw`/create path anywhere |
| Honest bounded-blocker path for a risk-control refusal (spec §9, brief STOP) | ✅ | `:269-292` prints `stage` + bounded `refusal_code` and skips; the message names the STOP condition and forbids enabling `dm` fingerprint parameters or adding undeclared parameters. `rate_limited` is the only code that skips on the *listing* path — everything else fails loudly, which is the right asymmetry |
| Probe claims no coverage | ✅ | Module docstring `:1-56` states one part / one moment / one credential, and never reads "this video has no captions" for `track_count=0` — the spec §6 product semantics are carried into the probe's own wording |

The three brief items and the three tightenings are all implemented. No STOP condition fired; nothing was
bent to make the call pass.

## 2. Offline rehearsals and the gate (target 2)

Seven rehearsals run in every default pytest run and none touches the network (verified by reading each
one; my focused run exercised them without any proxy/credential in the environment). Non-vacuity, checked
by asking what mutation each would catch:

| Rehearsal | Would fail if… |
|---|---|
| `:395-419` archive selection / read-only URI | the SQL drifted from the shipped DDL, the URI lost `mode=ro`, or a missing/part-less DB raised instead of answering `None` (it seeds through the real storage layer, so the query is exercised against the real schema) |
| `:430-441` archive preferred, sample fallback | the env override stopped being honoured, or the fallback needed any live call to resolve a part |
| `:453-459` schema-present, part-less archive | the pre-collection shape raised instead of falling through |
| `:471-477` loud-fail guard | `_pinned_package_version` swallowed `PackageNotFoundError` or returned a default |
| `:483-492` opt-in switch | the predicate accepted truthiness or any other spelling |
| `:495-505` listing evidence | labels or markers leaked into the printed line, or the count/language/AI-classification rendering changed |
| `:521-535` timeline evidence | the monotonic check were dropped, or an empty document passed |

Coverage gaps (not vacuity, recorded as Minor 4): `_load_gateway`'s `ImportError → pytest.fail` branch and
the two skip branches (`_record_risk_control_refusal`, the body `not_found` skip) have no offline
rehearsal, although all three are pure control flow drivable with a monkeypatched import and a synthetic
exception.

## 3. Tightenings M1 / M2 / M4 (target 3)

- **M1 ✅** — `from bilibili_api.video import API as VIDEO_API, Video` (adapter `:35`); the three call sites
  use `Video(...)` / `VIDEO_API[...]` (`:86`, `:546`, `:563`). `ALLOWED_PACKAGE_IMPORTS` stays an exact
  equality and moved the entry to `"bilibili_api.video": {"API", "Video"}` (test `:115-126`). The five
  previously-flagged module names are no longer bound, and none of them is reachable through any other
  allowed import (`Credential`, `request_settings`, `user`, `Api`, the five exceptions). No previously
  flagged *behaviour* became newly reachable: `Video` is the same class object as before, and its media
  methods are exactly what the token scan (M2) covers. **At plan level this is a restoration**: the
  pre-plan baseline imported only `Video` by name (`{"Video"}` in the allow-list) and Task 2 widened it to
  the whole module to reach `video.API[...]`; M1 puts the narrow form back and adds exactly the one name
  the subtitle endpoint description needs. The rename to `VIDEO_API` is a genuine readability
  win — `Api` (the request class) and `API` (the endpoint description dict) would otherwise sit two lines
  apart. The alarm is real in the pin (see Verdict), so M1 closed a hole rather than a stylistic one.
- **M2 ✅** — `download` is back in `FORBIDDEN_SEAM_METHOD_TOKENS` (test `:295-304`) with `subtitle`/`player`
  still allowed, and `AUTHORIZED_SEAM_METHOD_TOKENS` narrowed to `("subtitle", "player")` (`:310`).
  Narrowing the control tuple is *required* for consistency, not a loosening: keeping `download` there
  would have let a future attribute be simultaneously certified by the control and flagged by the scan.
  Re-derived: 0 hits, both controls hold (see Verdict). The positive control is intact and now strictly
  better aligned with the forbidden scan. The token set now matches the pre-plan baseline again (which
  already forbade `download`), so the plan's net effect on this guard is nil.
- **M4 ✅** — `test:2836-2868`, parametrized over `FakeNetworkException(503)` and a non-package
  `RuntimeError`, asserts `code == "transport_error"`, `detail == "fetch_subtitle_segments"`, upstream text
  absent from `str(...)`, and **`calls == [_listing_call()]`**. The pin is load-bearing by construction
  (see Verdict): the mutation the implementer recorded must produce a second listing record and fail. The
  test is additive; it does not restate or duplicate the existing `not_found`-class listing test
  (`test:2822-2833`), which still owns that path.

## 4. Assertion audit / no regression (target 4)

Removed-line audit of the diff (`+619/−34`; the arithmetic reconciles exactly: new module +535, test +75/−30,
adapter +9/−4):

- **0 assertions deleted.** The 30 removed test lines are 3 comment/docstring blocks and 3 constant lines:
  `"video"` out of the `bilibili_api` root set, the new `"bilibili_api.video": {"API", "Video"}` entry,
  `download` into the forbidden tuple, `download` out of the authorized tuple. The 4 removed adapter lines
  are the old import, the old endpoint expression and the two `video.Video(...)` call sites.
- Every changed assertion is **equal-or-stricter**: the import map is still compared with `==` and now
  constrains two names instead of blessing a module; the token scan gained a token and lost none; the
  control tuple lost only the token that would have contradicted that scan. Both constants now hold the
  pre-plan baseline value (M1 with one added name), so the plan's net effect on the two guards is a
  restoration, not a relaxation.
- Additions: M4's 2 cases + 8 tests in the new module (7 offline + 1 opt-in live) = the reported +9 passed
  / +1 skipped, which my focused run reproduces (`315 passed, 2 skipped`).
- **Metadata path untouched**: no diff hunk reaches `_await_upstream`, `_NOT_FOUND_API_CODES`, the
  page/`w_webid` path, `_resolve_w_webid`, the DTOs, or the seam. `video.Video` → `Video` binds the same
  class object, so `get_video_parts` / `get_completed_video_summary` are behaviourally identical. The
  `-101` divergence stays subtitle-only (`_SUBTITLE_NOT_FOUND_API_CODES`, adapter `:65`), and nothing in
  this diff moves it.
- Test seam: `DOCUMENTED_METADATA_CALLS`, the recorded-call assertions, and every pre-existing exact
  call-list assertion are unchanged; the alias import keeps working under the seam because the fixture
  swaps `sys.modules["bilibili_api.video"]` before the adapter is re-imported per test (which the 308
  green cases confirm).

## 5. The recorded live outcome — what it can and cannot prove (target 5)

The record (report "Live probe evidence"; plan "Live probe evidence (Task 3, 2026-09-11)", `:345-359`) is
`track_count=1` (`ai-zh:ai`), `segments=2913`, `first_start_ms=460`, `last_end_ms=7896020`, timeline
non-decreasing, PASSED, on the fixed public sample `BV1S8hA6MEvy` / cid `41314223900`.

What the evidence **does** support, honestly bounded:

- The locked call shape reached the player endpoint **once**, under a credential, for one public part —
  i.e. the plan's central question ("does the locked call shape reach this endpoint") is answered
  affirmatively, and the STOP condition on a risk-control refusal did not fire.
- A real inventory was normalized into a DTO tuple with a discriminating `is_ai`, and a real signed
  document normalized into 2913 rows whose millisecond timeline is plausible and internally ordered. The
  absolute magnitudes (`460` … `7896020` ≈ 2 h 11 m) are consistent with a lecture-length part, which is
  weak but non-zero corroboration that the `floor(seconds*1000)` scale is right.
- The fallback branch (no archive DB on this host — independently confirmed) is the branch that ran, so
  the probe's shipped selection logic is exercised end to end on the live path.

What it **cannot** prove:

- That it happened as transcribed. The reviewer seat cannot re-run it (no network, credential use
  forbidden), so this is implementer evidence, not independent evidence. QA decides whether an independent
  live re-run is owed.
- The `floor(seconds*1000)` half of spec §9. By design the probe holds no URL and no body, so it cannot
  compare a segment's ms against its source seconds; the conversion is pinned offline against the seam
  only. The live run evidences document-level plausibility, not the formula.
- Anything about the `archive-db` branch, which has never executed live (no archive exists here) and whose
  failure modes are therefore rehearsal-only.
- That nothing leaked into any file: the credential/payload scan is the implementer's, not mine.

Two record-level observations: the intermediate run (b) prints `part_source=sample-discovery`, a label the
committed module cannot emit (it emits only `archive-db` / `fixed-sample`) — consistent with the narrated
"fallback changed after run (b)", and the report says so; and the plan's **Evidence Index** (`plan:361-365`)
still names only `tests/test_live_metadata_smoke.py`, so the new probe module is missing there even though
the ledger (`progress.md`) claims the Evidence Index now carries the probe command and outcome — the
content landed in a separate section instead (Minor 1).

## 6. Item 6 — the `user` module acceptance: my call

The implementer's observation is correct (adapter `:71`/`:75`, `:669`, `:768` use `user.API`,
`user.VideoOrder`, `user.User`; `ALLOWED_PACKAGE_IMPORTS` binds the whole module). **My verdict: the
decision to take no action in this plan is sound; the recorded reason is not, and should not be carried
forward as "guarded".**

- *Sound on process/scope*: M1 authorized `video` only. Narrowing `user` would touch the delivered
  metadata surface from the previous iteration in the final task of a subtitle plan — unauthorized scope
  creep, and the plan is explicitly bounded to M1/M2/M4.
- *Sound on risk magnitude*: the pin's `user.py` exposes no raw-transport helper (unlike
  `video.get_client`), its only forbidden-token name is `AudioOrder` (which the scan *would* catch), and
  the three names the adapter actually uses are deliberate metadata-path choices.
- *Unsound as stated*: "the exact-set test still guards it" does not hold as a reachability argument. That
  test compares the *import statement* map, and it blesses the whole `user` module — that is what "bound
  whole" means. `user.get_api` (which reaches every description in `api.json`, including video/playback
  ones) and `user.ChannelSeries` remain nameable with no import-set change and no token hit. That is
  precisely the class M1 named for `video` — M1's own flag list included `get_api`. The acceptance is
  therefore an accepted risk outside this plan, not a guarded surface, and it should be recorded that way
  (see Minor 5).
- *Recommended disposition (PM-owned)*: register it as **accepted-risk residual** with an owner and a
  trigger — e.g. owner `project-manager`, trigger "the next plan that touches
  `sources/bilibili_api_gateway.py` (`20260911-subtitle-cli-cutover`)" — and correct the rationale text.
  Do not close it under `zero-residual` as "guarded by the exact-set test". No code change is required in
  this plan, and I do not treat it as a blocker.

---

## Strengths

1. **The live probe is designed so that "green" cannot be claimed without evidence.** `track_count=0` is a
   pass that prints credential presence; `rate_limited` is a recorded skip that names the STOP condition;
   a `not_found` body is a skip that says a run without segment evidence must not read green; everything
   else fails loudly. That is the exact degradation ladder the spec's product semantics and the plan's STOP
   conditions ask for, and it is asserted rather than described.
2. **Bounded output is enforced, not promised.** The evidence renderers are pure functions with
   exact-string assertions, and the `_track_evidence` rehearsal plants both sentinels (signed-URL marker
   and raw-body marker) *inside* display labels to prove labels never reach the output. The probe also
   prints the proxy as `present/absent` rather than its value — a leak channel a "debug print the
   environment" implementation would have opened.
3. **The archive read is genuinely read-only and cannot create anything**: `is_file()` guard,
   `mode=ro` URI, every unreadable case degrading to the fallback, and a rehearsal that records the
   connect URI so a future edit that drops `mode=ro` fails offline.
4. **M1's narrowing is exact and its rationale is checkable**: the pin's flagged names were verified to
   exist, and the alias `VIDEO_API` plus the exact `bilibili_api.video` entry keeps the boundary
   expressible; the accompanying comment states the reason at the point of the import.
5. **M4 is a coverage pin placed where the risk was**, not a restatement: it is the only assertion that
   fails if the bounded re-list is ever armed by a listing that never answered, and its two parameters
   cover both the package-wrapped and the library-level transport shape.
6. **Disclosure quality is high**: the report separates what was run from what was inferred, states the
   fallback change and its cause (run (a)'s metadata-route refusal), flags the `user` looseness instead of
   burying it, records three deliberate design decisions for the reviewer, and refuses to edit PM-owned
   harness artifacts — the honest-handoff behaviour the brief's third item requires.
7. **No assertion was weakened anywhere**, and the two constants that changed became strictly stronger
   (verified by reading the removed lines, not just the report's claim).

## Issues

### Critical

None.

### Important

None.

### Minor

**Minor 1 — the plan's Evidence Index is stale (PM-owned).**
`plan:361-365`. The Evidence Index still lists `tests/test_live_metadata_smoke.py` and omits the module
this task added, `tests/test_live_subtitle_smoke.py`; the probe command and outcome landed in a separate
`## Live probe evidence (Task 3, 2026-09-11)` section (`plan:345-359`), while `progress.md` says "the
plan's Evidence Index now carries the probe command and the bounded outcome". Item 5 of this review asks
about the Evidence Index specifically, so it is flagged rather than waved through. One-line fix: add the
probe module to the index bullets (and the same for the CLI plan's README, which the handoff already
names). Related, PM-owned: Task 3's checkboxes are still unticked in both the plan and the brief.

**Minor 2 — the module's documented bounded outcomes omit the listing's `not_found` class.**
`test_live_subtitle_smoke.py:32-46` promises that a sample upstream has removed "surfaces in the evidence
line as `track_count=0` or a bounded code", but the only handling around the initial listing is
`except GatewayRateLimited` (`:328-333`). A deleted sample video answers `-404`/`-62002`/HTTP 404 → mapped
to `GatewayNotFound` → the probe dies with an uncaught exception, no evidence line and no `stage` record.
Failure is a defensible outcome for a stale sample; the *documentation* is not accurate about it. Options:
catch `GatewayNotFound` on the listing and record `stage=track-listing track_count=not_found` + skip
(mirroring the body path, ~4 lines), or state that a part gone upstream fails loudly by design.

**Minor 3 — the newest-part query ignores `processing_status='gone'`.**
`:180-190`: `SELECT bvid, cid FROM video_parts WHERE cid > 0 ORDER BY video_part_id DESC LIMIT 1`.
`gone` is a first-class shipped part status (`storage/models.py:15`), and a part the archive already knows
is gone is exactly the one where the player endpoint answers 404 — so on the operator's host (the branch
that has never run live) the probe can hard-fail on a part its own database had already marked gone. Same
family, same query: `bvid` is not shape-checked, so a corrupt/foreign row would raise the adapter's
`ValueError` instead of falling back to the sample. One-line hardening
(`... AND processing_status != 'gone'`, plus a `_BVID_PATTERN`-shaped check on the selected `bvid`) keeps
all rehearsals green today (no `gone` row is seeded).

**Minor 4 — two probe guards have no offline rehearsal.**
`_load_gateway`'s `ImportError → pytest.fail` branch (`:155-167`) and the two skip branches
(`_record_risk_control_refusal` `:269-292`; the body-`not_found` skip `:355-362`) are exercised only by a
live run. The brief asked for the rehearsals to cover "selection, guards, evidence renderers"; the version
and switch guards are covered, the import guard is the one gap. Each is cheap to drive offline
(monkeypatched import, a synthetic `GatewayRateLimited`, a monkeypatched fetch) and would make the live
paths' control flow — not just their inputs — verified without network.

**Minor 5 — two docstrings claim the adapter never uses a `user.User` delegate, and it does.**
`test:106-114` ("not through a `user` delegate") and the docstring of
`test_gateway_imports_stay_on_metadata_surface` (`:1712-1714`, "never a `user.User` delegate") are
contradicted by adapter `:768` (`user.User(uid=mid, credential=…).get_access_id()`) — and by that test's
own positive control, which asserts `get_access_id` is present in the scanned attribute names. The
sentence is pre-existing text that this diff re-touched without correcting. It matters beyond tidiness:
it is the same "the import surface is what it says" reading that makes the item-6 acceptance look
stronger than it is (§6). Fix when `user` is next narrowed, or narrow the claim to "the page call itself".

**Minor 6 — the monotonic-timeline assertion is stricter than spec §3's own guarantee (disclosed, recorded).**
`:244-266` fails the probe if the probed document's `start_ms` timeline is not non-decreasing, while spec
§3/§6 preserve "overlapping or non-monotonic upstream rows … verbatim" and call that legal. The brief does
ask for "monotonic milliseconds", the implementer disclosed the tension, and the assertion message asks
for a recorded decision ("an observation about the upstream document"), so this is compliant — recorded
only so that a future failure of this assertion is not auto-read as an adapter defect. Optional
strengthening in the same area: the probe already reads the part from the archive DB and could compare
`last_end_ms` against that row's `duration_ms` to give the live run one genuinely independent check of the
millisecond scale (nice-to-have; the sample branch has no such row).

---

## ⚠️ Cannot verify from diff (PM to check)

1. **The live PASS itself** — not reproducible from this seat (no network, no credential). Accepted as
   implementer evidence carrying bounded facts only; QA owns the decision whether an independent live
   re-run is owed at the gate.
2. **`floor(seconds*1000)` against a real document** — the probe cannot see the source seconds by design,
   so spec §9's "milliseconds matching `floor(seconds*1000)`" stays offline-pinned (seam) and is
   *corroborated*, not proven, by the live timeline. Do not read the live evidence as conversion proof.
3. **The `archive-db` branch has never run live** — no archive database exists on this host (independently
   confirmed), so live evidence exists only for the `fixed-sample` fallback. Compliant with the brief's
   "or a fixed public sample when the archive is empty", but spec §9's phrasing "one `(bvid, cid)` from the
   operator's own archive" is met only via a part of the owner's own public collection.
4. **The run-(b)/(c) provenance** — run (b) prints a `part_source` label the committed module cannot emit
   (`sample-discovery`), so it came from a pre-final revision; the report says so explicitly and (c) is
   claimed against the shipped module. QA may optionally re-run once to see the shipped revision answer
   live.
5. **The full offline suite `1082 passed, 3 skipped`** — not re-run (assignment forbids it); arithmetically
   consistent with the recorded baseline (1073+2) and the delta (+9 passed, +1 opt-in skip), and the
   focused files reproduce exactly (`315 passed, 2 skipped`).
6. **Which `bili_asr` the live run imported** — resolved statically in the favourable direction (§Verdict:
   `tests/conftest.py` prepends the worktree `src`, and the control `src` lacks the subtitle methods, so
   the live run cannot have used it). PM may still ask the implementer to state the imported path
   explicitly, since the report does not.
7. **M4's mutation transcript** — re-verifiable only by mutating the worktree (forbidden here). The
   mechanism is verified instead (seam records before raising, `player_error` persists, exact call-list
   assertion), which is sufficient to conclude the pin is load-bearing.

## Assessment

**Task quality: Approved.**

All three brief items and all three PM-authorized tightenings are implemented as written, and the parts I
could exercise myself reproduce the report exactly: the focused files are green (`315 passed, 2 skipped`),
the live probe is collected and skipped for the documented reason, M1's import map is exact with the
previously-flagged module names gone, M2's scan re-derives to zero hits with both controls intact, M4's pin
is the assertion that fails under the mutation the implementer recorded, and no assertion anywhere was
deleted or loosened. The read-only archive read and the bounded-output boundary are enforced by code, not
by intention, and the live record is written in the honest, bounded voice the spec asks for.

The six Minor findings are advisory: one PM-owned plan/ledger bookkeeping fix (Minor 1), three small
robustness/coverage hardenings in the new probe module (Minor 2-4), one documentation correction that also
sharpens the item-6 record (Minor 5), and one disclosed design tension worth keeping visible (Minor 6).
None of them contradicts a locked clause, and none requires a fix round before the branch review package.
On item 6 I agree with deferring the `user` tightening but not with the reason recorded for it: it is an
accepted risk outside this plan's authorization, not a surface the exact-set test guards — PM's call, and
my recommendation is a residual with an owner/trigger rather than a "guarded" close.

---

## Revalidation — fix wave 1 (`c3d362c..6002f99`)

Targeted re-review of **Minors 2/3/4 only**, against the PM-authorized wave (Mode A, L2, diff-first,
read-only seat). Round 1 raised the findings; this round verifies their disposition and looks for
regressions introduced by the fix.

- Range: `c3d362c..6002f99` — `review/fix-1-diff.md`: **1 file, +394/−47**
  (`bilibili-asr-archive/tests/test_live_subtitle_smoke.py`, now 882 lines). One `diff --git` header:
  no adapter, no `tests/test_bilibili_api_gateway.py`, no harness artifact rides along.
- Worktree `…/.worktrees/20260911-subtitle-gateway` @ `6002f99`; `git status --porcelain` empty before
  **and** after this re-review — my only execution was the sanctioned offline pytest invocation.
- Inputs read: this report (full), the fix diff (once), the post-fix module (all 882 lines), the
  implementer fix report, `sources/models.py`, `bilibili_api_gateway.py` (`_BVID_PATTERN`, the
  `_SUBTITLE_NOT_FOUND_API_CODES` mapping), `storage/schema.sql`, `storage/models.py`,
  `storage/database.py`, `fixtures/metadata_records.py`, the plan's Evidence Index, and
  `projects/_default/residuals.json`.
- Discipline: `BILI_LIVE_SMOKE` and `BILI_LIVE_ARCHIVE_DB` both observed `<unset>`; no credential sourced,
  no network command run, no git mutation, no file written anywhere except this section.

### 1. Verdict (updated)

| Field | Round 1 | Round 2 (this revalidation) |
|---|---|---|
| Spec compliance | ✅ Compliant | ✅ Compliant (unchanged; the one behaviour change is the authorized Minor-2 option) |
| Task quality | Approved | **Approved** |
| Findings | 0 Critical · 0 Important · 6 Minor | 0 Critical · 0 Important · **0 open Minor** (3 fixed here · 1 fixed by PM in the plan · 1 → residual R1 · 1 accepted design choice) |
| ⚠️ Cannot verify from diff | 7 | unchanged in substance: the 5 that only a live/independent run could settle are carried; 2 were resolved statically in round 1 and stay resolved. **No new ⚠️ item.** |

**Verdict: Approve.** Minors 2, 3 and 4 are resolved exactly as claimed, the authorized behaviour change
is scoped to the documented `not_found` class only, **0 assertions were removed or loosened**, and the
fix introduces no production-code or cross-module regression.

### 2. Minor 2 — resolved, and the behaviour change is correctly scoped

Round-1 finding: the module documented a bounded outcome for a part upstream has removed, but the listing
path caught only `GatewayRateLimited`, so a listing `GatewayNotFound` died with an uncaught traceback and
no evidence line. The implementer took the preferred option (record + skip).

Verified in the post-fix module (`_probe_one_part`, `:333-406`):

| Claim | Verification |
|---|---|
| A listing `not_found` now records bounded evidence and skips | `:351-370` — `except GatewayNotFound:` prints `live subtitle probe evidence: part_source=<label> stage=track-listing track_count=not_found` and `pytest.skip(...)`; never reaches the `_track_evidence` print, because `pytest.skip` raises |
| The part is named | The line carries `part_source`, and the live test prints `part=source=… bvid=… cid=…` before it (`:437-440`) — the record is complete |
| `track_count=0` stays a **pass** with credential presence; a no-listing run does **not** | `:375-382` early-returns after the two prints; both `not_found` skips say "must not read as green" / "no listing evidence was obtained" |
| Docstring now matches the code | `:41-47` documents `track_count=not_found` as a bounded outcome and names both causes; `:31-33`'s "a sample that upstream has since removed is visible rather than silent" is now true as written (it was not before — that was the finding) |
| Strictness preserved for the loud classes | `sources/models.py:179-228`: `GatewayNotFound`, `GatewayRateLimited`, `GatewayTransportError`, `GatewayResponseError`, `GatewayShapeError` are **siblings** under `GatewayError`. Executed check: `issubclass(GatewayNotFound, GatewayTransportError/ResponseError/ShapeError)` = `[False, False, False]`, and `issubclass(GatewayNotFound, pytest.skip.Exception)` = `False`. So `transport_error` / `response_error` / `shape_error` still propagate out of `_probe_one_part` uncaught — **the change is scoped to exactly the documented `not_found` class** |
| `-101` is a real member of that class | Adapter `:57`: `_NOT_FOUND_API_CODES = {-404, -62002}`; `:65`: `_SUBTITLE_NOT_FOUND_API_CODES = _NOT_FOUND_API_CODES \| {-101}`; used **only** by the subtitle listing (`:727`), while `_await_upstream`'s default stays the two-code set (`:783`). The implementer's rationale (an anonymous probe could die on the spec's own documented `no-subtitle` outcome) is factually grounded, not rhetorical |
| Live gate, opt-in, renderers and timeline check unchanged | Gate is still the test's **first statement** (`:421-424`), skip reason byte-identical to round 1; `assert _pinned_package_version() == PINNED_PACKAGE_VERSION` still `:426`; `_track_evidence` (`:262-279`) and `_assert_bounded_segment_facts` (`:282-304`, monotonic check at `:293-300`) are outside every hunk of this diff — unchanged, and still the two renderers the live path calls (`:371-374`, `:405`) |

Judgment on the authorized change: **correct and bounded.** It removes an uncaught-traceback path that
could only ever produce *less* information than the documented outcome, keeps the run non-green, keeps the
bounded code in the printed evidence, and touches no other exception class. Two consequences I state
openly rather than as findings (§8).

### 3. Minor 3 — resolved, both halves, with the guard strictly loosened nowhere

Round-1 finding: the newest-part query ignored `processing_status = 'gone'` and never shape-checked `bvid`.

- **`gone` filter** — `:224-228`: `SELECT bvid, cid FROM video_parts WHERE cid > 0 AND processing_status != 'gone' ORDER BY video_part_id DESC LIMIT 1`. `gone` is a shipped first-class status (`storage/schema.sql:28-30` CHECK, `storage/models.py:15` `ProcessingStatus`), the column is `NOT NULL` (so `!=` cannot silently drop rows through NULL), and the repository **allocates** `video_part_id` (`database.py:211-222` rejects a non-`None` id), so "newest" really is the last inserted row.
- **`bvid` shape check** — `:236-237` rejects a non-`BV` row and hands the probe to the documented sample fallback; `BVID_PATTERN` (`:129-134`) is **character-identical** to the adapter's `_BVID_PATTERN` (`bilibili_api_gateway.py:68`, both `^BV[a-zA-Z0-9]{10}$`), and the comment states why it is mirrored rather than imported (the adapter imports the pinned distribution at module scope; `sources/models.py` imports nothing from `bilibili_api`, so the probe module stays pin-free and its rehearsals stay runnable — re-verified by reading `models.py:1-16`).
- **No false fallback for legitimate rows**: the fixture `BVID = "BV1AbCdEfGhJ"` and the live sample `BV1S8hA6MEvy` both satisfy the mirrored pattern; the `cid` checks are preserved verbatim as a second `if` (`:238-239`). The net effect versus the removed line is **strictly stronger** — a superset of the rejected inputs, the same accepted ones.
- The function docstring (`:200-214`) now describes both checks and the fallback they degrade to, in the same voice as the rest of the module.

### 4. Minor 4 — resolved, plus two disclosed extras

Round-1 gap: `_load_gateway`'s `ImportError` guard and the skip branches had no offline rehearsal.
Post-fix, every notified branch is driven offline, and the disclosed extras are real:

| Branch | Rehearsal (new unless marked) |
|---|---|
| `_load_gateway` ImportError | `test_unimportable_pinned_module_fails_loudly` (`:648-664`) — `sys.modules[…] = None` (executed check: this does raise `ImportError`/`ModuleNotFoundError`), asserts the message carries the distribution, the version and `uv sync` |
| listing risk-control refusal | `…[listing-risk-control-refusal]` (`:796-803`) |
| listing `not_found` (Minor 2's new branch) | `…[listing-not-found]` (`:804-811`) |
| body risk-control refusal | `…[body-risk-control-refusal]` (`:812-819`) |
| body `not_found` | `…[body-not-found]` (`:820-827`) |
| empty listing → early return, no body call **(extra)** | `test_probe_records_an_empty_listing_and_stops_before_the_body` (`:774-784`) |
| visible-track evidence chain, no label leak **(extra)** | `test_probe_records_the_whole_evidence_chain_without_leaking_a_label` (`:861-882`) |

The module docstring's new claim — "Every branch of that ladder is rehearsed offline … part selection, the
two loud-fail guards, both evidence renderers, and all four record-and-skip branches" (`:59-62`) — I audited
element by element and it is **true** (part selection: 5 rehearsals; two guards: `:636-645` + `:648-664`;
both renderers: `:679-702` + `:705-719`; exactly four record-and-skip branches: the 4 params above). This
matters: an inaccurate coverage claim is the same defect class as Minor 2, and this one holds.

### 5. Assertion audit — 0 assertions removed or loosened (independently counted)

Counted from the diff artifact itself (`awk`/`comm` over the fenced block), not from the report's prose:

- **Totals**: 47 removed / 394 added — exactly the disclosed `+394/−47`.
- **Census of removed lines**: `assert ` ×1, `print(` ×2, `pytest.skip(` ×1, `pytest.raises`/`with pytest` ×0.
- **None of those four was lost**: set-differencing the removed lines against the added lines leaves none of
  them. All four are re-added byte-identically — the moved block's `assert _pinned_package_version() ==
  PINNED_PACKAGE_VERSION` (now `:426`), the two `print(` calls (`:431-435`, `:438-440`) and the opt-in
  `pytest.skip(` (`:421-424`). So the fixed file contains **the same number of assertions, prints and
  skips as `c3d362c`, relocated rather than rewritten**.
- **The genuinely superseded removed lines (16)** are: 7 docstring prose lines, 5 rehearsal-comment lines,
  and 4 code lines — the old `def _seed_archive(...)` signature (superseded by the keyword-extended one,
  existing call sites unchanged), the old combined `bvid`/`cid` guard (superseded by the strictly stronger
  pair), the old ungathered SQL string (superseded by the `gone`-filtered one), and the old `upsert_part`
  call (superseded by the kwarg-passing one). **Not one of them is an assertion, a print, or a skip.**
- **The moved live-flow block differs only by the new `except` clause**: within its hunk the `try`, the
  `asyncio.run(gateway.get_subtitle_tracks(...))` call, the `except GatewayRateLimited` clause, its
  `_record_risk_control_refusal(...)` call and the `_track_evidence` print are **context lines** (byte-identical
  in both revisions); the only addition before them is `except GatewayNotFound:` + its body (`:351-370`), and
  the extracted live test adds only the `_probe_one_part(gateway, bvid, cid, part_source)` delegation
  (`:442`). Nothing else in the block changed.
- **Added assertion lines**: 20 lines containing `assert ` + `assert_leaks_no_markers` = 21, reconciling
  exactly with the disclosed "21 added assertion lines" (19 new `assert` statements + the multi-line
  evidence assert + the leak helper + the one moved-verbatim version assert).

### 6. Non-vacuity — spot-check of the three guards and one rehearsal

Mutation runs are forbidden in this seat (worktree mutation), so I reproduced each mutation's **effect**
without touching the checkout: in-memory SQLite on the shipped `schema.sql` with the exact seeding order the
rehearsal uses, direct evaluation of the old vs. new guard expressions, and the real exception classes
imported from the worktree `src` (`PYTHONDONTWRITEBYTECODE=1`, cwd `/tmp`, no file written).

| Finding | Emulated mutation | Unguarded result | Pinned rehearsal's assertion | Outcome |
|---|---|---|---|---|
| Minor 2 | drop the `except GatewayNotFound` clause | `GatewayNotFound` is not a `Skipped` (`issubclass` = `False`) → it propagates out of `_probe_one_part` | `pytest.raises(pytest.skip.Exception)` + the `track_count=not_found` substring + `calls == ["get_subtitle_tracks"]` (`:852-858`) | **fails exactly `[listing-not-found]`** (the other three params still pass) — matches the recorded `1 failed, 3 passed` |
| Minor 3a | drop `AND processing_status != 'gone'` | rows `(1, 2222, discovered)`, `(2, 3333, gone)` → ordering alone returns **`('BV1AbCdEfGhJ', 3333)`**, the row the archive wrote off | `_read_archive_part(...) == (BVID, REHEARSAL_CID)` (`:586`) | **fails that assertion** — the filter, not the ordering, is what keeps the gone row out |
| Minor 3b | drop the `bvid` shape check | old guard **accepts** `"not-a-bv-id"` (fixture `BVID`, the live sample and `bool cid` behave identically old vs. new) | `_read_archive_part(...) is None` (`:632`) + the fallback assertion (`:633`) | **fails both** — and the stricter guard demonstrably breaks no pre-existing seed |
| Minor 4 | `except ImportError` → a non-matching class | `pytest.fail.Exception` is not an `ImportError` (`issubclass` = `False`); the `None`-in-`sys.modules` monkeypatch does raise `ImportError` | `pytest.raises(pytest.fail.Exception)` (`:658-664`) | **fails `test_unimportable_pinned_module_fails_loudly`** |

All four match the implementer's mutation table row for row, including the "fails *exactly* the pinned
rehearsal" property. The remaining rows (M5–M8) are pinned by assertions I read directly
(`pytest.raises(pytest.skip.Exception)` and `"STOP condition"` for both rate-limited params; the wording
assert for the empty listing; `assert_leaks_no_markers` + `RAW_JSON_BODY_MARKER not in evidence` for the
label-leak mutation), and M7b's honest disclosure (the dropped early return fails via `IndexError` at
`tracks[0]`, not via a clean assertion) is an accurate description of a mutation artefact, not a gap: the
branch's own evidence line is separately pinned by M7a.

**Independent rehearsal run (sanctioned command, offline):**

```
$ env -u BILI_LIVE_SMOKE -u BILI_LIVE_ARCHIVE_DB … -m pytest tests/test_live_subtitle_smoke.py -v -rs
collected 17 items
… 16 passed, 1 skipped in 0.30s
SKIPPED [1] tests/test_live_subtitle_smoke.py:422: live subtitle probe is opt-in: set BILI_LIVE_SMOKE=1 to request it
```

17 collected / 16 passed / 1 skipped reproduces the report exactly (the 9 new cases are all present and
green), the live test is still collected, still the only networked test, and its skip reason is verbatim
unchanged from round 1 — only its line number moved (`:308` → `:422`).

### 7. Regression lens

- **Scope**: one test module, test-only. No production code, no adapter, no DTO, no storage, no harness
  artifact in the diff — so round 1's M1/M2 tightenings and the M4 adapter pin are byte-identical to what
  I approved (`tests/test_bilibili_api_gateway.py` untouched) and needed no re-derivation.
- **No new live surface**: the only new collaborator, `_ScriptedGateway` (`:722-760`), performs no I/O, and
  the live test's call sites are unchanged. `bilibili_api_gateway` still appears exactly twice in the
  module: inside `_load_gateway` (`:189`) and in the new guard rehearsal's monkeypatch string (`:656`).
- **Boundary of the printed material is unchanged or stronger**: the new line prints a fixed
  `part_source` label, a fixed stage and a fixed bounded code. The new evidence-chain rehearsal plants
  **both** leak sentinels inside a track label and asserts `assert_leaks_no_markers` over *everything*
  `_probe_one_part` prints (`:880-881`) — a wider leak check than round 1 had.
- **No collateral test damage**: `_seed_archive` gained two defaulted keywords; all four pre-existing call
  sites are unchanged, and the three pre-existing selection assertions (`:502`, `:529`, `:553`) still hold
  **under the stricter guard** (the fixture `BVID` and the sample both pass it — verified above). No
  duplicate test definition; no line over 88 columns in the module.
- **Importability**: the module still imports neither the adapter nor the pinned distribution
  (`models.py` and `storage/models.py` are stdlib-only), so the rehearsals remain runnable in an
  environment without the pin — the property the new `sys`/`re`/DTO imports could have broken.

### 8. PM decisions verified (not re-litigated)

- **Minor 1** — fixed in the plan by the PM: the Evidence Index (`plan:365-369`) now lists
  `tests/test_live_subtitle_smoke.py` alongside `tests/test_bilibili_api_gateway.py`.
- **Minor 5 / R1** — registered as an accepted-risk residual in `projects/_default/residuals.json`:
  `severity: low`, `decision: defer`, `owner: @project-manager`, `target: 20260911-subtitle-cli-cutover`,
  `source` = this report's item 6. That is exactly the disposition I recommended instead of a "guarded"
  close, and the adapter is untouched by this wave.
- **Minor 6** — accepted design choice; the monotonic-timeline assertion is unchanged (it lies outside
  every hunk), so a future failure of it still needs the recorded decision its message asks for.

### 9. Observations (explicitly **not** findings — no severity, no action owed)

1. **The listing `not_found` collapse also covers "the credential in effect silently stopped working".**
   The boundary maps both a removed part and `-101` to the same class, so an operator whose SESSDATA went
   bad now sees a recorded skip where round 1's code would have failed loudly. This is the disclosed cost
   of the authorized change, it is the spec's own caller-side mapping (`no-subtitle`), and it is mitigated
   by the printed `sessdata=<presence>` and by the skip naming both causes. QA may want to treat
   "credential not in effect" as its own live check; that is a plan-level question, not a defect here.
2. **`_ScriptedGateway` is a partial double of a 6-member `Protocol`** (`_probe_one_part`'s
   `gateway: BilibiliGateway` annotation, `:334`). A type checker would flag the two rehearsals' call
   sites, but this repo has no mypy/ruff configuration and no type-check gate (verified: `pyproject.toml`,
   no CI workflows), so nothing can fail. Noted only so a future typing gate is not surprised.
3. **Label collision for the reader**: the fix report's mutation ids `M1`–`M8` are unrelated to the plan's
   tightening ids `M1`/`M2`/`M4`. Worth a glance at plan QC so the two tables are not conflated.

### 10. Residual risk and carried ⚠️ items

- Carried unchanged from round 1 and **not** resolvable from this seat: the live PASS itself; the
  `floor(seconds*1000)` conversion; the `archive-db` branch never having executed live; the run-(b)/(c)
  provenance; the full-suite total (I re-ran only the sanctioned module command, which is the changed
  file). Items 6 and 7 of round 1's ⚠️ list stay resolved statically.
- Newly narrowed: the `archive-db` branch's *control flow* is now rehearsed offline (gone/foreign rows,
  early return, both blockers, the full evidence chain), so what remains live-only is the branch's I/O, not
  its logic.
- The fix leaves the worktree at `6002f99` with `git status --porcelain` empty (the mutation driver's
  restore-after-mutation claim is consistent with the clean tree I observed).

**Updated counts: 0 Critical · 0 Important · 0 open Minor (6 raised → 3 fixed in this wave, 1 fixed by the
PM, 1 registered as residual R1, 1 accepted design choice) · 1 open residual (R1, low).**

**Verdict: Approve** — the wave is a clean, surgical, test-only fix; it removes the round-1 gaps without
deleting, weakening or hiding a single assertion, and the one authorized behaviour change is exactly as
bounded as the PM authorized it to be.
