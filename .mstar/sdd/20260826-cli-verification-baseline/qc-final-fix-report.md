# QC final fix report — 20260826-cli-verification-baseline

## Scope

Resolved the remaining QC findings F-001 and F-004 on `plan/20260826-cli-verification-baseline`.

## F-001 — staged installed-distribution suite without recursion

The baseline already stages packaging inputs and invokes the temporary venv interpreter explicitly. The staged product suite now excludes the installer/verifier self-tests (`test_cli_help.py`, `test_installed_cli.py`, and `test_verify_baseline.py`), which provision virtual environments or exercise the verifier itself and would otherwise recurse. Product tests remain staged with checkout `src` injection removed, so product imports resolve from the installed wheel. The staging test asserts these exclusions.

## F-004 — precise process-level network boundary

Documentation now states the exact boundary: the pytest interpreter patches Python `socket.create_connection`, `socket.socket.connect`, and `connect_ex`, causing those calls to raise before reaching the OS. It explicitly does not claim a host/kernel firewall, protection for other processes, or coverage of every networking mechanism. The existing deterministic test covers the public connection paths.

## Verification

- Focused: `bilibili-asr-archive/.venv/bin/python -m pytest -q tests/test_verify_baseline.py` → `18 passed in 0.06s`
- Full suite: `bilibili-asr-archive/.venv/bin/python -m pytest -q` → `338 passed in 6.21s`
- `git diff --check` → passed

## Commit

`e38210f Prevent verifier test recursion and narrow network claim`

Working branch used: `plan/20260826-cli-verification-baseline`
Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260826-cli-verification-baseline`
