# QA Gate Report (L4 acceptance) — 20260909-metadata-cli-smoke

- Plan: `20260909-metadata-cli-smoke` · Iteration: `iter-2026-09-bilibili-api-sqlite`
- QA gate: **mandatory** · QA mode: **acceptance-only** (evidence reuse first; QC routed four fresh-evidence items U1–U4 to this gate)
- Review cwd: `/root/workspace/bilibili-asr-archive/.worktrees/20260909-metadata-cli-smoke` · Working branch: `feature/20260909-metadata-cli-smoke` · HEAD: `1a99751`
- Review range / Diff basis: cumulative plan branch `18b6353..1a99751` (4 commits: `849c046`, `cf490ff`, `c86daa7`, `1a99751`)
- Report date: 2026-09-10 · Executor: `qa-engineer` (leaf; no delegation)
- **Verdict: Approve (recommend merge)** — see [Verdict](#verdict)

## Scope tested

L4 acceptance of the SQLite-backed metadata CLI plan: DoD mapping for the plan's
Acceptance/Done criteria against reused L1/L2/L3 evidence plus the four QC-routed
fresh-evidence items — U1 suite re-runs at the post-fix head, U2 opted-in live
smoke (both resolution paths), U3 isolated-install packaging, U4 third-party
side-effect observation. Read-only on the worktree except this report and the
plan's `## QA Gate Summary` line; no git mutations.

## Checkout alignment (hard gate)

| Item | Assignment | Observed | Match |
|---|---|---|---|
| Review cwd | `.worktrees/20260909-metadata-cli-smoke` | same | ✅ |
| Working branch | `feature/20260909-metadata-cli-smoke` | same (`git branch --show-current`) | ✅ |
| HEAD | `1a99751` | `1a997518e06d99c36a66297b689d2a373820a732` | ✅ |
| Range | `18b6353..1a99751`, 4 commits | `git log` shows exactly `849c046 → cf490ff → c86daa7 → 1a99751` on top of `18b6353` | ✅ |
| Tree | clean start/end | clean at start; re-verified clean (`git status --porcelain` = 0 lines) after all runs and scratch cleanup | ✅ |

Runner environment: the worktree has no `.venv`; all commands use the control-checkout
interpreter `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`
(exactly as the implementers and the assignment prescribe). Code-under-test proof:
the control checkout has **no** `src/bili_asr/config.py` (verified by `ls`), while every
new test module imports `bili_asr.config` at collection — the green runs below therefore
necessarily executed the worktree `src/` via `tests/conftest.py`'s `sys.path` insert.

## Evidence reuse map (acceptance-only)

Reused (findings, not a test log — QC is diff review):

- Implementer reports: `implementer-task-1-report.md` (CLI rewiring, 31 focused tests, TDD red→green, legacy-test retirement arithmetic 857−34+31=854, pyproject audit-only decision), `implementer-task-2-report.md` (3 E2E tests covering all five scripted scenarios, non-vacuous sentinel scans), `implementer-task-3-report.md` (live smoke opt-in design, offline rehearsal of all three outcome branches, docs), `implementer-qc-fix-1-report.md` (W1/W2 + S-fix-1…7, disclosed deviation: one redundant anonymous manual probe).
- L2 task reviews: `review/task-1-review.md`, `task-2-review.md`, `task-3-review.md` (all Approved, 0 Critical/Important) via `progress.md` ledger incl. PM dispositions (suite/isolated-install/live-smoke evidence explicitly deferred to this gate).
- QC bundle: `qc1/qc2/qc3.md` + `qc-consolidated.md` — initial tri 3×Request Changes (0 Critical; W1 exit-2 doc drift, W2 default-bound doc gap; 7 fix-now suggestions), fix wave `1a99751`, revalidation: qc2 **Approve**, qc3 **Approve**, qc1 no open defects (**Unconfirmed** solely per the ⚪ template floor = U1–U4 routing). Composition-contract facts cross-seat verified: single entrypoint, repository-only `archive.db` writes, zero legacy-sidecar I/O, structural redaction, bounded smoke.
- Docs accuracy: I independently spot-read the README fresh-start section and `docs/metadata-storage.md` exit tables at `1a99751` — default bound `DEFAULT_PAGE_LIMIT = 10`, two exit-2 variants (gateway fail-fast vs unexpected internal error), exit-1 meaning restored, blank `--sessdata`/blank-env anonymous clause, exact smoke command — consistent with the fix report and the PM-edited spec.

## Fresh evidence executed at this gate (U1–U4)

### U1 — suite re-runs (post-fix baseline)

| Command (from worktree `bilibili-asr-archive/`, control venv python, `-p no:cacheprovider`) | Expected (QC consolidated) | Observed |
|---|---|---|
| `python -m pytest -q` | 861 passed, 2 skipped | **861 passed, 2 skipped in 55.57s** (exit 0) |
| `python -m pytest tests/test_metadata_cli.py tests/test_metadata_e2e.py tests/test_live_metadata_smoke.py -v -rs` | 38 passed, 1 skipped | **38 passed, 1 skipped in 2.13s** (exit 0) |

The single focused skip is the opt-in gate (`tests/test_live_metadata_smoke.py:250: live smoke is opt-in`). Implementer-reported counts are now independently confirmed at `1a99751`. The two full-suite skips are the Plan-2 and Task-3 opt-in live smokes.

### U2 — opted-in live smoke (both resolution paths)

1. **Anonymous bounded-failure path — EXECUTED, valid evidence.**
   Command: `cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v -rs` (exact assignment command + `-rs` for skip-reason capture).
   Observed: `1 passed, 1 skipped in 0.50s`. The live test **ran** (opt-in honored; pinned-dist loud-fail guard passed: `bilibili-api-python==17.4.2` present). It executed the real CLI `fetch-meta --mid 23191782 --start-page 1 --limit-pages 1` into a temporary archive root; upstream rejected the no-credential request with the designed bounded failure (scalar code `response_error`, exit 2). Before reporting, the test asserted the bounded-failure evidence (terminal run row, one scalar page row, user row present, zero video/part/discovery rows, zero cursor rows, bounded stderr with `metadata gateway failure`) and the sidecar/leak scans — then skipped with the documented reason naming the code and the credential requirement. This is precisely the "clearly-reasoned skip" outcome the assignment and Plan-2's QA note define as valid bounded-failure evidence. The offline rehearsal test passed in the same run.
2. **Credential happy path — explicit live-network blocker (recorded, not fabricated).**
   `BILI_SESSDATA` check on this machine: **unset** (`[ -n "$BILI_SESSDATA" ]` false; presence checked only, value never read into any output). Credential entry verified from source without modifying the test: the CLI resolves the credential itself via `config.resolve_sessdata` (flag → `BILI_SESSDATA` → None); the test reads the env var only for value-leak scanning and the anonymous-vs-credential branch. With no credential available, per the assignment and the test's own skip semantics, the happy path is recorded as **explicit live-network blocker: no operator credential on this machine**. The anonymous bounded-failure evidence from step 1 stands as the live-smoke evidence the plan's Completion Evidence clause accepts ("live-smoke evidence or an explicit live network blocker" — here both: bounded-path evidence + explicit blocker for the happy path).

### U3 — isolated-install packaging evidence

Executed once, then all scratch removed (nothing committed, worktree re-verified clean):

1. `uv build --wheel --out-dir /tmp/qa-u3-dist` → `bili_asr-0.1.0-py3-none-any.whl` built successfully from the worktree sources (`pyproject.toml` untouched).
2. `uv venv /tmp/qa-u3-venv --python 3.12` + `uv pip install --python /tmp/qa-u3-venv/bin/python --offline <wheel>` → installed successfully **fully offline** (warm uv cache; full dependency tree incl. the pinned `bilibili-api-python==17.4.2` per dist metadata `Requires-Dist`).
3. From a neutral cwd (no worktree shadowing): `import bili_asr, bili_asr.cli, bili_asr.config` all resolve to the **scratch venv's site-packages**; `cli.main` callable; `DEFAULT_PAGE_LIMIT = 10`, `DEFAULT_MID = 23191782` present in the installed `config`.
4. Package data: `site-packages/bili_asr/storage/schema.sql` present in the installed dist (Plan-1 package-data contract holds through packaging).
5. Console script: `/tmp/qa-u3-venv/bin/bili-asr --help` → exit 0; usage lists `fetch-meta` / `status` / `runs` with the corrected SQLite wording (S-fix-1 visible in the packaged artifact).
6. Cleanup: removed `/tmp/qa-u3-venv`, `/tmp/qa-u3-dist`, the marker file, and the setuptools byproducts the build dropped in the worktree (`bilibili-asr-archive/build/`, `src/bili_asr.egg-info/` — untracked, created by this U3 run); `git status --porcelain` back to 0 lines.

### U4 — third-party side-effect observation during the live run

Method: filesystem marker bracket around the U2 live run (`find /root /tmp /var/tmp -xdev -type f -newer <marker>` after the run). Observation:

- **No writes attributable to the pinned package** were observed outside the temporary archive root. All `-newer` hits were concurrent host/harness activity from other sessions (`/root/.npm/_logs`, `/root/.dsh` session stores, other sessions' `/tmp` scratch) — none under the venv, none under any bilibili-related cache location, none in the control checkout.
- Source-level confirmation: the only filesystem writes in the installed `bilibili_api` package live in modules the metadata path never invokes (`ass.py` danmaku/ASS conversion, `interactive_video.py`, `login_v2.py` QR temp file, download/picture helpers); the network/session layer used by `fetch-meta` performs no cache or cookie-jar persistence.
- The live run's temporary archive root was fully torn down (`find /tmp/pytest-of-root -name '*archive*' -newer <marker>` → empty).

## DoD mapping (plan `## Acceptance / Done Criteria`)

The plan lists 8 criterion bullets; together with the `## Completion Evidence` clause
(offline tests + live-smoke evidence or explicit blocker + clean command path) the
assignment's count of 9 acceptance items maps as rows 1–8 + 9.

| # | Criterion | Evidence | Mode |
|---|---|---|---|
| 1 | CLI creates/reads only the fresh SQLite DB at `{archive_root}/archive.db` | Task-1 report + 31 focused tests (fresh-DB creation, read commands existence-check); QC cross-seat "repository-only archive.db writes"; U1 re-run green (includes those tests); U3 installed artifact exposes same CLI | Reused + fresh U1/U3 |
| 2 | Offline fake-gateway E2E: single-part, multipart, duplicate-page idempotency, failed page w/ cursor preservation, resume | Task-2 report (3 E2E tests map 1:1 onto the five scenarios, exact-row + view assertions); task-2 review Approved; U1 focused re-run: all three E2E tests passed | Reused + fresh U1 |
| 3 | Opt-in live smoke bounded: UID 23191782, `--limit-pages 1`, temp root, no subtitle/playback/audio/ASR code | **Fresh U2**: anonymous bounded path executed (`response_error` → exit 2 → reasoned skip after assertions); bound verified from test source (`LIVE_SMOKE_MID` literal, `--start-page 1 --limit-pages 1`, temp root, imports limited to cli/config/storage/fixtures); happy path = explicit `BILI_SESSDATA`-unset blocker | Fresh U2 (+ source read) |
| 4 | No legacy files (`manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`) created or read | `LEGACY_SIDECAR_PATHS` absence assertions in all three new test files; QC verified zero legacy-sidecar I/O; U1 re-run green; in U2's live run the sidecar-absence assertions executed before the bounded-failure skip | Reused + fresh U1/U2 |
| 5 | No credentials/signed URLs/raw JSON/raw exception text in output, logs, persisted rows | E2E sentinel scans non-vacuous (positive controls, S-fix-7b); status-output no-leak scan; live smoke scans output+rows incl. operator env value (S-fix-4 truthiness); C5 bounded `unexpected error` line (no traceback/payload); U2's live scan ran against real upstream surfaces before skipping. This report and all outputs contain masked presence only | Reused + fresh U1/U2 |
| 6 | README + `docs/metadata-storage.md` accurate fresh-start workflow, commands, exit codes | QC revalidation W1/W2 resolved (five-way spec/README/docs/docstring/test consistency, seats 2/3 Approve); my independent spot-read at `1a99751` confirms default bound, two exit-2 variants, exit-1 row, credential boundary, exact smoke command | Reused + fresh doc read |
| 7 | Existing suite green or intentional contract changes updated in-plan | **Fresh U1**: 861 passed, 2 skipped at `1a99751`; intentional changes (34 legacy JSONL-contract CLI tests retired, 4 rewritten) documented in Task-1 report + PM adjudication in `progress.md`; arithmetic reconciles 854→857→858→861 | Reused + fresh U1 |
| 8 | `git diff --check` clean | **Freshly executed** at `1a99751`: exit 0, clean; tree clean after all runs (0 porcelain lines) | Fresh |
| 9 | Completion Evidence: offline tests + live-smoke evidence or explicit live-network blocker + clean metadata command path | Offline = U1 (full + focused); live smoke = U2 bounded-path evidence + explicit `BILI_SESSDATA`-unset blocker for the happy path (plan allows either; both recorded); clean command path = AC 1/2 + U3 isolated install + console script | Fresh U1–U3 |

## Residual check

- Engine status (mstar v3.7.3): `residuals: none open`.
- No project residual register exists (`{HARNESS_DIR}/projects/` absent — nothing ever registered for this plan).
- QC consolidated: "Zero open residual R# (`zero-residual` satisfied)"; plan Review Gate Summary: "Residual findings: none open"; next-iteration carries (TOCTOU remainder, `ingestion_runs` scoping note, test-helper consolidation) are Durable Roadmap items in the plan, not residuals.
- **Confirmed: zero open residuals for this plan.**

## Findings

No new defects. Minor operational notes (non-blocking, no action required):

1. U3 via `uv build` drops untracked setuptools byproducts (`build/`, `src/bili_asr.egg-info/`) into the worktree; removed in this session. Future gate runners should build with `--out-dir` outside the worktree (as done here) and re-check `git status`.
2. U2's happy path remains pending on operator credential availability; the plan's Completion Evidence clause is satisfied via the bounded-path evidence + explicit blocker, and the credential path's logic is rehearsed offline (all three branches) — carrying the happy-path demonstration forward is optional and needs no code change.

## Not tested

- The credential happy path live (blocked: `BILI_SESSDATA` unset — recorded, not fabricated; no cookie material was created, read into outputs, or written anywhere).
- Corpus-scale or subtitle/audio/ASR behavior (explicitly out of the plan's Verification Boundary).
- Spec integration merge / PR (PM-owned; integration merge precedes Done).

## Reproduction steps

From `/root/workspace/bilibili-asr-archive/.worktrees/20260909-metadata-cli-smoke/bilibili-asr-archive` with the control venv python:

1. `python -m pytest -q -p no:cacheprovider` → 861 passed, 2 skipped
2. `python -m pytest tests/test_metadata_cli.py tests/test_metadata_e2e.py tests/test_live_metadata_smoke.py -v -rs -p no:cacheprovider` → 38 passed, 1 skipped
3. `BILI_LIVE_SMOKE=1 python -m pytest tests/test_live_metadata_smoke.py -v -rs -p no:cacheprovider` (anonymous) → 1 passed, 1 skipped (documented bounded anonymous rejection skip)
4. `uv build --wheel --out-dir <tmp>`; `uv venv <tmp-venv> --python 3.12`; `uv pip install --python <tmp-venv>/bin/python --offline <wheel>`; import `bili_asr.cli`; run `<tmp-venv>/bin/bili-asr --help`; clean all scratch
5. `git diff --check` → clean

## Verdict

**Approve (recommend merge).**

- All 9 acceptance items mapped: 8 covered by reused L1/L2/L3 evidence, every routed gap closed with fresh L4 runs (U1 exact-baseline re-runs, U2 live bounded-path evidence + explicit credential blocker, U3 packaging verified end-to-end, U4 clean observation).
- Checkout alignment verified; worktree left clean at `1a99751` with zero scratch residue.
- Zero open residuals; QC converged verdict is unconditionally discharged (its Approve was conditional on exactly this gate closing U1–U4).
- The plan is **not** marked Done by this report (integration merge precedes Done; PM owns the merge).

/qa-gate evidence recorded in the plan's `## QA Gate Summary`.
