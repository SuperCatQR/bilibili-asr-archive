# Bilibili ASR archival workspace

Personal tooling for archiving transcripts from Bilibili UP 未明子 (UID
23191782): discover videos, prefer AI/CC subtitles, and use local Qwen3-ASR
when audio transcription is needed. Media is for personal archival only.

## Repository layout

| Path | Purpose |
| --- | --- |
| [`bilibili-asr-archive/`](bilibili-asr-archive/README.md) | Installable Python product: `bili-asr`, source, tests, scripts and operator documentation. Run product commands from this directory. |
| [`.mstar/`](.mstar/AGENTS.md) | Tracked development harness: plans, iterations, knowledge, specifications and workflow records. Its documents travel with commits and worktrees; some engine runtime state stays local. |
| [`AGENTS.md`](AGENTS.md) | Workspace conventions and branch policy. |

The repository root is the workspace, not the Python package root.

## Install and check

Use Linux or WSL with Python 3.12+ and system `ffmpeg`. Hardened archive
publication and reclaim require a WSL-native/Linux filesystem; keep archive
data off `/mnt/c`. The commands below are Bash commands, starting at the
repository root:

```bash
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg
cd bilibili-asr-archive
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
bili-asr --help
python -m pytest -q
python -m compileall -q src tests scripts
git diff --check
```

These test and compilation commands match [CI](.github/workflows/ci.yml).
Default tests use fixtures; live and scale probes require explicit opt-in.
Installing dependencies can use the network. There is no configured standalone
linter; compilation and Git's whitespace check are the additional local checks.
Optional GPU/model installation is separate; follow the
[product README](bilibili-asr-archive/README.md) and
[WSL/ROCm recipe](bilibili-asr-archive/docs/wsl-rocm-gpu.md).

For the isolated offline verification baseline, supply a reviewed wheel
directory containing the complete build, runtime and development dependency
closure. With the development environment above active, run from the product
directory:

```bash
python scripts/prepare_offline_baseline_fixture.py --wheel-source /path/to/reviewed-wheels --output .offline-baseline
python scripts/verify_baseline.py --offline-packages .offline-baseline --advisory-snapshot tests/fixtures/advisories-empty.json
```

The [baseline documentation](bilibili-asr-archive/README.md#deterministic-verification-baseline)
explains its isolated install, socket guard, advisory snapshot and excluded
recursive provisioning tests. Baseline verification currently requires Python
3.12 specifically. The empty advisory fixture is deterministic test evidence,
not a current vulnerability assessment.

The harness has its own validation command. From the repository root, with
Python 3.12, Node.js 20, and Bun available:

```bash
npm install --global @mstar-harness/cli@3.11.2
python3.12 bilibili-asr-archive/scripts/validate_harness_state.py .mstar
```

CI provisions Bun and runs this check as a blocking gate. A harness validation
failure therefore fails the workflow instead of being hidden by an advisory
step.

## Local runtime data

The [ignore rules](.gitignore) exclude product `archive/audio/`,
`archive/transcripts/`, `archive/manifest/`, `logs/` and `models/`, plus
`verification-results/baseline.json`. Virtual environments, Python caches,
`.env`, `.worktrees/`, `.tmp/`, `.tmp2/` and `.agent-teams/` also stay local.
This list does not mean all of `archive/` or `verification-results/` is ignored;
custom archive roots need their own placement/ignore decision.

Harness exclusions include `.mstar/sdd/`, `snapshots/`,
`.execution-maintenance/`, `.status-write.lockdir/` directories, session logs,
backup files, `store.db*` and `archived/store-migration/backups/`.
See the [harness contract](.mstar/AGENTS.md) for the tracked/runtime boundary.
A fresh worktree contains committed documents, not another checkout's local
credentials, environment, checkpoints or archive data.

## Operational references

- [Product README and CLI tour](bilibili-asr-archive/README.md)
- [Documentation index](bilibili-asr-archive/docs/README.md), including design philosophy and roadmap
- [Metadata and subtitle storage contracts](bilibili-asr-archive/docs/metadata-storage.md)
- [Archive and artifact-root placement](bilibili-asr-archive/docs/artifact-root.md)
- [Audio retention and reclaim policy](bilibili-asr-archive/docs/audio-retention-policy.md)
- [WSL long-livestream acceptance procedure](bilibili-asr-archive/docs/wsl-long-live.md)
- [Verification result conventions](bilibili-asr-archive/verification-results/README.md)
