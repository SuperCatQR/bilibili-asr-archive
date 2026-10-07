"""Verify spec 04 D4.5 on the target host: a declared revision must not break a
local-directory *load*.

Why this script exists
----------------------
``asr.provenance()`` performs **no** model load: it builds an ``ASRRunner`` and
reads ``asdict(self.config)``.  ``model_revision`` is only assembled inside
``_get_model`` (``asr.py``), which only ``transcribe()`` reaches — so a
``provenance()`` smoke test proves nothing about D4.5's assumption ("passing
``model_revision`` with a local checkpoint directory is accepted by the pinned
loader").  This script performs a real load, twice, and records the exact loader
kwargs.  Loads a model; run it on the ASR host only.

Usage
-----
The target host's checkout may predate the branch, so stage the branch package
beside it and put the staged ``src`` on ``PYTHONPATH`` — the host checkout is
never modified::

    # from the branch worktree, on the machine that can reach the host
    tar -C src -cf - --exclude=__pycache__ bili_asr \
      | ssh <host> 'wsl -e bash -c "rm -rf /tmp/t3probe && mkdir -p /tmp/t3probe/src \
          && tar -C /tmp/t3probe/src -xf -"'

    # on the host, from the product directory
    BILI_ASR_MODEL=/root/e2e-asr/nano/master \
    BILI_ASR_MODEL_ID=FunAudioLLM/Fun-ASR-Nano-2512 \
    BILI_ASR_MODEL_REVISION=master BILI_ASR_DEVICE=cpu \
    PYTHONPATH=/tmp/t3probe/src .venv/bin/python scripts/probe_target_host_load.py

Arms: a negative control (``provenance()`` → 0 factory invocations), the declared
revision, and no declared revision.  Exit code is non-zero unless both real loads
succeed.  The revision variable is read from ``asr.ASR_MODEL_REVISION_ENV_VAR``
rather than hard-coded, so a rename cannot silently turn arm A into arm B.
"""

from __future__ import annotations

import bili_asr.asr.config as _module_asr_config
import bili_asr.asr.constants as _module_asr_constants
import bili_asr.asr.runner as _module_asr_runner


import os
import subprocess
import sys
import traceback

import bili_asr.asr as asr

#: The declared-revision variable, imported rather than spelled out: four
#: hard-coded copies would silently decay arm A into arm B after a rename while
#: the script still printed ``RESULT {... True ...}``.
REVISION_ENV_VAR = _module_asr_constants.ASR_MODEL_REVISION_ENV_VAR

#: A short slice of audio.  The default names the documented WSL2 ASR host's
#: layout as an *example*, not as a contract: this script exists to be re-run
#: somewhere else, so both paths are overridable and the checkpoint path is
#: expected to be supplied on a new host.
SOURCE = os.environ.get("BILI_ASR_PROBE_SOURCE", "/root/e2e-asr/nano/master/example/zh.mp3")
SLICE = os.environ.get("BILI_ASR_PROBE_SLICE", "/tmp/t3probe/slice.wav")
SECONDS = os.environ.get("BILI_ASR_PROBE_SECONDS", "3")


def main() -> int:
    print("bili_asr.asr.__file__ =", asr.__file__)
    print("has module-level provenance:", hasattr(asr, "provenance"))
    print("has ASRRunner.provenance:", hasattr(_module_asr_runner.ASRRunner, "provenance"))

    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", SOURCE, "-t", SECONDS,
         "-ar", "16000", "-ac", "1", SLICE],
        check=True,
    )
    print("slice:", SLICE, os.path.getsize(SLICE), "bytes")

    calls: list[dict] = []
    real_load = asr._load_default_model

    def spy(**kwargs):
        calls.append(dict(kwargs))
        return real_load(**kwargs)

    asr._load_default_model = spy

    # --- negative control: the recorded probe would have proved nothing -------
    _module_asr_runner.ASRRunner(_module_asr_config.default_config()).provenance()
    print(
        "\n--- arm 0 (negative control): factories invoked after construction + "
        f"provenance() = {len(calls)}"
    )

    def arm(label: str, revision: str | None) -> bool:
        calls.clear()
        if revision is None:
            os.environ.pop(REVISION_ENV_VAR, None)
        else:
            os.environ[REVISION_ENV_VAR] = revision
        runner = _module_asr_runner.ASRRunner(_module_asr_config.default_config())
        print(f"\n--- arm {label}: {REVISION_ENV_VAR}={revision!r}")
        try:
            segments = runner.transcribe(SLICE)
        except Exception:
            print("    LOAD/TRANSCRIBE FAILED:")
            traceback.print_exc()
            return False
        print("    loader kwargs:", calls[0] if calls else "NONE")
        print(
            f"    OK — {len(segments)} segment(s); factories invoked: {len(calls)}; "
            f"attempts={runner.model_load_attempts}; "
            f"constructions={runner.model_constructions}"
        )
        print("    provenance():", runner.provenance())
        return True

    declared = arm("A (declared revision)", "master")
    undeclared = arm("B (no declared revision)", None)
    print("\nRESULT", {"declared_revision_loads": declared,
                       "no_revision_loads": undeclared})
    return 0 if (declared and undeclared) else 1


if __name__ == "__main__":
    sys.exit(main())
