# Task 2 review — Resolve and apply proxy configuration in the gateway

- **Plan:** `20260911-live-metadata-path-fix` · **Task:** 2 · **Mode:** A / L2 / diff-first
- **Diff basis:** `cc56e46..0a2e2f5` (feature worktree `fix/20260911-live-metadata-path-fix`)
- **Brief:** `.mstar/sdd/20260911-live-metadata-path-fix/task-2-brief.md`
- **Reviewer:** code-reviewer, read-only seat (no git commands, no product writes, no full suite)

## Verification performed

| # | Check | Result |
|---|---|---|
| 1 | Read brief, plan (§Problem D2, Global Constraints, Locked decisions), implementer report, `review/task-2-diff.md` | done |
| 2 | Read on-disk worktree state: `src/bili_asr/config.py`, `src/bili_asr/sources/bilibili_api_gateway.py` (imports + `__init__`), `tests/fixtures/fake_bilibili_gateway.py`, new test block, AST/seam-surface tests | done |
| 3 | Read the **installed pin** (`bilibili-asr-archive/.venv/.../bilibili_api`): package-level export of `request_settings` (`__init__.py:17,229`), `RequestSettings.set_proxy`/`get_proxy`/`set` (`utils/network.py:244-310`), lazy propagation to live sessions (`:284-290`, `:1070-1090`), `CurlCFFIClient` session build and `set_proxy` (`clients/CurlCFFIClient.py:52-57,71-72`), `Credential(proxy=...)` per-request swap (`network.py:1161-1194`, `:2331-2349`) | done |
| 4 | Ran the brief's focused command once (explicitly permitted by the Assignment) | `158 passed, 1 skipped in 2.38s` — matches the implementer exactly |
| 5 | Read-only, network-free probe of the **real pin** wired to the worktree adapter (no files written, no request sent) | no env proxy → `resolved_proxy=None`, `request_settings.get_proxy()==''`, session `proxies={'all': ''}`; `BILI_HTTP_PROXY` set → both the setting and the session become `http://127.0.0.1:7890`, including a session that already existed in-process |
| 6 | Diff line accounting per file from the diff artifact (no git) | `config.py +50/−3`, `gateway +22/−3`, `fixture +25/−5`, `test +227/−4` → total `+324/−15` |

## Spec Compliance

**✅ Spec compliant** (no Critical, no Important). Item by item against the Assignment's verbatim constraints:

1. **Locked precedence** — `resolve_proxy` (`src/bili_asr/config.py:154-175`) builds
   `(argument_value, *environ.get(name) for name in PROXY_ENV_VARS)` and `PROXY_ENV_VARS`
   (`config.py:46-52`) is exactly `BILI_HTTP_PROXY, HTTPS_PROXY, https_proxy, ALL_PROXY, all_proxy`
   — the locked ladder, no insertions, no omissions. `HTTP_PROXY`/`http_proxy` are correctly *not*
   consulted, and a test documents that decision (`tests/test_bilibili_api_gateway.py:805-811`). ✅
2. **Blank/whitespace = unset** — the `None`-skip + `strip()` + truthiness loop
   (`config.py:169-174`) applies at *every* level including the constructor argument, so an empty
   `BILI_HTTP_PROXY` cannot shadow a real `HTTPS_PROXY`. Covered for `""`, `"   "`, `"\t\n"` at the
   helper level (`:786-792`), at the gateway level (`:858-868`), and for argument-vs-chain
   (`:775-782`). ✅
3. **No-proxy default leaves the library untouched** — `bilibili_api_gateway.py:270-272` calls
   `set_proxy` only under `if self.resolved_proxy is not None`; nothing else in the adapter touches
   request settings. Test `:871-885` asserts `applied_proxies == []` before *and* after a real page
   call; my probe #5 confirms the real consequence (`proxies={'all': ''}` preserved). ✅
4. **Import boundary** — `bilibili_api_gateway.py:20` is still the only `bilibili_api` import site;
   `config.py` imports only `argparse`, `os`, `collections.abc`, `dataclasses` — no cycle
   (`bili_asr/__init__.py` trivial, `sources/__init__.py` imports `models` only). Enforced by
   `test_only_the_gateway_module_imports_bilibili_api` (`:1054`) and the exact-equality import map at
   `:86` / `test_gateway_imports_stay_on_metadata_surface` (`:1066`). ✅
5. **Unchanged surfaces** — the diff artifact contains exactly four files: the two product sources
   named in the brief, the brief's test file, and the disclosed fixture. No DTO, protocol, taxonomy,
   ingestor, repository, `schema.sql`, `pyproject.toml`/`uv.lock` (Task 1 territory), or CLI change;
   `src/bili_asr/cli.py:571` is byte-identical (`sessdata=` only) and the presence-only display path
   (`redact_sessdata`) is untouched. ✅
6. **No proxy/credential in output, logs, rows** — the adapter has no logging, no `print`, no
   `__repr__`, and no message construction that interpolates configuration (grep: zero hits for
   `logging|logger|print(|request_log`), so the "logs" clause holds by construction; the observable
   surfaces are asserted at `:888-911` (DTO `repr`/`str`, adapter `repr`, mapped-error `str`/`repr`)
   and `:914-948` (full persisted-row blob). The `PROXY_BOUNDARY_VALUE` sentinel in the *fixture* is
   the same synthetic leak-detector convention the suite already uses for `SESSDATA_BOUNDARY_VALUE`,
   not a real proxy value — not a violation of the "fixtures" clause. ✅
7. **Offline only / smoke opt-in** — every new test runs over `bilibili_api_seam`; the live smoke is
   untouched and still skip-gated. ✅
8. **Brief's three checkboxes** — pure helper ✔, credential boundary ✔, test set (precedence, blank,
   no-proxy default, apply-once, no-leak over output *and* rows) ✔. ✅

**PM adjudication of the disclosed fixture deviation — independently confirmed:** (a) additive and
minimal: one recorder list (`fake_bilibili_gateway.py:142`), one mirror module (`:208-221`), its
registration in the package module map (`:292`, `:299`), plus the module docstring — the pre-existing
fakes are unchanged; (b) it weakens nothing: `script.calls` is untouched, so every exact-list
assertion in `test_metadata_ingest.py:703/852/917`, `test_metadata_cli.py:343`,
`test_metadata_e2e.py:304/574` keeps its full strength, and the seam-surface/import-map assertions in
the gateway test file were **updated as exact equalities, not relaxed** (`:86`, `:1128-1136`);
(c) no product-source file outside the brief's scope changed. The deviation was genuinely
unavoidable: the adapter's top-level `from bilibili_api import ..., request_settings` cannot import
against a fake package that lacks the name, and four modules share this seam.

**⚠️ Cannot verify from diff (for PM):**

- **Full-suite and mutation evidence are trusted, not re-run.** `885 passed, 2 skipped` and the six
  mutation checks (which would require writing product source) were not reproduced — the Assignment
  forbids both. Independently reproduced by me: the brief's focused command (**158 passed, 1
  skipped**) and the real-package wiring behaviour (probe #5).
- **`git diff --check` clean** — no git command was run (Assignment); not independently verified.
- **Durability of the chosen library surface is not covered by any offline test.** The seam proves the
  adapter *calls* `request_settings.set_proxy` with the right value exactly once; it cannot prove that
  this remains the surface `CurlCFFIClient` reads at session build. Only the implementer's manual
  wire-level probe (which I reproduced) covers that link. Risk is bounded: the pin is 17.4.2 and the
  installed version is asserted equal to `PINNED_PACKAGE_VERSION` by
  `test_package_version_reports_installed_distribution` (`:670`) and by the live smoke (`:1230`), so a
  library swap fails loudly elsewhere. Worth one line in the Task 4 docs note or a residual if PM
  wants it owned.
- **No production caller passes `proxy=`.** The only construction site is `src/bili_asr/cli.py:571`
  (`sessdata=` only); the shipped operator knob is therefore the environment chain, not the
  constructor argument. This matches the plan's locked interface ("CLI surface unchanged", Task 2
  Files list) — flagged only so nobody assumes a CLI `--proxy` exists.
- **Task 4 surfaces** (`.env.example`, docs, live smoke happy-path assertions) are out of this range by
  design; the live path itself remains unproven offline.

## Strengths

1. **The blank rule is implemented at the resolution level, not per-caller.** Because the skip happens
   inside the single loop (`config.py:169-174`), the argument and all five environment levels share one
   semantics — the class of bug where a blank high-precedence value silently disables a configured
   proxy is structurally impossible, not just tested away.
2. **The no-proxy default is a real behavioural guarantee, not a comment.** The guard at
   `bilibili_api_gateway.py:271` and the `applied_proxies == []` assertions before/after a page call
   (`:871-885`) protect exactly the behaviour whose loss re-introduces D2; my probe confirms the real
   session still shows `proxies={'all': ''}` when nothing resolves.
3. **The transport surface choice is documented with verified evidence, and the tempting shortcut was
   refused.** The docstring names `request_settings.set_proxy` as the setting `CurlCFFIClient` reads
   and explains why `Credential(proxy=...)` is wrong (it swaps the same global around every request —
   `network.py:2331-2349`), and the implementer explicitly rejected a dynamic `importlib` call because
   it would evade the AST import-surface test. That is the right call under review pressure.
4. **Apply-once is effective against an already-built session.** `RequestSettings.set` fills the
   per-loop lazy queue (`network.py:284-290`) that `get_client()` drains with
   `session.set_<name>(value)` (`:1070-1090`); probe #5 showed a session created *before* the gateway
   still receiving the proxy. The construction-time application is therefore correct even in a
   long-lived process.
5. **The no-leak tests are not vacuous where vacuity is easy.** `:934-935` first proves the run
   persisted something (`outcome == "limited"`, `list_pending_parts()` truthy) before scanning the
   whole-row blob via `persisted_row_text`, so `assert PROXY_BOUNDARY_VALUE not in persisted` is a
   meaningful scan of real rows, and the ingest path is exercised through the real
   ingestor+repository composition rather than a stub.
6. **The seam extension is honest by construction.** It is a recorder (spy) for the adapter's call,
   not a substitute for the logic under test: `resolve_proxy` is independently unit-tested against
   explicit mappings, and the "nothing resolved" branch is asserted as *no call at all*, so the seam
   cannot mask the very behaviour it instruments.
7. **Surgical scope discipline.** Four files, every hunk traceable to the locked precedence, apply-once,
   the no-proxy default, or a required test/seam assertion; zero adjacency refactoring, zero
   documentation/CLI/edge-surface creep, and the disclosed scope deviation was surfaced rather than
   buried.

## Issues

#### Critical

None.

#### Important

None.

#### Minor

1. **Seam fidelity: the fake accepts a call shape the real API rejects.**
   `tests/fixtures/fake_bilibili_gateway.py:210` declares `def set_proxy(proxy: str = "") -> None:`,
   but the mirrored real target is `RequestSettings.set_proxy(self, proxy: str)`
   (`utils/network.py:301`) — **no default**. The default therefore makes the seam more permissive
   than reality: a future adapter regression that called `request_settings.set_proxy()` with no
   argument would stay green offline and fail live with `TypeError`. The adapter's current call shape
   is correct and unaffected, so this is latent. Cheap fix: drop the default parameter. (Related and
   acceptable: the fake models `request_settings` as a module of functions while the real object is a
   `RequestSettings` instance — behaviourally equivalent for the adapter's single call shape, so no
   further action needed.)
2. **Disclosed figures for the fixture do not match the diff.** The implementer report
   (§Scope disclosure) and the Assignment both state `+30/−8` for
   `tests/fixtures/fake_bilibili_gateway.py`; the diff artifact contains **`+25/−5`** for that file
   (hunks `@@ -10,11 +10,13 @@`, `@@ -137,6 +139,7 @@`, `@@ -202,6 +205,21 @@`, `@@ -271,12 +289,14 @@`).
   The report's overall `+324/−15` is correct, and the substance of the disclosure (additive, minimal,
   unavoidable) is accurate — only the per-file number is stale. Documentation accuracy only; no code
   impact.
3. **Process-global setting vs per-instance `resolved_proxy` (self-disclosed).**
   `request_settings` is process-global, so a second `BilibiliApiGateway` in the same process silently
   overrides the first gateway's proxy while `self.resolved_proxy` on the first instance still reports
   the old value. No test covers two live gateways, and the only production construction site is
   `src/bili_asr/cli.py:571` (one gateway per process), so the exposure is latent and the design is
   the one the plan locked ("the adapter applies it to the pinned package's request settings").
   Recommend recording the limitation in the Task 4 operator docs — or filing it as a residual — so it
   is owned rather than re-discovered.

## Assessment

**Task quality:** Approved

The locked proxy contract is implemented exactly as specified, the no-proxy default is a genuine
behavioural guarantee verified against the real pin, the import boundary and every untouched surface
hold, and the disclosed fixture deviation is minimal, additive, and does not weaken a single existing
assertion. The three Minor findings are a latent seam-permissiveness nit, one stale disclosure number,
and one already-self-disclosed global-state limitation — none of them blocks Task 3 or the plan's
acceptance criteria. Findings cleanup stays with PM (zero-residual; this report is advisory input
only).
