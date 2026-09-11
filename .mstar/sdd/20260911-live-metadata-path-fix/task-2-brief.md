### Task 2: Resolve and apply proxy configuration in the gateway

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`
- Modify: `bilibili-asr-archive/src/bili_asr/config.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: `BilibiliApiGateway` constructor and the pinned package's request settings.
- Produces: `BilibiliApiGateway(sessdata=None, proxy=None)` with locked precedence
  (argument → `BILI_HTTP_PROXY` → `HTTPS_PROXY` → `https_proxy` → `ALL_PROXY` →
  `all_proxy`), a `resolved_proxy` attribute, and the proxy applied to the package before
  the first request.

- [ ] Implement proxy resolution as a pure helper (empty/blank values are "unset";
  precedence exactly as locked) and apply a resolved proxy to the package's request
  settings at construction; when nothing resolves, leave the library default untouched.
- [ ] Keep the credential boundary intact: no proxy value, and never a credential, appears
  in DTOs, exception messages, logs, or persisted rows; the CLI display path stays
  presence-only.
- [ ] Test: precedence order, blank-value handling, no-proxy default (library setting
  untouched), apply-once behaviour, and the no-leak assertions over output and rows.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_cli.py -v`

