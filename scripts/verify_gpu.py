"""Verify the selected GPU runtime and optionally real local ASR/alignment."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("cuda", "rocm"), required=True)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--aligner", type=Path)
    parser.add_argument("--language", default="Chinese")
    args = parser.parse_args()
    if any((args.audio, args.model, args.aligner)) and not all((args.audio, args.model, args.aligner)):
        parser.error("real inference requires --audio, --model and --aligner together")
    for path in (args.audio, args.model, args.aligner):
        if path is not None and not path.is_absolute():
            parser.error("audio and checkpoint paths must be absolute")
    import torch

    backend = "rocm" if torch.version.hip else "cuda" if torch.version.cuda else "cpu"
    if backend != args.backend or not torch.cuda.is_available():
        raise RuntimeError("selected GPU backend is unavailable")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("GPU does not support the model's BF16 execution")
    tensor = torch.ones((32, 32), device="cuda", dtype=torch.bfloat16)
    product = tensor @ tensor
    torch.cuda.synchronize()
    if not bool(torch.isfinite(product).all().item()):
        raise RuntimeError("BF16 matrix multiplication failed")
    result = {"backend": backend, "torch": torch.__version__, "cuda": torch.version.cuda,
              "hip": torch.version.hip, "device": torch.cuda.get_device_name(0),
              "bf16": True, "real_inference": "not_run"}
    if args.audio:
        from bili_asr.asr import ASRConfig, ASRRunner

        runner = ASRRunner(ASRConfig(model_name=str(args.model), aligner_name=str(args.aligner),
                                     device="cuda", language=args.language, offline=True))
        started = time.monotonic()
        try:
            cues = runner.transcribe(str(args.audio))
            if not cues or not runner.characters():
                raise RuntimeError("real sample produced no transcript or character alignment")
            result.update(real_inference="passed", segments=len(cues), seconds=round(time.monotonic() - started, 2))
        finally:
            runner.release()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
