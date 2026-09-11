# SDD Progress — 20260911-live-metadata-path-fix

Task 1: complete (`25a11fe..cc56e46`, review Approved — Critical 0 / Important 0 / Minor 4)

- Implementer commit: `cc56e46 fix(deps): declare curl_cffi as the runtime HTTP backend`
- Task reviewer: `review/task-1-review.md` (fresh code-reviewer, Mode A, L2, diff-first)
- Runtime evidence: red-first parity test; focused `105 passed, 1 skipped`; full offline suite
  `866 passed, 2 skipped` (865+2 baseline + 1 new test); `uv lock --check` exit 0 and a second
  `uv lock` byte-identical (sha256 4cf305d6…); lock diff `+35/-0` (additive, 99 packages)
- Scope: exactly `pyproject.toml` (+`curl_cffi>=0.16`), `uv.lock`, `tests/test_bilibili_api_gateway.py`;
  pin `bilibili-api-python==17.4.2` retained; no `src/` change (mtime probe confirmed by reviewer)
- Reviewer independently reproduced: `uv lock --check` + digest, focused counts, and
  **non-vacuity** (stripping the declaration makes the test fail)
- PM disposition of reviewer ⚠️ items: (1) wheel hash vs PyPI → QA gate; (2) "fresh install can
  import a backend" (no `uv sync` run; venv has the diagnosis install) → Task 4 + QA gate closes it
  with a clean sync; (3) full-suite re-run → QA gate.

## Minor (for plan QC) — Task 1 (code-reviewer)

1. Test's pinned-distribution half reads whichever `bilibili-api-python` is installed; asserting
   `version == PINNED_PACKAGE_VERSION` would make it exact (constant already in scope).
2. Client-intersection check is extras-blind (a future `httpx; extra == "dev"` would trip it).
3. Report table arithmetic: test file `+75/-1` (headline 111 insertions correct).
4. Module docstring's absolute "real package never required" precedes its own explicit exception.

## Next

Task 2: resolve and apply proxy configuration in the gateway (BASE `cc56e46`).

## Task 1 Gate

- [x] Implementation committed on assigned feature branch
- [x] Task reviewer completed (Approved; no Critical/Important findings)
- [x] Reviewer ⚠️ items dispositioned by PM (QA-gate + Task-4 routing recorded above)
- [x] Ready to proceed to Task 2

## End of Task 1

Task 2: complete (`cc56e46..0a2e2f5`, review Approved — Critical 0 / Important 0 / Minor 3)

- Implementer commit: `0a2e2f5 fix(gateway): resolve and apply the proxy for the pinned package`
- Task reviewer: `review/task-2-review.md` (fresh code-reviewer, Mode A, L2, diff-first)
- Runtime evidence: red-first (ImportError → TypeError on the new kwarg); focused
  `158 passed, 1 skipped` (baseline 139+1 → +19 proxy tests); full offline suite
  `885 passed, 2 skipped` (866+2 baseline → 0 regressions); 6 mutation checks each caught
  (always-apply, per-request apply, reversed precedence, dropped blank handling, error leak,
  DTO/row leak); reviewer re-ran the focused command and probed the real pin's wiring
- Scope: `src/bili_asr/config.py` (pure `resolve_proxy` + env constants, third-party-free),
  `src/bili_asr/sources/bilibili_api_gateway.py` (`BilibiliApiGateway(sessdata, proxy)`,
  `resolved_proxy`, apply-once), `tests/test_bilibili_api_gateway.py`,
  **plus the shared fake seam** `tests/fixtures/fake_bilibili_gateway.py` (+25/−5)
- PM adjudication: the seam fixture was outside the brief's file list but is shared by 4 test
  modules and could not be avoided; **accepted**. Reviewer independently confirmed the change is
  additive (recorder list + mirror module + docstring), `script.calls` untouched so all exact
  call-list assertions in the ingest/CLI/E2E suites keep full strength.
- PM disposition of reviewer ⚠️ items: full suite + mutation checks + `git diff --check` →
  mandatory QA gate re-runs; proxy surface wired to the real `CurlCFFIClient` link → covered by
  the reviewer's manual wire probe + version-pin assertions; Task-4 surfaces untouched by design.

## Minor (for plan QC) — Task 2 (code-reviewer)

1. Fake `set_proxy(proxy: str = "")` has a default the real `RequestSettings.set_proxy(self, proxy: str)`
   lacks — a no-arg call would pass offline and fail live.
2. Disclosure arithmetic: fixture is `+25/−5` (headline `+324/−15` correct).
3. `request_settings` is process-global while `resolved_proxy` is per-instance (latent; one construction site).

## Next

Task 3: risk-control-safe user-video page call (BASE `0a2e2f5`).

## Task 2 Gate

- [x] Implementation committed on assigned feature branch
- [x] Task reviewer completed (Approved; no Critical/Important findings)
- [x] Disclosed scope deviation adjudicated by PM (fixture extension accepted; reviewer-confirmed additive)
- [x] Ready to proceed to Task 3

## End of Task 2

Task 3: complete (`0a2e2f5..3a96dd1`, review Approved — Critical 0 / Important 0 / Minor 3)

- Implementer commit: `3a96dd1 fix(gateway): issue the user-video page call in a risk-control-safe shape`
- Task reviewer: `review/task-3-review.md` (fresh code-reviewer, Mode A, L2, diff-first)
- Runtime evidence: red 7 failed → focused `158 passed, 1 skipped`; full offline suite
  `892 passed, 2 skipped` (885+2 baseline → +7 new shape tests); offline probe against the
  **real pin**: construction accepted, `dm-family keys: []`, `w_webid` present; `git diff --check` clean
- Call shape now issued: package config `url/method/verify/wbi` + `dm=False` override, params
  `mid/ps/tid/pn/keyword/order/order_avoided/platform/w_webid` (non-empty `access_id` preferred,
  else `""`, memoized per user per adapter instance), response via the untouched normalizer
- PM adjudication: (1) seam call-label rename (`user.get_videos` → `space.arc.search`) with
  mechanical assertion renames in three metadata test files — **accepted**; reviewer verified
  line by line that strictness (exact lists/counts/order, import allow-list, forbidden-name
  positive control) is unchanged and `user.get_videos` detection is now *stronger*;
  (2) token-route `except Exception` degradation — **accepted** (plan-locked; `CancelledError`
  propagates, tested).
- PM action completed: pinned spec §Required upstream calls annotated with the transport
  amendment (PM-owned edit; reviewer had flagged it as outstanding).
- PM disposition of reviewer ⚠️ items: live acceptance → Task 4 + QA gate; full-suite re-run →
  QA gate; WBI signature well-formedness → rests on source inspection + live evidence (recorded).

## Minor (for plan QC) — Task 3 (code-reviewer)

1. Stale docstring at `tests/test_bilibili_api_gateway.py:1220` (prose predates the new import set).
2. `_resolve_w_webid`'s blanket `except Exception` also masks programming errors as "token
   unavailable" (plan-locked, documented, tested — diagnosability note only).
3. The token route sits outside the seam's documented-call allow-list by design (asserted separately).

## Next

Task 4: bounded live verification + operator documentation (BASE `3a96dd1`).

## Task 3 Gate

- [x] Implementation committed on assigned feature branch
- [x] Task reviewer completed (Approved; no Critical/Important findings)
- [x] Disclosed changes adjudicated by PM (label rename accepted; degradation accepted)
- [x] PM-owned spec annotation applied
- [x] Ready to proceed to Task 4

## End of Task 3

Task 4: implemented (`3a96dd1..f4af1aa`, review **Needs fixes** — 0 Critical / 1 Important / 5 Minor)

- Implementer commit: `f4af1aa test(metadata): assert the live happy path; document transport + proxy`
- Task reviewer: `review/task-4-review.md` (fresh code-reviewer, Mode A, L2, diff-first)
- Runtime evidence: default run skips cleanly (`1 passed, 1 skipped`); red evidence on the new
  assertions (mutation → `assert 1 == 2`, restored); full suite `892 passed, 2 skipped` at that head
- Live attempt at Task-4 time: exit 2, bounded `response_error` (upstream JSON `-400` at the then-default
  `ps=100`), cursor unchanged, no leak — recorded honestly as a bounded blocker, not success
- **I1 (Important, docs-only):** `docs/metadata-storage.md:198-210` says "the ingestor's page size of 100"
  and "whether the endpoint caps `ps` below 100 was not settled" — false at HEAD after Task 5
  (`PAGE_SIZE = 30`, README says 30, D4 settled with live evidence). Reviewer: not a Task-4 execution
  fault (true of Task 4's own observations), fix = rewrite the bullet as a dated reading + settled D4 evidence.
- PM ruling on routing: **one batched docs/hygiene fix wave** (Task-4 I1 + Task-4 minors + Task-5 minors),
  then targeted re-review by the two raising seats.
- Reviewer verified sound: happy-path assertions non-vacuous and strictly stronger; anonymous bounded
  failure asserted-then-skipped; credentialed bounded failure `pytest.fail`; scope guard exactly the
  4 allowed paths; no credential/payload leakage; proxy precedence matches code.

Task 5: implemented (`f4af1aa..f44066c`, review **Approved** — 0 Critical / 0 Important / 6 Minor)

- Implementer commit: `f44066c fix(metadata): bound the shipped page size to the upstream-accepted 30`
- Task reviewer: `review/task-5-review.md` (fresh code-reviewer, Mode A, L2, diff-first)
- Runtime evidence: focused `160 passed, 1 skipped` (reviewer reproduced exactly); full suite
  `894 passed, 2 skipped`; red proof (reverting the three sites → default test + 9 shipped-path pins fail)
- **Live happy path achieved (exit 0):** `outcome=limited videos=30 parts=33 discoveries=30 page_rows=1
  cursor_next_page=2 cursor_state=limited observed_total=1691`; artifact `/tmp/task5-live-run.log`
  (reviewer confirmed the evidence line verbatim, zero credential hits)
- PM ruling verified independently by the reviewer as sound: the shipped `PAGE_SIZE` literal change is
  exactly one literal + 4 comment lines, recorded in the plan's locked decision + Task 5 file list
- Reviewer verified: all three sites read 30 on disk; shipped-path trace `cli → ingestor(PAGE_SIZE) →
  adapter → ps=page_size`; no CLI flag; 20 pin renames same-shape (`==` / `.count()==N`), nothing loosened;
  no `ps=100` assertion remains; legacy `bili_client.py` untouched

## Minor (for the batched fix wave / plan QC)

Task 4: (a) documented live-smoke command hides the evidence line on success → document `-s`/`-rP`
(and QA should use it on the first attempt); (b) docs/README offer `--sessdata` although only
`BILI_SESSDATA` reaches the smoke; (c) `test_live_metadata_smoke.py:205-207` comment claims per-video
part coverage but asserts an aggregate; (d) documented `source ../.env` + `.venv/bin/python` do not
resolve from a linked worktree (no `.env`/`.venv` there); (e) `.env.example:16-19` wording tension.
Task 5: (f) `src/bili_asr/config.py:30` stale "page size of 100" comment; (g) `docs/metadata-storage.md:209`
"not settled" (same as I1); (h) fake seam scripts `"ps": 100` (inert); (i) red-proof transcript abridged;
(j) report says 7 pins, enumerates 6.

## Next

Batched docs/hygiene fix wave (I1 + a–j where fixable) → targeted re-review N=2 →
branch review package → plan QC tri (N=3) → mandatory QA gate (owns the live re-run with `-s`).

Fix wave 1: implemented (`f44066c..5667844`, batched docs/hygiene findings; re-review in flight)

- Implementer commit: `5667844 docs(metadata): reconcile page-size/live-smoke prose with the shipped 30 default`
- Runtime evidence: live smoke stays `1 passed, 1 skipped` (no network); full offline suite
  `894 passed, 2 skipped`; metadata-focused four files `197 passed, 1 skipped`; `git diff --check` clean
- Covered: Task-4 I1 (docs page-size narrative reconciled: dated reading + settled D4 evidence +
  shipped 30 default), Task-4 M1 (`-s -v` documented with the "pytest hides passing stdout"
  rationale and a first-attempt `-s`/`-rP` note), M2 (`BILI_SESSDATA`-only credential channel in
  docs/README **plus** the same false claim inside the test's own skip message — disclosed),
  M3 (test comment/docstring aligned to the aggregate assertion; rationale: `_normalize_video_parts`
  may legitimately return `()` and no per-video part count is persisted), M4 (documented commands now
  use `CONTROL=/root/workspace/bilibili-asr-archive` for `.env` + interpreter, with the worktree
  limitation stated), M5 (`.env.example` proxy/retention wording + commented default `0`),
  Task-5 #1 (`config.py` comment → 30/300 videos), Task-5 #3 (seam scripted `"ps": 30`)
- PM-owned corrections in the same round: spec protocol default `page_size: int = 30`; spec clause 1
  rewritten for the WBI shape + `ps=30`; page-size annotation retained
- Stale-100 sweep result: no unintended `100` remains in product/docs prose (the dated reading and
  the rejection evidence intentionally mention it)

## Next

Targeted re-review N=2 (Task-4 seat + Task-5 seat) → plan Task 4/5 closure → branch review package
(`25a11fe..HEAD`) → plan QC tri (N=3) → mandatory QA gate (owns the live re-run with `-s`, the full
suite, `uv lock --check`, and a clean `uv sync` install proof) → PR to main → plan Done.

Fix wave 1 re-review (targeted N=2): **both seats Approve**

- Task-4 seat (`## Revalidation` in review/task-4-review.md): I1 + M1–M5 all resolved; M3 "wording over
  strengthening" pushback upheld on verified evidence (empty pagelist is legitimate; no per-video part
  count is persisted); regression lens: every hunk is prose/comment/string/inert fixture — no assertion,
  constant, DTO, schema, CLI, or packaging change; sanctioned focused run `1 passed, 1 skipped`
- Task-5 seat (`## Revalidation` in review/task-5-review.md): its three acted-on Minors resolved (config
  comment arithmetic 10×30=300; docs "not settled" gone; fixture `"ps": 30` inertness re-proven three
  ways); report-only Minors #4/#5 accepted with no action; focused run `160 passed, 1 skipped`
- PM-owned follow-ups applied in the same pass: plan "Page call" + "Page size" bullets rewritten so the
  plan no longer claims the spec was never rewritten (it was annotated AND corrected in place)

Task 4: complete (`3a96dd1..f4af1aa` + fix wave `5667844`, review Approved after fixes)
Task 5: complete (`f4af1aa..f44066c` + fix wave `5667844`, review Approved)

## Next

Branch review package (`25a11fe..5667844`) → plan QC tri (N=3) → consolidated → mandatory QA gate
(owns the live re-run with `-s`, the full suite, `uv lock --check`, and a clean `uv sync` proof) →
PR to main → plan Done.

Plan QC tri (N=3): seat1 **Request Changes** (0C/1W/5S/0⚪) · seat2 **Approve** (0C/0W/8S/0⚪) · seat3 **Approve** (0C/0W/10S/0⚪)

- Seat 1's single Warning (F-001, knowledge/doc-only): `.mstar/knowledge/architecture-patterns/normalized-metadata-stack.md`
  still asserted the invalidated "anonymous anti-bot rejection" claim that this plan's §Problem D1 declares
  invalid, while the plan itself is tracked on main → main shipped both statements unreconciled; the plan's
  "no further remediation is required" sentence did not hold for the tracked knowledge doc.
- All three seats independently re-derived D1–D4 from the **installed pin sources** (seat 3 also audited the
  lockfile delta: zero removal lines, sha256 sdist + 21 wheels incl. `manylinux2014_aarch64`), confirmed
  contract intactness, and confirmed the live evidence is genuinely branch code (conftest puts the worktree
  `src` ahead of the control venv's editable install; control `main` still has `PAGE_SIZE = 100`).
- QA hand-offs recorded by all seats: fresh `uv sync` / `uv lock --check` proof; a real request through that
  fresh env; full suite at HEAD; the bounded live smoke re-run **with `-s`**; and (seat 1) running the live
  smoke **from the worktree package dir** because the control `.venv` editable install points at pre-fix code.

Fix wave 2 (product, `5667844..a898fdf`) **and** PM harness corrections (`c9f820c` on main):

- `a898fdf` (tests + docs only, behaviour-free, +9 tests → full suite **903 passed, 2 skipped**):
  live-smoke anonymous arm restricted to the documented bounded codes (`ANONYMOUS_BOUNDED_ERROR_CODES` +
  gate helper, positive control, 6 params); `.env.example` claim corrected; page-size bound documented
  (no runtime validation); **fake-endpoint mirror parity test vs the installed pin** + "dm is the only
  override" behavioural test; fake `set_proxy` default removed + signature parity test; proxy globality /
  "force direct" documented; stale test docstring corrected; packaging test now asserts the pin version.
  Non-vacuity proven by mutation probes (broadening/narrowing the code set, mirror drift, extra override,
  re-added default, pin-version drift — each fails the guarding test and passes again when reverted).
- `c9f820c` (PM-owned harness edits, committed so they cannot be lost — QC2 F-006): knowledge doc bullet
  rewritten (+3 transport/proxy/call-shape bullets, `last_updated` bumped, explicit invalidation note);
  plan §Durable Roadmap corrected; plan Task-2 shared-fixture deviation disclosed in its Files list;
  spec protocol block now lists the 4th shipped method, page-call clause names the WBI-signed call with
  `ps=30`, page-size bound annotated.

Targeted re-review N=2 in flight (seat 1 for the Warning + seat 2 for its F-001…F-008 dispositions).
