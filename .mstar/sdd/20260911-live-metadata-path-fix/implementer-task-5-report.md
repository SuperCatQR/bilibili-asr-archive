# Task 5 implementer report — bound the default page size to an upstream-accepted value

- **Status: DONE_WITH_CONCERNS** (all brief checkboxes done and verified, including the live re-run;
  one deliberate, disclosed scope extension — see §1.2 / concern C1 — needs a PM/QC ruling)
- Plan: `.mstar/plans/20260911-live-metadata-path-fix.md` (Task 5, defect D4)
- Brief: `.mstar/sdd/20260911-live-metadata-path-fix/task-5-brief.md`
- Working branch: `fix/20260911-live-metadata-path-fix` (dedicated worktree
  `.worktrees/20260911-live-metadata-path-fix`), commit **`f44066c`**
  `fix(metadata): bound the shipped page size to the upstream-accepted 30`
- No push, no `main` mutation, no other branch touched. No subagent dispatched (delegation forbidden).
  The only harness file written is this report; no plan / snapshot / status / compass / spec edit.

## 1. Implemented / attempted

### 1.1 Brief checkboxes

- [x] Protocol default and adapter default page size changed 100 → **30**; parameter name unchanged,
      explicit `page_size` override still flows through, **no CLI flag added**.
- [x] Seam (fake protocol double) updated; every test that pinned the old default updated
      (§2 disclosure table); two new non-vacuous tests added (§3).
- [x] PM annotates the pinned spec's "Required upstream calls #1" with the page-size bound —
      satisfied by the PM's own annotation (present uncommitted in the control root, mtime 07:42, quoted
      in §1.2/C4); **not done by me** (this task read no spec file and edited no spec).
- [x] Bounded live re-run of the smoke performed and recorded (§4).

### 1.2 Scope note — the shipped path does not use the adapter/protocol defaults (C1)

Reconnaissance found a third value site that the brief's file list does not name, and that the
brief's own instructions cannot be satisfied without:

- the shipped command path never reaches the adapter default —
  `cli.py:572-575` builds `MetadataIngestor(gateway, repository)` and calls
  `collect_user_pages(mid, start_page, page_limit)`;
- `metadata_ingest.py:225` calls `get_user_video_page(mid, page_number, PAGE_SIZE)` with an
  **explicit third argument**, i.e. the adapter/protocol defaults are bypassed;
- `metadata_ingest.py:46` was `PAGE_SIZE = 100`.

Evidence that this is the value actually shipped and actually sent:

- the pre-change pins `space.arc.search(pn=1, ps=100)` in `tests/test_metadata_cli.py` are exact
  call-list assertions over the **real CLI** — they can only read `ps=100` because the ingestor
  passes `PAGE_SIZE` explicitly;
- `tests/test_metadata_ingest.py:704/852/917` and `tests/test_metadata_e2e.py:305/308/443/575-580`
  run the same ingestor composition;
- the brief itself mandates updating those pins to `ps=30` — unachievable while `PAGE_SIZE = 100`
  unless the forbidden ingestor *logic* is rewritten (dropping the explicit argument), which would
  also delete the public `PAGE_SIZE` name from `__all__`;
- the opt-in live smoke drives exactly that CLI path (`_bounded_live_argv` → `main`) for the
  acceptance criterion "live path able to collect a page";
- corroboration from the PM's own spec annotation (already written before this task started,
  `.mstar/.../specs/bilibili-api-gateway.md` at 07:42, 20 added lines): "**Page-size bound**
  … The one bounded page uses `ps=30`" — i.e. the annotated product behaviour is a *shipped*
  `ps=30`, which only the `PAGE_SIZE` site can deliver.

Decision taken (human interaction is unavailable mid-run in this session, and the assignment says
never to guess): the one-token **value** change `PAGE_SIZE = 100 → 30` is included, because it is the
only reading under which the brief is self-consistent and its live acceptance criterion reachable.
It changes **no** logic: no control flow, cursor semantics (still page-based), DTO field, repository
call, schema, CLI surface, or error taxonomy. Scope clause "do not touch the ingestor **logic**" is
respected; the plan's Global-Constraints sentence "the ingestor unchanged" is technically stretched
by one literal, which is why this report is `DONE_WITH_CONCERNS` rather than `DONE`.
If the PM/QC rules the strict reading, reverting means restoring `PAGE_SIZE = 100` **and** restoring
the ingestor-path pins to `ps=100` — i.e. accepting that D4 stays open on the shipped path and the
live smoke's happy path is again unreachable.

## 2. Files changed (9 files, one commit)

| File | Change |
|---|---|
| `src/bili_asr/sources/models.py:102` (+3-line comment at 98-100) | `BilibiliGateway.get_user_video_page` protocol default `100 → 30`; comment records the upstream bound |
| `src/bili_asr/sources/bilibili_api_gateway.py:283` (+4-line docstring) | adapter default `100 → 30`; docstring states the default and that an explicit `page_size` still overrides |
| `src/bili_asr/services/metadata_ingest.py:50` (+4-line comment) | shipped `PAGE_SIZE = 100 → 30` (see §1.2) |
| `tests/fixtures/fake_bilibili_gateway.py:258` | `FakeGateway` protocol double default `100 → 30` (parity with the protocol) |
| `README.md:509` | current-behaviour statement "the ingestor's page size is 100" → `30` |
| `tests/test_bilibili_api_gateway.py` | 2 imports, 7 pins, 2 new tests (see below) |
| `tests/test_metadata_cli.py` | 5 pins |
| `tests/test_metadata_e2e.py` | 7 pins |
| `tests/test_metadata_ingest.py` | 3 pins |

Every touched assertion (all are exact call-list / docstring renames `ps=100 → ps=30`; **no
assertion was weakened, loosened, skipped, or deleted**):

- `tests/test_bilibili_api_gateway.py` — 199, 444, 1028, 1084 (`assert bilibili_api_seam.calls == [...]`),
  1391 (call list with `video.get_info` / `video.get_pages`), 1418 (opt-in live-probe docstring
  "``ps=30``"); new tests at 216 and 234; imports `inspect` and `BilibiliGateway`.
- `tests/test_metadata_ingest.py` — 704 (ingestor-over-seam call list), 852, 917.
- `tests/test_metadata_e2e.py` — 305, 308, 443 (`.count(...) == 2`), 575, 577, 578, 580.
- `tests/test_metadata_cli.py` — 344, 346, 383, 401 (`.count(...) == 2`), 435 (`.count(...) == 1`).

Not touched: `src/bili_asr/bili_client.py` (legacy client, already 30), DTO fields, ingestor logic,
repository, `schema.sql`, CLI surface, `pyproject.toml`, `uv.lock`, the spec, any harness artifact.

## 3. Tests

Interpreter: `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`
(the control venv; `tests/conftest.py` inserts the worktree `src` first, verified — with the venv's
installed package alone `metadata_ingest.PAGE_SIZE` still reads 100 from the control tree, while the
pytest runs below observe 30, so the worktree sources are what is executed).

Focused (brief command):

```
cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -q
160 passed, 1 skipped in 1.55s
```

Four metadata suites (gateway + ingest + cli + e2e): `197 passed, 1 skipped in 3.24s`.

Full offline suite:

```
.venv/bin/python -m pytest -q
894 passed, 2 skipped in 60.87s
```

Baseline was 892 passed / 2 skipped → 892 + 2 new tests = 894; skip count unchanged.

### Red / green evidence (non-vacuity)

Temporarily reverting the three value sites to 100 (backup, targeted `sed`, restore verified with
`md5sum -c` → `models.py: OK`, `bilibili_api_gateway.py: OK`, `metadata_ingest.py: OK`):

```
$ pytest tests/test_bilibili_api_gateway.py -q -k "defaults_to_upstream_accepted_size or explicit_size_override_keeps_normalization"
>       assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
E       AssertionError: assert ['space.arc.s...n=1, ps=100)'] == ['space.arc.s...pn=1, ps=30)']
E         At index 0 diff: 'space.arc.search(pn=1, ps=100)' != 'space.arc.search(pn=1, ps=30)'
FAILED tests/test_bilibili_api_gateway.py::test_get_user_video_page_defaults_to_upstream_accepted_size
1 failed, 1 passed, 132 deselected in 0.11s
```

The `page_size=50` override test passes either way by design (it pins explicit flow-through, not the
default). The shipped-path pins fail loudly on a 100 regression:

```
$ pytest tests/test_metadata_cli.py tests/test_metadata_ingest.py -q      # with the values reverted
FAILED tests/test_metadata_cli.py::test_fetch_meta_without_flags_resumes_from_stored_cursor
FAILED tests/test_metadata_ingest.py::test_bilibili_api_gateway_run_persists_normalized_rows
FAILED tests/test_metadata_ingest.py::test_bilibili_api_gateway_foreign_owner_page_requests_no_parts
FAILED tests/test_metadata_ingest.py::test_malformed_upstream_bvid_page_fails_bounded_and_preserves_the_prior_cursor[aid-carrying]
FAILED tests/test_metadata_ingest.py::test_malformed_upstream_bvid_page_fails_bounded_and_preserves_the_prior_cursor[aid-less]
9 failed, 52 passed in 2.73s
```

Green after restore, on the committed tree:

```
$ pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -q
160 passed, 1 skipped in 1.55s
$ pytest tests/test_bilibili_api_gateway.py -v -k "defaults_to_upstream_accepted_size or explicit_size_override_keeps_normalization or forwards_requested_page_and_size"
test_get_user_video_page_forwards_requested_page_and_size PASSED
test_get_user_video_page_defaults_to_upstream_accepted_size PASSED
test_get_user_video_page_explicit_size_override_keeps_normalization PASSED
3 passed, 131 deselected in 0.10s
```

New test detail:

- `test_get_user_video_page_defaults_to_upstream_accepted_size` — omits `page_size`, asserts the
  issued call is `space.arc.search(pn=1, ps=30)` **and** that the protocol declaration's default is
  30 (`inspect.signature(BilibiliGateway.get_user_video_page)`); fails if either site reverts to 100.
- `test_get_user_video_page_explicit_size_override_keeps_normalization` — `page_number=2,
  page_size=50` issues `ps=50` and the DTO/`observed_total` normalization is unchanged
  (`mid`, `page_number`, `observed_total == 7`, `videos` tuple, `bvid`/`aid`/trimmed `title`/`pubdate`/`mid`).
- The shipped CLI/ingestor path's `ps=30` is pinned by the updated
  `tests/test_metadata_cli.py` / `tests/test_metadata_e2e.py` / `tests/test_metadata_ingest.py`
  call lists (real CLI over the fake seam, end to end).

## 4. Live re-run evidence

Command (worktree product dir, credential from the repo-root `.env` sourced into the environment,
proxy as specified; the credential value was never printed or persisted):

```
cd bilibili-asr-archive && set -a && source /root/workspace/bilibili-asr-archive/.env && set +a \
  && BILI_HTTP_PROXY=http://127.0.0.1:7890 BILI_LIVE_SMOKE=1 \
     /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
     tests/test_live_metadata_smoke.py -v -s
```

- **Outcome: PASSED / happy path.** `2 passed in 2.75s`, **exit code 0** (the live test plus its
  offline rehearsal; the live test reported `PASSED`, not a skip, and with a credential present the
  bounded-failure branch fails loudly, so this is the exit-0 success branch).
- Count-only evidence line printed by the run:

  `live smoke evidence: outcome=limited videos=30 parts=33 discoveries=30 page_rows=1 cursor_next_page=2 cursor_state=limited observed_total=1691`

- Per-table row counts (evidence line + the smoke helper's own assertions): `videos` 30,
  `video_parts` 33, `ingestion_discoveries` 30, `ingestion_pages` 1 (page 1, outcome `ok`,
  `error_code` NULL), `bilibili_users` 1 (the owner), `ingestion_runs` 1 (terminal, not `running`;
  `requested_start_page=1`, `requested_page_limit=1`, `finished_at` set), `ingestion_cursors` 1.
- Cursor: `next_page=2`, `state=limited`, `observed_total=1691`.
- Interpretation: `videos=30` is exactly one accepted page of 30 → upstream accepted `ps=30` where
  `ps=100` had answered `-400`/HTTP 412, and the page landed as real normalized rows with an advanced
  cursor. **No bounded blocker; no STOP condition triggered; no retry after a throttle was needed.**
- Hygiene: the smoke asserted the absence of credentials/playback markers in CLI output and every
  persisted row, and the absence of the legacy sidecars; the temporary archive root is removed by the
  fixture.
- **Bounded-call disclosure (C3):** the smoke was invoked **twice** — first with `-v` (exit 0, but the
  count-only evidence line went to pytest's capture and was therefore not visible), then again with
  `-s` after a ~100 s pause to print that line for this record. Both invocations are one page, one
  CLI run, no retries; two bounded upstream page requests total. Raw log of the second run:
  `/tmp/task5-live-run.log` (outside the repo).

## 5. Self-review notes

- `git diff --check` clean on the working tree and on the commit range (`f4af1aa..HEAD`).
- Diff is 86 insertions / 27 deletions over 9 files; every hunk traces to D4 or to the brief's
  mandated disclosures.
- Strictness unchanged: all pin edits are literal `ps=100 → ps=30` inside unchanged
  `assert ... == [...]` / `.count(...) == N` expressions; `git diff` shows no changed operator,
  expected value, skip, or xfail anywhere.
- Credential safety: a scan of the full diff for `sessdata=<value>`, `pssign`, `bilivideo`,
  `BILI_SESSDATA=` finds no credential or marker values (only the pre-existing test sentinel constant
  names and the redacted `sessdata: present` label). Nothing secret was printed, logged, or written;
  `.env` was only sourced.
- Writes: only the 9 product files inside the feature worktree, plus this report in `.mstar/sdd/...`.
  No harness artifact (plan / snapshot / status / compass / spec) was modified **by me**. Attribution
  note for QC: the control root does show tracked `.mstar` edits — the spec annotation + plan update
  (mtime 07:42, the PM's Task-5 annotation/evidence work) and `status.json` / both `snapshot.json`
  files (mtime 06:56, engine state); this report is the only file I wrote (mtime 07:51).
- Test-double parity: `FakeGateway`'s default now mirrors the protocol default, so a future
  "restore 100" in one place is caught by the seam test.
- Naming: the `naming-analyzer` preference was applied to the two new test names — verb-phrase,
  scope-consistent with the existing `test_get_user_video_page_*` family, no abbreviations, no ambiguity.

## 6. Concerns / disclosures for PM and QC

- **C1 (needs a ruling) — scope extension:** `src/bili_asr/services/metadata_ingest.py:50`
  `PAGE_SIZE 100 → 30`. Rationale and evidence chain in §1.2; without it the brief's own mandated
  `ps=30` pins (ingest/e2e/cli) cannot pass and the live smoke's happy path is unreachable, i.e. D4
  stays open on the shipped path. Value only — no logic, DTO, repository, schema, or CLI-surface
  change. If QC rules the strict reading, the revert path is stated in §1.2.
- **C2 — docs narrative:** `README.md:509`'s current-behaviour statement was updated to 30.
  `docs/metadata-storage.md:196-210` was deliberately **left unchanged**: it is a dated record of the
  2026-09-11 observation (when the shipped page size *was* 100, so the sentence stays historically
  true) and its closing sentence says whether the endpoint caps `ps` below 100 "was not settled by
  those observations". That question is now settled by D4's probes and this live run; updating that
  narrative is a docs/evidence-narrative change outside this task's brief, so it is flagged here for
  the PM/QA (or a docs touch-up) rather than piggyback-edited.
- **C3 — two bounded live invocations** instead of one, for the reason in §4. No retry storm, no
  additional call shape, total two one-page requests.
- **C4 —** the pinned spec's page-size-bound annotation is **already present** in the control root
  (uncommitted, PM-authored, mtime 07:42: "**Page-size bound (2026-09-11, same plan).** The one bounded
  page uses `ps=30`"), with the numbered clause 1 left showing `ps=100` as the annotated-not-rewritten
  original. I did not touch the spec. The PM may want to align the clause-1 literal with the
  annotation now that the shipped code is 30 (and note that the last bullet of
  `docs/metadata-storage.md`'s 2026-09-11 observation, C2, is superseded by this task's live run).
- **C5 —** the new default test pins the protocol *declaration* via `inspect.signature` in addition to
  the observed call; that is an intentional contract pin (the brief's deliverable names the
  protocol default), not an implementation-detail assertion.

## 7. Residuals

None registered by me (registration is PM-owned). No in-repo leftover: worktree clean at `f44066c`,
no untracked files, temporary files used for the red check removed (`/tmp/t5backup`), no credential
material anywhere. Open items for the PM: C1 ruling, C2 docs narrative, C4 spec annotation.
