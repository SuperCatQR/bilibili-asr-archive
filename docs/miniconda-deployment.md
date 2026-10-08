# Miniconda production deployment

Use one Python 3.12 environment per deployment. Never install this project or
GPU wheels into Conda base. This guide targets Linux hosts, including Ubuntu
WSL2 for AMD. NVIDIA instructions are a validation procedure, not a claim of
tested NVIDIA support.

## Dependency records

- `deployment/environment.yml` pins the initial Conda Python, pip and ffmpeg
  requests. Install Conda packages before pip packages; create a new environment
  if Conda dependencies change after pip installation.
- `deployment/application-requirements.txt` is generated from `uv.lock`, with
  exact package versions and wheel hashes, including the ASR and test extras.
  It deliberately excludes torch, which is supplied separately for the host.
- `deployment/amd-wsl-gpu.txt` records the measured AMD wheel pair. CUDA wheels
  must be selected for the NVIDIA driver on the actual host and recorded there.

Regenerate the application export after changing dependencies:

```bash
uv lock
uv export --locked --extra asr --extra dev --no-emit-project \
  --output-file deployment/application-requirements.txt
```

The same lock resolves developer uv and deployment pip packages. Conda does
not consume uv.lock: pip consumes its exported requirements. Do not run an
exact uv sync inside a deployment environment: torch is excluded from the
application lock and could be removed. `librosa` is required by Transformers'
Qwen processor even though container decoding uses the project's ffmpeg path.

## Provision the environment

Install Miniconda from its official installer and verify its published SHA-256.
The examples assume `/opt/miniconda3/bin/conda` and a checkout at
`/srv/bilibili-asr-archive`; set these paths to the actual deployment location.

```bash
export CONDA_EXE=/opt/miniconda3/bin/conda
export PRODUCT=/srv/bilibili-asr-archive
export DEPLOY_ENV=bili-asr-production
cd "$PRODUCT"
"$CONDA_EXE" env create --file deployment/environment.yml --name "$DEPLOY_ENV"
"$CONDA_EXE" run --no-capture-output -n "$DEPLOY_ENV" python --version
```

Before installing pip dependencies, choose one GPU branch below. Never let
pip select an arbitrary torch build from the general PyPI index.

### AMD WSL ROCm

Provision the driver, DXG transport and ROCm libraries using steps 1-5 in
[the AMD WSL recipe](wsl-rocm-gpu.md). Its system configuration still applies;
replace its venv commands with Conda commands here.

```bash
"$CONDA_EXE" run --no-capture-output -n "$DEPLOY_ENV" python -m pip install \
  -r deployment/amd-wsl-gpu.txt
"$CONDA_EXE" env config vars set -n "$DEPLOY_ENV" \
  HSA_ENABLE_DXG_DETECTION=1 LD_LIBRARY_PATH=/opt/rocm-7.2.1/lib
```

The ROCm library path must match the installed version. If additional loader
paths are required, include them explicitly; do not rely on ~/.bashrc.
Apply the WSL HSA runtime replacement from step 7 of the AMD recipe inside
this environment's `torch/lib`. For that recipe only, set `VENV` to the Conda
environment prefix (discover it with `conda run ... python -c
'import sys; print(sys.prefix)'`). Do not modify other environments.

Conda activation contributes loader environment and activation scripts.
The issue #251 trial observed a GPU through `conda run` while a direct call
to the environment interpreter initially did not. Use `conda run` for startup
and validation; an absolute interpreter alone is supported only after its
complete loader environment has been independently verified.

### NVIDIA CUDA

Run `nvidia-smi` and select the Linux/Pip/Python CUDA wheel command from the
[official PyTorch selector](https://pytorch.org/get-started/locally/). Confirm
that the selected runtime supports the host driver. Execute that command via
`conda run -n "$DEPLOY_ENV" python -m pip`, replacing its bare pip invocation.
Pin the selected torch version and index URL in the deployment evidence;
archive `pip freeze --all` and downloaded wheel SHA-256 values.

Do not use `bili-asr check-asr-env` to certify NVIDIA: it checks AMD WSL DXG,
ROCm loader, ROCm torch, HSA runtime and device probe specifically. Use
`scripts/verify_gpu.py --backend cuda` below, followed by real model inference.
NVIDIA remains untested on hardware in the recorded trial.

## Install and verify the application

```bash
"$CONDA_EXE" run --no-capture-output -n "$DEPLOY_ENV" python -m pip install \
  --require-hashes -r deployment/application-requirements.txt
"$CONDA_EXE" run --no-capture-output -n "$DEPLOY_ENV" python -m pip install --no-deps .
"$CONDA_EXE" run --no-capture-output -n "$DEPLOY_ENV" python -m pip check
"$CONDA_EXE" run --no-capture-output -n "$DEPLOY_ENV" bili-asr --help
"$CONDA_EXE" run --no-capture-output -n "$DEPLOY_ENV" python -m pytest -q \
  tests/test_workflow_control_plane.py tests/test_transcript_projection.py \
  tests/test_metadata_repository.py tests/test_metadata_ingest.py \
  tests/test_metadata_page_retries.py tests/test_metadata_cli.py \
  tests/test_dependency_lock.py tests/test_production_startup.py tests/test_verify_gpu.py
```

For AMD, first run all five checks:

```bash
"$CONDA_EXE" run --no-capture-output -n "$DEPLOY_ENV" bili-asr check-asr-env
```

For either backend, use an 8-15 second real speech sample and downloaded local
Qwen3 ASR and forced-aligner checkpoints. Use `--backend cuda` on NVIDIA.
The JSON reports hardware versions, BF16 execution and inference outcome;
it omits transcript text. Without the three input paths it performs GPU/BF16
preflight only and explicitly reports inference as not run. GNU timeout bounds
this diagnostic so a blocked GPU kernel cannot hang deployment acceptance.

```bash
timeout --kill-after=10s 180s "$CONDA_EXE" run --no-capture-output -n "$DEPLOY_ENV" \
  python scripts/verify_gpu.py --backend rocm \
  --audio /srv/bili-samples/speech.wav \
  --model /srv/bili-models/Qwen3-ASR-1.7B-hf \
  --aligner /srv/bili-models/Qwen3-ForcedAligner-0.6B-hf --language Chinese
```

## Non-interactive startup

Create `.env` in the deployment checkout, outside version control, with mode
600, owned by the service user. Use KEY=value assignments; quoted values are
supported. No shell commands, variable expansion or `export` prefixes are
evaluated. Values override the inherited environment. Never enable shell
tracing or log the file. The loader checks group/other permissions on POSIX.

```bash
chmod 600 "$PRODUCT/.env"
cd "$PRODUCT"
"$CONDA_EXE" run --no-capture-output -n "$DEPLOY_ENV" \
  python scripts/production.py --env-file "$PRODUCT/.env" -- \
  workflow plan --archive-root /srv/bili-data/archive --part-id 42 \
  --model /srv/bili-models/Qwen3-ASR-1.7B-hf \
  --aligner /srv/bili-models/Qwen3-ForcedAligner-0.6B-hf --device cuda --language Chinese
"$CONDA_EXE" run --no-capture-output -n "$DEPLOY_ENV" \
  python scripts/production.py --env-file "$PRODUCT/.env" -- \
  workflow run --archive-root /srv/bili-data/archive --limit 20
```

This invocation works under a service or scheduler without interactive
activation. `cuda` is the PyTorch device spelling for both CUDA and ROCm.
Model paths are frozen at planning time; the worker reads that stored profile.

## Rebuild and redeploy

Old project environment/data compatibility is not a requirement. A deployment
change creates a new isolated environment from the current definitions and
reruns acceptance. Do not add schema migrations or preserve an old project
environment merely for compatibility. If reverting code, rebuild its matching
environment from its recorded dependency export; revalidate GPU and inference.
An incompatible archive database must be discarded and recollected under the
project's rebuild-only policy.

For the issue #251 template machine, the original plan to retain the old venv
was superseded by the user's instruction to remove old project environments
after successful verification. That cleanup did not include unrelated
projects, model checkpoints or media files. This guide does not run cleanup
or delete data on any host.

## Template trial and reproducibility limits

[Issue #251 trial record](https://github.com/SuperCatQR/bilibili-asr-archive/issues/251#issuecomment-6051632156)
reports the following results on 2026-10-08. These are existing host evidence,
not a rerun of this repository change:

| Item | Recorded result |
|---|---|
| Host | Ubuntu WSL2, AMD RX 7800 XT, 15.8 GB |
| Code | 75175954efb5753026c0990afe581ae5c942f842 |
| Environment | /opt/miniconda3/envs/bili-asr-production, Python 3.12.15 |
| GPU | torch 2.9.1+rocm7.2.0.lw.git7e1940d4, triton 3.5.1+rocm7.2.0.gita272dfa8 |
| Application | transformers 5.19.0; real inference required adding librosa 1.0.0 |
| Checks | five AMD checks, pip check, 81 focused tests passed |
| Inference | local Qwen3 pair, 8-second Chinese speech, aligned segment, 13.40 s including load |
| Startup | conda run, .env mode 600 |
| Evidence | deployment-evidence/ on template host |

The current application export comes from the repository lock, not an invented
copy of that host's full pip freeze. The Conda YAML pins direct requests, not
every transitive Conda artifact. After each accepted host installation record
`git rev-parse HEAD`, `conda list --explicit`, `conda env export`, `pip freeze
--all`, wheel checksums, driver/runtime versions, and verification outputs in
an operator-owned evidence directory. Do not include .env or credentials in
these records. An explicit Conda export is platform-specific and must be
regenerated for each target platform. A new lock/export needs fresh host
acceptance; it is not certified by the earlier trial.

See also the official [Conda environment guidance](https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html)
and [conda run reference](https://docs.conda.io/projects/conda/en/latest/commands/run.html).
