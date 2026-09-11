# Task 1 Review — Declare the HTTP backend and prove the packaging contract

**Plan:** `20260911-live-metadata-path-fix`
**Review mode:** Mode A · L2 · diff-first (per-task SDD review)
**Reviewer seat:** code-reviewer (fresh; read-only)
**Base → Head:** `25a11fe` → `cc56e46` (product-only range; harness-only plan commit `c29a87a` excluded)
**Diff basis:** `.mstar/sdd/20260911-live-metadata-path-fix/review/task-1-diff.md` (read once; git not re-run)
**Worktree under review:** `/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix` @ `fix/20260911-live-metadata-path-fix`
**Implementer report:** `.mstar/sdd/20260911-live-metadata-path-fix/implementer-task-1-report.md`
**Verdict:** ✅ **Approved** — 0 Critical, 0 Important, 4 Minor

---

## Spec Compliance

### Brief items (task-1-brief.md)

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Add the HTTP backend to runtime `dependencies` (locked: `curl_cffi`) without touching unrelated dependencies; regenerate `uv.lock`; `uv lock --check` no-op | ✅ | `pyproject.toml:14` `"curl_cffi>=0.16"` — the diff's `[project].dependencies` hunk is a single added line; `bilibili-api-python==17.4.2` and `requests>=2.32` untouched. Lock delta is `+35/-0`. `uv lock --check` **independently reproduced** by this seat in a `/tmp` copy of `pyproject.toml` + `uv.lock`: exit 0, `Resolved 99 packages in 3ms`, and the copy's sha256 `4cf305d699a386e10302d84cc3aa45de24a28b96c6e094bf1f44f690e5d3da32` equals the digest the implementer reported before/after its re-lock |
| 2 | Add an offline test asserting the dependency is declared (parity between `pyproject.toml` and the installed distribution, mirroring the existing package-data parity pattern); no network | ✅ | `tests/test_bilibili_api_gateway.py:683-736` `test_http_backend_declared_and_absent_from_pinned_package_requirements`. Only file reads (`tomllib` + `pathlib` via `__file__`), `importlib.metadata`, and `packaging` parsing — no sockets, no subprocess, no monkeypatching, no clock/env/cwd dependence. Mirrors the existing pattern at `tests/test_storage_schema.py:186-196` (declaration side + runtime/installed-artifact side) |
| 3 | Record the pinned-package rationale in the test docstring: why the backend must be declared even though the library does not require it transitively | ✅ | Docstring lines 691-703 name the pin (`17.4.2`), the `ArgsException("尚未安装第三方请求库或未注册自定义第三方请求库")` failure mode, and that the spec-locked pin means no version bump can supply the transport. Claim verified against live metadata: `importlib.metadata.distribution("bilibili-api-python")` → `Provides-Extra: None`, 12 `Requires-Dist` entries, **none** an HTTP client |

### Global Constraints (plan § Global Constraints)

| Constraint | Status | Evidence |
|---|---|---|
| Retain the pin `bilibili-api-python==17.4.2`; no bump or replacement | ✅ | `pyproject.toml:13` and `uv.lock` `requires-dist` row unchanged; no `bilibili-api-python` package block in the lock diff |
| Only `sources/bilibili_api_gateway.py` imports `bilibili_api`; AST test keeps enforcing | ✅ | AST boundary test scans `src/bili_asr` only (`tests/test_bilibili_api_gateway.py:824`); the new test uses `importlib.metadata.distribution("bilibili-api-python")` — a string lookup, not an import. `test_only_the_gateway_module_imports_bilibili_api` passes in the reproduced focused run |
| DTOs, protocol surface, error taxonomy, ingestor, repository, schema, CLI surface unchanged | ✅ | Diff touches no `src/` file; mtime probe of the whole package tree returns only the three briefed files |
| Credentials / proxy: no new credential surface | ✅ | No credential, proxy, or log surface touched by this task |
| All tests stay offline; live smoke stays opt-in and bounded | ✅ | Focused run reproduced: `105 passed, 1 skipped` — the skip is `test_live_smoke_single_public_page_for_archive_owner` |
| Scope guard: only `pyproject.toml`, `uv.lock`, `tests/test_bilibili_api_gateway.py` may change | ✅ | Independent probe `find <pkg> -type f -newermt "06:50:30"` (excluding untracked `__pycache__` / `.pytest_cache` / `.test-tmp`) returns exactly: `pyproject.toml` (06:53), `uv.lock` (06:53), `tests/test_bilibili_api_gateway.py` (06:55) |
| `git diff --check` clean (plan Done Criteria) | ✅ (equivalent) | No trailing whitespace/tabs in any of the three files; longest added line is 100 chars — inside the file's pre-existing 103 envelope |

### Implementer-claim verification

| Claim (report) | Independently verified? |
|---|---|
| Red first: assert fails before the declaration, `declared_names == {'bilibili-api-python','requests'}`, at `:708` | ✅ Replayed the test's exact assertion blocks offline against a `/tmp` copy of `pyproject.toml` with the `curl_cffi` line stripped → `FAIL: declaration missing -> ['bilibili-api-python', 'requests']`. The reported RED traceback line **708** is exactly the assert's line in the current file |
| Focused file `105 passed, 1 skipped` | ✅ Reproduced verbatim by this seat (sanctioned command, worktree cwd) |
| Full suite `866 passed, 2 skipped` (plan baseline 865 + 2) | ⚠️ Not re-run (per review instruction); delta of exactly +1 test is arithmetically consistent with the diff (+1 test function) |
| `uv lock --check` no-op; second `uv lock` byte-identical | ✅ Both independently reproduced (exit 0 + matching sha256 `4cf305d6…`) |
| Lock diff purely additive (`+35/-0`); no unrelated re-pin | ✅ Diff arithmetic: 2 one-line project-block additions + a 33-line `curl-cffi` block. Lock re-parsed: 99 packages, alphabetically sorted, no duplicates, `certifi` and `cffi` already present before this change |
| Lock dependency graph consistent with the transport | ✅ Installed `curl_cffi 0.16.3` unconditional `Requires-Dist` is exactly `cffi>=2.0.0`, `certifi>=2024.2.2`; every other entry is extras-gated (`extra`/`cli`/`dev`/`build`/`test`). The lock records exactly `{certifi, cffi}` — extras correctly excluded, nothing missing |
| Guard is non-vacuous (trips on a control distribution declaring a client) | ✅ Corroborated: `curl_cffi` itself declares `httpx==0.23.1` under its `dev`/`test` extras, i.e. a distribution that would trip the second assertion exists in the real index |
| All wheels hashed | ✅ 21 wheels + sdist, every `hash` exactly 64 lowercase hex chars |

---

## Strengths

- **The test is genuinely two-sided and non-vacuous.** The declaration half discriminates (proven by independent replay, not by trusting the RED paste). The upstream half is a real tripwire over live distribution metadata rather than a copy of a hard-coded expectation, and its premise was verified against the installed `17.4.2` (`Provides-Extra: None`, 12 requirements, no HTTP client).
- **Reuse over reimplementation.** `packaging.requirements.Requirement` + `packaging.utils.canonicalize_name` (both already a declared `dev` dependency) remove the `curl_cffi`/`curl-cffi` ambiguity and correctly handle extras/markers, instead of a hand-rolled name parser.
- **Minimal, correct lock delta.** Purely additive, correctly sorted, dependency-complete, no other package block moved — and reproducible (`uv lock --check` exit 0 with an unchanged digest).
- **Surgical scope.** Exactly the three briefed files; independently confirmed by mtime probe rather than by taking `git status` on trust.
- **Honest evidence.** The report proactively discloses the one claim it did *not* execute (`uv sync`), the loud-fail choice, the deliberate non-assertion of importability, and the decision to verify the lockfile by command evidence instead of a second test. The RED traceback line matches the shipped file, so the evidence is coherent with the artifact rather than reconstructed after the fact.
- **No hidden coupling beyond a disclosed one.** The test resolves `pyproject.toml` from `__file__`, so it is immune to cwd; it carries no proxy/credential/diagnosis-time state; and under pytest `conftest.py:12` makes `bili_asr` resolve to the **worktree** `src/` (the venv's editable install points at the control checkout), so the implementer's runs did exercise the code under review — a useful property for Tasks 2–4 as well.

---

## Issues

### Critical

None.

### Important

None.

### Minor

1. **`tests/test_bilibili_api_gateway.py:713-726` — the tripwire is version-agnostic while claiming to speak about the pin.** The second half reads whichever `bilibili-api-python` the running interpreter happens to have. If a developer's venv drifted to a release whose dependency set changed, the test's verdict would silently describe a different distribution than the "pinned package" the docstring, the constant name, and the plan name. `PINNED_PACKAGE_VERSION = "17.4.2"` is already in scope one screen above and unused here; `assert pinned_distribution.version == PINNED_PACKAGE_VERSION` would make the claim exact and matches the repo's existing precedent for pin assertions (`tests/test_live_metadata_smoke.py:254`). Optional polish — not a correctness defect, and the assert message is intelligible either way.
2. **`tests/test_bilibili_api_gateway.py:730-733` — the intersection is extras-blind.** `pinned_distribution.requires` includes extras-gated entries, so a future `httpx; extra == "dev"` on the pinned package would trip the guard with the message "the pinned package now declares an HTTP client", although the *runtime* closure would be unaffected (today `17.4.2` publishes no extras, so this is future-facing only). Either restrict the intersection to marker-free requirements or word the message as "declares an HTTP client in `Requires-Dist`" — the guard's actual subject.
3. **Report arithmetic nit (no product impact).** The report's Files-changed table lists `tests/test_bilibili_api_gateway.py` as `+76/-1`; the diff is `+75/-1` (4 hunks: +3/-1, +4/-0, +13/-0, +55/-0). The headline "111 insertions, 1 deletion" is correct (1 + 75 + 35), and the lock's `+35/-0` is correct.
4. **`tests/test_bilibili_api_gateway.py:5-6` — the module docstring's absolute phrasing sits before its own exception.** "neither the real package nor network access is ever required" remains on line 5 while the packaging-contract exception is introduced on lines 14-17. The exception is explicit and adjacent, so a reader is not misled — noted only for precision; no change required.

---

## Answering the assigned judgement notes

- **Non-vacuous and offline?** Yes, both halves. Declaration half: fails with the declaration removed (independently replayed). Upstream half: reads real distribution metadata, currently discriminating, and trips on control distributions that exist in the index (`curl_cffi`'s `httpx` extras). Offline: file/`importlib.metadata` reads only — no network, no subprocess, no live call.
- **`uv.lock` additive/scoped?** Yes. `+35/-0`; two project-block rows plus one correctly-sorted `curl-cffi 0.16.3` block (sdist + 21 well-formed sha256 wheels); dependency set matches the installed distribution's unconditional requirements exactly; no other package re-pinned; `uv lock --check` reproduced as a no-op with an unchanged digest.
- **Hidden determinism/environment coupling?** One coupling, disclosed rather than hidden: the offline suite gains a second fail-loud path that requires `bilibili-api-python` installed in the running interpreter (`pytest.fail`, not skip). It is stated in the module docstring and mirrors existing precedent (`tests/test_live_metadata_smoke.py:93-101`, `tests/test_bilibili_api_gateway.py:1004`), and it is satisfied by construction whenever the suite runs in the project venv. No clock, env-var, cwd, ordering, or diagnosis-time proxy/credential dependence. Accepted, not a defect.

---

## ⚠️ Cannot verify from diff (for PM to resolve)

1. **Wheel/sdist hash integrity against PyPI.** No egress from the review seat (`web_fetch` to `pypi.org/pypi/curl-cffi/0.16.3/json` failed), and the local uv cache holds no `curl_cffi-0.16.3` wheel to hash. All 21 wheel hashes and the sdist hash are structurally valid (64-hex sha256) and `uv lock --check` passes, but their correspondence to the real artifacts rests on the implementer's `uv lock` run. Low risk; a QA-side sync over the lock would close it.
2. **"A fresh install can import an HTTP backend" (plan § Acceptance / Done Criteria).** Deliberately not executed by the implementer (lock-only, no `uv sync`), and the `curl_cffi 0.16.3` present in `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv` is the pre-existing diagnosis install, not delivery evidence. Recommendation: have Task 4 / QA confirm a clean `uv sync` installs `curl-cffi 0.16.3` from the new lock, so the criterion is closed by an executed install rather than by declaration + lock alone.
3. **Full-suite figure** (`866 passed, 2 skipped`) was not re-run by this seat, per the review instruction to trust implementer evidence; the +1 delta is arithmetically consistent with the diff.

---

## Assessment

**Task quality: Approved.**

Spec compliance holds on every briefed item and every Global Constraint that this task can touch, including the scope guard (independently confirmed). No Critical or Important findings. The four Minor findings are two optional-precision polish items in the new test, one report arithmetic nit, and one docstring phrasing note — none blocks Task 2 dispatch. The single environment coupling is disclosed, precedented, and benign.

**Cleanup:** zero-residual; PM owns disposition of the Minor items (they need not gate Tasks 2–4). The two ⚠️ items are PM/QA-owned (fresh-sync confirmation and hash-integrity closure), not implementer defects.

---

## Reviewer compliance

- Read-only seat honoured. The only file written is this report.
- No git mutation, no branch change, no worktree mutation, no subagent dispatch, no full-suite re-run.
- One sanctioned focused command executed: the specified worktree `pytest tests/test_bilibili_api_gateway.py -v` → `105 passed, 1 skipped`. It left only untracked, gitignored pytest artifacts (`.pytest_cache` — pre-existing from the implementer's run, `tests/__pycache__`, `bilibili-asr-archive/.test-tmp/`).
- Read-only verification outside the worktree: `uv lock --check` inside a `/tmp` copy of `pyproject.toml` + `uv.lock` (temp dir removed afterwards); `importlib.metadata` introspection with the project venv; an offline replay of the new test's assertion logic against a `/tmp` stripped copy of `pyproject.toml`.
