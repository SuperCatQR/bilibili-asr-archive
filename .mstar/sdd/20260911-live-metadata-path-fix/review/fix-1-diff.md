# Fix Wave 1 Diff — 20260911-live-metadata-path-fix

Base: `f44066c`
Head: `5667844`
Scope: batched docs/hygiene findings I1 + M1-M5 + Task-5 minors (see review/task-4-review.md, review/task-5-review.md)

```diff
diff --git a/.env.example b/.env.example
index 5c35b47..337de50 100644
--- a/.env.example
+++ b/.env.example
@@ -16,15 +16,16 @@
 
 # —— HTTP 代理（可选；直连 B 站不通或被风控时需要）——
 # 为什么要显式配置：pinned 的 bilibili-api-python(17.4.2) CurlCFFIClient 建会话时写死
-#   proxies={"all": ""}，会绕过 HTTPS_PROXY / ALL_PROXY 等环境变量，只认这里配置的代理。
+#   proxies={"all": ""}，库自身会绕过 HTTPS_PROXY / ALL_PROXY 等环境变量；网关在构造请求前
+#   自己解析一次代理（下面的顺序包含这些环境变量），所以它们依然有效，只是必须由网关应用。
 # 解析顺序（先非空者胜，空值视为未设置；均未设置时不强制代理，保持库默认行为）：
 #   构造参数 → BILI_HTTP_PROXY → HTTPS_PROXY/https_proxy → ALL_PROXY/all_proxy
 # 代理 URL 属配置而非凭据，不会写入 CLI 输出、日志或数据库。
-# 示例：
+# 默认：不设置（不强制代理）。示例值（非默认）：
 # BILI_HTTP_PROXY=http://127.0.0.1:7890
 
 # —— ASR 模型（可选；默认 FunAudioLLM/Fun-ASR-Nano-2512）——
 # BILI_ASR_MODEL=FunAudioLLM/Fun-ASR-Nano-2512
 
 # —— 音频保留（可选；默认 0 = archived 后删除音频以省磁盘，设为 1 = 保留音频供未来重跑）——
-# BILI_KEEP_AUDIO=1
+# BILI_KEEP_AUDIO=0
diff --git a/bilibili-asr-archive/README.md b/bilibili-asr-archive/README.md
index cb270d0..e6c3904 100644
--- a/bilibili-asr-archive/README.md
+++ b/bilibili-asr-archive/README.md
@@ -564,12 +564,24 @@ upstream: exactly one public metadata page for UID 23191782
 subtitle/playback/audio/ASR code. Default pytest runs skip it; the proxy is
 part of the command on a proxied host:
 
-    cd bilibili-asr-archive
-    set -a; source ../.env; set +a              # repo-root .env (gitignored)
+    CONTROL=/root/workspace/bilibili-asr-archive   # the control checkout
+    cd "$CONTROL/bilibili-asr-archive"
+    set -a; source "$CONTROL/.env"; set +a          # gitignored; absent in a worktree
     export BILI_HTTP_PROXY=http://127.0.0.1:7890
-    BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v
-
-With a credential in the environment (`--sessdata` or `BILI_SESSDATA`) the
+    BILI_LIVE_SMOKE=1 "$CONTROL/bilibili-asr-archive/.venv/bin/python" \
+      -m pytest tests/test_live_metadata_smoke.py -s -v
+
+The control checkout owns the `.env` credential file and the `.venv`
+interpreter, and a linked feature worktree has neither — a worktree run must
+address them by absolute control-checkout path (as above) or provision its own
+environment. Keep `-s` (or `-rP`) in the command on the first live attempt:
+pytest captures the stdout of a *passing* test, so a plain `-v` run hides the
+count-only evidence line on the happy path and would force a second page
+request against a risk-controlled endpoint.
+
+The smoke's credential signal is the `BILI_SESSDATA` environment variable alone
+(sourced from `.env` above): it builds its own `fetch-meta` argv and passes no
+`--sessdata`, so that CLI flag is not a smoke input. With that credential the
 smoke requires the happy path: exit 0, `outcome=limited` on the page bound
 (or `complete` on an empty first page), and the real normalized rows — user,
 videos, their parts, one discovery row per video, a terminal run row, exactly
diff --git a/bilibili-asr-archive/docs/metadata-storage.md b/bilibili-asr-archive/docs/metadata-storage.md
index 529b223..42115c1 100644
--- a/bilibili-asr-archive/docs/metadata-storage.md
+++ b/bilibili-asr-archive/docs/metadata-storage.md
@@ -157,15 +157,24 @@ into a temporary archive root. On a proxied host — and on this host, whose
 direct route to Bilibili is blocked — the proxy is part of the command:
 
 ```
-cd bilibili-asr-archive
-set -a; source ../.env; set +a              # repo-root .env (gitignored)
+CONTROL=/root/workspace/bilibili-asr-archive   # the control checkout
+cd "$CONTROL/bilibili-asr-archive"
+set -a; source "$CONTROL/.env"; set +a          # gitignored; absent in a worktree
 export BILI_HTTP_PROXY=http://127.0.0.1:7890
-BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v
+BILI_LIVE_SMOKE=1 "$CONTROL/bilibili-asr-archive/.venv/bin/python" \
+  -m pytest tests/test_live_metadata_smoke.py -s -v
 ```
 
-`BILI_SESSDATA` may come from the sourced `.env` instead of an explicit
-`export`, and `BILI_HTTP_PROXY` may live in `.env` as well (the gateway reads
-the same environment).
+The control checkout owns both the `.env` credential file and the `.venv`
+interpreter; a linked feature worktree has neither, so a worktree run must
+address them by absolute control-checkout path (as above) or provision its
+own environment. `-s` (or `-rP`) is part of the command: pytest captures the
+stdout of a *passing* test, so a plain `-v` run hides the evidence line on the
+happy path and would force a second page request against a risk-controlled
+endpoint — use `-s`/`-rP` on the first live attempt.
+
+`BILI_SESSDATA` and `BILI_HTTP_PROXY` may come from the sourced `.env` instead
+of an explicit `export` (the gateway reads the same environment).
 
 - Opt-in only (`BILI_LIVE_SMOKE=1`); default pytest runs skip it without
   failure. An opted-in run in an environment without the pinned
@@ -174,8 +183,10 @@ the same environment).
 - Bound: exactly one page for UID 23191782 (`--start-page 1 --limit-pages 1`)
   into a temporary archive root; no subtitle, playback, audio, or ASR code is
   invoked, and nothing outside the temporary root is written.
-- **With a credential** (`--sessdata` or `BILI_SESSDATA`) the happy path is
-  required: exit 0, `outcome=limited` on the page bound (or `complete` when
+- **With a credential** (`BILI_SESSDATA` only — the smoke builds its own
+  `fetch-meta` argv and passes no `--sessdata`, so that flag is a CLI surface
+  the smoke never uses) the happy path is required: exit 0,
+  `outcome=limited` on the page bound (or `complete` when
   the first page comes back empty), and real normalized rows — the user row,
   one video row per collected video joined to that user, the part rows of
   those videos, one discovery row per collected video, a terminal run row,
@@ -196,7 +207,7 @@ the same environment).
   ran, not as a defect.
 - **Observed on 2026-09-11** (this host, proxy configured): the live run was
   refused by upstream risk control. The CLI's one production page (the
-  ingestor's page size of 100) ended twice — before and after a cooldown —
+  then-shipped page size of 100) ended twice — before and after a cooldown —
   in the bounded `response_error` branch, whose underlying upstream answer is
   the JSON code `-400`; a direct call with the same credential, proxy, and
   call shape but a page size of 5 returned `code=0` with real rows (5 videos,
@@ -204,10 +215,15 @@ the same environment).
   with HTTP 412 (`rate_limited`). So the transport and the call shape do
   reach and satisfy upstream, while this egress is intermittently under
   risk control; a loud live-smoke failure means the bounded page was refused
-  upstream, not that the database or the CLI is broken. Whether the endpoint
-  also caps `ps` below 100 was not settled by these observations: the
-  `-400` answers all came from the page size of 100, but risk control was
-  rejecting other probes with 412 at the same time.
+  upstream, not that the database or the CLI is broken.
+- **Settled on the same day (focused probes after the call-shape fix):** the
+  endpoint does reject the old page size. With the same credential, proxy,
+  and call shape, `ps=30` returned `code=0` with 30 items and `ps=50`
+  returned `code=0` with 50 items, while `ps=100` was rejected — HTTP 412 on
+  the probes and the JSON code `-400` on production runs. The shipped page
+  size is therefore the value upstream accepts: `PAGE_SIZE = 30` in
+  `src/bili_asr/services/metadata_ingest.py`, which is also the pinned
+  package's own documented `ps` value.
 
 ## Exit codes
 
diff --git a/bilibili-asr-archive/src/bili_asr/config.py b/bilibili-asr-archive/src/bili_asr/config.py
index 577e18a..8e97f70 100644
--- a/bilibili-asr-archive/src/bili_asr/config.py
+++ b/bilibili-asr-archive/src/bili_asr/config.py
@@ -27,8 +27,8 @@ DEFAULT_MID = 23191782
 #: ``--limit-pages`` defaults to this instead of unbounded: a full
 #: collection without an explicit bound would otherwise only terminate on
 #: an upstream empty page, exposing every run to unbounded anti-bot risk.
-#: Ten pages at the ingestor's page size of 100 is a resumable, conservative
-#: slice; operators opt into longer batches explicitly.
+#: Ten pages at the ingestor's page size of 30 (300 videos) is a resumable,
+#: conservative slice; operators opt into longer batches explicitly.
 DEFAULT_PAGE_LIMIT = 10
 
 #: Environment variable carrying the optional SESSDATA credential.
diff --git a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
index 4829d2b..c3328f8 100644
--- a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
+++ b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
@@ -476,7 +476,7 @@ def make_videos_response(*items: object, count: int | None = 2) -> dict:
 
     response: dict = {"list": {"vlist": list(items)}}
     if count is not None:
-        response["page"] = {"pn": 1, "ps": 100, "count": count}
+        response["page"] = {"pn": 1, "ps": 30, "count": count}
     return response
 
 
diff --git a/bilibili-asr-archive/tests/test_live_metadata_smoke.py b/bilibili-asr-archive/tests/test_live_metadata_smoke.py
index 45d3632..4b1a928 100644
--- a/bilibili-asr-archive/tests/test_live_metadata_smoke.py
+++ b/bilibili-asr-archive/tests/test_live_metadata_smoke.py
@@ -135,8 +135,9 @@ def _assert_collected_page_rows(connection, mid: int) -> str:
     The successful run is terminal (``limited`` on the explicit page bound
     with a non-empty page, ``complete`` on an empty one) and leaves exactly
     one page-evidence row, the user row, one video row per collected video
-    with one run/page discovery row each, at least one part row per collected
-    video, and a cursor that advanced past the committed page.
+    with one run/page discovery row each, at least one part row in aggregate
+    over the collected page (not one per video: an individual video may have
+    no parts upstream), and a cursor that advanced past the committed page.
 
     Returns a one-line, count-only evidence summary (no credential, no
     collected metadata values) for the live run to print.
@@ -202,8 +203,10 @@ def _assert_collected_page_rows(connection, mid: int) -> str:
     observed_total = cursor_row["observed_total"]
     if run_row["outcome"] == "limited":
         assert video_count >= 1
-        # Every collected video exposes at least one part upstream, and each
-        # collected video is recorded once as discovered on this page.
+        # The page carries at least one part in aggregate (parts are fetched
+        # for every collected video; an individual video may legitimately have
+        # no parts upstream, so this is deliberately not a per-video claim),
+        # and each collected video is recorded once as discovered on this page.
         assert part_count >= 1
         assert discovery_count == video_count
         assert tuple(page_row)[:2] == (1, "ok")
@@ -338,8 +341,9 @@ def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
                 " credential the run is anonymous, and upstream rejects some"
                 " anonymous metadata access; the smoke accepts this bounded"
                 " no-credential outcome rather than treating it as a defect."
-                " Provide a credential via --sessdata or"
-                f" {SESSDATA_ENV_VAR} for the happy-path run."
+                f" Provide a credential via {SESSDATA_ENV_VAR} in the"
+                " environment for the happy-path run; this smoke builds its"
+                " own argv, so its --sessdata flag is never passed."
             )
         pytest.fail(
             "live smoke ended in a bounded upstream failure despite an"
```
