# Task 4 implementer report — Bounded live verification and operator documentation

- **Status: DONE_WITH_CONCERNS**
- Plan: `20260911-live-metadata-path-fix` (task 4 of 4, final)
- Working branch: `fix/20260911-live-metadata-path-fix`
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix`
- Commit: `f4af1aa` (`test(metadata): assert the live smoke happy path and document the live transport`), parent `3a96dd1`
- Report author: `fullstack-dev` (leaf executor; no delegation, no subagents)
- Date of the live work: 2026-09-11, 07:30–07:39 (+08:00)

**Concern in one line:** every offline deliverable is complete and green, but the live one-page
CLI run was **refused by upstream** in both attempts (bounded `response_error` / HTTP 412), so
acceptance criterion 4 is met only through its documented blocker arm; the same call shape at a
smaller page size *did* return real rows, which isolates the blocker to upstream risk control on
this egress plus an unresolved question about the production page size of 100.

Clarifications needed before starting: none. The brief's values were verbatim and complete, so no
question was raised.

---

## 1. Implemented

### 1.1 `bilibili-asr-archive/tests/test_live_metadata_smoke.py`

Happy-path assertions strengthened (opt-in gate `BILI_LIVE_SMOKE=1`, one-page bound UID 23191782,
temporary archive root, anonymous bounded-failure branch, loud-fail guard for the missing pinned
dist — all kept):

- run row: terminal outcome in (`complete`, `limited`) — explicitly not `running` — with
  `requested_start_page=1`, `requested_page_limit=1`, `finished_at` set;
- **exactly one** page-evidence row (`COUNT(*) = 1`, was a `fetchone()` presence check), page 1,
  and `error_code IS NULL` on a committed page;
- user row = 1 for the mid; videos join that user through `mid` with no orphans; parts join their
  video through `bvid` with no orphans; **discovery rows join the video they discovered** (new
  join assertion);
- **discovery rows = collected videos** (one run/page discovery row per collected video);
- **at least one part row** for a collected page (a collected Bilibili video always exposes a part);
- cursor advanced **past the committed page** (`next_page = page_number + 1`, state `limited`);
  the `complete` sub-branch keeps `next_page = 1`, state `complete`, and asserts 0 videos / 0 parts
  / 0 discoveries;
- one count-only evidence line printed on success and one bounded line
  (`live smoke evidence: exit=2 error_code=…`) on the bounded-failure branch, so a live run leaves
  recordable row counts and a scalar code without any credential, proxy, or metadata value;
- module/test docstrings corrected: the anonymous branch is now described as a bounded no-credential
  outcome (`rate_limited`, or `response_error` for other upstream failures) rather than as an
  established "upstream anti-bot rejection" fact.

The offline rehearsal test (fake `bilibili_api` seam, runs in every default suite) covers the new
assertions for all three branches and now also guards the evidence line's shape.

### 1.2 `bilibili-asr-archive/docs/metadata-storage.md`

- New **Runtime HTTP backend** section: the pinned `bilibili-api-python==17.4.2` declares no HTTP
  client; without one every request fails in-process (`ArgsException`) and maps to the bounded
  `response_error`; `curl_cffi` is a declared runtime dependency, and a bare
  `pip install bilibili-api-python==17.4.2` is not enough.
- New **Upstream page-call shape** subsection: WBI-signed `Api` request, `dm` disabled, `w_webid`
  present (empty allowed), HTTP 412 answered to both the `dm` shape and a missing `w_webid`, and the
  unchanged bounded error taxonomy (checked line-by-line against
  `sources/bilibili_api_gateway.py`).
- New **HTTP proxy** section: why the pinned `CurlCFFIClient` needs an explicit proxy
  (`proxies={"all": ""}` defeats the environment lookup, so `HTTPS_PROXY`/`ALL_PROXY` alone are
  ignored and a blocked direct route times out), the locked precedence (argument →
  `BILI_HTTP_PROXY` → `HTTPS_PROXY`/`https_proxy` → `ALL_PROXY`/`all_proxy`), blank = unset, no
  proxy forced when nothing resolves.
- **Exact bounded live smoke command** rewritten with the credential + proxy form, the corrected
  expectations for the credentialed (happy path) and anonymous (bounded) branches, the evidence
  line, and a dated **Observed on 2026-09-11** note recording the refusal actually seen (§3).

### 1.3 `bilibili-asr-archive/README.md`

`fetch-meta` section gains the **Runtime HTTP backend** and **HTTP proxy** bullets (with the
precedence and the reason the standard variables are not enough, pointing at the storage doc), and
the **Opt-in bounded live smoke** subsection now shows the full command (`.env` sourcing + proxy)
and the corrected expectations.

### 1.4 `.env.example` (worktree root)

`BILI_HTTP_PROXY` documented next to `BILI_SESSDATA`: commented, with an example
(`http://127.0.0.1:7890`), the reason it must be explicit for the pinned client, and the resolution
order.

**Scope guard respected:** only `tests/test_live_metadata_smoke.py`, `docs/metadata-storage.md`,
`README.md`, and the worktree-root `.env.example` were modified. No adapter, config, DTO, ingestor,
repository, schema, CLI, `pyproject.toml`, or `uv.lock` change. No harness artifact other than this
report was written; plan/snapshot/status/compass/specs untouched. Nothing was pushed; no branch other
than the working branch was touched.

---

## 2. Tests and red/green evidence

**(a) Default run must skip cleanly** — PASS

```
cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v
tests/test_live_metadata_smoke.py::test_live_smoke_fetch_meta_one_page_lands_normalized_rows SKIPPED [ 50%]
tests/test_live_metadata_smoke.py::test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam PASSED [100%]
1 passed, 1 skipped in 0.30s
```

**(b) Red evidence for the new assertions** (mutation check on the offline rehearsal, then restored;
note: `sed`-rewriting a file within the same second keeps its size, so the first restore needed a
`__pycache__` purge before the green reading — the final green runs below were taken after purging):

- `assert discovery_count == video_count` → `== video_count + 1`:
  `E assert 1 == (1 + 1)` at the discovery assertion → FAILED (assertion is live, not vacuous).
- `... == 1, "the one-page run leaves exactly one page row"` → `== 2`:
  `E AssertionError: the one-page run leaves exactly one page row`, `E assert 1 == 2` → FAILED.

**(c) Full offline suite before commit** — PASS, baseline matched

```
cd bilibili-asr-archive && .venv/bin/python -m pytest -q
892 passed, 2 skipped in 49.67s
```

(baseline in the assignment: 892 passed, 2 skipped; the plan's older §Acceptance text still says 865).

**(d) `git diff --check`** on the committed change: clean. Credential scan over the full diff
(`grep -qF "$BILI_SESSDATA"` — the value is never printed): no match. No proxy/credential value
appears in the test, docs, `.env.example`, or the commit message; only the presence-only statement
and the loopback proxy URL the assignment itself specifies.

---

## 3. Live run evidence

Environment for every live call: operator credential sourced in-shell from the control checkout's
`.env` (`set -a; source …/.env; set +a`; value never read, echoed, or persisted), `BILI_HTTP_PROXY=http://127.0.0.1:7890`,
control interpreter `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`
(`bilibili-api-python 17.4.2`, `curl_cffi 0.16.3`, Python 3.12.3), worktree sources first on
`sys.path` (so the fixed adapter is the one under test).

### 3.1 The required live command, attempt 1 (~07:32)

```
cd bilibili-asr-archive && set -a && source /root/workspace/bilibili-asr-archive/.env && set +a \
  && BILI_HTTP_PROXY=http://127.0.0.1:7890 BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest \
     tests/test_live_metadata_smoke.py -v
```

- CLI exit code inside the test: **2**; pytest exit 1 (loud failure — a credential *was* present).
- Evidence line: `live smoke evidence: exit=2 error_code=response_error`.
- Whole run: 1.44 s (no timeout, so not a transport/DNS stall).

### 3.2 Cooldown, then the single permitted retry (~07:36:50, ~170 s idle)

Identical command and identical bounded outcome: CLI exit **2**,
`live smoke evidence: exit=2 error_code=response_error`, 0.87 s. No further live retry was made.

### 3.3 Bounded-failure row counts (asserted by the smoke before the credentialed loud fail)

Both live attempts passed `_assert_bounded_failure_rows`, i.e. the persisted shape is exactly:

| table | rows | detail |
|---|---|---|
| `ingestion_runs` | 1 | `outcome=failed`, `finished_at` set, `requested_start_page=1`, `requested_page_limit=1` |
| `ingestion_pages` | 1 | `page_number=1`, `outcome=failed`, `error_code='response_error'` (bounded scalar) |
| `bilibili_users` | 1 | `mid=23191782` (committed with the run start) |
| `videos` | 0 | no growth |
| `video_parts` | 0 | no growth |
| `ingestion_discoveries` | 0 | no growth |
| `ingestion_cursors` | 0 | **cursor unchanged / never written** |

Also asserted and true for both attempts: `archive.db` created, **no legacy sidecar**
(`manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`), and the no-leak scans over CLI
output + every persisted row passed (static markers, plus the operator credential value when present).

### 3.4 Diagnostic probes that localise the blocker (bounded, purpose-built)

| # | time | call (through the real adapter unless noted) | result |
|---|---|---|---|
| 1 | 07:33:41 | `_fetch_user_video_page(mid, 1, ps=5)`, raw | `NetworkException` **HTTP 412** (risk-control HTML) |
| 2 | 07:33:59 | `get_user_video_page(mid, 1, ps=100)`, mapped | `GatewayResponseError` → `response_error`; cause `ResponseCodeException` **upstream code -400** |
| 3 | 07:37:35 | `get_user_video_page(mid, 1, ps=5)`, mapped | **`code=0`, `videos=5`, `observed_total=1691`** — a real page |
| 4 | 07:37:55 | same process: `ps=5` then `ps=100` | both `NetworkException` **HTTP 412** → `rate_limited` |

Request budget spent on live traffic: **6 upstream calls** (2 smoke attempts = 2 page calls, plus 4
probes); no retry storm, no fingerprint spoofing, no alternate endpoint, no alternate credential.

### 3.5 What this proves, and what it does not

Proven:

- **D1/D2 are fixed live**: the request leaves the process and travels through the configured
  `BILI_HTTP_PROXY` (probe 3 returned real upstream data with the operator credential present).
- **D3 is fixed live**: the corrected shape (`dm` disabled, `w_webid` present) is accepted —
  probe 3 got `code=0` with 5 videos and `observed_total=1691`, matching the plan's §Problem
  reproduction.
- The CLI's bounded path is honest under refusal: exit 2, terminal `failed` run row, one scalar
  `error_code`, no entity/discovery/cursor growth, credential and playback markers absent.

Not proven / unresolved:

- **A completed live one-page CLI run** (acceptance criterion 4, first arm) — both attempts were
  refused. The production call is issued at the ingestors page size (`PAGE_SIZE = 100`,
  `services/metadata_ingest.py`), and all three `-400` answers came from that shape.
- **Whether upstream also caps `ps` below 100.** Suggestive (3× `-400` at `ps=100`; `code=0` at
  `ps=5`, 20 s before a `ps=5` probe was answered with 412), but *not* settled: the egress answered
  412 to `ps=5` as well (probe 4, and probe 1), so a clean page-size A/B could not be obtained inside
  this task's retry budget. I deliberately did not force further probes: page size lives in the
  ingestor/spec (out of this plan's scope) and the plan forbids retry storms.
- Consequence for the next steps: the parts fan-out is one legacy pagelist call per collected video,
  so a larger page size also multiplies risk-control exposure — the earlier diagnosis session saw
  `-799` (`rate_limited`) on exactly that endpoint after ~25 requests.

### 3.6 Escalation / decision needed (PM)

1. Accept criterion 4 through the documented-blocker arm, or schedule the live arm elsewhere. The
   blocker is recorded with exact evidence (this section + the dated note now in
   `docs/metadata-storage.md`).
2. If the page-size hypothesis is to be settled, that is a new bounded task (clean-window probes
   `ps=5/30/50/100`, or the QA gate's own live re-run) — and if it turns out the endpoint caps `ps`,
   the fix touches `services/metadata_ingest.py` (`PAGE_SIZE`) and the iteration's page-size
   contract, i.e. **outside this task's scope guard**; it must not be done silently inside Task 4.
3. The QA gate's mandatory live re-run will very likely hit the same refusal; treat a bounded
   refusal as environmental evidence, not as a Task-1…Task-4 regression, and re-run within a clean
   window.

---

## 4. Files changed

| path (worktree-relative) | change |
|---|---|
| `bilibili-asr-archive/tests/test_live_metadata_smoke.py` | happy-path assertions + evidence lines + docstrings |
| `bilibili-asr-archive/docs/metadata-storage.md` | backend, page-call shape, proxy, live-smoke command/expectations, dated observation |
| `bilibili-asr-archive/README.md` | backend + proxy bullets, live-smoke command/expectations |
| `.env.example` | `BILI_HTTP_PROXY` commented with an example and the resolution order |

Commit `f4af1aa` on `fix/20260911-live-metadata-path-fix`; working tree clean afterwards.

---

## 5. Self-review notes

- `git diff --check` clean; diff reviewed file by file before commit.
- No credential value anywhere (diff scan, tests, docs, commit message, this report); only
  presence-only statements, and the loopback proxy URL the assignment itself specifies. The
  operator `.env` was read by the shell only and was never copied into the worktree.
- Docs accuracy: every claim was checked against the code before writing —
  the `curl_cffi` declaration (`pyproject.toml`), the adapter's `dm=False` / `w_webid` shape and
  `Api`/`Api`-endpoint usage, the taxonomy constants (`-412/-352/-799`, `-404/-62002`, 412/429),
  `resolve_proxy` and `PROXY_ENV_VARS`, `PAGE_SIZE = 100`, and the CLI's presence-only
  `sessdata:` display. Nothing is documented that was not verified; the one behavioural statement
  that could not be reproduced (a completed live page) is written as a **dated observation with the
  evidence attached**, not as an expectation.
- The anonymous/credentialed expectation wording was deliberately made conditional
  ("if upstream rejects anonymous metadata access …") because this task's live budget did not
  include an anonymous attempt; the earlier "anonymous anti-bot rejection" claim was retired, as the
  plan's problem statement requires.
- Naming: the `naming-analyzer` skill was loaded before touching names; no new public/introduced
  name was needed (the existing `_assert_collected_page_rows` now returns the count-only evidence
  line it already knew how to read, documented in its docstring), so no rename was justified.
- Residual hygiene: the only writes outside the four product files are this report and the
  throwaway probe scripts under `/tmp` (`/tmp/live-diag*.py`, no credential material, not part of the
  repo). No harness artifact was modified.

## 6. Open items for the reviewer / PM

1. Live arm of acceptance criterion 4: blocked by upstream refusal (evidence §3), needs the PM's
   decision in §3.6.
2. Page-size cap hypothesis (`ps=100` → `-400`): unresolved, flagged for the QA gate / follow-up.
3. Nothing else outstanding; the offline suite is green at the assignment baseline.
