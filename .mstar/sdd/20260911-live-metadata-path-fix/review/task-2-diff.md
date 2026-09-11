# Task 2 Diff — 20260911-live-metadata-path-fix

Base: `cc56e46`
Head: `0a2e2f5`

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/config.py b/bilibili-asr-archive/src/bili_asr/config.py
index d1c4168..577e18a 100644
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
@@ -31,6 +34,23 @@ DEFAULT_PAGE_LIMIT = 10
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
diff --git a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
index 3e83719..f892c1e 100644
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
+from bilibili_api import Credential, request_settings
 from bilibili_api.exceptions import (
     ApiException,
     NetworkException,
@@ -27,6 +28,7 @@ from bilibili_api.exceptions import (
 from bilibili_api.user import User
 from bilibili_api.video import Video
 
+from bili_asr.config import resolve_proxy
 from bili_asr.sources.models import (
     GatewayNotFound,
     GatewayRateLimited,
@@ -242,15 +244,32 @@ def _complete_summary_from_detail(
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
 
     async def get_user_video_page(
         self, mid: int, page_number: int, page_size: int = 100
diff --git a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
index 312d3ec..30cf067 100644
--- a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
+++ b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
@@ -10,11 +10,13 @@ Every package-seam test scripts these fakes instead of touching the pinned
 - ``FakeUpstreamScript`` / ``build_fake_package`` / ``bilibili_api_seam``
   install the fake ``bilibili_api`` package on ``sys.modules`` for the real
   adapter tests.  The fake mirrors only the documented import surface the
-  adapter may use (``Credential``, ``user.User.get_videos``,
-  ``video.Video.get_info``/``get_pages``, and the exceptions taxonomy) and
-  exposes no playback, subtitle, audio, or download method, so a silent
-  switch to another package API fails loudly instead of silently
-  succeeding.
+  adapter may use (``Credential``, ``request_settings.set_proxy`` /
+  ``get_proxy``, ``user.User.get_videos``, ``video.Video.get_info`` /
+  ``get_pages``, and the exceptions taxonomy) and exposes no playback,
+  subtitle, audio, or download method, so a silent switch to another package
+  API fails loudly instead of silently succeeding.  ``applied_proxies``
+  records every proxy the adapter hands to the package settings, so its
+  apply-once behavior is asserted without a network call.
 - ``script_parts_by_bvid`` scripts one parts payload per requested ``bvid``
   for seam tests that collect a page holding several distinct videos.
 - ``DOCUMENTED_METADATA_CALLS`` with ``assert_only_documented_metadata_calls``
@@ -137,6 +139,7 @@ class FakeUpstreamScript:
     info_response: object = None
     info_error: BaseException | None = None
     calls: list[str] = dataclasses.field(default_factory=list)
+    applied_proxies: list[str] = dataclasses.field(default_factory=list)
 
 
 class FakeGateway:
@@ -202,6 +205,21 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
 
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
@@ -271,12 +289,14 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
     package.user = user_mod
     package.video = video_mod
     package.exceptions = exceptions_mod
+    package.request_settings = request_settings_mod
 
     return {
         "bilibili_api": package,
         "bilibili_api.user": user_mod,
         "bilibili_api.video": video_mod,
         "bilibili_api.exceptions": exceptions_mod,
+        "bilibili_api.request_settings": request_settings_mod,
     }
 
 
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index 1d6f4ab..ca6c37b 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -31,6 +31,7 @@ import pytest
 from packaging.requirements import Requirement
 from packaging.utils import canonicalize_name
 
+from bili_asr.config import PROXY_ENV_VAR, PROXY_ENV_VARS, resolve_proxy
 from bili_asr.services.metadata_ingest import MetadataIngestor
 from bili_asr.sources.models import (
     GatewayNotFound,
@@ -82,7 +83,7 @@ PACKAGE_HTTP_CLIENT_CANONICAL_NAMES = frozenset({"curl-cffi", "httpx", "aiohttp"
 
 #: The exact bilibili_api import surface the adapter is allowed to use.
 ALLOWED_PACKAGE_IMPORTS = {
-    "bilibili_api": {"Credential"},
+    "bilibili_api": {"Credential", "request_settings"},
     "bilibili_api.user": {"User"},
     "bilibili_api.video": {"Video"},
     "bilibili_api.exceptions": {
@@ -94,6 +95,10 @@ ALLOWED_PACKAGE_IMPORTS = {
     },
 }
 
+#: Realistic-looking proxy URL: configuration rather than a credential, but it
+#: must still stay off DTOs, mapped errors, debug renders, and persisted rows.
+PROXY_BOUNDARY_VALUE = "http://PROXY-URL-THAT-MUST-NOT-LEAK:7890"
+
 #: The complete documented exception surface the fake seam must mirror.
 ALLOWED_EXCEPTION_NAMES = (
     "ApiException",
@@ -126,11 +131,11 @@ def _public_names(obj: object) -> list[str]:
     return sorted(name for name in vars(obj) if not name.startswith("_"))
 
 
-def _load_gateway(sessdata: str | None = None):
+def _load_gateway(sessdata: str | None = None, proxy: str | None = None):
     """Import the adapter against the installed seam and build it."""
 
     module = importlib.import_module("bili_asr.sources.bilibili_api_gateway")
-    return module.BilibiliApiGateway(sessdata=sessdata)
+    return module.BilibiliApiGateway(sessdata=sessdata, proxy=proxy)
 
 
 # --------------------------------------------------- deterministic factories
@@ -732,6 +737,214 @@ def test_http_backend_declared_and_absent_from_pinned_package_requirements():
     )
 
 
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
+    assert bilibili_api_seam.calls == ["user.get_videos(pn=1, ps=100)"]
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
+    assert bilibili_api_seam.calls == ["user.get_videos(pn=1, ps=100)"]
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
 
 
@@ -912,7 +1125,17 @@ def test_fake_seam_exposes_only_documented_metadata_surface():
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
```
