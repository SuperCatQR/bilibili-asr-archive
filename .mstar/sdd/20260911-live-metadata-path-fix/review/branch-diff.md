# Branch Review Package — 20260911-live-metadata-path-fix

Plan: `20260911-live-metadata-path-fix` (single-plan workflow)
Range: `25a11fe..5667844`
Base: `25a11fe` (main at branch creation)
Head: `5667844`
Working branch: `fix/20260911-live-metadata-path-fix`
Commits: cc56e46 (curl_cffi dep), 0a2e2f5 (proxy), 3a96dd1 (risk-control-safe page call), f4af1aa (live smoke + docs), f44066c (page size 30), 5667844 (docs/hygiene fix wave)

```diff
diff --git a/.env.example b/.env.example
index 9413426..337de50 100644
--- a/.env.example
+++ b/.env.example
@@ -14,8 +14,18 @@
 # —— 凭据（可选；不填则匿名访问，匿名会被上游风控拦截，元数据采集返回有界 response_error）——
 # BILI_SESSDATA='你的_SESSDATA_Cookie_值'
 
+# —— HTTP 代理（可选；直连 B 站不通或被风控时需要）——
+# 为什么要显式配置：pinned 的 bilibili-api-python(17.4.2) CurlCFFIClient 建会话时写死
+#   proxies={"all": ""}，库自身会绕过 HTTPS_PROXY / ALL_PROXY 等环境变量；网关在构造请求前
+#   自己解析一次代理（下面的顺序包含这些环境变量），所以它们依然有效，只是必须由网关应用。
+# 解析顺序（先非空者胜，空值视为未设置；均未设置时不强制代理，保持库默认行为）：
+#   构造参数 → BILI_HTTP_PROXY → HTTPS_PROXY/https_proxy → ALL_PROXY/all_proxy
+# 代理 URL 属配置而非凭据，不会写入 CLI 输出、日志或数据库。
+# 默认：不设置（不强制代理）。示例值（非默认）：
+# BILI_HTTP_PROXY=http://127.0.0.1:7890
+
 # —— ASR 模型（可选；默认 FunAudioLLM/Fun-ASR-Nano-2512）——
 # BILI_ASR_MODEL=FunAudioLLM/Fun-ASR-Nano-2512
 
 # —— 音频保留（可选；默认 0 = archived 后删除音频以省磁盘，设为 1 = 保留音频供未来重跑）——
-# BILI_KEEP_AUDIO=1
+# BILI_KEEP_AUDIO=0
diff --git a/bilibili-asr-archive/README.md b/bilibili-asr-archive/README.md
index b5bb9a1..e6c3904 100644
--- a/bilibili-asr-archive/README.md
+++ b/bilibili-asr-archive/README.md
@@ -506,7 +506,7 @@ only restart path.
 
 - **Default page bound**: `--limit-pages` is optional and defaults to
   `DEFAULT_PAGE_LIMIT = 10`. The canonical command above therefore stops
-  after 10 pages (the ingestor's page size is 100), ends the run `limited`,
+  after 10 pages (the ingestor's page size is 30), ends the run `limited`,
   and still exits 0 — a limited run is never claimed as complete. A full
   archive walk is a series of resumable runs: re-run the same command to
   continue from the stored cursor, or pass an explicit `--limit-pages` for
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
@@ -547,17 +561,42 @@ Exit 2 variants:
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
+    CONTROL=/root/workspace/bilibili-asr-archive   # the control checkout
+    cd "$CONTROL/bilibili-asr-archive"
+    set -a; source "$CONTROL/.env"; set +a          # gitignored; absent in a worktree
+    export BILI_HTTP_PROXY=http://127.0.0.1:7890
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
index c75e1ef..42115c1 100644
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
@@ -97,24 +152,78 @@ likewise means anonymous.
 
 ## Exact bounded live smoke command
 
+The smoke is opt-in and bounded: one public metadata page for UID 23191782
+into a temporary archive root. On a proxied host — and on this host, whose
+direct route to Bilibili is blocked — the proxy is part of the command:
+
 ```
-cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v
+CONTROL=/root/workspace/bilibili-asr-archive   # the control checkout
+cd "$CONTROL/bilibili-asr-archive"
+set -a; source "$CONTROL/.env"; set +a          # gitignored; absent in a worktree
+export BILI_HTTP_PROXY=http://127.0.0.1:7890
+BILI_LIVE_SMOKE=1 "$CONTROL/bilibili-asr-archive/.venv/bin/python" \
+  -m pytest tests/test_live_metadata_smoke.py -s -v
 ```
 
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
+- **With a credential** (`BILI_SESSDATA` only — the smoke builds its own
+  `fetch-meta` argv and passes no `--sessdata`, so that flag is a CLI surface
+  the smoke never uses) the happy path is required: exit 0,
+  `outcome=limited` on the page bound (or `complete` when
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
+  then-shipped page size of 100) ended twice — before and after a cooldown —
+  in the bounded `response_error` branch, whose underlying upstream answer is
+  the JSON code `-400`; a direct call with the same credential, proxy, and
+  call shape but a page size of 5 returned `code=0` with real rows (5 videos,
+  `observed_total=1691`), and later probes of both page sizes were answered
+  with HTTP 412 (`rate_limited`). So the transport and the call shape do
+  reach and satisfy upstream, while this egress is intermittently under
+  risk control; a loud live-smoke failure means the bounded page was refused
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
 
diff --git a/bilibili-asr-archive/pyproject.toml b/bilibili-asr-archive/pyproject.toml
index 8b87c4b..1b35307 100644
--- a/bilibili-asr-archive/pyproject.toml
+++ b/bilibili-asr-archive/pyproject.toml
@@ -11,6 +11,7 @@ requires-python = ">=3.12"
 dependencies = [
     "requests>=2.32",
     "bilibili-api-python==17.4.2",
+    "curl_cffi>=0.16",
 ]
 license = { text = "Proprietary" }
 
diff --git a/bilibili-asr-archive/src/bili_asr/config.py b/bilibili-asr-archive/src/bili_asr/config.py
index d1c4168..8e97f70 100644
--- a/bilibili-asr-archive/src/bili_asr/config.py
+++ b/bilibili-asr-archive/src/bili_asr/config.py
@@ -5,15 +5,18 @@ so the command layer only composes validated values, and so every display
 or debug path that could show the credential instead shows a redacted
 presence label.  The SESSDATA value is resolved from ``--sessdata`` or the
 ``BILI_SESSDATA`` environment variable, is never echoed, logged,
-persisted, or rendered by any helper here.  ``status`` and ``runs`` take
-no credential and no page arguments; they share only the database-name
-constant below.
+persisted, or rendered by any helper here.  The proxy the gateway applies
+to the pinned package is resolved here as well (:func:`resolve_proxy`),
+from the constructor argument or ``BILI_HTTP_PROXY`` and the conventional
+host variables.  ``status`` and ``runs`` take no credential and no page
+arguments; they share only the database-name constant below.
 """
 
 from __future__ import annotations
 
 import argparse
 import os
+from collections.abc import Mapping
 from dataclasses import dataclass, field
 
 #: Bilibili user collected by default (未明子).
@@ -24,13 +27,30 @@ DEFAULT_MID = 23191782
 #: ``--limit-pages`` defaults to this instead of unbounded: a full
 #: collection without an explicit bound would otherwise only terminate on
 #: an upstream empty page, exposing every run to unbounded anti-bot risk.
-#: Ten pages at the ingestor's page size of 100 is a resumable, conservative
-#: slice; operators opt into longer batches explicitly.
+#: Ten pages at the ingestor's page size of 30 (300 videos) is a resumable,
+#: conservative slice; operators opt into longer batches explicitly.
 DEFAULT_PAGE_LIMIT = 10
 
 #: Environment variable carrying the optional SESSDATA credential.
 SESSDATA_ENV_VAR = "BILI_SESSDATA"
 
+#: Documented operator knob for the HTTP proxy the gateway applies to the
+#: pinned package.  The pinned client otherwise forces ``proxies={"all": ""}``
+#: and ignores the environment, so a proxied host needs this set.
+PROXY_ENV_VAR = "BILI_HTTP_PROXY"
+
+#: Proxy variables in locked precedence order: the documented knob first, then
+#: the conventional host variables (the upper-case spelling of each pair
+#: first).  A host that already exports ``HTTPS_PROXY`` therefore needs no
+#: application change.
+PROXY_ENV_VARS = (
+    PROXY_ENV_VAR,
+    "HTTPS_PROXY",
+    "https_proxy",
+    "ALL_PROXY",
+    "all_proxy",
+)
+
 #: File name of the fresh SQLite database below the archive root.  Must
 #: stay identical to the storage layer's archive database name because the
 #: read commands check for its existence before opening it.
@@ -131,10 +151,36 @@ def redact_sessdata(sessdata: str | None) -> str:
     return SESSDATA_PRESENT_LABEL if sessdata else SESSDATA_ABSENT_LABEL
 
 
+def resolve_proxy(
+    argument_value: str | None, environ: Mapping[str, str]
+) -> str | None:
+    """Return the proxy from the argument, else the environment, else None.
+
+    The resolution order is locked: the explicit argument first, then
+    :data:`PROXY_ENV_VARS` in the order declared there.  A blank or
+    whitespace-only value counts as unset and never blocks the next level, so
+    an empty environment entry cannot silently disable a proxy a
+    lower-precedence variable provides; surrounding whitespace is stripped
+    from the value that is returned.  When nothing resolves the caller must
+    leave the library's own proxy behaviour untouched.
+    """
+
+    candidates = (argument_value, *(environ.get(name) for name in PROXY_ENV_VARS))
+    for candidate in candidates:
+        if candidate is None:
+            continue
+        value = candidate.strip()
+        if value:
+            return value
+    return None
+
+
 __all__ = [
     "ARCHIVE_DATABASE_NAME",
     "DEFAULT_MID",
     "DEFAULT_PAGE_LIMIT",
+    "PROXY_ENV_VAR",
+    "PROXY_ENV_VARS",
     "SESSDATA_ABSENT_LABEL",
     "SESSDATA_ENV_VAR",
     "SESSDATA_PRESENT_LABEL",
@@ -142,5 +188,6 @@ __all__ = [
     "MetadataConfigError",
     "load_metadata_config",
     "redact_sessdata",
+    "resolve_proxy",
     "resolve_sessdata",
 ]
diff --git a/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py b/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py
index afddeb7..0f98fc5 100644
--- a/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py
+++ b/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py
@@ -43,7 +43,11 @@ from bili_asr.storage.models import (
 )
 
 SOURCE_PACKAGE = "bilibili-api-python"
-PAGE_SIZE = 100
+#: Shipped page size of the user-video page call.  Upstream answers ``ps=100``
+#: with its bounded ``-400``/HTTP 412 rejection while 30 — the pinned
+#: package's own documented value — returns ``code=0``, so the shipped default
+#: stays inside the bound upstream accepts.
+PAGE_SIZE = 30
 
 
 def _now() -> int:
diff --git a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
index 3e83719..0335948 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
@@ -12,11 +12,12 @@ from __future__ import annotations
 
 import importlib.metadata
 import math
+import os
 import re
 from collections.abc import Awaitable, Callable, Mapping
 from typing import Any
 
-from bilibili_api import Credential
+from bilibili_api import Credential, request_settings, user
 from bilibili_api.exceptions import (
     ApiException,
     NetworkException,
@@ -24,9 +25,10 @@ from bilibili_api.exceptions import (
     ResponseException,
     WbiRetryTimesExceedException,
 )
-from bilibili_api.user import User
+from bilibili_api.utils.network import Api
 from bilibili_api.video import Video
 
+from bili_asr.config import resolve_proxy
 from bili_asr.sources.models import (
     GatewayNotFound,
     GatewayRateLimited,
@@ -51,6 +53,13 @@ _NOT_FOUND_HTTP_STATUSES = frozenset({404})
 # Same shape check the package itself applies in Video.set_bvid.
 _BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")
 
+# The package's own endpoint description for the user-video page call
+# (``bilibili_api.user.API["info"]["video"]``).  ``url``/``method``/
+# ``verify``/``wbi`` are read from it so this adapter cannot drift from the
+# pinned package; ``dm`` is deliberately overridden per call (see
+# ``BilibiliApiGateway._fetch_user_video_page``).
+_USER_VIDEO_PAGE_ENDPOINT = user.API["info"]["video"]
+
 
 def _require_positive_argument(value: object, field: str) -> None:
     """Reject caller-argument violations before any upstream call."""
@@ -242,29 +251,50 @@ def _complete_summary_from_detail(
 class BilibiliApiGateway:
     """Concrete :class:`BilibiliGateway` adapter over the pinned package."""
 
-    def __init__(self, sessdata: str | None = None) -> None:
-        """Build the package credential; a blank value means public access.
+    def __init__(self, sessdata: str | None = None, proxy: str | None = None) -> None:
+        """Build the package credential and apply one resolved proxy.
 
         The optional SESSDATA value is passed to the package ``Credential``
         object only.  It is never written to DTOs, logs, exception messages,
         or persistent records.
+
+        ``proxy`` is an explicit programmatic override; when it is blank or
+        omitted the locked chain in :mod:`bili_asr.config` decides
+        (``BILI_HTTP_PROXY`` first, then the conventional host variables).
+        A resolved proxy is applied here, once, through the package's
+        request settings: that is the value the pinned ``CurlCFFIClient``
+        reads when it builds its session, and its own default
+        (``proxies={"all": ""}``) would otherwise defeat ``trust_env`` and
+        ignore environment proxies.  ``Credential(proxy=...)`` is
+        deliberately not used — it swaps that same global setting around
+        every call instead of configuring it.  When nothing resolves, the
+        library default is left untouched.  The resolved value is
+        configuration, not a credential, and still never appears in DTOs,
+        logs, exception messages, or persistent records.
         """
 
         self._credential = Credential(sessdata=sessdata) if sessdata else Credential()
+        self.resolved_proxy = resolve_proxy(proxy, os.environ)
+        if self.resolved_proxy is not None:
+            request_settings.set_proxy(self.resolved_proxy)
+        self._w_webid_by_mid: dict[int, str] = {}
 
     async def get_user_video_page(
-        self, mid: int, page_number: int, page_size: int = 100
+        self, mid: int, page_number: int, page_size: int = 30
     ) -> UserVideoPage:
-        """Fetch and normalize exactly one bounded user-video page."""
+        """Fetch and normalize exactly one bounded user-video page.
+
+        The default is the upstream-accepted page size declared by the
+        :class:`~bili_asr.sources.models.BilibiliGateway` protocol; an
+        explicit ``page_size`` still overrides it.
+        """
 
         _require_positive_argument(mid, "mid")
         _require_positive_argument(page_number, "page_number")
         _require_positive_argument(page_size, "page_size")
         response = await self._await_upstream(
             "get_user_video_page",
-            lambda: User(
-                uid=mid, credential=self._credential
-            ).get_videos(pn=page_number, ps=page_size),
+            lambda: self._fetch_user_video_page(mid, page_number, page_size),
         )
         return _normalize_user_video_page(response, requested_mid=mid, page_number=page_number)
 
@@ -304,6 +334,70 @@ class BilibiliApiGateway:
         except importlib.metadata.PackageNotFoundError:
             return PINNED_PACKAGE_VERSION
 
+    async def _fetch_user_video_page(
+        self, mid: int, page_number: int, page_size: int
+    ) -> Any:
+        """Issue one WBI-signed page request in the shape upstream accepts.
+
+        The request is built from the package's own endpoint description and
+        signed by the package's ``Api``.  Two fields are this adapter's:
+        ``dm`` is disabled, because the device-fingerprint parameters it would
+        add cannot be satisfied here and the endpoint answers HTTP 412 with
+        them; and ``w_webid`` is always sent as a present string, because the
+        endpoint answers HTTP 412 when the parameter is missing.  Every other
+        parameter name and value stays exactly the set the package's own page
+        call sends.
+        """
+
+        w_webid = await self._resolve_w_webid(mid)
+        return await (
+            Api(
+                url=_USER_VIDEO_PAGE_ENDPOINT["url"],
+                method=_USER_VIDEO_PAGE_ENDPOINT["method"],
+                verify=_USER_VIDEO_PAGE_ENDPOINT["verify"],
+                wbi=_USER_VIDEO_PAGE_ENDPOINT["wbi"],
+                dm=False,
+                credential=self._credential,
+            )
+            .update_params(
+                mid=mid,
+                ps=page_size,
+                tid=0,
+                pn=page_number,
+                keyword="",
+                order=user.VideoOrder.PUBDATE.value,
+                order_avoided=True,
+                platform="web",
+                w_webid=w_webid,
+            )
+            .result
+        )
+
+    async def _resolve_w_webid(self, mid: int) -> str:
+        """Resolve the page request's ``w_webid`` parameter for one user.
+
+        The package's ``User.get_access_id`` scrapes the user's dynamic page,
+        which no longer server-renders ``access_id``: the route costs one
+        extra page fetch and currently yields nothing.  The token is a request
+        parameter rather than a credential, and the endpoint requires it to be
+        present, so an unavailable token degrades to the empty string instead
+        of failing the page call.  Each user's outcome is remembered for this
+        adapter's lifetime, so at most one scrape attempt happens per user no
+        matter how many pages are collected.
+        """
+
+        if mid not in self._w_webid_by_mid:
+            try:
+                access_id: object = await user.User(
+                    uid=mid, credential=self._credential
+                ).get_access_id()
+            except Exception:
+                # Best effort only: this optional token route must never fail
+                # the metadata call it decorates.
+                access_id = None
+            self._w_webid_by_mid[mid] = access_id if isinstance(access_id, str) else ""
+        return self._w_webid_by_mid[mid]
+
     async def _await_upstream(
         self, operation: str, call: Callable[[], Awaitable[Any]]
     ) -> Any:
diff --git a/bilibili-asr-archive/src/bili_asr/sources/models.py b/bilibili-asr-archive/src/bili_asr/sources/models.py
index d81415c..8647147 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/models.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/models.py
@@ -95,8 +95,11 @@ class UserVideoPage:
 class BilibiliGateway(Protocol):
     """Application-owned gateway protocol for the pinned package adapter."""
 
+    # 30 is the page size the user-video endpoint accepts: the pinned package
+    # documents ``ps`` as ``const int: 30`` and upstream answers ``ps=100``
+    # with its bounded ``-400``/HTTP 412 rejection.
     async def get_user_video_page(
-        self, mid: int, page_number: int, page_size: int = 100
+        self, mid: int, page_number: int, page_size: int = 30
     ) -> UserVideoPage: ...
 
     async def get_video_parts(self, bvid: str) -> tuple[VideoPart, ...]: ...
diff --git a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
index 312d3ec..c3328f8 100644
--- a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
+++ b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
@@ -10,11 +10,23 @@ Every package-seam test scripts these fakes instead of touching the pinned
 - ``FakeUpstreamScript`` / ``build_fake_package`` / ``bilibili_api_seam``
   install the fake ``bilibili_api`` package on ``sys.modules`` for the real
   adapter tests.  The fake mirrors only the documented import surface the
-  adapter may use (``Credential``, ``user.User.get_videos``,
-  ``video.Video.get_info``/``get_pages``, and the exceptions taxonomy) and
-  exposes no playback, subtitle, audio, or download method, so a silent
-  switch to another package API fails loudly instead of silently
-  succeeding.
+  adapter may use (``Credential``, ``request_settings.set_proxy`` /
+  ``get_proxy``, the ``user`` endpoint description and ``access_id`` route,
+  the WBI-signed ``utils.network.Api`` the user-video page call is issued
+  through, ``video.Video.get_info`` / ``get_pages``, and the exceptions
+  taxonomy) and exposes no playback, subtitle, audio, or download method, so
+  a silent switch to another package API fails loudly instead of silently
+  succeeding.  ``applied_proxies`` records every proxy the adapter hands to
+  the package settings, so its apply-once behavior is asserted without a
+  network call.
+- ``FakeApiRequest`` with ``script.api_requests`` records every page request
+  the adapter issues through the package's ``Api``: the transport flags it
+  took from the package endpoint description (device-fingerprint ``dm``
+  overridden) and the exact parameters it handed over, so the
+  risk-control-relevant call shape is assertable without a network call.
+  ``script.access_id_calls`` records the separate ``access_id`` token route
+  (kept out of ``calls``: it is a memoized, best-effort token fetch, not a
+  metadata call).
 - ``script_parts_by_bvid`` scripts one parts payload per requested ``bvid``
   for seam tests that collect a page holding several distinct videos.
 - ``DOCUMENTED_METADATA_CALLS`` with ``assert_only_documented_metadata_calls``
@@ -31,6 +43,7 @@ from __future__ import annotations
 import dataclasses
 import sys
 import types
+from enum import Enum
 
 import pytest
 
@@ -44,8 +57,35 @@ FAKE_PACKAGE_VERSION = "17.4.2"
 #: Adapter module the seam fixture reloads against the installed fake.
 GATEWAY_ADAPTER_MODULE = "bili_asr.sources.bilibili_api_gateway"
 
-#: The exact upstream call names the gateway adapter may issue.
-DOCUMENTED_METADATA_CALLS = ("user.get_videos", "video.get_info", "video.get_pages")
+#: The package's own endpoint description for the user-video page call
+#: (``bilibili_api.user.API["info"]["video"]``), mirroring the pinned
+#: distribution literally — including ``dm: True``.  The adapter must take
+#: ``url``/``method``/``verify``/``wbi`` from it and override ``dm``, so a
+#: package-side change to any of those fields stays visible here.
+FAKE_USER_VIDEO_PAGE_ENDPOINT = {
+    "url": "https://api.bilibili.com/x/space/wbi/arc/search",
+    "method": "GET",
+    "verify": False,
+    "wbi": True,
+    "dm": True,
+    "params": {
+        "mid": "int: uid",
+        "ps": "const int: 30",
+        "tid": "int: 分区 ID，0 表示全部",
+        "pn": "int: 页码",
+        "keyword": "str: 关键词，可为空",
+        "w_webid": "str: w_webid",
+    },
+    "comment": "搜索用户视频",
+}
+
+#: The exact upstream call names the gateway adapter may issue.  The page call
+#: is recorded as ``space.arc.search`` because the adapter issues that request
+#: itself through the package's ``Api``: the package's ``User.get_videos``
+#: delegate cannot pass upstream risk control (it injects device-fingerprint
+#: ``dm`` parameters and scrapes ``w_webid`` from a page that no longer
+#: server-renders it).
+DOCUMENTED_METADATA_CALLS = ("space.arc.search", "video.get_info", "video.get_pages")
 
 #: Realistic-looking SESSDATA value that must never leave the process.
 SESSDATA_BOUNDARY_VALUE = "SESSDATA-VALUE-THAT-MUST-NOT-LEAK"
@@ -118,16 +158,58 @@ class FakeWbiRetryTimesExceedException(FakeApiException):
         super().__init__("WBI 重试达到最大次数")
 
 
+def _device_fingerprint_params() -> dict:
+    """Mirror of the package's ``_enc_dm`` injection: the same parameter names.
+
+    A request built with ``dm`` enabled carries these parameters upstream, so
+    the fake adds them too: the "no device-fingerprint parameters are sent"
+    assertion then detects the real risk-control defect instead of merely
+    restating the recorded ``dm`` flag.
+    """
+
+    return {
+        "dm_img_list": "[]",
+        "dm_img_str": "AB",
+        "dm_cover_img_str": "AB",
+        "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}',
+    }
+
+
+@dataclasses.dataclass
+class FakeApiRequest:
+    """One recorded package-``Api`` request: the call shape that was issued.
+
+    ``params`` is the exact mapping the adapter handed to ``update_params``,
+    captured when the request was issued, with the package's
+    device-fingerprint injection mirrored when ``dm`` is on.
+    """
+
+    url: str
+    method: str
+    verify: bool
+    wbi: bool
+    dm: bool
+    params: dict
+
+
 @dataclasses.dataclass
 class FakeUpstreamScript:
     """Scripted upstream behavior; records every call the gateway makes.
 
-    A scripted response may be a plain value or a callable receiving the
+    A scripted page response may be a plain value or a callable receiving the
     documented page parameters (``pn``, ``ps``) so per-page behavior can be
     scripted for multi-page runs.  The scripted ``parts_response`` may
     likewise be a plain value or a callable receiving the requested
     ``bvid``, so each video's parts can be scripted independently (see
     :func:`script_parts_by_bvid`).
+
+    ``videos_response`` / ``videos_error`` script the user-video page request
+    the adapter issues through the package ``Api``; ``access_id`` /
+    ``access_id_error`` script the separate ``access_id`` token route
+    (``None`` by default, which is what the route currently yields in
+    production).  ``user_video_page_endpoint`` is the package-side endpoint
+    description the adapter must read its transport fields from; a test may
+    rewrite it before the adapter module is (re-)imported.
     """
 
     videos_response: object = None
@@ -136,7 +218,15 @@ class FakeUpstreamScript:
     parts_error: BaseException | None = None
     info_response: object = None
     info_error: BaseException | None = None
+    access_id: str | None = None
+    access_id_error: BaseException | None = None
+    user_video_page_endpoint: dict = dataclasses.field(
+        default_factory=lambda: dict(FAKE_USER_VIDEO_PAGE_ENDPOINT)
+    )
     calls: list[str] = dataclasses.field(default_factory=list)
+    access_id_calls: list[str] = dataclasses.field(default_factory=list)
+    api_requests: list[FakeApiRequest] = dataclasses.field(default_factory=list)
+    applied_proxies: list[str] = dataclasses.field(default_factory=list)
 
 
 class FakeGateway:
@@ -165,7 +255,7 @@ class FakeGateway:
         self._completions[bvid] = completed
 
     async def get_user_video_page(
-        self, mid: int, page_number: int, page_size: int = 100
+        self, mid: int, page_number: int, page_size: int = 30
     ) -> UserVideoPage:
         self.page_calls.append((mid, page_number, page_size))
         return self._scripted(self._pages, page_number, "user-video-page")
@@ -202,6 +292,21 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
 
     package.Credential = Credential
 
+    request_settings_mod = types.ModuleType("bilibili_api.request_settings")
+
+    def set_proxy(proxy: str = "") -> None:
+        """Mirror of ``request_settings.set_proxy``; records the applied value."""
+
+        script.applied_proxies.append(proxy)
+
+    def get_proxy() -> str:
+        """Mirror of ``request_settings.get_proxy`` (``""`` before any set)."""
+
+        return script.applied_proxies[-1] if script.applied_proxies else ""
+
+    request_settings_mod.set_proxy = set_proxy
+    request_settings_mod.get_proxy = get_proxy
+
     exceptions_mod = types.ModuleType("bilibili_api.exceptions")
     exceptions_mod.ApiException = FakeApiException
     exceptions_mod.NetworkException = FakeNetworkException
@@ -211,30 +316,99 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
 
     user_mod = types.ModuleType("bilibili_api.user")
 
+    class VideoOrder(Enum):
+        """Mirror of ``user.VideoOrder`` (only the default order is exposed)."""
+
+        PUBDATE = "pubdate"
+
     class User:
-        """Mirror of ``user.User(uid, credential)`` with only get_videos."""
+        """Mirror of ``user.User(uid, credential)`` with only the access_id route.
+
+        The user-video page data no longer flows through this class: the
+        adapter issues the endpoint description's request itself through the
+        package ``Api``.
+        """
 
         def __init__(self, uid: int, credential: object = None) -> None:
             self.uid = uid
             self.credential = credential
 
-        async def get_videos(
+        async def get_access_id(self) -> str | None:
+            script.access_id_calls.append(f"user.get_access_id(uid={self.uid})")
+            if script.access_id_error is not None:
+                raise script.access_id_error
+            return script.access_id
+
+    user_mod.API = {"info": {"video": script.user_video_page_endpoint}}
+    user_mod.User = User
+    user_mod.VideoOrder = VideoOrder
+
+    network_mod = types.ModuleType("bilibili_api.utils.network")
+
+    class Api:
+        """Mirror of ``utils.network.Api`` for the documented page request.
+
+        The package's ``Api`` is built from an endpoint description whose
+        ``url``/``method``/``verify``/``wbi`` the adapter must state and whose
+        ``dm`` it must override, so those fields are required here and are
+        recorded with the parameters of the issued request.  ``result``
+        answers with the scripted page payload or raises the scripted
+        failure.  Only the local request shaping under test is mirrored (the
+        ``dm`` parameter injection); signing, cookies, and retries are not,
+        because the adapter may not depend on them.
+        """
+
+        def __init__(
             self,
-            tid: int = 0,
-            pn: int = 1,
-            ps: int = 30,
-            keyword: str = "",
-            order: object = None,
-        ) -> dict:
-            script.calls.append(f"user.get_videos(pn={pn}, ps={ps})")
+            url: str,
+            method: str,
+            verify: bool,
+            wbi: bool,
+            dm: bool,
+            credential: object = None,
+        ) -> None:
+            self.url = url
+            self.method = method
+            self.verify = verify
+            self.wbi = wbi
+            self.dm = dm
+            self.credential = credential
+            self.params: dict = {}
+
+        def update_params(self, **kwargs: object) -> "Api":
+            """Mirror of ``Api.update_params`` (replaces the parameters)."""
+
+            self.params = dict(kwargs)
+            return self
+
+        @property
+        async def result(self) -> object:
+            """Mirror of ``Api.result``: record, then answer or fail."""
+
+            params = dict(self.params)
+            if self.dm:
+                params.update(_device_fingerprint_params())
+            page_number = params.get("pn")
+            page_size = params.get("ps")
+            script.api_requests.append(
+                FakeApiRequest(
+                    url=self.url,
+                    method=self.method,
+                    verify=self.verify,
+                    wbi=self.wbi,
+                    dm=self.dm,
+                    params=params,
+                )
+            )
+            script.calls.append(f"space.arc.search(pn={page_number}, ps={page_size})")
             if script.videos_error is not None:
                 raise script.videos_error
             response = script.videos_response
             if callable(response):
-                response = response(pn=pn, ps=ps)
+                response = response(pn=page_number, ps=page_size)
             return response
 
-    user_mod.User = User
+    network_mod.Api = Api
 
     video_mod = types.ModuleType("bilibili_api.video")
 
@@ -271,12 +445,15 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
     package.user = user_mod
     package.video = video_mod
     package.exceptions = exceptions_mod
+    package.request_settings = request_settings_mod
 
     return {
         "bilibili_api": package,
         "bilibili_api.user": user_mod,
+        "bilibili_api.utils.network": network_mod,
         "bilibili_api.video": video_mod,
         "bilibili_api.exceptions": exceptions_mod,
+        "bilibili_api.request_settings": request_settings_mod,
     }
 
 
@@ -299,7 +476,7 @@ def make_videos_response(*items: object, count: int | None = 2) -> dict:
 
     response: dict = {"list": {"vlist": list(items)}}
     if count is not None:
-        response["page"] = {"pn": 1, "ps": 100, "count": count}
+        response["page"] = {"pn": 1, "ps": 30, "count": count}
     return response
 
 
@@ -414,7 +591,9 @@ __all__ = [
     "BVID",
     "DOCUMENTED_METADATA_CALLS",
     "FAKE_PACKAGE_VERSION",
+    "FAKE_USER_VIDEO_PAGE_ENDPOINT",
     "FakeApiException",
+    "FakeApiRequest",
     "FakeGateway",
     "FakeNetworkException",
     "FakeResponseCodeException",
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index 50b21b0..f759143 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -5,13 +5,18 @@ on ``sys.modules`` before the gateway module is (re-)imported, so neither the
 real package nor network access is ever required.  The fake package seam, the
 shared scripted protocol double, and the secret/raw-payload sentinels live in
 ``tests/fixtures/fake_bilibili_gateway.py``.  The fake mirrors only the
-documented import surface the gateway may use (``Credential``, ``user.User``,
-``video.Video``, and the exceptions taxonomy) and exposes no playback,
-subtitle, audio, or download methods, which makes silent use of other package
-APIs impossible.  The import boundary and the method surface itself are
+documented import surface the gateway may use (``Credential``, the ``user``
+endpoint description and ``access_id`` route, the WBI-signed
+``utils.network.Api``, ``video.Video``, and the exceptions taxonomy) and
+exposes no playback, subtitle, audio, or download methods, which makes silent
+use of other package APIs impossible.  The import boundary and the method
+surface itself are
 additionally inspected statically with AST over the package sources.  The
 only networked test is the opt-in live smoke, which skips unless
-``BILI_LIVE_SMOKE=1`` is set.
+``BILI_LIVE_SMOKE=1`` is set.  The packaging-contract test is the one
+exception to the "installed distribution never needed" rule: it reads the
+pinned distribution's metadata and fails loudly when that distribution is
+absent, because the contract it checks cannot be proven without it.
 """
 
 from __future__ import annotations
@@ -19,13 +24,20 @@ from __future__ import annotations
 import ast
 import asyncio
 import importlib
+import importlib.metadata
+import inspect
 import os
 import pathlib
+import tomllib
 
 import pytest
+from packaging.requirements import Requirement
+from packaging.utils import canonicalize_name
 
+from bili_asr.config import PROXY_ENV_VAR, PROXY_ENV_VARS, resolve_proxy
 from bili_asr.services.metadata_ingest import MetadataIngestor
 from bili_asr.sources.models import (
+    BilibiliGateway,
     GatewayNotFound,
     GatewayRateLimited,
     GatewayResponseError,
@@ -38,6 +50,7 @@ from bili_asr.sources.models import (
 from bili_asr.storage.database import MetadataRepository, open_database
 from fixtures.fake_bilibili_gateway import (
     BVID,
+    FAKE_USER_VIDEO_PAGE_ENDPOINT,
     MID,
     PUBDATE,
     RAW_JSON_BODY_MARKER,
@@ -59,12 +72,26 @@ from fixtures.fake_bilibili_gateway import (
     persisted_row_text,
 )
 
+PINNED_PACKAGE_DISTRIBUTION_NAME = "bilibili-api-python"
 PINNED_PACKAGE_VERSION = "17.4.2"
 
-#: The exact bilibili_api import surface the adapter is allowed to use.
+#: PEP 503 canonical name of the runtime HTTP backend this project declares.
+#: The pinned package drives whichever client is installed while declaring
+#: none itself, so this declaration is what lets a fresh install reach the
+#: network at all.
+HTTP_BACKEND_CANONICAL_NAME = "curl-cffi"
+
+#: The HTTP clients the pinned package can drive, named in its own error
+#: message (``pip3 install (curl_cffi|httpx|aiohttp)``).  None of them may
+#: arrive through the application's dependency closure on its own.
+PACKAGE_HTTP_CLIENT_CANONICAL_NAMES = frozenset({"curl-cffi", "httpx", "aiohttp"})
+
+#: The exact bilibili_api import surface the adapter is allowed to use.  The
+#: user-video page call is issued through ``user``'s own endpoint description
+#: and the WBI-signed ``utils.network.Api``, not through a ``user`` delegate.
 ALLOWED_PACKAGE_IMPORTS = {
-    "bilibili_api": {"Credential"},
-    "bilibili_api.user": {"User"},
+    "bilibili_api": {"Credential", "request_settings", "user"},
+    "bilibili_api.utils.network": {"Api"},
     "bilibili_api.video": {"Video"},
     "bilibili_api.exceptions": {
         "ApiException",
@@ -75,6 +102,19 @@ ALLOWED_PACKAGE_IMPORTS = {
     },
 }
 
+#: Realistic-looking proxy URL: configuration rather than a credential, but it
+#: must still stay off DTOs, mapped errors, debug renders, and persisted rows.
+PROXY_BOUNDARY_VALUE = "http://PROXY-URL-THAT-MUST-NOT-LEAK:7890"
+
+#: Realistic-looking ``access_id`` token: a request parameter the package
+#: route may yield, which must stay off DTOs and mapped errors like every
+#: other upstream value.
+ACCESS_ID_BOUNDARY_VALUE = "ACCESS-ID-THAT-MUST-NOT-LEAK"
+
+#: Sentinel endpoint URL proving the transport fields are read from the
+#: package's own endpoint description instead of being hard-coded.
+CHANGED_ENDPOINT_URL = "https://changed-endpoint.example.invalid/x/space/wbi/arc/search"
+
 #: The complete documented exception surface the fake seam must mirror.
 ALLOWED_EXCEPTION_NAMES = (
     "ApiException",
@@ -107,11 +147,11 @@ def _public_names(obj: object) -> list[str]:
     return sorted(name for name in vars(obj) if not name.startswith("_"))
 
 
-def _load_gateway(sessdata: str | None = None):
+def _load_gateway(sessdata: str | None = None, proxy: str | None = None):
     """Import the adapter against the installed seam and build it."""
 
     module = importlib.import_module("bili_asr.sources.bilibili_api_gateway")
-    return module.BilibiliApiGateway(sessdata=sessdata)
+    return module.BilibiliApiGateway(sessdata=sessdata, proxy=proxy)
 
 
 # --------------------------------------------------- deterministic factories
@@ -156,7 +196,7 @@ def test_get_user_video_page_normalizes_documented_fields(bilibili_api_seam):
     assert summary.title == "未明子讲座"
     assert summary.pubdate == PUBDATE
     assert summary.mid == MID
-    assert bilibili_api_seam.calls == ["user.get_videos(pn=1, ps=100)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
     # The credential value must never surface on any DTO or page.
     assert SESSDATA_BOUNDARY_VALUE not in repr(page)
     assert SESSDATA_BOUNDARY_VALUE not in str(page)
@@ -170,7 +210,52 @@ def test_get_user_video_page_forwards_requested_page_and_size(bilibili_api_seam)
 
     asyncio.run(gateway.get_user_video_page(MID, page_number=4, page_size=50))
 
-    assert bilibili_api_seam.calls == ["user.get_videos(pn=4, ps=50)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=4, ps=50)"]
+
+
+def test_get_user_video_page_defaults_to_upstream_accepted_size(bilibili_api_seam):
+    """An omitted page size issues the upstream-accepted ``ps=30``.
+
+    The endpoint answers the former ``ps=100`` default with its bounded
+    ``-400``/HTTP 412 rejection, so the protocol declaration and the adapter
+    both default to 30 — reverting either to 100 fails this test.
+    """
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
+    declared = inspect.signature(BilibiliGateway.get_user_video_page)
+    assert declared.parameters["page_size"].default == 30
+
+
+def test_get_user_video_page_explicit_size_override_keeps_normalization(
+    bilibili_api_seam,
+):
+    """An explicit page size still flows through and normalizes the page."""
+
+    bilibili_api_seam.videos_response = make_videos_response(
+        make_vlist_item(title="  未明子讲座  "), count=7
+    )
+    gateway = _load_gateway()
+
+    page = asyncio.run(gateway.get_user_video_page(MID, page_number=2, page_size=50))
+
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=2, ps=50)"]
+    assert isinstance(page, UserVideoPage)
+    assert (page.mid, page.page_number, page.observed_total) == (MID, 2, 7)
+    assert isinstance(page.videos, tuple)
+    (summary,) = page.videos
+    assert isinstance(summary, VideoSummary)
+    assert (summary.bvid, summary.aid, summary.title, summary.pubdate, summary.mid) == (
+        BVID,
+        111,
+        "未明子讲座",
+        PUBDATE,
+        MID,
+    )
 
 
 def test_get_user_video_page_tolerates_plain_list_container(bilibili_api_seam):
@@ -356,7 +441,146 @@ def test_get_user_video_page_rejects_malformed_upstream_bvid(
 
     assert caught.value.code == "shape_error"
     assert "bvid" in str(caught.value)
-    assert bilibili_api_seam.calls == ["user.get_videos(pn=1, ps=100)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
+
+
+# ------------------------------------- user page: risk-control-safe request
+
+
+def test_user_video_page_request_carries_the_documented_parameter_set(
+    bilibili_api_seam,
+):
+    """The page request sends the package's parameters with ``dm`` disabled.
+
+    Device-fingerprint parameters cannot be satisfied here and make the
+    endpoint answer HTTP 412; the same endpoint answers ``code=0`` without
+    them, and the request must still carry ``w_webid`` (empty is the value
+    the unavailable token route degrades to).
+    """
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=2, page_size=50))
+
+    (request,) = bilibili_api_seam.api_requests
+    assert request.dm is False
+    assert [key for key in request.params if key.startswith("dm_")] == []
+    assert request.params == {
+        "mid": MID,
+        "ps": 50,
+        "tid": 0,
+        "pn": 2,
+        "keyword": "",
+        "order": "pubdate",
+        "order_avoided": True,
+        "platform": "web",
+        "w_webid": "",
+    }
+
+
+def test_user_video_page_request_prefers_the_package_access_id(bilibili_api_seam):
+    """A non-empty ``access_id`` from the package route is what gets sent."""
+
+    bilibili_api_seam.access_id = ACCESS_ID_BOUNDARY_VALUE
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    assert bilibili_api_seam.access_id_calls == [f"user.get_access_id(uid={MID})"]
+    assert (
+        bilibili_api_seam.api_requests[0].params["w_webid"]
+        == ACCESS_ID_BOUNDARY_VALUE
+    )
+    # A request parameter still never surfaces on a DTO.
+    assert ACCESS_ID_BOUNDARY_VALUE not in repr(page)
+
+
+def test_user_video_page_request_falls_back_to_empty_w_webid_when_the_route_fails(
+    bilibili_api_seam,
+):
+    """A failing token scrape never fails the page call itself."""
+
+    bilibili_api_seam.access_id_error = FakeNetworkException(412, UPSTREAM_ERROR_TEXT)
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    assert page.observed_total == 1
+    assert bilibili_api_seam.api_requests[0].params["w_webid"] == ""
+    assert UPSTREAM_ERROR_TEXT not in str(page)
+
+
+def test_user_video_page_resolves_the_access_id_once_per_user(bilibili_api_seam):
+    """Repeated pages of one user scrape the token route at most once."""
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+    asyncio.run(gateway.get_user_video_page(MID, page_number=2))
+
+    assert bilibili_api_seam.access_id_calls == [f"user.get_access_id(uid={MID})"]
+    assert len(bilibili_api_seam.api_requests) == 2
+
+
+def test_user_video_page_resolves_the_access_id_per_user(bilibili_api_seam):
+    """The memoized token is bound to the user it was scraped for."""
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    bilibili_api_seam.videos_response = make_videos_response(
+        make_vlist_item(mid=MID + 1), count=1
+    )
+    asyncio.run(gateway.get_user_video_page(MID + 1, page_number=1))
+
+    assert bilibili_api_seam.access_id_calls == [
+        f"user.get_access_id(uid={MID})",
+        f"user.get_access_id(uid={MID + 1})",
+    ]
+
+
+def test_user_video_page_request_takes_its_transport_from_the_package_endpoint(
+    bilibili_api_seam,
+):
+    """``url``/``method``/``verify``/``wbi`` come from the package description."""
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    (request,) = bilibili_api_seam.api_requests
+    assert request.url == FAKE_USER_VIDEO_PAGE_ENDPOINT["url"]
+    assert request.method == FAKE_USER_VIDEO_PAGE_ENDPOINT["method"]
+    assert request.wbi is FAKE_USER_VIDEO_PAGE_ENDPOINT["wbi"]
+    assert request.verify is FAKE_USER_VIDEO_PAGE_ENDPOINT["verify"]
+    # The package's own description carries ``dm: True``; the adapter turns
+    # that off itself.
+    assert FAKE_USER_VIDEO_PAGE_ENDPOINT["dm"] is True
+    assert request.dm is False
+
+
+def test_user_video_page_request_follows_a_changed_package_endpoint(
+    bilibili_api_seam,
+):
+    """No transport field is hard-coded: the package description decides."""
+
+    bilibili_api_seam.user_video_page_endpoint["url"] = CHANGED_ENDPOINT_URL
+    bilibili_api_seam.user_video_page_endpoint["wbi"] = False
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    (request,) = bilibili_api_seam.api_requests
+    assert request.url == CHANGED_ENDPOINT_URL
+    assert request.wbi is False
 
 
 # -------------------------------------------------------------- video parts
@@ -658,6 +882,269 @@ def test_package_version_reports_installed_distribution(bilibili_api_seam, monke
     assert gateway.get_package_version() == "9.9.9"
 
 
+# ------------------------------------------------------- runtime HTTP backend
+
+
+def test_http_backend_declared_and_absent_from_pinned_package_requirements():
+    """The declared HTTP backend cannot arrive transitively from the pin.
+
+    ``bilibili-api-python==17.4.2`` publishes no HTTP client in
+    ``Requires-Dist`` and no extra carrying one, yet every request raises
+    ``ArgsException("尚未安装第三方请求库或未注册自定义第三方请求库")`` until
+    ``curl_cffi``, ``httpx``, or ``aiohttp`` is installed.  The pin is
+    spec-locked, so no version bump can supply the transport: the
+    application must declare the backend itself, and a fresh install without
+    that declaration can never reach the network.  This test fails if the
+    declaration is dropped, and the installed distribution's own metadata is
+    what proves the dependency is load-bearing rather than transitive.
+
+    Offline and deterministic: it reads this checkout's ``pyproject.toml``
+    and the installed distributions' metadata only.
+    """
+
+    project_root = pathlib.Path(__file__).resolve().parents[1]
+    pyproject = tomllib.loads(
+        (project_root / "pyproject.toml").read_text(encoding="utf-8")
+    )
+    declared_names = {
+        canonicalize_name(Requirement(raw).name)
+        for raw in pyproject["project"]["dependencies"]
+    }
+    assert HTTP_BACKEND_CANONICAL_NAME in declared_names, (
+        "the runtime HTTP backend must stay declared in"
+        f" [project].dependencies ({HTTP_BACKEND_CANONICAL_NAME} missing)"
+    )
+
+    try:
+        pinned_distribution = importlib.metadata.distribution(
+            PINNED_PACKAGE_DISTRIBUTION_NAME
+        )
+    except importlib.metadata.PackageNotFoundError as error:
+        pytest.fail(
+            "the packaging contract needs the pinned distribution installed to"
+            f" read its Requires-Dist ({error}); run uv sync first"
+        )
+
+    upstream_names = {
+        canonicalize_name(Requirement(raw).name)
+        for raw in pinned_distribution.requires or ()
+    }
+    transitive_clients = upstream_names & PACKAGE_HTTP_CLIENT_CANONICAL_NAMES
+    assert not transitive_clients, (
+        f"the pinned package now declares an HTTP client ({sorted(transitive_clients)});"
+        " re-check whether the explicit backend declaration and the rationale"
+        " above still hold"
+    )
+
+
+# --------------------------------------------- proxy resolution and application
+
+
+@pytest.fixture
+def empty_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
+    """Remove every proxy variable the adapter consults, ambient ones included."""
+
+    for name in PROXY_ENV_VARS:
+        monkeypatch.delenv(name, raising=False)
+
+
+@pytest.mark.parametrize("env_var", PROXY_ENV_VARS)
+def test_resolve_proxy_reads_every_locked_environment_level(env_var):
+    """Each variable of the locked chain resolves on its own."""
+
+    assert resolve_proxy(None, {env_var: PROXY_BOUNDARY_VALUE}) == PROXY_BOUNDARY_VALUE
+
+
+def test_resolve_proxy_follows_the_locked_precedence_ladder():
+    """The first set variable wins, proven level by level down the chain."""
+
+    environment = {
+        name: f"http://{index}.example.com:7890"
+        for index, name in enumerate(PROXY_ENV_VARS)
+    }
+
+    for higher_levels_cleared, expected_name in enumerate(PROXY_ENV_VARS):
+        remaining = {
+            name: value
+            for name, value in environment.items()
+            if PROXY_ENV_VARS.index(name) >= higher_levels_cleared
+        }
+        assert resolve_proxy(None, remaining) == environment[expected_name]
+
+
+def test_resolve_proxy_argument_outranks_the_whole_environment_chain():
+    """An explicit argument wins over every environment level."""
+
+    environment = {name: PROXY_BOUNDARY_VALUE for name in PROXY_ENV_VARS}
+
+    assert resolve_proxy("http://argument.example.com:7890", environment) == (
+        "http://argument.example.com:7890"
+    )
+
+
+@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
+def test_resolve_proxy_blank_values_are_unset_and_never_block_lower_levels(blank):
+    """A blank or whitespace-only value resolves nothing and shadows nothing."""
+
+    environment = {PROXY_ENV_VAR: blank, "HTTPS_PROXY": PROXY_BOUNDARY_VALUE}
+
+    assert resolve_proxy(blank, {PROXY_ENV_VAR: blank}) is None
+    assert resolve_proxy(blank, environment) == PROXY_BOUNDARY_VALUE
+
+
+def test_resolve_proxy_strips_surrounding_whitespace():
+    """A configured value is used without the whitespace around it."""
+
+    assert resolve_proxy(f"  {PROXY_BOUNDARY_VALUE}  ", {}) == PROXY_BOUNDARY_VALUE
+    assert (
+        resolve_proxy(None, {"ALL_PROXY": f"\t{PROXY_BOUNDARY_VALUE}\n"})
+        == PROXY_BOUNDARY_VALUE
+    )
+
+
+def test_resolve_proxy_without_any_setting_resolves_to_none():
+    """Nothing configured means no proxy; only the locked chain is consulted."""
+
+    assert resolve_proxy(None, {}) is None
+    # ``HTTP_PROXY`` is deliberately not part of the locked chain: the two
+    # upstream endpoints this adapter calls are HTTPS.
+    assert resolve_proxy(None, {"HTTP_PROXY": PROXY_BOUNDARY_VALUE}) is None
+
+
+def test_gateway_applies_the_resolved_proxy_once_before_the_first_call(
+    bilibili_api_seam, empty_proxy_environment
+):
+    """The proxy reaches the package settings exactly once, at construction."""
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway(proxy=PROXY_BOUNDARY_VALUE)
+
+    assert gateway.resolved_proxy == PROXY_BOUNDARY_VALUE
+    assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]
+    assert bilibili_api_seam.calls == []
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
+    # Apply-once: no request re-applies or re-reads the setting.
+    assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]
+
+
+def test_gateway_resolves_the_proxy_from_the_environment_without_an_argument(
+    bilibili_api_seam, empty_proxy_environment, monkeypatch
+):
+    """Without an argument the documented operator knob is applied."""
+
+    monkeypatch.setenv(PROXY_ENV_VAR, PROXY_BOUNDARY_VALUE)
+    gateway = _load_gateway()
+
+    assert gateway.resolved_proxy == PROXY_BOUNDARY_VALUE
+    assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]
+
+
+def test_gateway_argument_outranks_the_environment(
+    bilibili_api_seam, empty_proxy_environment, monkeypatch
+):
+    """An explicit argument wins over the whole environment chain."""
+
+    monkeypatch.setenv(PROXY_ENV_VAR, "http://environment.example.com:7890")
+    monkeypatch.setenv("HTTPS_PROXY", "http://fallback.example.com:7890")
+    gateway = _load_gateway(proxy=PROXY_BOUNDARY_VALUE)
+
+    assert gateway.resolved_proxy == PROXY_BOUNDARY_VALUE
+    assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]
+
+
+def test_gateway_skips_a_blank_environment_value(
+    bilibili_api_seam, empty_proxy_environment, monkeypatch
+):
+    """A blank BILI_HTTP_PROXY falls through to the standard host variable."""
+
+    monkeypatch.setenv(PROXY_ENV_VAR, "   ")
+    monkeypatch.setenv("HTTPS_PROXY", PROXY_BOUNDARY_VALUE)
+    gateway = _load_gateway()
+
+    assert gateway.resolved_proxy == PROXY_BOUNDARY_VALUE
+    assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]
+
+
+def test_gateway_leaves_the_package_setting_untouched_without_a_proxy(
+    bilibili_api_seam, empty_proxy_environment
+):
+    """Nothing resolved means no call into the package's request settings."""
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    assert gateway.resolved_proxy is None
+    assert bilibili_api_seam.applied_proxies == []
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
+    assert bilibili_api_seam.applied_proxies == []
+
+
+def test_gateway_proxy_stays_out_of_dtos_and_mapped_errors(
+    bilibili_api_seam, empty_proxy_environment
+):
+    """The resolved proxy never surfaces on a DTO or a mapped error."""
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway(
+        sessdata=SESSDATA_BOUNDARY_VALUE, proxy=PROXY_BOUNDARY_VALUE
+    )
+
+    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+    for surface in (repr(page), str(page)):
+        assert PROXY_BOUNDARY_VALUE not in surface
+        assert SESSDATA_BOUNDARY_VALUE not in surface
+    # A debug render of the adapter must not dump its configuration either.
+    assert PROXY_BOUNDARY_VALUE not in repr(gateway)
+    assert SESSDATA_BOUNDARY_VALUE not in repr(gateway)
+
+    bilibili_api_seam.videos_error = FakeNetworkException(503, UPSTREAM_ERROR_TEXT)
+    with pytest.raises(GatewayTransportError) as caught:
+        asyncio.run(gateway.get_user_video_page(MID, page_number=2))
+
+    assert PROXY_BOUNDARY_VALUE not in str(caught.value)
+    assert PROXY_BOUNDARY_VALUE not in repr(caught.value)
+
+
+def test_gateway_proxy_stays_out_of_persisted_rows(
+    bilibili_api_seam, empty_proxy_environment, tmp_root
+):
+    """A full collection run persists no proxy value and no credential."""
+
+    bilibili_api_seam.videos_response = make_videos_response(
+        make_vlist_item(aid=None, sessdata_note=SESSDATA_BOUNDARY_VALUE), count=1
+    )
+    bilibili_api_seam.info_response = make_detail_response()
+    bilibili_api_seam.parts_response = [make_part_item()]
+    gateway = _load_gateway(
+        sessdata=SESSDATA_BOUNDARY_VALUE, proxy=PROXY_BOUNDARY_VALUE
+    )
+    connection = open_database(os.path.join(tmp_root, "proxy-hygiene.sqlite"))
+    try:
+        repository = MetadataRepository(connection)
+        result = MetadataIngestor(gateway, repository).collect_user_pages(
+            MID, start_page=1, page_limit=1
+        )
+
+        assert result.outcome == "limited"
+        assert repository.list_pending_parts()
+        persisted = persisted_row_text(connection)
+    finally:
+        connection.close()
+
+    assert_leaks_no_markers(persisted, context="persisted rows")
+    assert PROXY_BOUNDARY_VALUE not in persisted
+    assert SESSDATA_BOUNDARY_VALUE not in persisted
+    for surface in (repr(result), str(result)):
+        assert PROXY_BOUNDARY_VALUE not in surface
+        assert SESSDATA_BOUNDARY_VALUE not in surface
+
+
 # ------------------------------------------------------- DTO self-validation
 
 
@@ -824,7 +1311,9 @@ def test_gateway_source_never_names_forbidden_seam_methods():
 
     assert forbidden_hits == []
     # Positive control: the scan sees the documented metadata attribute calls.
-    assert {"get_videos", "get_pages", "get_info"} <= attribute_names
+    assert {"get_access_id", "update_params", "get_pages", "get_info"} <= (
+        attribute_names
+    )
 
 
 def test_fake_seam_exposes_only_documented_metadata_surface():
@@ -833,12 +1322,23 @@ def test_fake_seam_exposes_only_documented_metadata_surface():
     modules = build_fake_package(FakeUpstreamScript())
     package = modules["bilibili_api"]
 
-    assert _public_names(modules["bilibili_api.user"]) == ["User"]
+    assert _public_names(modules["bilibili_api.user"]) == ["API", "User", "VideoOrder"]
     assert _public_names(modules["bilibili_api.video"]) == ["Video"]
+    assert _public_names(modules["bilibili_api.utils.network"]) == ["Api"]
     assert _public_names(modules["bilibili_api.exceptions"]) == sorted(
         ALLOWED_EXCEPTION_NAMES
     )
-    assert _public_names(package) == ["Credential", "exceptions", "user", "video"]
+    assert _public_names(modules["bilibili_api.request_settings"]) == [
+        "get_proxy",
+        "set_proxy",
+    ]
+    assert _public_names(package) == [
+        "Credential",
+        "exceptions",
+        "request_settings",
+        "user",
+        "video",
+    ]
     assert _public_names(package.Credential) == []
 
     user = package.user.User(uid=MID)
@@ -857,6 +1357,10 @@ def test_fake_seam_exposes_only_documented_metadata_surface():
             getattr(user, surface_name)
         with pytest.raises(AttributeError):
             getattr(video, surface_name)
+    # The page delegate the risk-control-safe shape replaces is gone, so a
+    # regression to it fails loudly instead of passing through the seam.
+    with pytest.raises(AttributeError):
+        user.get_videos
 
 
 def test_gateway_dto_drops_unknown_upstream_payload_fields(bilibili_api_seam):
@@ -884,7 +1388,7 @@ def test_gateway_dto_drops_unknown_upstream_payload_fields(bilibili_api_seam):
         assert_leaks_no_markers(repr(surface), context="gateway DTO repr")
         assert_leaks_no_markers(str(surface), context="gateway DTO str")
     assert bilibili_api_seam.calls == [
-        "user.get_videos(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=30)",
         "video.get_info",
         "video.get_pages",
     ]
@@ -911,7 +1415,7 @@ def test_live_smoke_single_public_page_for_archive_owner(tmp_root):
     """Opt-in live probe: ONE public metadata page for UID 23191782.
 
     Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The probe
-    requests exactly one bounded page (``ps=100``) for the archive owner
+    requests exactly one bounded page (``ps=30``) for the archive owner
     through the real adapter, ingests it into a fresh temporary SQLite
     database, calls no subtitle/playback/audio/ASR/export endpoint,
     requires no credential, and keeps every raw upstream payload
diff --git a/bilibili-asr-archive/tests/test_live_metadata_smoke.py b/bilibili-asr-archive/tests/test_live_metadata_smoke.py
index fc9823d..4b1a928 100644
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
@@ -127,30 +129,48 @@ def _assert_no_credential_or_playback_leaks(
         )
 
 
-def _assert_collected_page_rows(connection, mid: int) -> None:
-    """Assert the normalized evidence a successful one-page run leaves."""
+def _assert_collected_page_rows(connection, mid: int) -> str:
+    """Assert the normalized evidence a successful one-page run leaves.
+
+    The successful run is terminal (``limited`` on the explicit page bound
+    with a non-empty page, ``complete`` on an empty one) and leaves exactly
+    one page-evidence row, the user row, one video row per collected video
+    with one run/page discovery row each, at least one part row in aggregate
+    over the collected page (not one per video: an individual video may have
+    no parts upstream), and a cursor that advanced past the committed page.
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
@@ -161,9 +181,18 @@ def _assert_collected_page_rows(connection, mid: int) -> None:
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
@@ -174,14 +203,31 @@ def _assert_collected_page_rows(connection, mid: int) -> None:
     observed_total = cursor_row["observed_total"]
     if run_row["outcome"] == "limited":
         assert video_count >= 1
+        # The page carries at least one part in aggregate (parts are fetched
+        # for every collected video; an individual video may legitimately have
+        # no parts upstream, so this is deliberately not a per-video claim),
+        # and each collected video is recorded once as discovered on this page.
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
@@ -241,9 +287,10 @@ def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
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
@@ -268,7 +315,10 @@ def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
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
@@ -278,6 +328,8 @@ def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
                 " a bounded run record); rerun to capture the failure shape"
             )
         error_code = _assert_bounded_failure_rows(connection, LIVE_SMOKE_MID)
+        # The bounded scalar code only: no output text, no upstream payload.
+        print(f"live smoke evidence: exit=2 error_code={error_code}")
         assert error_code in err
         assert "metadata gateway failure" in err
         # Same resolution rule as ``resolve_sessdata``: a missing or blank
@@ -285,11 +337,13 @@ def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
         if not os.environ.get(SESSDATA_ENV_VAR):
             pytest.skip(
                 "live smoke ended in the documented bounded anonymous"
-                f" rejection (error_code={error_code!r}, exit 2): upstream"
-                " anti-bot control currently rejects no-credential metadata"
-                " access; this is the expected no-credential behavior, not a"
-                " defect. Provide a credential via --sessdata or"
-                f" {SESSDATA_ENV_VAR} for the happy-path run."
+                f" rejection (error_code={error_code!r}, exit 2): without a"
+                " credential the run is anonymous, and upstream rejects some"
+                " anonymous metadata access; the smoke accepts this bounded"
+                " no-credential outcome rather than treating it as a defect."
+                f" Provide a credential via {SESSDATA_ENV_VAR} in the"
+                " environment for the happy-path run; this smoke builds its"
+                " own argv, so its --sessdata flag is never passed."
             )
         pytest.fail(
             "live smoke ended in a bounded upstream failure despite an"
@@ -350,7 +404,12 @@ def test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam(
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
diff --git a/bilibili-asr-archive/tests/test_metadata_cli.py b/bilibili-asr-archive/tests/test_metadata_cli.py
index 854fc5c..4564e8d 100644
--- a/bilibili-asr-archive/tests/test_metadata_cli.py
+++ b/bilibili-asr-archive/tests/test_metadata_cli.py
@@ -341,9 +341,9 @@ def test_fetch_meta_creates_fresh_database_and_completes(
     # page fetch, one parts fetch, one empty-page fetch (aid present, so no
     # detail call).
     assert bilibili_api_seam.calls == [
-        "user.get_videos(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=30)",
         "video.get_pages",
-        "user.get_videos(pn=2, ps=100)",
+        "space.arc.search(pn=2, ps=30)",
     ]
 
 
@@ -379,8 +379,8 @@ def test_fetch_meta_limit_pages_stops_limited_exit_zero(
     finally:
         connection.close()
     assert [
-        call for call in bilibili_api_seam.calls if call.startswith("user.get_videos")
-    ] == ["user.get_videos(pn=1, ps=100)"]
+        call for call in bilibili_api_seam.calls if call.startswith("space.arc.search")
+    ] == ["space.arc.search(pn=1, ps=30)"]
 
 
 def test_fetch_meta_start_page_overrides_cursor(
@@ -398,7 +398,7 @@ def test_fetch_meta_start_page_overrides_cursor(
     assert main(["fetch-meta", "--archive-root", tmp_root, "--start-page", "1"]) == 0
 
     # Page 1 was requested again even though the stored cursor pointed at 2.
-    assert bilibili_api_seam.calls.count("user.get_videos(pn=1, ps=100)") == 2
+    assert bilibili_api_seam.calls.count("space.arc.search(pn=1, ps=30)") == 2
     connection = open_database(tmp_root)
     try:
         start_pages = [
@@ -432,7 +432,7 @@ def test_fetch_meta_without_flags_resumes_from_stored_cursor(
 
     # Page 1 was not refetched: the run resumed at the cursor's page 2,
     # while run 1's own completion check already touched page 2.
-    assert bilibili_api_seam.calls.count("user.get_videos(pn=1, ps=100)") == 1
+    assert bilibili_api_seam.calls.count("space.arc.search(pn=1, ps=30)") == 1
     connection = open_database(tmp_root)
     try:
         start_pages = [
diff --git a/bilibili-asr-archive/tests/test_metadata_e2e.py b/bilibili-asr-archive/tests/test_metadata_e2e.py
index 781263a..4cf068d 100644
--- a/bilibili-asr-archive/tests/test_metadata_e2e.py
+++ b/bilibili-asr-archive/tests/test_metadata_e2e.py
@@ -302,10 +302,10 @@ def test_fetch_meta_normalizes_single_part_and_multipart_videos_end_to_end(
     # page fetch, one parts fetch per distinct video, then the completing
     # empty-page fetch (aids present, so no detail calls).
     assert script.calls == [
-        "user.get_videos(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=30)",
         "video.get_pages",
         "video.get_pages",
-        "user.get_videos(pn=2, ps=100)",
+        "space.arc.search(pn=2, ps=30)",
     ]
     assert_only_documented_metadata_calls(script.calls)
 
@@ -440,7 +440,7 @@ def test_fetch_meta_rerun_of_same_page_stores_no_duplicate_rows(
     assert "sessdata: present" in out
     assert_leaks_no_markers(out + err, context="fetch-meta re-run output")
     # Page 1 was fetched exactly twice: once per run.
-    assert script.calls.count("user.get_videos(pn=1, ps=100)") == 2
+    assert script.calls.count("space.arc.search(pn=1, ps=30)") == 2
 
     for relative in LEGACY_SIDECAR_PATHS:
         assert not os.path.exists(os.path.join(tmp_root, relative))
@@ -572,11 +572,11 @@ def test_fetch_meta_failed_page_preserves_cursor_and_resume_succeeds(
     # The full call trace: bounded page fetches, one parts fetch per new
     # video, the failed resume page, then the successful resume.
     assert script.calls == [
-        "user.get_videos(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=30)",
         "video.get_pages",
-        "user.get_videos(pn=2, ps=100)",
-        "user.get_videos(pn=2, ps=100)",
+        "space.arc.search(pn=2, ps=30)",
+        "space.arc.search(pn=2, ps=30)",
         "video.get_pages",
-        "user.get_videos(pn=3, ps=100)",
+        "space.arc.search(pn=3, ps=30)",
     ]
     assert_only_documented_metadata_calls(script.calls)
diff --git a/bilibili-asr-archive/tests/test_metadata_ingest.py b/bilibili-asr-archive/tests/test_metadata_ingest.py
index 5a767ae..a89bf8f 100644
--- a/bilibili-asr-archive/tests/test_metadata_ingest.py
+++ b/bilibili-asr-archive/tests/test_metadata_ingest.py
@@ -701,7 +701,7 @@ def test_bilibili_api_gateway_run_persists_normalized_rows(tmp_root, bilibili_ap
         # The pinned adapter drove exactly the three documented upstream
         # calls: one page fetch, the aid completion, one parts fetch.
         assert script.calls == [
-            "user.get_videos(pn=1, ps=100)",
+            "space.arc.search(pn=1, ps=30)",
             "video.get_info",
             "video.get_pages",
         ]
@@ -849,7 +849,7 @@ def test_bilibili_api_gateway_foreign_owner_page_requests_no_parts(
         assert [tuple(row) for row in page_rows] == [(1, "failed", "shape_error")]
 
         # Exactly one page fetch: no parts, no detail, nothing else.
-        assert script.calls == ["user.get_videos(pn=1, ps=100)"]
+        assert script.calls == ["space.arc.search(pn=1, ps=30)"]
         assert_only_documented_metadata_calls(script.calls)
     finally:
         connection.close()
@@ -914,7 +914,7 @@ def test_malformed_upstream_bvid_page_fails_bounded_and_preserves_the_prior_curs
             (2, "failed", "shape_error")
         ]
         # The malformed bvid never reached the parts or detail fetches.
-        assert script.calls == calls_after_first + ["user.get_videos(pn=2, ps=100)"]
+        assert script.calls == calls_after_first + ["space.arc.search(pn=2, ps=30)"]
     finally:
         connection.close()
 
diff --git a/bilibili-asr-archive/uv.lock b/bilibili-asr-archive/uv.lock
index 7a0db3e..7f899f0 100644
--- a/bilibili-asr-archive/uv.lock
+++ b/bilibili-asr-archive/uv.lock
@@ -85,6 +85,7 @@ version = "0.1.0"
 source = { editable = "." }
 dependencies = [
     { name = "bilibili-api-python" },
+    { name = "curl-cffi" },
     { name = "requests" },
 ]
 
@@ -101,6 +102,7 @@ dev = [
 [package.metadata]
 requires-dist = [
     { name = "bilibili-api-python", specifier = "==17.4.2" },
+    { name = "curl-cffi", specifier = ">=0.16" },
     { name = "funasr", marker = "extra == 'asr'", specifier = ">=1.2" },
     { name = "packaging", marker = "extra == 'dev'", specifier = ">=24" },
     { name = "pytest", marker = "extra == 'dev'", specifier = ">=8" },
@@ -478,6 +480,39 @@ wheels = [
     { url = "https://files.pythonhosted.org/packages/99/89/87ef49ffe383ef4e147d27b7bf2088fb0b54ea409dd87b5a89442e5828a5/cryptography-50.0.1-cp39-abi3-win_amd64.whl", hash = "sha256:55d16b1ef3ee0958d893a977b19777887e546c9954ea81b200c3301a864013f2", size = 3875429, upload-time = "2026-08-25T19:45:24.418Z" },
 ]
 
+[[package]]
+name = "curl-cffi"
+version = "0.16.3"
+source = { registry = "https://pypi.org/simple" }
+dependencies = [
+    { name = "certifi" },
+    { name = "cffi" },
+]
+sdist = { url = "https://files.pythonhosted.org/packages/82/e1/730125c43e3e331d98e17af3cb310ba526b3f1101b7635ca23d976ebfcf5/curl_cffi-0.16.3.tar.gz", hash = "sha256:d15d0c2a35f2d75bec430c28946c2a833f421c85773bdb0795182cc5c515665b", size = 239020, upload-time = "2026-09-02T11:58:23.266Z" }
+wheels = [
+    { url = "https://files.pythonhosted.org/packages/79/7a/ec08ef0665c4ef4ea76b47042eb1c043e4afb374d8b9218e00272c9e73a2/curl_cffi-0.16.3-cp310-abi3-macosx_10_9_x86_64.whl", hash = "sha256:0f1f6878863fba393801e4d59b2f2766d1983b5c9d9dfa11d4becfd6a74cc937", size = 3025646, upload-time = "2026-09-02T11:57:39.326Z" },
+    { url = "https://files.pythonhosted.org/packages/4c/86/e21b8ed384db26401a4438f20f01c7bcd9c3a6f8ceede458344e2d62775c/curl_cffi-0.16.3-cp310-abi3-macosx_11_0_arm64.whl", hash = "sha256:f3b63da797912bc82911e34dfe449725514e4281527fb516931fc457087cfb44", size = 2784023, upload-time = "2026-09-02T11:57:40.986Z" },
+    { url = "https://files.pythonhosted.org/packages/97/2d/25b106e64178829be1ce171b6cd45ba354ab7a2a5169001866b38d4c440f/curl_cffi-0.16.3-cp310-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.whl", hash = "sha256:d5a4103f2baa1fcf619ec3101b419827d367044ba106b206228137cc71a5a9c5", size = 12834219, upload-time = "2026-09-02T11:57:42.711Z" },
+    { url = "https://files.pythonhosted.org/packages/e7/dd/db27a521777d0cf00f9a1554453ae730539dd134bca108d8df256a85c91e/curl_cffi-0.16.3-cp310-abi3-manylinux2014_i686.manylinux_2_17_i686.whl", hash = "sha256:f2795f0ef2e8cc0e6d702e52367af6600f5bcf10e44d683e256254adc7e3589f", size = 12655304, upload-time = "2026-09-02T11:57:45.334Z" },
+    { url = "https://files.pythonhosted.org/packages/72/01/2bbf141baa0fc3921d31a90de5465b7a94188845a8fe84dee86bf7bd90f1/curl_cffi-0.16.3-cp310-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl", hash = "sha256:a875a661e2f9a949be29454880bbb9553307a487c4c08819738298cf5c1622e2", size = 13484311, upload-time = "2026-09-02T11:57:47.58Z" },
+    { url = "https://files.pythonhosted.org/packages/bb/d4/745ca299a2a223ee18574ec7cff75de620a92ce69b3cb09490db8fba614b/curl_cffi-0.16.3-cp310-abi3-manylinux_2_28_armv7l.manylinux_2_31_armv7l.whl", hash = "sha256:0851e710608122a2716bdee35788bbd7e9d4a0fd42899b2bca9181277095af8e", size = 12840616, upload-time = "2026-09-02T11:57:50.016Z" },
+    { url = "https://files.pythonhosted.org/packages/5e/bf/98d72d7a081cc155a71ab66bde6a18640d4ac5d4f6766f729a92cb4257c0/curl_cffi-0.16.3-cp310-abi3-manylinux_2_34_riscv64.manylinux_2_39_riscv64.whl", hash = "sha256:1d7e553442cefec100dfd1fca4ae7035ab6c094457244bf60a38670b8ac8185d", size = 12612602, upload-time = "2026-09-02T11:57:52.584Z" },
+    { url = "https://files.pythonhosted.org/packages/36/cf/2fdaff71fd6f39c5994495af8378e6e26bca8e447d94d2f75a76337908c8/curl_cffi-0.16.3-cp310-abi3-musllinux_1_2_aarch64.whl", hash = "sha256:60621b3f561346046dd62be33abfb50c8b88a8007699d6b11d39ad4755312c4a", size = 12588697, upload-time = "2026-09-02T11:57:55.138Z" },
+    { url = "https://files.pythonhosted.org/packages/74/55/68c399019bc24ea6ac783c98139a2555f88589631f3d127fe6b9073f019b/curl_cffi-0.16.3-cp310-abi3-musllinux_1_2_x86_64.whl", hash = "sha256:20a7b1b473371cfaf2118958034977e457c6fa279fbd11543c9e0ab58be9eedd", size = 13253555, upload-time = "2026-09-02T11:57:57.524Z" },
+    { url = "https://files.pythonhosted.org/packages/9b/72/1732a24ef4a2aeba994b80ec163debe8deda403c07e4abbc0443bca078b8/curl_cffi-0.16.3-cp310-abi3-win_amd64.whl", hash = "sha256:fe87b66e324ed7318166698e02169f3208dbda32b872a27d2bc61a9c19b335eb", size = 1978602, upload-time = "2026-09-02T11:58:00.033Z" },
+    { url = "https://files.pythonhosted.org/packages/45/bb/67bec3132aeabac99dfe2f299a9b43dcb5de23ad96219ee98516d177fc9c/curl_cffi-0.16.3-cp310-abi3-win_arm64.whl", hash = "sha256:5a2ba880019f9e5a9e8f38ae22de6e4ea4c8d34a51ae4f1a2fce962c7b632006", size = 1713140, upload-time = "2026-09-02T11:58:01.558Z" },
+    { url = "https://files.pythonhosted.org/packages/49/e3/b88f9b1a60a1e29b42e9371c1b3f4fdd83bf8177fcf863df67438da12693/curl_cffi-0.16.3-cp313-cp313-android_24_arm64_v8a.whl", hash = "sha256:01c31369b1c8063c7e459152c508c90de7a4218aa66ee3a1f575ae37ce44bc5a", size = 8607348, upload-time = "2026-09-02T11:58:03.095Z" },
+    { url = "https://files.pythonhosted.org/packages/fb/f4/3dedff1a31c93a9b18acaa346e23832c29bc18075138e90e9af795188e5e/curl_cffi-0.16.3-cp314-cp314-android_24_arm64_v8a.whl", hash = "sha256:0c8b70191dc88ea770a5c39d7e213bff1606e248c13566777e6527f0d8cf96ec", size = 8607323, upload-time = "2026-09-02T11:58:05.099Z" },
+    { url = "https://files.pythonhosted.org/packages/73/b7/99708ed83c11132ec0311a28ed46fe1cd10e8cb6ecd3c82f01f1f80c3c2c/curl_cffi-0.16.3-cp314-cp314t-macosx_10_15_x86_64.whl", hash = "sha256:8055ec9d7c15237747be254739c40057e3684f56854e95c12aaf3c95838ba2d6", size = 3026149, upload-time = "2026-09-02T11:58:06.973Z" },
+    { url = "https://files.pythonhosted.org/packages/5d/d5/6c0400fb64097c4662da4e5d2d1e7daa8027d1431b1c8880c0f8f2051ae1/curl_cffi-0.16.3-cp314-cp314t-macosx_11_0_arm64.whl", hash = "sha256:391096e903ec98b909bb355e008ec7c211d710b6a23663a7f1f10aa54a027538", size = 2784153, upload-time = "2026-09-02T11:58:08.726Z" },
+    { url = "https://files.pythonhosted.org/packages/87/a4/3c8702d25e21f420e88707701af15006e72a2a2b9f3fa419c7c80ce7451c/curl_cffi-0.16.3-cp314-cp314t-manylinux2014_aarch64.manylinux_2_17_aarch64.whl", hash = "sha256:6cef43f248b3635de9b82337e0ed2c7403aa1506e51587144d552702eb9d0775", size = 12839612, upload-time = "2026-09-02T11:58:10.745Z" },
+    { url = "https://files.pythonhosted.org/packages/be/bf/44a7e7a1e309136a1b086332feb03c7718169af550bdbf7eab52ae0497e0/curl_cffi-0.16.3-cp314-cp314t-manylinux2014_x86_64.manylinux_2_17_x86_64.whl", hash = "sha256:e1fffac4b5a02c5ec74d184d668c5b882f80fa1d961e7adba6e1755877af41e1", size = 13488945, upload-time = "2026-09-02T11:58:13.15Z" },
+    { url = "https://files.pythonhosted.org/packages/52/83/5321d5fb67ff16195fb0c3bd5434be4532c85967c80546092a1cf3654cc9/curl_cffi-0.16.3-cp314-cp314t-musllinux_1_2_aarch64.whl", hash = "sha256:849026be5b36cf7b95d5fce63a84aa7b17248e83b4374e67715e7387ca2be50c", size = 12592235, upload-time = "2026-09-02T11:58:15.58Z" },
+    { url = "https://files.pythonhosted.org/packages/12/aa/0b4e110729a86b434196d15e2e2839d992a9b8f3003f0569c77e27a9faca/curl_cffi-0.16.3-cp314-cp314t-musllinux_1_2_x86_64.whl", hash = "sha256:82cc688349c8e8955d346cc5cc7759b68742edc587ae47ba5783a096502a7a92", size = 13259593, upload-time = "2026-09-02T11:58:17.971Z" },
+    { url = "https://files.pythonhosted.org/packages/4c/3a/e4f199cfc9f131411543aacdf6811d8b72b81ce6ac6e9f6ddffecfc31e54/curl_cffi-0.16.3-cp314-cp314t-win_amd64.whl", hash = "sha256:72376595490c4822ad1a5360adb568660ca66dff4ba2c2de2912778c15f43edb", size = 2031033, upload-time = "2026-09-02T11:58:19.949Z" },
+    { url = "https://files.pythonhosted.org/packages/18/8f/9354e5552982d38abd3ce2db859f049fee6bff0eee4e25aacaaa2b29f0b4/curl_cffi-0.16.3-cp314-cp314t-win_arm64.whl", hash = "sha256:b450fad876aa9f9ed3edfb6e3a48a8c28eafa66aae634eff17800a8b5006568d", size = 1782234, upload-time = "2026-09-02T11:58:21.629Z" },
+]
+
 [[package]]
 name = "decorator"
 version = "5.3.1"
```
