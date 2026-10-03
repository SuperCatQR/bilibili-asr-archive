# Raw findings — seat-tests-dx (test coverage + DX/tooling after the delta)

Scope: delta `ff39fd0..1e756df` (tests/ half + verification tooling), read-only. Base tree: `bilibili-asr-archive/`.
Method: `mstar-audit/references/audit-playbook.md` §4/§7/§ Finding format and `references/test-audit.md` (both read).
Read-only carried out as required: no source edits, no test execution; suite state taken from tree/git/records.
Already-registered issues cited, not re-reported: `I-000145`, `I-000099`, `I-000034`, `I-000111`, `I-000137`, `I-000067`.

---

### [TEST-01] The installed console-script lane cannot open a database, so packaged schema resources are unverified

- **Evidence**: `tests/test_cli_help.py:27-42,67-104,927` — `run_installed` is called four times, only for `--help` and `status` (the `status` call at `:41` and `:97` fails with "no archive database" before any DB open); `src/bili_asr/storage/database.py:55-57` — schemas load via `resources.files(__package__)` and are declared only in `pyproject.toml:81-82` `[tool.setuptools.package-data]`; `tests/installed_cli.py:3-10` — the lane's own docstring claims it is the installation-delivery proof.
- **Impact**: The only isolated-install lane never executes a command that opens `archive.db`, so a packaging regression that drops `schema.sql` / `schema-transcripts.sql` from the wheel (a one-line `package-data` edit) or a missing runtime dep in `[project.dependencies]` leaves every installed-lane test green while the shipped `bili-asr` is unusable. The 44+ in-process CLI tests that do open DBs all run against the sys.path source tree (`tests/conftest.py:21`), not the artifact.
- **Effort**: S — one installed-lane test: seed an archive root, run `run_installed(cli, ["status", "--archive-root", ...])` (or `coverage`) and assert exit 0 + schema-backed output.
- **Risk**: LOW — additive test on the existing `isolated_cli` fixture; provisioning cost already paid module-wide.
- **Confidence**: HIGH (read the lane's full call set and the schema-loading path).
- **Fix sketch**: Add one post-install invocation that materializes/opens a database through the installed script and asserts a schema-derived exit, pinning `package-data` and the declared dependency closure.

### [TEST-02] The R14 store write-back has no end-to-end witness — unit tests only

- **Evidence**: `src/bili_asr/cli/asr.py:284-296` — write-back fires only when `not use_manifest and queue_source is not None and source == "asr" and getattr(queue_source, "asr_run_id", None) is not None`; `src/bili_asr/services/queue_source.py:138-157` — `ensure_asr_run` leaves `asr_run_id = None` on store failure (deliberate best-effort); `src/bili_asr/coordinator.py:780-805` — the chain route re-derives the source and also returns early when `ensure_asr_run` yields `None`; `tests/test_storage_queue_writes.py:718-861` — only direct `record_local_transcript(...)` unit calls; the chain's ASR arm reaches `archived` and asserts ledger/attempts only (`tests/test_derived_queue_chain.py:399-408`), while `_part_transcript_count` is read only for the **caption** part pre-audio (`:327,452`) — never for the ASR part after the run; `grep 'FROM transcripts' tests/test_cli_asr.py tests/test_page_pipeline.py tests/test_cli_artifact_root.py` → no rows.
- **Impact**: The compound guard (`asr_run_id is not None`) is the exact condition R14/I-000067 names: when it is not met the run still archives and reads green, while `v_missing_transcript` keeps listing the part and re-runs re-pay the GPU. A regression in `_ensure_asr_run` wiring or in the `source == "asr"` guard changes behavior no CLI or chain test can see — the delta added the producer (`cli/asr.py`, `coordinator.py:780-805`) with service-level proof only.
- **Effort**: M — drive one successful store-route `main(["asr", ...])` row (fixtures exist: `_seed_archive_database`, `_stub_runner_model`) or extend the chain case at `tests/test_derived_queue_chain.py:399-408` with `_part_transcript_count(tmp_root, QUEUED_BVID, QUEUED_PAGE_INDEX) == 1`, plus one row where `ensure_asr_run` fails to prove the archive still succeeds without a row.
- **Risk**: LOW — adds assertions to an existing fixture class; no production change.
- **Confidence**: HIGH (grep of all CLI-ASR test sites; `I-000067` remains open but tracks the defect, not the missing witness).
- **Fix sketch**: Extend `tests/test_cli_asr.py`'s store-route audio branch with the `transcripts` join count on the successful row and the best-effort no-row case.

### [TEST-03] `opt_in_gate` does not gate — the central skip claimed by plan 008 is per-file again

- **Evidence**: `tests/conftest.py:209-225` — the fixture resolves the marker→env name and **returns a tuple without skipping**; `tests/conftest.py:198-204` comment claims "the default run's skip text is therefore byte-identical … the central gate"; the docstring at `:210-216` claims it "skips with the reason the test passes"; every consumer still carries its own gate: `tests/test_live_metadata_smoke.py:337-339`, `tests/test_live_subtitle_smoke.py:445-447`, `tests/test_live_subtitle_cli_smoke.py:854-856`, `tests/test_integrity.py:294-296`, `tests/test_persistence_scale.py:201-203`.
- **Impact**: The gate is advisory, not enforcing: a new opt-in test that takes the fixture and forgets the manual `pytest.skip` runs unconditionally in the default suite — against the live network for `live_smoke`, or a ~100 s 10k-row fixture for `scale` — while looking covered by the "central gate". Plan 008's declared outcome ("single shared conftest fixture that … skips centrally") is not what the tree does, and its plan-QC never turned red because no test asserts the fixture skips.
- **Effort**: XS — make the fixture perform the skip (reason passed by the caller) or add a self-test that the fixture skips unmarked/opted-out cases.
- **Risk**: LOW — the five consumers keep their explicit checks during migration; the fixture change is additive.
- **Confidence**: HIGH (read the fixture body and all five consumers).
- **Fix sketch**: Have `opt_in_gate` call `pytest.skip(reason)` when `os.environ.get(env_var) != "1"`, deleting the repeated blocks; pin it with a rehearsal test (the files already have `_skip_reason_is_stable` patterns to extend).

### [TEST-04] The `tmp_root` hardening witness does not reproduce the collision it claims to guard

- **Evidence**: `tests/test_conftest_tmp_root.py:30-47` — the stale dir is named `manifest-test-stale-leftover`, which can never equal the old pattern `manifest-test-{pid}-{counter}`, so the `pytest.raises(FileExistsError)` at `:36-37` proves `os.makedirs` semantics, not PID-reuse immunity; the only assertion that actually fails on the pre-fix code is the UUID-format regex at `:44-46`.
- **Impact**: The fixture is genuinely hardened (`tests/conftest.py:141-148`, UUID suffix), but the test that will guard it does not exercise a colliding leftover — a future edit that keeps the UUID in the name but re-derives the path differently, or one that reintroduces a deterministic component, can still slip past the witness while the recorded flake class (a killed run's dir colliding on PID reuse) is claimed covered. `I-000099`'s defect half is stale at `1e756df`; the witness half is weaker than the entry implies.
- **Effort**: XS — create a stale dir whose name equals the current fixture's deterministic prefix before calling the fixture.
- **Risk**: LOW — test-only; the current implementation is already immune.
- **Confidence**: HIGH (read the test body and the fixture).
- **Fix sketch**: Compute `manifest-test-{os.getpid()}-{next-counter-preview}` impossible from outside; instead pin the contract directly — call the fixture twice and assert both names differ and neither raises when a same-prefix stale dir exists.

### [TEST-05] The baseline suite silently drops ~44 in-process test definitions because they share a file with 5 installer tests

- **Evidence**: `scripts/verify_baseline.py:271-279` — the staged tree excludes `test_cli_help.py` wholesale; `tests/test_cli_help.py` holds 49 test definitions, of which only 5 take the `isolated_cli` fixture (`:30,39,67,90,927`); the remainder are pure in-process `main()`/`capsys` contract tests (the `coverage --reference` family, `:253-906`); `grep -rc reference tests/` shows ~40 of the `--reference` contract assertions live there and in `tests/test_quality.py` only.
- **Impact**: The repository's declared "complete product pytest suite" (`README.md:443`) omits the largest CLI-contract file by file-level exclusion granularity — a whole subsystem's CLI surface (coverage/quality reference options, redaction, CSV column freeze) never runs in the one automated-adjacent lane. A regression there is caught only by an ad-hoc manual run, which is exactly the drift class `I-000145` records.
- **Effort**: S — split the installer tests into `tests/test_installed_cli.py` (the name already referenced everywhere: `tests/installed_cli.py:65`, `scripts/verify_baseline.py:275`, `README.md:443`) or move the in-process family to a file that is not excluded.
- **Risk**: LOW — mechanical move; staging ignore set already names the right target (`test_installed_cli.py`), so the fix also repairs the dangling reference.
- **Confidence**: HIGH (counted definitions and fixture users; exclusion read).
- **Fix sketch**: Create `tests/test_installed_cli.py` with the five `isolated_cli` tests (matching the helper's own documented command at `tests/installed_cli.py:65`), leave the in-process tests in `test_cli_help.py`, and keep the staging exclusion as-is.
- **Narrowed during write-up**: the staged tree copies **no `src/`** (`scripts/verify_baseline.py:258-289` — README, docs, `scripts/`, `tests/` only), so the literal `.replace()` of the conftest `sys.path` line at `:280-287` fails **closed**: if the exact bytes drift, the staged suite's `import bili_asr` finds no source tree and the baseline goes red loudly. The earlier silent-downgrade reading is withdrawn; only the missing post-condition assertion (and the assert-nothing `test_staged_test_tree_copies_checkout_inputs`, `tests/test_verify_baseline.py:214-225`) remains, as a lead below, not a finding.

### [DX-01] The one verification command cannot run without a hand-provisioned offline wheel fixture; the checked-in evidence is a failed-prerequisite run

- **Evidence**: `scripts/verify_baseline.py:78-79` — `offline_dependency_closure_unavailable: install failed` raises `PrerequisiteError` when the offline fixture is absent; `README.md:437-438` — the operator must first run `prepare_offline_baseline_fixture.py --wheel-source /path/to/reviewed-wheels`; `verification-results/baseline.json` (gitignored, `.gitignore:59`; mtime 2026-09-30) records `status: prerequisite_failed` with **0** recorded commands, i.e. the last persisted evidence establishes nothing.
- **Impact**: There is no command an operator can run on a fresh checkout that answers "is this tree green" — the closest thing exits before testing anything unless a wheel corpus has been hand-built. Verification therefore stays per-worktree and ad hoc, which is the condition under which `I-000145`'s 18 pre-existing failures and `I-000034`'s deterministic red survived to the audit. (No-CI itself is by-design and not reported; the cost reported here is the missing local substitute.)
- **Effort**: M — either vendor a small self-contained offline fixture path (e.g. build wheels from the lock's dev closure in-step) or add a documented `pytest -q` fast lane that the baseline wraps when the fixture is absent.
- **Risk**: MED — the offline/no-network contract is deliberate; any change must preserve `safe_env()` and the socket deny guard (`scripts/verify_baseline.py:290-306`).
- **Confidence**: HIGH (baseline artifact + command source read).
- **Fix sketch**: Add a documented fast lane (`python -m pytest -q` from the package root with the conftest preamble, per-worktree) as the green/red signal, keep the offline wheel baseline as the release-grade lane, and record both in `verification-results/README.md`.

### [DX-02] The marker capability landed by plan 008 is undocumented and one registered marker is dead

- **Evidence**: `pyproject.toml:84-92` registers `live_smoke` / `scale` / `slow`; `README.md:1334,1352,1369` documents only per-file `BILI_LIVE_SMOKE=1 … pytest tests/test_<file>` invocations; `grep -rn '\-m live_smoke|\-m scale' README.md docs/*.md` → no hits; `grep -rn 'mark.slow' tests/` → 0 users.
- **Impact**: The selection capability that justified the delta's marker work (`-m live_smoke` / `-m scale`) is undiscoverable from the docs, and `slow` is registered but unused — the next operator copies the per-file idiom and the drift class plan 008 targeted (a fifth opt-in class copying a fourth idiom) resumes. Cost is operator time per live run, not a defect.
- **Effort**: XS — one README paragraph documenting `-m` lanes and dropping or using `slow`.
- **Risk**: LOW — docs + one pyproject line.
- **Confidence**: HIGH (grep of README/docs and marker usage).
- **Fix sketch**: Document the three marker lanes next to the existing live commands; remove the unused `slow` registration or annotate it as reserved.

### [DX-03] No lint / typecheck / formatter / editorconfig anywhere; the delta already carries inert `# noqa` directives

- **Evidence**: no `[tool.ruff]` / `[tool.mypy]` / `[tool.black]` in `pyproject.toml` (grep empty), no pre-commit config, no `.editorconfig` in the package root; `src/bili_asr/asr.py:1365-1367` — three `# noqa: F401` re-export shims whose directive would only be meaningful with a linter that is not configured.
- **Impact**: 26k LOC across 62 modules accept no static gate; the delta's own `noqa` lines show contributors assuming one exists. The strongest concrete cost in this delta: the three canonical-stem implementations were consolidated only after a STOP (`tests/test_stem_contract.py:1-10` records the divergence class), and the duplication clusters plan 010 closed were all statically detectable — each cost a dedicated plan round that a lint/type layer would have surfaced earlier. Feedback loop stays "run the suite and read the failure".
- **Effort**: M — one ruff config + one CI-less `uv run ruff check` documented beside the test lane; keep the rule set minimal to avoid a reformat churn.
- **Risk**: MED — a broad formatter pass would churn ~26k LOC and collide with in-flight plans; start with lint-only on new/changed files.
- **Confidence**: HIGH (configs absent; noqa directives read).
- **Fix sketch**: Add `[tool.ruff]` with `select = ["F", "E9"]` (F401 alone would catch the re-export shims), document the command next to the test lane, and never run a repo-wide format in the same plan.

---

## Leads (not findings)

- **Lead (withdrawn finding)**: `staged_test_tree`'s literal `.replace()` of the conftest `sys.path` line (`scripts/verify_baseline.py:280-287`) has no post-condition assertion (`tests/test_verify_baseline.py:214-225` asserts only the file set), but because the staged tree copies no `src/`, a drift in those bytes fails closed (no `bili_asr` importable) rather than silently grading the checkout — XS hardening (assert the replace changed the text, or pin the staged conftest's import origin), not a defect.
- **Lead**: `tests/test_live_*.py` keep file-local `LIVE_SMOKE_ENV` constants while `conftest.OPT_IN_ENV_VARS` is the new SSOT; two consumers (`test_live_metadata_smoke.py:337`, `test_live_subtitle_smoke.py:445`) read the fixture's `env_var` rather than their own constant, so drift is currently benign — but only four of six consumers assert equality. Low value until TEST-03 is fixed; fold into that plan.
- **Lead**: `tests/test_search.py:258-284`'s `assert selects <= 4` is a bounded query-count witness for the O-R3 batching fix and does fail on the per-hit pre-fix shape (1 probe + 1 MATCH + 2 snippets + 2 titles = 6) — retained, no action. Noted because commit `9f7a11b` dropped a different count equality; this one is not the brittle kind.
- **Lead**: `I-000034` (whole-stderr byte equality on timestamped ROCm output) is a live instance of the zone/timestamp-independence class; the delta did not touch `test_check_asr_env.py`. Repair belongs to the registered issue, not a new plan.
- **Lead**: `I-000111` (`check-asr-env` helper resolution in installed layouts) — reproduced only as a reference; the installed lane's scope gap (TEST-01) would have surfaced it if the lane opened real commands.

## Verification records consulted (read-only)

- `verification-results/baseline.json` — `status: prerequisite_failed`, 0 commands, mtime 2026-09-30.
- No in-repo CI config (`.github/` absent), no recorded pytest report for the delta's head `1e756df`.
- `I-000145`'s "repaired" note: the drift commit `ee4a8e8` re-seeds fixtures (`_seed_archive_database` caption row, `ManifestStore.save` snapshot materialization) and keeps two genuinely-red residuals (`test_two_process_same_attempt_key_numbers_do_not_conflict`, `test_malformed_attempt_history_fails_closed_for_authoritative_append`) as recorded code regressions — i.e. the note is accurate but the issue remains open; no new finding added.

Truncated coverage: `src/bili_asr/coordinator.py` and `storage/database.py` delta bodies were examined only through greps of call/assertion sites, not full reads; `sidecar_projection.py` + `search_index.py` delta test surfaces were sampled, not swept; the three `test_live_*.py` bodies (≈4.3k lines) were read only in windows around gates/markers; `test_search.py` beyond the batching case and `test_storage_queue_writes.py` beyond the record_* family were not read. Files with content read: ~26 (2 full reads: the playbook and `test-audit.md`; the rest narrow grep/sed windows).
