"""Conservative pre-call checks; never rewrite transcript evidence."""

from __future__ import annotations

from collections import Counter
import re

from bili_asr.workflow_errors import JobExecutionError


def check_source_quality(prepared: dict) -> None:
    """Reject dense, long, heavily repeated ASR segments before spending API tokens.

    A long segment or ordinary rhetorical repetition alone is insufficient.
    Thresholds deliberately target the observed multi-thousand-character bursts.
    """
    if prepared["snapshot"]["base"]["source_kind"] != "asr-local":
        return
    for ordinal, segment in enumerate(prepared["snapshot"]["base"]["segments"]):
        text = segment["text"]
        duration = max(1, segment["end_ms"] - segment["start_ms"])
        if len(text) < 1000 or len(text) * 1000 <= duration * 100:
            continue
        words = re.findall(r"[a-z]+|[\u4e00-\u9fff]", text[:100_000].casefold())
        counts = Counter(tuple(words[i:i + 4]) for i in range(max(0, len(words) - 3)))
        repeats = max(counts.values(), default=0)
        if repeats >= 24:
            raise JobExecutionError("editorial_source_repetition", {
                "transcript_id": prepared["snapshot"]["base"]["transcript_id"],
                "segment_ordinal": ordinal, "start_ms": segment["start_ms"],
                "end_ms": segment["end_ms"], "characters": len(text),
                "repeated_fourgram_count": repeats,
            })
