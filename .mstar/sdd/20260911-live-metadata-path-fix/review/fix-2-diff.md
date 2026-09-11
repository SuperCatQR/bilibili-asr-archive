# Fix Wave 2 Diff — 20260911-live-metadata-path-fix

Base: `5667844`
Head: `a898fdf`
Scope: plan QC tri actionable suggestions (tests + docs only; behaviour-free)

```diff
diff --git a/.env.example b/.env.example
index 337de50..d74d655 100644
--- a/.env.example
+++ b/.env.example
@@ -11,7 +11,8 @@
 # 生命周期：Cookie 会过期，过期后在 .env 里重抄一次即可。
 #
 
-# —— 凭据（可选；不填则匿名访问，匿名会被上游风控拦截，元数据采集返回有界 response_error）——
+# —— 凭据（可选；不填则匿名访问：匿名元数据采集被上游风控拦截时以有界 rate_limited 结束，
+#    其他上游失败为有界 response_error；口径与 README、docs/metadata-storage.md 一致）——
 # BILI_SESSDATA='你的_SESSDATA_Cookie_值'
 
 # —— HTTP 代理（可选；直连 B 站不通或被风控时需要）——
diff --git a/bilibili-asr-archive/README.md b/bilibili-asr-archive/README.md
index e6c3904..d044657 100644
--- a/bilibili-asr-archive/README.md
+++ b/bilibili-asr-archive/README.md
@@ -506,11 +506,13 @@ only restart path.
 
 - **Default page bound**: `--limit-pages` is optional and defaults to
   `DEFAULT_PAGE_LIMIT = 10`. The canonical command above therefore stops
-  after 10 pages (the ingestor's page size is 30), ends the run `limited`,
-  and still exits 0 — a limited run is never claimed as complete. A full
-  archive walk is a series of resumable runs: re-run the same command to
-  continue from the stored cursor, or pass an explicit `--limit-pages` for
-  a longer slice.
+  after 10 pages (the ingestor's page size is 30 — the upstream-accepted
+  default, `ps=30`; larger page sizes are not guaranteed, and an explicit
+  programmatic override is forwarded rather than clamped or rejected: there is
+  no CLI flag for it), ends the run `limited`, and still exits 0 — a limited
+  run is never claimed as complete. A full archive walk is a series of
+  resumable runs: re-run the same command to continue from the stored cursor,
+  or pass an explicit `--limit-pages` for a longer slice.
 - **Resume semantics**: without `--resume` or `--start-page`, a run continues
   from the stored cursor when one exists and starts at page 1 otherwise.
   `--resume` requires a stored cursor and exits `1` when there is none;
@@ -536,6 +538,9 @@ only restart path.
   gateway resolves the knob itself in the order constructor argument →
   `BILI_HTTP_PROXY` → `HTTPS_PROXY`/`https_proxy` → `ALL_PROXY`/`all_proxy`,
   treats a blank value as unset, and forces no proxy when nothing resolves.
+  The resolved value is applied to the package's process-global settings, and
+  a blank value cannot override a host-level variable — forcing direct access
+  means unsetting those variables for the process (there is no in-app switch).
   Details: [docs/metadata-storage.md](docs/metadata-storage.md).
 
 | Exit | Meaning |
@@ -595,8 +600,9 @@ anonymous metadata access the smoke verifies the bounded-failure evidence
 (terminal run row, one scalar page row with a `rate_limited` /
 `response_error` code, no entity or discovery growth, no cursor row) and
 reports that bounded no-credential outcome as a reasoned skip rather than a
-defect. Expectations and the underlying transport/proxy requirements are
-documented in [docs/metadata-storage.md](docs/metadata-storage.md).
+defect; any other bounded code fails the smoke loudly. Expectations and the
+underlying transport/proxy requirements are documented in
+[docs/metadata-storage.md](docs/metadata-storage.md).
 
 ### Mixed batch outcomes
 
diff --git a/bilibili-asr-archive/docs/metadata-storage.md b/bilibili-asr-archive/docs/metadata-storage.md
index 42115c1..376fa12 100644
--- a/bilibili-asr-archive/docs/metadata-storage.md
+++ b/bilibili-asr-archive/docs/metadata-storage.md
@@ -112,6 +112,20 @@ and the gateway spec define them. The bounded error taxonomy is unchanged:
 `not_found`, shape problems to `shape_error`, and other upstream failures to
 `response_error`/`transport_error`.
 
+### Page size
+
+The adapter and the `BilibiliGateway` protocol default `page_size` to **30**,
+and the shipped service path passes that same value explicitly
+(`PAGE_SIZE = 30` in `src/bili_asr/services/metadata_ingest.py`); it is also the
+pinned package's own documented `ps` value. Larger page sizes are **not**
+guaranteed: with the same credential, proxy, and call shape, `ps=30` and
+`ps=50` were answered with `code=0` while `ps=100` was rejected (HTTP 412 on
+direct probes, JSON code `-400` on production runs). The adapter forwards an
+explicit `page_size` override upstream unchanged — it neither clamps nor
+rejects it — so an over-large override surfaces as the upstream bounded code
+(`rate_limited`/`response_error`) rather than as a caller error. There is no
+CLI flag for the page size.
+
 ## HTTP proxy
 
 The pinned client builds its session with an explicitly empty proxy
@@ -132,6 +146,17 @@ When nothing resolves, the library default is left untouched and no proxy is
 forced. A proxy URL is configuration, not a credential, and is never written
 to DTOs, logs, exception messages, or persisted rows.
 
+Two consequences of that design matter when troubleshooting:
+
+- The resolved value is applied to the package's **process-global** request
+  settings, so it is the effective proxy for every gateway in the process, not
+  only for the instance that resolved it.
+- A blank value counts as *unset*, so `BILI_HTTP_PROXY=""` cannot override a
+  host-level `HTTPS_PROXY`/`ALL_PROXY`. There is no in-app "no proxy" switch:
+  forcing a direct connection means unsetting every variable of the chain
+  (`BILI_HTTP_PROXY`, `HTTPS_PROXY`, `https_proxy`, `ALL_PROXY`, `all_proxy`)
+  for the process before the command runs.
+
 ```
 export BILI_HTTP_PROXY=http://127.0.0.1:7890
 bili-asr fetch-meta --mid 23191782 --limit-pages 1 --archive-root archive
@@ -204,7 +229,8 @@ of an explicit `export` (the gateway reads the same environment).
   scalar code — `rate_limited`, or `response_error` for other upstream
   failures — no video/part/discovery growth, no cursor row). That bounded
   no-credential outcome is reported as a reasoned skip, after its assertions
-  ran, not as a defect.
+  ran, not as a defect; any other bounded code — a `transport_error` from a
+  dead proxy, for instance — fails the smoke loudly, credential or not.
 - **Observed on 2026-09-11** (this host, proxy configured): the live run was
   refused by upstream risk control. The CLI's one production page (the
   then-shipped page size of 100) ended twice — before and after a cooldown —
@@ -224,6 +250,12 @@ of an explicit `export` (the gateway reads the same environment).
   size is therefore the value upstream accepts: `PAGE_SIZE = 30` in
   `src/bili_asr/services/metadata_ingest.py`, which is also the pinned
   package's own documented `ps` value.
+- **Achieved on 2026-09-11 (same day, after the page-size fix):** the shipped
+  path completed a real end-to-end live run — CLI exit 0, one collected page,
+  `outcome=limited videos=30 parts=33 discoveries=30`, `observed_total=1691`,
+  and the cursor advanced to `next_page=2` with state `limited`. Count-only:
+  no credential, no proxy, and no collected metadata value is recorded here.
+  The intermittency noted above still applies to a fresh run.
 
 ## Exit codes
 
diff --git a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
index c3328f8..d0e308a 100644
--- a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
+++ b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
@@ -61,7 +61,10 @@ GATEWAY_ADAPTER_MODULE = "bili_asr.sources.bilibili_api_gateway"
 #: (``bilibili_api.user.API["info"]["video"]``), mirroring the pinned
 #: distribution literally — including ``dm: True``.  The adapter must take
 #: ``url``/``method``/``verify``/``wbi`` from it and override ``dm``, so a
-#: package-side change to any of those fields stays visible here.
+#: package-side change to any of those fields stays visible here.  The mirror
+#: itself is not taken on trust: the offline parity test in
+#: ``tests/test_bilibili_api_gateway.py`` compares it against the installed
+#: pinned distribution it claims to mirror.
 FAKE_USER_VIDEO_PAGE_ENDPOINT = {
     "url": "https://api.bilibili.com/x/space/wbi/arc/search",
     "method": "GET",
@@ -79,6 +82,13 @@ FAKE_USER_VIDEO_PAGE_ENDPOINT = {
     "comment": "搜索用户视频",
 }
 
+#: The endpoint-description fields the adapter reads from the package's own
+#: description (``dm`` is the one field it overrides).  The offline mirror
+#: parity test compares exactly these against the installed distribution, so
+#: a pin that renames, drops, or flips one of them fails there instead of
+#: surfacing only live.
+MIRRORED_ENDPOINT_FIELDS = ("url", "method", "verify", "wbi")
+
 #: The exact upstream call names the gateway adapter may issue.  The page call
 #: is recorded as ``space.arc.search`` because the adapter issues that request
 #: itself through the package's ``Api``: the package's ``User.get_videos``
@@ -294,8 +304,14 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
 
     request_settings_mod = types.ModuleType("bilibili_api.request_settings")
 
-    def set_proxy(proxy: str = "") -> None:
-        """Mirror of ``request_settings.set_proxy``; records the applied value."""
+    def set_proxy(proxy: str) -> None:
+        """Mirror of ``request_settings.set_proxy``; records the applied value.
+
+        The pinned ``RequestSettings.set_proxy(self, proxy: str)`` has no
+        default, so neither does this double: a no-argument call must fail
+        offline exactly where it would fail live (``TypeError``) instead of
+        passing here and breaking against the real package.
+        """
 
         script.applied_proxies.append(proxy)
 
@@ -602,6 +618,7 @@ __all__ = [
     "FakeWbiRetryTimesExceedException",
     "GATEWAY_ADAPTER_MODULE",
     "MID",
+    "MIRRORED_ENDPOINT_FIELDS",
     "NO_LEAK_MARKERS",
     "PUBDATE",
     "RAW_JSON_BODY_MARKER",
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index f759143..cf33c46 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -52,6 +52,7 @@ from fixtures.fake_bilibili_gateway import (
     BVID,
     FAKE_USER_VIDEO_PAGE_ENDPOINT,
     MID,
+    MIRRORED_ENDPOINT_FIELDS,
     PUBDATE,
     RAW_JSON_BODY_MARKER,
     SESSDATA_BOUNDARY_VALUE,
@@ -115,6 +116,74 @@ ACCESS_ID_BOUNDARY_VALUE = "ACCESS-ID-THAT-MUST-NOT-LEAK"
 #: package's own endpoint description instead of being hard-coded.
 CHANGED_ENDPOINT_URL = "https://changed-endpoint.example.invalid/x/space/wbi/arc/search"
 
+
+def _probe_installed_pinned_endpoint() -> dict | str:
+    """Read the pin's endpoint description, or the reason it could not be read.
+
+    Runs once, at module import time — before any seam fixture can install the
+    fake ``bilibili_api`` package on ``sys.modules``: a lazy import inside a
+    seam test would return the fake, and the mirror would then be compared
+    against itself.  The description is pure package data, so this needs no
+    network.  A string return is a human-readable reason (distribution absent,
+    key renamed, unexpected shape) that the parity tests turn into a loud
+    failure with install guidance.
+    """
+
+    try:
+        module = importlib.import_module("bilibili_api.user")
+        endpoint = module.API["info"]["video"]
+    except (ImportError, KeyError, AttributeError, TypeError) as error:
+        return f"{type(error).__name__}: {error}"
+    if not isinstance(endpoint, dict):
+        return f"the description is not a mapping ({type(endpoint).__name__})"
+    return dict(endpoint)
+
+
+#: The installed pin's own user-video endpoint description, captured before the
+#: seam can shadow the package; see :func:`_probe_installed_pinned_endpoint`.
+_INSTALLED_PINNED_ENDPOINT = _probe_installed_pinned_endpoint()
+
+
+def _probe_installed_request_settings_parameters() -> dict | str:
+    """Read the pin's request-settings parameter shapes, or why not.
+
+    Captured at import time for the same reason as the endpoint description: a
+    lazy import inside a seam test would read the fake.  Only the parameter
+    name/kind/default triples are kept — the shape a mirrored double must not
+    loosen (``RequestSettings.set_proxy(self, proxy: str)`` has no default).
+    """
+
+    try:
+        settings = importlib.import_module("bilibili_api").request_settings
+        return {
+            name: [
+                (parameter.name, str(parameter.kind), parameter.default)
+                for parameter in inspect.signature(
+                    getattr(settings, name)
+                ).parameters.values()
+            ]
+            for name in ("set_proxy", "get_proxy")
+        }
+    except (ImportError, AttributeError, TypeError, ValueError) as error:
+        return f"{type(error).__name__}: {error}"
+
+
+#: The installed pin's request-settings parameter shapes, captured the same way.
+_INSTALLED_REQUEST_SETTINGS_PARAMETERS = _probe_installed_request_settings_parameters()
+
+
+def _require_installed(probe: dict | str, what: str) -> dict:
+    """Return a successful import-time probe, or fail loudly with guidance."""
+
+    if isinstance(probe, str):
+        pytest.fail(
+            f"this parity contract needs the pinned distribution's {what}"
+            f" ({PINNED_PACKAGE_DISTRIBUTION_NAME}=={PINNED_PACKAGE_VERSION});"
+            f" it could not be read ({probe}). Run uv sync first."
+        )
+    return probe
+
+
 #: The complete documented exception surface the fake seam must mirror.
 ALLOWED_EXCEPTION_NAMES = (
     "ApiException",
@@ -583,6 +652,101 @@ def test_user_video_page_request_follows_a_changed_package_endpoint(
     assert request.wbi is False
 
 
+def test_fake_endpoint_mirror_matches_the_installed_pinned_description():
+    """The seam's mirrored endpoint description is the installed pin's.
+
+    ``FAKE_USER_VIDEO_PAGE_ENDPOINT`` is the sole offline oracle for the
+    risk-control-relevant call shape, so its claim to mirror
+    ``bilibili_api.user.API["info"]["video"]`` literally is checked against
+    the distribution it mirrors, not only against itself (the same
+    packaging-parity pattern the HTTP-backend test uses).  A pin bump that
+    renames a key or flips ``verify``/``wbi``/``dm`` fails here instead of
+    staying green offline and surfacing only live.
+
+    Offline and deterministic: reading the installed distribution is the only
+    I/O.  When its description cannot be read the test fails loudly with
+    install guidance, because the contract it checks cannot be proven without
+    it.
+    """
+
+    pinned_endpoint = _require_installed(
+        _INSTALLED_PINNED_ENDPOINT, "endpoint description"
+    )
+
+    for field in MIRRORED_ENDPOINT_FIELDS:
+        assert FAKE_USER_VIDEO_PAGE_ENDPOINT[field] == pinned_endpoint[field], (
+            f"the fake endpoint mirror drifted from the installed pin on {field!r}"
+        )
+    # ``dm`` is mirrored literally too: the pin's ``True`` is the very field
+    # the adapter overrides, so the mirror must keep carrying it.
+    assert FAKE_USER_VIDEO_PAGE_ENDPOINT["dm"] is True
+    assert pinned_endpoint["dm"] is True
+    # The parameter names the adapter forwards are the pin's own set.
+    assert set(FAKE_USER_VIDEO_PAGE_ENDPOINT["params"]) == set(pinned_endpoint["params"])
+
+
+def test_adapter_overrides_only_dm_of_the_installed_pinned_endpoint(
+    bilibili_api_seam,
+):
+    """``dm`` is the only field the adapter changes on the pin's own shape.
+
+    The mirror-parity test above proves the seam's description equals the
+    installed pin's; this test scripts the seam with the pin's *own* values
+    and runs the real adapter, so the issued request reproduces every transport
+    field of the pinned distribution except ``dm``, which the
+    risk-control-safe shape turns off.  Together they pin the shipped call
+    shape to the distribution the adapter actually drives.
+    """
+
+    pinned_endpoint = _require_installed(
+        _INSTALLED_PINNED_ENDPOINT, "endpoint description"
+    )
+    bilibili_api_seam.user_video_page_endpoint.update(pinned_endpoint)
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    (request,) = bilibili_api_seam.api_requests
+    for field in MIRRORED_ENDPOINT_FIELDS:
+        assert getattr(request, field) == pinned_endpoint[field]
+    assert pinned_endpoint["dm"] is True
+    assert request.dm is False
+
+
+def test_fake_request_settings_double_is_no_more_permissive_than_the_pin():
+    """The seam keeps the pin's strict ``set_proxy``/``get_proxy`` shapes.
+
+    ``bilibili_api.request_settings`` is the pinned package's process-global
+    ``RequestSettings`` instance, whose ``set_proxy(self, proxy: str)`` has no
+    default: a no-argument call raises ``TypeError`` against the real package.
+    The seam mirrors it as a module-level function, so a default added there
+    would let a no-argument call pass offline and fail live; the pin's own
+    parameter shapes are compared instead.
+
+    Offline and deterministic: the pinned distribution is read for its
+    signatures only, and the fake is built directly (no seam fixture).
+    """
+
+    pinned_parameters = _require_installed(
+        _INSTALLED_REQUEST_SETTINGS_PARAMETERS, "request-settings parameter shapes"
+    )
+    fake_settings = build_fake_package(FakeUpstreamScript())[
+        "bilibili_api.request_settings"
+    ]
+
+    for name in ("set_proxy", "get_proxy"):
+        mirrored_parameters = [
+            (parameter.name, str(parameter.kind), parameter.default)
+            for parameter in inspect.signature(
+                getattr(fake_settings, name)
+            ).parameters.values()
+        ]
+        assert mirrored_parameters == pinned_parameters[name], (
+            f"the seam's {name} signature is more permissive than the pin's"
+        )
+
+
 # -------------------------------------------------------------- video parts
 
 
@@ -898,6 +1062,10 @@ def test_http_backend_declared_and_absent_from_pinned_package_requirements():
     declaration is dropped, and the installed distribution's own metadata is
     what proves the dependency is load-bearing rather than transitive.
 
+    The installed distribution is asserted to *be* the pin before its
+    requirements are read, so a drifted environment fails loudly here instead
+    of silently drawing the conclusion from another release.
+
     Offline and deterministic: it reads this checkout's ``pyproject.toml``
     and the installed distributions' metadata only.
     """
@@ -925,6 +1093,12 @@ def test_http_backend_declared_and_absent_from_pinned_package_requirements():
             f" read its Requires-Dist ({error}); run uv sync first"
         )
 
+    assert pinned_distribution.version == PINNED_PACKAGE_VERSION, (
+        "the installed distribution is not the pin this contract is about"
+        f" ({pinned_distribution.version!r} != {PINNED_PACKAGE_VERSION!r});"
+        " install the pinned release (uv sync) before re-reading Requires-Dist"
+    )
+
     upstream_names = {
         canonicalize_name(Requirement(raw).name)
         for raw in pinned_distribution.requires or ()
@@ -1264,7 +1438,15 @@ def test_only_the_gateway_module_imports_bilibili_api():
 
 
 def test_gateway_imports_stay_on_metadata_surface():
-    """The adapter imports only Credential, User, Video, and exceptions."""
+    """The adapter imports exactly the enforced allow-list, nothing broader.
+
+    ``ALLOWED_PACKAGE_IMPORTS`` is compared exactly: ``Credential`` and the
+    ``request_settings``/``user`` modules from the package root, the
+    WBI-signed ``utils.network.Api``, ``video.Video``, and the five exception
+    names.  ``User`` is deliberately not among them — the page call goes
+    through the ``user`` module's endpoint description and the package ``Api``,
+    never a ``user.User`` delegate.
+    """
 
     gateway_path = (
         pathlib.Path(__file__).resolve().parent.parent
diff --git a/bilibili-asr-archive/tests/test_live_metadata_smoke.py b/bilibili-asr-archive/tests/test_live_metadata_smoke.py
index 4b1a928..64e79a0 100644
--- a/bilibili-asr-archive/tests/test_live_metadata_smoke.py
+++ b/bilibili-asr-archive/tests/test_live_metadata_smoke.py
@@ -24,9 +24,11 @@ Default pytest runs skip the smoke; it executes only when the operator sets
   Without a credential the run is anonymous, and an upstream rejection of
   anonymous metadata access is one bounded failure among others
   (``rate_limited``, or ``response_error`` for other upstream failures): the
-  smoke reports that case as the documented no-credential behavior (a
-  clearly-reasoned skip, after its assertions ran), while the same bounded
-  failure with an operator credential in the environment is a loud failure.
+  smoke reports exactly those documented codes as the documented no-credential
+  behavior (a clearly-reasoned skip, after its assertions ran), while any other
+  bounded code — ``transport_error`` from a dead proxy, for instance — fails
+  loudly, as does the same bounded failure with an operator credential in the
+  environment.
 """
 
 from __future__ import annotations
@@ -44,6 +46,7 @@ from fixtures.fake_bilibili_gateway import (
     SESSDATA_BOUNDARY_VALUE,
     SIGNED_URL_MARKER,
     UPSTREAM_ERROR_TEXT,
+    FakeNetworkException,
     FakeResponseCodeException,
     assert_leaks_no_markers,
     bilibili_api_seam,
@@ -55,6 +58,15 @@ from fixtures.fake_bilibili_gateway import (
 
 PINNED_PACKAGE_VERSION = "17.4.2"
 
+#: The bounded scalar codes the operator docs enumerate for anonymous metadata
+#: access (``README.md`` / ``docs/metadata-storage.md``): ``rate_limited`` for
+#: an upstream risk-control rejection, ``response_error`` for other upstream
+#: failures.  Only these may take the anonymous arm's reasoned-skip path; any
+#: other code — ``transport_error`` from a dead proxy, ``shape_error`` from a
+#: normalization regression, ``not_found`` — means the run failed for a reason
+#: the documentation does not cover and must fail loudly instead.
+ANONYMOUS_BOUNDED_ERROR_CODES = frozenset({"rate_limited", "response_error"})
+
 #: The archive owner whose public metadata the bounded smoke may collect.
 LIVE_SMOKE_MID = 23191782
 
@@ -278,6 +290,26 @@ def _bounded_live_argv(tmp_root: str) -> list[str]:
     ]
 
 
+def _assert_anonymous_error_code_is_documented(error_code: str) -> None:
+    """Fail loudly unless a no-credential bounded code is a documented one.
+
+    The anonymous arm may report a reasoned skip only for the codes
+    :data:`ANONYMOUS_BOUNDED_ERROR_CODES` enumerates and the operator docs
+    repeat.  Every other bounded code is a defect of the environment or the
+    adapter — a dead proxy surfaces ``transport_error`` — so it must fail the
+    smoke instead of reading as "documented anonymous behavior".
+    """
+
+    if error_code not in ANONYMOUS_BOUNDED_ERROR_CODES:
+        pytest.fail(
+            "live smoke ended in an anonymous bounded failure the docs do not"
+            f" enumerate (error_code={error_code!r});"
+            f" {sorted(ANONYMOUS_BOUNDED_ERROR_CODES)} are the documented"
+            " anonymous outcomes, so this run failed for another reason (a dead"
+            " proxy, for instance, surfaces transport_error)"
+        )
+
+
 def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
     tmp_root: str,
     capsys: pytest.CaptureFixture[str],
@@ -335,6 +367,9 @@ def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
         # Same resolution rule as ``resolve_sessdata``: a missing or blank
         # BILI_SESSDATA means no credential was in play.
         if not os.environ.get(SESSDATA_ENV_VAR):
+            # Only the documented anonymous codes may take the skip path: any
+            # other bounded code fails loudly here.
+            _assert_anonymous_error_code_is_documented(error_code)
             pytest.skip(
                 "live smoke ended in the documented bounded anonymous"
                 f" rejection (error_code={error_code!r}, exit 2): without a"
@@ -368,8 +403,10 @@ def test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam(
     caught by every default (offline) run instead of first failing at the
     QA gate's live execution.  The scripted branches cover the limited
     happy path, the ``complete`` happy-path sub-branch (an empty first
-    page — practically unreachable live for this UID), and the bounded
-    upstream failure.  No live behavior is claimed here.
+    page — practically unreachable live for this UID), the bounded
+    upstream failure (an ``-400`` rejection, whose code the anonymous arm
+    accepts), and the bounded transport failure (whose code it must
+    reject).  No live behavior is claimed here.
     """
 
     monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)
@@ -451,9 +488,11 @@ def test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam(
     assert "metadata gateway failure" in err
     connection = open_database(failure_root)
     try:
-        assert _assert_bounded_failure_rows(connection, LIVE_SMOKE_MID) == (
-            "response_error"
-        )
+        error_code = _assert_bounded_failure_rows(connection, LIVE_SMOKE_MID)
+        assert error_code == "response_error"
+        # Positive control for the anonymous arm: the code this real CLI path
+        # produces for an upstream rejection is one the arm accepts.
+        _assert_anonymous_error_code_is_documented(error_code)
         assert_leaks_no_markers(out + err, context="rehearsal failure output")
         assert_leaks_no_markers(
             persisted_row_text(connection),
@@ -463,3 +502,49 @@ def test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam(
         connection.close()
     for relative in LEGACY_SIDECAR_PATHS:
         assert not os.path.exists(os.path.join(failure_root, relative))
+
+    # Branch four: a bounded *transport* failure — the shape a dead proxy
+    # produces (the D2 symptom) — reaches the CLI as ``transport_error``,
+    # which the anonymous arm must reject instead of reporting a reasoned
+    # skip.  This is the seam-level pin for the documented-code set check.
+    transport_root = os.path.join(tmp_root, "transport")
+    script.videos_error = FakeNetworkException(503, UPSTREAM_ERROR_TEXT)
+    assert main(_bounded_live_argv(transport_root)) == 2
+    out, err = capsys.readouterr()
+    assert "metadata gateway failure" in err
+    connection = open_database(transport_root)
+    try:
+        error_code = _assert_bounded_failure_rows(connection, LIVE_SMOKE_MID)
+        assert error_code == "transport_error"
+    finally:
+        connection.close()
+    assert_leaks_no_markers(out + err, context="rehearsal transport output")
+    with pytest.raises(pytest.fail.Exception):
+        _assert_anonymous_error_code_is_documented(error_code)
+    for relative in LEGACY_SIDECAR_PATHS:
+        assert not os.path.exists(os.path.join(transport_root, relative))
+
+
+@pytest.mark.parametrize("error_code", ["rate_limited", "response_error"])
+def test_anonymous_arm_accepts_the_documented_bounded_codes(error_code):
+    """The anonymous arm's skip path covers exactly the documented codes.
+
+    The parameters are the literal codes ``README.md`` / ``docs/metadata-storage.md``
+    enumerate, deliberately not derived from
+    :data:`ANONYMOUS_BOUNDED_ERROR_CODES`: a set that drops or renames one of
+    them would otherwise shrink this test instead of failing it.
+    """
+
+    assert error_code in ANONYMOUS_BOUNDED_ERROR_CODES
+    _assert_anonymous_error_code_is_documented(error_code)
+
+
+@pytest.mark.parametrize(
+    "error_code",
+    ["transport_error", "not_found", "shape_error", "unknown_failure"],
+)
+def test_anonymous_arm_fails_loudly_on_every_undocumented_code(error_code):
+    """Any other bounded code fails instead of reading as a reasoned skip."""
+
+    with pytest.raises(pytest.fail.Exception):
+        _assert_anonymous_error_code_is_documented(error_code)
```
