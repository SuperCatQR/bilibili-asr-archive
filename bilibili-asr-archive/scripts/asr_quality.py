"""Judge transcript quality automatically — no reference and no human needed.

Everything here is derived from what the pipeline already produces:

* the model's own per-cue **confidence** (mean token score), recorded in the
  raw sidecar, which points at the passages the model itself was unsure about;
* **anomalies** that need no reference: cues that open with a closing mark,
  fragments, over-long cues, consecutive duplicates, and text that repeats;
* optionally, **agreement with a second transcript** of the same audio (the
  upstream caption, a different model, a different VAD).  Two independent
  systems agreeing is evidence; disagreeing marks the passage as contested.

Usage:
    python scripts/asr_quality.py <raw.json|transcript.srt|transcript.txt> [--reference OTHER]

Exit status is 0 for a report, 1 when ``--fail-under`` is given and the mean
confidence is below it.
"""

from __future__ import annotations

import argparse
import collections
import difflib
import json
import re
import statistics
import sys
from pathlib import Path

PUNCT = "。，？！、；：,?!.;:…—·\"'“”‘’（）()《》"
LEADING = "，。！？、；："
LOW_CONFIDENCE = 0.4
OVERLONG_CHARS = 60
MIN_CHARS = 6
MIN_SECONDS = 1.0


def flatten(text: str) -> str:
    return re.sub(f"[{re.escape(PUNCT)}]", "", text).replace(" ", "").lower()


def load_segments(path: Path) -> tuple[list[dict], dict]:
    """Read cues (and provenance) from a raw sidecar, an SRT, or a plain text."""

    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        segments = payload.get("segments") or []
        return segments, payload.get("provenance") or {}
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() != ".srt":
        return [{"start": 0.0, "end": 0.0, "text": line} for line in text.splitlines() if line.strip()], {}
    rows = re.findall(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)\n(.+)", text)
    to_seconds = lambda h, m, s, ms: int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    return [{"start": to_seconds(*row[0:4]), "end": to_seconds(*row[4:8]), "text": row[8]} for row in rows], {}


def reference_text(segments: list[dict]) -> str:
    return flatten("".join(str(s.get("text") or "") for s in segments))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--reference", type=Path, default=None,
                        help="a second transcript of the same audio (SRT/TXT)")
    parser.add_argument("--fail-under", type=float, default=None,
                        help="exit 1 when mean confidence is below this")
    args = parser.parse_args(argv)

    segments, provenance = load_segments(args.transcript)
    if not segments:
        print(f"{args.transcript}: no cues found", file=sys.stderr)
        return 1

    duration = max((float(s.get("end") or 0) for s in segments), default=0.0)
    chars = sum(len(str(s.get("text") or "")) for s in segments)
    print(f"transcript : {args.transcript}")
    if provenance:
        print(f"produced by: model={provenance.get('model_name')} revision={provenance.get('model_revision')} "
              f"device={provenance.get('device')} vad={provenance.get('vad_model')} "
              f"lang={provenance.get('language')}")
    print(f"scale      : {len(segments)} cues, {chars} chars over {duration:.0f}s "
          f"({chars / (duration / 60):.0f} chars/min)" if duration else
          f"scale      : {len(segments)} cues, {chars} chars")

    scores = [float(s["confidence"]) for s in segments
              if isinstance(s.get("confidence"), (int, float))]
    if scores:
        low = sorted((s for s in segments if isinstance(s.get("confidence"), (int, float))
                      and float(s["confidence"]) <= LOW_CONFIDENCE),
                     key=lambda s: float(s["confidence"]))
        print(f"confidence : mean {statistics.mean(scores):.3f} "
              f"p10 {sorted(scores)[max(0, len(scores) // 10)]:.3f} "
              f"min {min(scores):.3f} | {len(low)}/{len(scores)} cues at or below {LOW_CONFIDENCE}")
        for cue in low[:3]:
            print(f"  unsure   : {float(cue['start']):7.1f}s conf={float(cue['confidence']):.2f} "
                  f"{str(cue['text'])[:44]!r}")
    else:
        print("confidence : not recorded in this artefact (run the pinned model to capture it)")

    texts = [str(s.get("text") or "") for s in segments]
    anomalies = {
        "cue opens with a mark": sum(1 for t in texts if t[:1] in LEADING),
        "fragment cue": sum(1 for s, t in zip(segments, texts)
                            if len(t.strip(LEADING)) < MIN_CHARS
                            and (float(s.get("end") or 0) - float(s.get("start") or 0)) < MIN_SECONDS),
        "over-long cue": sum(1 for t in texts if len(t) > OVERLONG_CHARS),
        "consecutive duplicate": sum(1 for a, b in zip(texts, texts[1:]) if a and a == b),
    }
    joined = "".join(texts)
    grams = collections.Counter(joined[i:i + 8] for i in range(max(0, len(joined) - 8)))
    anomalies["repeated 8-gram (>=3x)"] = sum(1 for count in grams.values() if count >= 3)
    print("anomalies  : " + ", ".join(f"{name}={count}" for name, count in anomalies.items()))

    if args.reference:
        other, _ = load_segments(args.reference)
        mine, theirs = reference_text(segments), reference_text(other)
        ratio = difflib.SequenceMatcher(None, mine, theirs, autojunk=False).ratio()
        print(f"agreement  : {ratio:.4f} against {args.reference.name} "
              f"({len(mine)} vs {len(theirs)} chars) — below ~0.95 means the two systems "
              f"contested the audio, not that either is wrong")

    if args.fail_under is not None and scores and statistics.mean(scores) < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
