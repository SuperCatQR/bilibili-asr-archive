# Task 1 Diff — 20260911-live-metadata-path-fix

Base: `25a11fe`
Head: `cc56e46`

```diff
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
 
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index 50b21b0..1d6f4ab 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -11,7 +11,10 @@ subtitle, audio, or download methods, which makes silent use of other package
 APIs impossible.  The import boundary and the method surface itself are
 additionally inspected statically with AST over the package sources.  The
 only networked test is the opt-in live smoke, which skips unless
-``BILI_LIVE_SMOKE=1`` is set.
+``BILI_LIVE_SMOKE=1`` is set.  The packaging-contract test is the one
+exception to the "installed distribution never needed" rule: it reads the
+pinned distribution's metadata and fails loudly when that distribution is
+absent, because the contract it checks cannot be proven without it.
 """
 
 from __future__ import annotations
@@ -19,10 +22,14 @@ from __future__ import annotations
 import ast
 import asyncio
 import importlib
+import importlib.metadata
 import os
 import pathlib
+import tomllib
 
 import pytest
+from packaging.requirements import Requirement
+from packaging.utils import canonicalize_name
 
 from bili_asr.services.metadata_ingest import MetadataIngestor
 from bili_asr.sources.models import (
@@ -59,8 +66,20 @@ from fixtures.fake_bilibili_gateway import (
     persisted_row_text,
 )
 
+PINNED_PACKAGE_DISTRIBUTION_NAME = "bilibili-api-python"
 PINNED_PACKAGE_VERSION = "17.4.2"
 
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
 #: The exact bilibili_api import surface the adapter is allowed to use.
 ALLOWED_PACKAGE_IMPORTS = {
     "bilibili_api": {"Credential"},
@@ -658,6 +677,61 @@ def test_package_version_reports_installed_distribution(bilibili_api_seam, monke
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
 # ------------------------------------------------------- DTO self-validation
 
 
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
