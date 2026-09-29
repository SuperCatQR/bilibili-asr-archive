---
stage: 2
seat: security-cross-domain
domain: security (cross-domain)
pr: 19
head: 84e9767146c03977812591a48a991e0fce7de985
diff_base: 9d530cd646e50142cd92789b2494c72806025ffd
---

# Stage 2 evidence — security (cross-domain) (PR #19)

## [SEC-01] Pin or declare the decoder the new `.m4a` fallback actually needs

- **Evidence**: `bilibili-asr-archive/src/bili_asr/asr.py:403-406`, `bilibili-asr-archive/README.md:143-144`,
  `bilibili-asr-archive/pyproject.toml:36`, `bilibili-asr-archive/uv.lock:763-764`
- **Impact**: the install boundary and the documented decode chain disagree — an operator who follows the README
  installs the extra, believes only `ffmpeg` is missing, and gets a second `LibsndfileError` instead of audio
- **Effort**: S (docs-only: XS) · **Risk**: MED · **Confidence**: HIGH · **Merge class**: should-fix
- **Fix sketch**: declare and lock the package the docs name, or decode through the already-required `ffmpeg`

No attacker, no boundary defeat, no exploitability is claimed: this is install-boundary hygiene. The functional
half is graded by the code seat as BUG-01 (`must-fix`).

## Checked and clean (recorded so the next pass need not re-flag)

- **No credential material added.** Added-line scans for provider keys, `Bearer`/`Authorization`, `sessdata=` /
  `bili_jct`, signed-URL shapes and PEM found only the English prose word "token-for-token".
- **No new sink.** No `eval` / `exec` / `pickle` / `yaml.load` / `shell=True` / `os.system` / `subprocess` /
  URL-fetch in the added lines.
- **No new prompt-injection path.** The prompt is built from `config.hotwords` = `DEFAULT_HOTWORDS` +
  `_extra_hotwords(os.environ[...])` (`asr.py:791`, `:345`) — literals and an env knob. No ingested archive
  content reaches it.
- **Confinement unchanged and upstream.** `path_policy.confined_audio_file` still `O_NOFOLLOW` + regular-file
  check; the reader path is materialized to a `mkstemp` 0600 file before either reader sees it.
- **Host-path detail in the new docs** (`/mnt/e/...`, `192.168.3.21`) matches an already-committed pattern in the
  published set (`bundle-transfer-to-isolated-host.md`); repository is private; no secret values. Note, not finding.
