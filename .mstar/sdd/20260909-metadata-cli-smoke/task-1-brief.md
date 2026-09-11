### Task 1: Replace metadata CLI construction and commands

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py`
- Create: `bilibili-asr-archive/src/bili_asr/config.py`
- Modify: `bilibili-asr-archive/pyproject.toml`
- Test: `bilibili-asr-archive/tests/test_metadata_cli.py`

**Interfaces:**
- Consumes: CLI arguments, environment configuration, and service constructors.
- Produces: SQLite-backed command handlers with documented exit behavior.

- [ ] Add configuration loading for archive root, optional SESSDATA, and bounded
  metadata page parameters; redact credentials from any display path.
- [ ] Wire `fetch-meta` to the new ingestor and expose `--mid`, `--start-page`,
  `--limit-pages`, `--archive-root`, and optional `--sessdata`.
- [ ] Wire `status` to `v_pending_metadata` and `runs` to normalized run/page
  queries; fail clearly when the fresh database is missing for read commands.
- [ ] Remove metadata command reads/writes of old JSONL and cursor sidecars from
  the new path without changing unrelated future processing modules.
- [ ] Test parser behavior, fresh database creation, status/run output, exit codes,
  and no-old-file assertions.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_metadata_cli.py -v`

