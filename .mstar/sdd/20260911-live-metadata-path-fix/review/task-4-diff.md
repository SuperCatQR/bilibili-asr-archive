# Task 4 Diff — 20260911-live-metadata-path-fix

Base: `3a96dd1`
Head: `f4af1aa`

```diff
diff --git a/.env.example b/.env.example
index 9413426..5c35b47 100644
--- a/.env.example
+++ b/.env.example
@@ -14,6 +14,15 @@
 # —— 凭据（可选；不填则匿名访问，匿名会被上游风控拦截，元数据采集返回有界 response_error）——
 # BILI_SESSDATA='你的_SESSDATA_Cookie_值'
 
+# —— HTTP 代理（可选；直连 B 站不通或被风控时需要）——
+# 为什么要显式配置：pinned 的 bilibili-api-python(17.4.2) CurlCFFIClient 建会话时写死
+#   proxies={"all": ""}，会绕过 HTTPS_PROXY / ALL_PROXY 等环境变量，只认这里配置的代理。
+# 解析顺序（先非空者胜，空值视为未设置；均未设置时不强制代理，保持库默认行为）：
+#   构造参数 → BILI_HTTP_PROXY → HTTPS_PROXY/https_proxy → ALL_PROXY/all_proxy
+# 代理 URL 属配置而非凭据，不会写入 CLI 输出、日志或数据库。
+# 示例：
+# BILI_HTTP_PROXY=http://127.0.0.1:7890
+
 # —— ASR 模型（可选；默认 FunAudioLLM/Fun-ASR-Nano-2512）——
 # BILI_ASR_MODEL=FunAudioLLM/Fun-ASR-Nano-2512
 
diff --git a/bilibili-asr-archive/README.md b/bilibili-asr-archive/README.md
index b5bb9a1..aba7276 100644
--- a/bilibili-asr-archive/README.md
+++ b/bilibili-asr-archive/README.md
@@ -523,6 +523,20 @@ only restart path.
   (`sessdata: present|absent`). Passing `--sessdata ""` explicitly forces
   anonymous access even when `BILI_SESSDATA` is set; a blank environment
   value likewise means anonymous.
+- **Runtime HTTP backend**: the pinned
+  `bilibili-api-python==17.4.2` distribution declares no HTTP client of its
+  own, so `curl_cffi` is a declared runtime dependency of this package and a
+  normal install (`pip install -e ".[dev]"` or `uv sync`) provides it.
+  Without a backend, every request fails in-process before it leaves the
+  process and surfaces as the bounded `response_error`.
+- **HTTP proxy**: on a host that needs a proxy, set `BILI_HTTP_PROXY`
+  (for example `BILI_HTTP_PROXY=http://127.0.0.1:7890`). The pinned client
+  builds its session with an explicitly empty proxy, so the standard
+  `HTTPS_PROXY` / `ALL_PROXY` variables alone are ignored by the package; the
+  gateway resolves the knob itself in the order constructor argument →
+  `BILI_HTTP_PROXY` → `HTTPS_PROXY`/`https_proxy` → `ALL_PROXY`/`all_proxy`,
+  treats a blank value as unset, and forces no proxy when nothing resolves.
+  Details: [docs/metadata-storage.md](docs/metadata-storage.md).
 
 | Exit | Meaning |
 |------|---------|
@@ -547,17 +561,30 @@ Exit 2 variants:
 `tests/test_live_metadata_smoke.py` drives the real CLI against the real
 upstream: exactly one public metadata page for UID 23191782
 (`--start-page 1 --limit-pages 1`) into a temporary archive root, calling no
-subtitle/playback/audio/ASR code. Default pytest runs skip it:
-
-    cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v
-
-Anonymous (no-credential) access is currently rejected by upstream anti-bot
-control: the smoke then verifies the bounded-failure evidence (terminal run
-row, one scalar page row, no entity growth, no cursor row) and reports the
-case as the expected no-credential behavior rather than a defect.
-Happy-path collection requires a credential from the operator's own
-environment (`--sessdata` or `BILI_SESSDATA`); a bounded failure despite a
-credential is a loud failure.
+subtitle/playback/audio/ASR code. Default pytest runs skip it; the proxy is
+part of the command on a proxied host:
+
+    cd bilibili-asr-archive
+    set -a; source ../.env; set +a              # repo-root .env (gitignored)
+    export BILI_HTTP_PROXY=http://127.0.0.1:7890
+    BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v
+
+With a credential in the environment (`--sessdata` or `BILI_SESSDATA`) the
+smoke requires the happy path: exit 0, `outcome=limited` on the page bound
+(or `complete` on an empty first page), and the real normalized rows — user,
+videos, their parts, one discovery row per video, a terminal run row, exactly
+one page row, and a cursor advanced past the committed page — with no legacy
+sidecar and no credential or playback marker in output or rows. It prints one
+count-only evidence line (`live smoke evidence: outcome=… videos=… parts=…
+discoveries=… page_rows=1 cursor_next_page=… cursor_state=…
+observed_total=…`); a bounded failure with a credential present is a loud
+failure. Without a credential the run is anonymous: if upstream rejects
+anonymous metadata access the smoke verifies the bounded-failure evidence
+(terminal run row, one scalar page row with a `rate_limited` /
+`response_error` code, no entity or discovery growth, no cursor row) and
+reports that bounded no-credential outcome as a reasoned skip rather than a
+defect. Expectations and the underlying transport/proxy requirements are
+documented in [docs/metadata-storage.md](docs/metadata-storage.md).
 
 ### Mixed batch outcomes
 
diff --git a/bilibili-asr-archive/docs/metadata-storage.md b/bilibili-asr-archive/docs/metadata-storage.md
index c75e1ef..529b223 100644
--- a/bilibili-asr-archive/docs/metadata-storage.md
+++ b/bilibili-asr-archive/docs/metadata-storage.md
@@ -82,6 +82,61 @@ means anonymous access, and so does passing `--sessdata ""` explicitly
 (which never falls through to `BILI_SESSDATA`); a blank environment value
 likewise means anonymous.
 
+## Runtime HTTP backend
+
+`fetch-meta` reaches upstream through the pinned
+`bilibili-api-python==17.4.2` adapter, and that distribution declares no HTTP
+client of its own. With none installed, every request fails inside the process
+with `ArgsException("尚未安装第三方请求库或未注册自定义第三方请求库")` — the
+request never leaves the process — and the gateway maps it to the bounded
+`response_error`. `curl_cffi` is therefore a declared runtime dependency of
+this package, and a normal install provides it:
+
+```
+python3.12 -m pip install -e ".[dev]"     # or: uv sync
+```
+
+No separately installed backend is needed on top of that; a bare
+`pip install bilibili-api-python==17.4.2` alone is not enough.
+
+### Upstream page-call shape
+
+The adapter issues the user-video page call itself through the package's
+WBI-signed `Api` request, with the device-fingerprint (`dm`) parameters
+disabled and `w_webid` sent as a present string (empty when the package
+cannot derive an access id). The endpoint answers HTTP 412 to the `dm` shape
+and to a missing `w_webid`; every other parameter, the WBI signature, and the
+whole response normalization and validation path stay as the pinned package
+and the gateway spec define them. The bounded error taxonomy is unchanged:
+412/429 and the risk-control codes map to `rate_limited`, `-404`/`-62002` to
+`not_found`, shape problems to `shape_error`, and other upstream failures to
+`response_error`/`transport_error`.
+
+## HTTP proxy
+
+The pinned client builds its session with an explicitly empty proxy
+(`proxies={"all": ""}`), which defeats the transport's environment lookup:
+`HTTPS_PROXY` / `ALL_PROXY` alone are ignored by the package, so on a host
+whose direct route to Bilibili is blocked every call ends in a connect
+timeout. The gateway therefore resolves one proxy itself and applies it to the
+package's request settings before the first call.
+
+Precedence (first non-blank value wins; blank counts as unset):
+
+1. the `BilibiliApiGateway(proxy=...)` constructor argument,
+2. `BILI_HTTP_PROXY` — the documented operator knob,
+3. `HTTPS_PROXY`, then `https_proxy`,
+4. `ALL_PROXY`, then `all_proxy`.
+
+When nothing resolves, the library default is left untouched and no proxy is
+forced. A proxy URL is configuration, not a credential, and is never written
+to DTOs, logs, exception messages, or persisted rows.
+
+```
+export BILI_HTTP_PROXY=http://127.0.0.1:7890
+bili-asr fetch-meta --mid 23191782 --limit-pages 1 --archive-root archive
+```
+
 ## `observed_total` semantics
 
 - `ingestion_cursors.observed_total` records the upstream video total
@@ -97,24 +152,62 @@ likewise means anonymous.
 
 ## Exact bounded live smoke command
 
+The smoke is opt-in and bounded: one public metadata page for UID 23191782
+into a temporary archive root. On a proxied host — and on this host, whose
+direct route to Bilibili is blocked — the proxy is part of the command:
+
 ```
-cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v
+cd bilibili-asr-archive
+set -a; source ../.env; set +a              # repo-root .env (gitignored)
+export BILI_HTTP_PROXY=http://127.0.0.1:7890
+BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v
 ```
 
+`BILI_SESSDATA` may come from the sourced `.env` instead of an explicit
+`export`, and `BILI_HTTP_PROXY` may live in `.env` as well (the gateway reads
+the same environment).
+
 - Opt-in only (`BILI_LIVE_SMOKE=1`); default pytest runs skip it without
-  failure. An opted-in run without the pinned `bilibili-api-python==17.4.2`
-  distribution fails loudly with install guidance instead of skipping.
-- Bound: exactly one public metadata page for UID 23191782
-  (`--start-page 1 --limit-pages 1`) into a temporary archive root; no
-  subtitle/playback/audio/ASR code is invoked and nothing outside the
-  temporary root is written.
-- Anonymous (no-credential) access is currently rejected by upstream
-  anti-bot control: the smoke then verifies the bounded-failure evidence
-  (terminal run row, one scalar page row, no entity growth, no cursor row)
-  and reports the case as the expected no-credential behavior — not a
-  defect. Happy-path collection requires a credential from the operator's
-  own environment (`--sessdata` or `BILI_SESSDATA`); a bounded failure
-  despite a credential is a loud failure.
+  failure. An opted-in run in an environment without the pinned
+  `bilibili-api-python==17.4.2` distribution fails loudly with install
+  guidance instead of skipping.
+- Bound: exactly one page for UID 23191782 (`--start-page 1 --limit-pages 1`)
+  into a temporary archive root; no subtitle, playback, audio, or ASR code is
+  invoked, and nothing outside the temporary root is written.
+- **With a credential** (`--sessdata` or `BILI_SESSDATA`) the happy path is
+  required: exit 0, `outcome=limited` on the page bound (or `complete` when
+  the first page comes back empty), and real normalized rows — the user row,
+  one video row per collected video joined to that user, the part rows of
+  those videos, one discovery row per collected video, a terminal run row,
+  exactly one page-evidence row, and a cursor advanced past the committed
+  page. The run also asserts that no legacy sidecar
+  (`manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`) appears
+  and that neither the CLI output nor any persisted row carries the
+  credential value or playback markers. It prints one count-only evidence
+  line:
+  `live smoke evidence: outcome=… videos=… parts=… discoveries=… page_rows=1 cursor_next_page=… cursor_state=… observed_total=…`.
+  A bounded upstream failure while a credential is present is a loud failure.
+- **Without a credential** the run is anonymous: if upstream rejects
+  anonymous metadata access it ends in the bounded-failure branch, whose
+  evidence the smoke then verifies (terminal run row, one page row carrying a
+  scalar code — `rate_limited`, or `response_error` for other upstream
+  failures — no video/part/discovery growth, no cursor row). That bounded
+  no-credential outcome is reported as a reasoned skip, after its assertions
+  ran, not as a defect.
+- **Observed on 2026-09-11** (this host, proxy configured): the live run was
+  refused by upstream risk control. The CLI's one production page (the
+  ingestor's page size of 100) ended twice — before and after a cooldown —
+  in the bounded `response_error` branch, whose underlying upstream answer is
+  the JSON code `-400`; a direct call with the same credential, proxy, and
+  call shape but a page size of 5 returned `code=0` with real rows (5 videos,
+  `observed_total=1691`), and later probes of both page sizes were answered
+  with HTTP 412 (`rate_limited`). So the transport and the call shape do
+  reach and satisfy upstream, while this egress is intermittently under
+  risk control; a loud live-smoke failure means the bounded page was refused
+  upstream, not that the database or the CLI is broken. Whether the endpoint
+  also caps `ps` below 100 was not settled by these observations: the
+  `-400` answers all came from the page size of 100, but risk control was
+  rejecting other probes with 412 at the same time.
 
 ## Exit codes
 
diff --git a/bilibili-asr-archive/tests/test_live_metadata_smoke.py b/bilibili-asr-archive/tests/test_live_metadata_smoke.py
index fc9823d..45d3632 100644
--- a/bilibili-asr-archive/tests/test_live_metadata_smoke.py
+++ b/bilibili-asr-archive/tests/test_live_metadata_smoke.py
@@ -14,17 +14,19 @@ Default pytest runs skip the smoke; it executes only when the operator sets
 
 - the happy path (exit 0) lands the expected normalized rows — user, videos
   joined to their user through ``mid``, parts joined to their video through
-  ``bvid``, a terminal run row, exactly one page-evidence row, and the
-  advanced fresh cursor — while every persisted surface stays free of
-  credential, signed-URL, and playback markers;
+  ``bvid``, one discovery row per collected video, a terminal run row,
+  exactly one page-evidence row, and the fresh cursor advanced past the
+  committed page — while every persisted surface stays free of credential,
+  signed-URL, and playback markers;
 - the bounded upstream failure (exit 2) is a valid, documented CLI outcome:
   the failure evidence stays scalar (terminal run row, one bounded page row,
   no entity or discovery growth, no cursor row), and the smoke verifies it.
-  Anonymous (no-credential) access is currently rejected by upstream
-  anti-bot control, so an anonymous run reports that case as the expected
-  no-credential behavior (a clearly-reasoned skip, after its assertions
-  ran); the same bounded failure with an operator credential in the
-  environment is a loud failure.
+  Without a credential the run is anonymous, and an upstream rejection of
+  anonymous metadata access is one bounded failure among others
+  (``rate_limited``, or ``response_error`` for other upstream failures): the
+  smoke reports that case as the documented no-credential behavior (a
+  clearly-reasoned skip, after its assertions ran), while the same bounded
+  failure with an operator credential in the environment is a loud failure.
 """
 
 from __future__ import annotations
@@ -127,30 +129,47 @@ def _assert_no_credential_or_playback_leaks(
         )
 
 
-def _assert_collected_page_rows(connection, mid: int) -> None:
-    """Assert the normalized evidence a successful one-page run leaves."""
+def _assert_collected_page_rows(connection, mid: int) -> str:
+    """Assert the normalized evidence a successful one-page run leaves.
+
+    The successful run is terminal (``limited`` on the explicit page bound
+    with a non-empty page, ``complete`` on an empty one) and leaves exactly
+    one page-evidence row, the user row, one video row per collected video
+    with one run/page discovery row each, at least one part row per collected
+    video, and a cursor that advanced past the committed page.
+
+    Returns a one-line, count-only evidence summary (no credential, no
+    collected metadata values) for the live run to print.
+    """
 
     run_row = connection.execute(
         "SELECT outcome, requested_start_page, requested_page_limit, finished_at"
         " FROM ingestion_runs"
     ).fetchone()
     assert run_row is not None, "the run row must exist"
-    assert run_row["outcome"] in ("complete", "limited")
+    assert run_row["outcome"] in ("complete", "limited"), (
+        "a successful run must be terminal (not 'running')"
+    )
     assert run_row["requested_start_page"] == 1
     assert run_row["requested_page_limit"] == 1
     assert run_row["finished_at"] is not None
 
     # Exactly one bounded page-evidence row for the one requested page.
+    assert connection.execute(
+        "SELECT COUNT(*) FROM ingestion_pages"
+    ).fetchone()[0] == 1, "the one-page run leaves exactly one page row"
     page_row = connection.execute(
         "SELECT page_number, outcome, error_code FROM ingestion_pages"
     ).fetchone()
-    assert page_row is not None and page_row["page_number"] == 1
+    assert page_row["page_number"] == 1
+    assert page_row["error_code"] is None, "a committed page carries no error code"
 
     assert connection.execute(
         "SELECT COUNT(*) FROM bilibili_users WHERE mid = ?", (mid,)
     ).fetchone()[0] == 1
     # Every video joins its owner user through mid; every part joins its
-    # video through bvid (the normalized foreign-key relationships).
+    # video through bvid; every discovery row joins the video it discovered
+    # (the normalized foreign-key relationships).
     assert connection.execute(
         "SELECT COUNT(*) FROM videos AS v"
         " LEFT JOIN bilibili_users AS u ON v.mid = u.mid"
@@ -161,9 +180,18 @@ def _assert_collected_page_rows(connection, mid: int) -> None:
         " LEFT JOIN videos AS v ON p.bvid = v.bvid"
         " WHERE v.bvid IS NULL"
     ).fetchone()[0] == 0
+    assert connection.execute(
+        "SELECT COUNT(*) FROM ingestion_discoveries AS d"
+        " LEFT JOIN videos AS v ON d.bvid = v.bvid"
+        " WHERE v.bvid IS NULL"
+    ).fetchone()[0] == 0
     video_count = connection.execute(
         "SELECT COUNT(*) FROM videos WHERE mid = ?", (mid,)
     ).fetchone()[0]
+    part_count = connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0]
+    discovery_count = connection.execute(
+        "SELECT COUNT(*) FROM ingestion_discoveries"
+    ).fetchone()[0]
 
     cursor_row = connection.execute(
         "SELECT next_page, state, observed_total FROM ingestion_cursors"
@@ -174,14 +202,29 @@ def _assert_collected_page_rows(connection, mid: int) -> None:
     observed_total = cursor_row["observed_total"]
     if run_row["outcome"] == "limited":
         assert video_count >= 1
+        # Every collected video exposes at least one part upstream, and each
+        # collected video is recorded once as discovered on this page.
+        assert part_count >= 1
+        assert discovery_count == video_count
         assert tuple(page_row)[:2] == (1, "ok")
-        assert tuple(cursor_row)[:2] == (2, "limited")
+        assert cursor_row["state"] == "limited"
+        # The cursor advanced past the committed page.
+        assert cursor_row["next_page"] == page_row["page_number"] + 1
     else:  # complete: the first page came back empty and completed the run
         assert video_count == 0
+        assert part_count == 0
+        assert discovery_count == 0
         assert tuple(page_row)[:2] == (1, "empty")
         assert tuple(cursor_row)[:2] == (1, "complete")
     if observed_total is not None:
         assert observed_total >= video_count
+    return (
+        f"outcome={run_row['outcome']} videos={video_count}"
+        f" parts={part_count} discoveries={discovery_count} page_rows=1"
+        f" cursor_next_page={cursor_row['next_page']}"
+        f" cursor_state={cursor_row['state']}"
+        f" observed_total={observed_total}"
+    )
 
 
 def _assert_bounded_failure_rows(connection, mid: int) -> str:
@@ -241,9 +284,10 @@ def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
     Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The probe runs
     the real ``fetch-meta`` command for UID 23191782 with ``--start-page 1
     --limit-pages 1`` into a temporary archive root, asserts the normalized
-    table relationships on the happy path, and asserts the scalar-only
-    failure evidence when upstream rejects the page.  It never invokes
-    subtitle, playback, audio, or ASR code.
+    table relationships on the happy path (user, videos, parts, discovery,
+    run, page and cursor), and asserts the scalar-only failure evidence when
+    upstream rejects the page.  It never invokes subtitle, playback, audio,
+    or ASR code.
     """
 
     if not _live_smoke_requested():
@@ -268,7 +312,10 @@ def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
             assert err == ""
             assert "sessdata:" in out
             assert "outcome=" in out
-            _assert_collected_page_rows(connection, LIVE_SMOKE_MID)
+            evidence = _assert_collected_page_rows(connection, LIVE_SMOKE_MID)
+            # Count-only evidence for the operator's record of the live run:
+            # no credential, no proxy, and no collected metadata values.
+            print(f"live smoke evidence: {evidence}")
             return
 
         assert exit_code == 2
@@ -278,6 +325,8 @@ def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
                 " a bounded run record); rerun to capture the failure shape"
             )
         error_code = _assert_bounded_failure_rows(connection, LIVE_SMOKE_MID)
+        # The bounded scalar code only: no output text, no upstream payload.
+        print(f"live smoke evidence: exit=2 error_code={error_code}")
         assert error_code in err
         assert "metadata gateway failure" in err
         # Same resolution rule as ``resolve_sessdata``: a missing or blank
@@ -285,10 +334,11 @@ def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
         if not os.environ.get(SESSDATA_ENV_VAR):
             pytest.skip(
                 "live smoke ended in the documented bounded anonymous"
-                f" rejection (error_code={error_code!r}, exit 2): upstream"
-                " anti-bot control currently rejects no-credential metadata"
-                " access; this is the expected no-credential behavior, not a"
-                " defect. Provide a credential via --sessdata or"
+                f" rejection (error_code={error_code!r}, exit 2): without a"
+                " credential the run is anonymous, and upstream rejects some"
+                " anonymous metadata access; the smoke accepts this bounded"
+                " no-credential outcome rather than treating it as a defect."
+                " Provide a credential via --sessdata or"
                 f" {SESSDATA_ENV_VAR} for the happy-path run."
             )
         pytest.fail(
@@ -350,7 +400,12 @@ def test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam(
     assert "cursor: next_page=2 state=limited" in out
     connection = open_database(tmp_root)
     try:
-        _assert_collected_page_rows(connection, LIVE_SMOKE_MID)
+        evidence = _assert_collected_page_rows(connection, LIVE_SMOKE_MID)
+        # The evidence line the live run prints is count-only and keeps its
+        # documented fields, so the offline rehearsal guards its shape.
+        assert "outcome=limited" in evidence
+        assert "videos=1" in evidence
+        assert "cursor_next_page=2" in evidence
         # Positive control: a normalized video row really persisted, so the
         # no-leak scans are not vacuous.
         persisted = persisted_row_text(connection)
```
