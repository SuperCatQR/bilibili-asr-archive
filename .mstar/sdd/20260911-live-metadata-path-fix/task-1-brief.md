### Task 1: Declare the HTTP backend and prove the packaging contract

**Files:**
- Modify: `bilibili-asr-archive/pyproject.toml`
- Modify: `bilibili-asr-archive/uv.lock`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: existing `pyproject.toml` dependency block.
- Produces: a declared runtime HTTP backend (`curl_cffi`) so a fresh install can issue
  requests, plus an offline contract test that fails if the declaration disappears.

- [ ] Add the HTTP backend to the runtime `dependencies` (locked: `curl_cffi`) without
  touching unrelated dependencies; regenerate `uv.lock` and confirm `uv lock --check`
  reports a no-op.
- [ ] Add an offline test asserting the dependency is declared (parity between
  `pyproject.toml` and the installed distribution, mirroring the existing package-data
  parity pattern) — no network in the test.
- [ ] Record the pinned-package rationale in the test docstring: why the backend must be
  declared even though the library does not require it transitively.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v`

