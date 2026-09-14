"""Deterministic, read-only subtitle and transcript artifact quality signals."""

from __future__ import annotations

import collections
import difflib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, NamedTuple

from .archive import LOW_CONFIDENCE, archive_stem
from .asr import _FORBIDDEN_PROVENANCE as _FORBIDDEN_MARKER
from .page_identity import artifact_stem, page_identity, parse_work_id

#: Reasons that describe a structural defect: an artifact is missing, unreadable,
#: or internally inconsistent.  Only these make a work item invalid.
DEFECT_REASON_CODES = (
    "empty",
    "malformed",
    "non_monotonic",
    "overlap",
    "out_of_range",
    "identity_mismatch",
    "artifact_missing",
)
#: Reasons that record what the recorded content measures.  They are advisory:
#: they describe the transcript, never that the archive is broken, so they leave
#: the validity count and the exit status alone.
CONTENT_REASON_CODES = (
    "low_confidence",
    "leading_mark",
    "fragment_cue",
    "overlong_cue",
    "duplicate_cue",
    "repeated_ngram",
    "reference_disagreement",
)
#: The ordered vocabulary.  The seven defect codes keep their original positions,
#: so existing output keeps its spelling and its sort order.
REASON_CODES = DEFECT_REASON_CODES + CONTENT_REASON_CODES
#: A cue never opens on one of these marks, and a fragment is measured after
#: stripping them.  This is the retired report's own mark set, not the wider one
#: :mod:`bili_asr.asr` shapes cues with (``!``, ``?``, ``,``, ``;`` and ``:``
#: are absent here), so the two are deliberately not the same value.
LEADING = "，。！？、；："
#: Content thresholds, matching the cue shaping bounds in :mod:`bili_asr.asr`
#: (``_CUE_MAX_CHARS`` / ``_CUE_MIN_CHARS`` / ``_CUE_MIN_SECONDS``) so a cue the
#: shaper sized is reported only when it could not be merged into a neighbour.
OVERLONG_CHARS = 60
FRAGMENT_MAX_CHARS = 6
FRAGMENT_MAX_SECONDS = 1.0
#: Two transcripts of the same audio agreeing below this ratio is the
#: ``reference_disagreement`` signal — the systems contested the audio.
REFERENCE_AGREEMENT_FLOOR = 0.95
#: Marks stripped before two transcripts are compared, so punctuation and
#: spacing differences never read as disagreement.  Kept identical to the set
#: the retired standalone quality report used, so recorded agreement ratios
#: stay comparable across the merge.
_REFERENCE_PUNCT = "。，？！、；：,?!.;:…—·\"'“”‘’（）()《》"
_REFERENCE_STRIP = re.compile(f"[{re.escape(_REFERENCE_PUNCT)}]")
#: The published ``.md`` bundle opens with a YAML frontmatter block carrying the
#: title, the bilibili URL, and the work's identity.  That block is metadata,
#: never transcript text, so it is dropped before a plain-text artifact is
#: flattened for comparison.  A closing ``---`` line is required, so a lone
#: leading ``---`` in a transcript stays where it is.
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
#: Repeated-ngram detection: every ``_NGRAM_CHARS``-character window that
#: occurs ``_NGRAM_MIN_REPEATS`` times or more.  Eight characters is the retired
#: report's window, and both figures are pinned from both sides by
#: ``test_ngram_window_is_the_pinned_eight_characters``.
_NGRAM_CHARS = 8
_NGRAM_MIN_REPEATS = 3
_MAX_BYTES = 8 * 1024 * 1024
_MAX_CUES = 10_000
#: How much flattened text either transcript may hold before the comparison is
#: refused.  ``_MAX_BYTES`` bounds the reference's *bytes*, which is not the
#: same thing as the *work* of comparing them: with ``autojunk`` off — the
#: setting that keeps recorded ratios comparable, so it is not negotiable — a
#: pair of long, near-identical, low-entropy strings, which is exactly what two
#: transcripts of the same audio are, costs super-linearly.  Measured on this
#: host by tiling real transcript text to length and injecting 2–20 % edits:
#: 4 000 characters per side ≈ 6 s, 8 000 ≈ 53 s, 12 000 ≈ 136 s, 16 000 ≈ 323 s
#: (worst cases), while 10 000 ≈ 6 s and 20 000 ≈ 37 s on the same generator.
#: The byte cap alone admits ~2.7 M characters per side, i.e. hours of CPU with
#: no output; this bound caps the work at tens of seconds worst case.
#: Real transcripts are far smaller: the recorded 448 s probe flattens to 2 098
#: characters per side (~280 per minute of audio), so the longest row in this
#: archive (1 115 s) is ≈5 200 and this bound covers ≈70 minutes of audio — every
#: real comparison here, with several times the headroom.  The trade-off is
#: deliberate and stated: a near-identical pair of *very* long transcripts is
#: refused rather than measured, because a ratio nobody can wait for is not a
#: measurement, and the refusal is loud (stderr + exit 1), never silent.
_MAX_COMPARE_CHARS = 20_000
#: Credential-like words as they can appear in a *file name*.  A marker's
#: trailing ``\b`` cannot end the match after an underscore (``_`` is a word
#: character), so ``token_abc123.srt`` escaped it while ``token-abc123.srt`` did
#: not.  A name may join its words with either separator, so this scan supplies
#: that boundary: the marker opens at the start of the name or after a
#: letter-free separator, and must not run into a following letter — every
#: separator form redacts, while an ordinary word such as ``tokenizer`` is left
#: alone.  ``asr._FORBIDDEN_PROVENANCE`` now carries the *same* separator-aware
#: boundary (plan QC F-001: the old one published ``myorg/token_abc`` verbatim),
#: so for credentials this scan is a redundant second opinion at the site that
#: reads names; it stays because it states the name-level rule where names are
#: read.
_NAME_CREDENTIAL = re.compile(
    r"(?:^|[^A-Za-z])(?:sessdata|cookie|token|password|secret|credential)(?![A-Za-z])",
    re.IGNORECASE,
)
_SRT_TIME = re.compile(
    r"^(?P<h>\d{1,3}):(?P<m>[0-5]\d):(?P<s>[0-5]\d)[,.](?P<ms>\d{1,3})$"
)


class Cue(NamedTuple):
    """One cue, as the single parser reads it from any artifact shape.

    ``confidence`` is the model's own per-cue score when the artifact records it
    (the raw sidecar does, an SRT does not); ``None`` means not recorded, never
    "low".
    """

    start: float
    end: float
    text: str
    confidence: float | None


class ReferenceUnavailable(ValueError):
    """A supplied reference transcript cannot be used for comparison.

    ``reason`` is a bounded, redaction-safe scalar so the caller reports a
    diagnostic instead of crashing on the reference.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ReferenceAgreement(NamedTuple):
    """One transcript compared against a second transcript of the same audio.

    ``reference`` is the reference's **basename only** — the operator's path,
    its parents, and any URL- or credential-shaped name never leave here.
    """

    reference: str
    agreement: float
    floor: float
    compared_chars: tuple[int, int]


@dataclass(frozen=True)
class QualityResult:
    """Stable projection of quality observations for one manifest row.

    ``reasons`` holds defect codes only, so validity counts and exit status read
    from it unchanged.  ``content_reasons`` holds the advisory content codes and
    never affects either.
    """

    source: str | None
    language: str | None
    status: str | None
    cue_count: int
    artifact_count: int
    reasons: tuple[str, ...]
    diagnostics: tuple[str, ...]
    content_reasons: tuple[str, ...] = ()
    reference: ReferenceAgreement | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "language": self.language,
            "status": self.status,
            "cue_count": self.cue_count,
            "artifact_count": self.artifact_count,
            "reasons": list(self.reasons),
            "diagnostics": list(self.diagnostics),
        }


class QualityAnalyzer:
    """Inspect local subtitle/archive artifacts without changing them."""

    def analyze(
        self,
        row: Mapping[str, object],
        archive_root: Path,
        reference: Path | None = None,
    ) -> QualityResult:
        """Measure one manifest row's artifacts.

        ``reference`` is an optional second transcript of the same audio.  It is
        compared against the row's own transcript: the best comparable text
        among the row's artifacts, which is the archived SRT when one exists and
        otherwise a cue sidecar or the plain transcript, with the published
        ``.md`` bundle as the last resort.  A reference that cannot be read
        raises :class:`ReferenceUnavailable`; it never degrades into a silent
        "no comparison".
        """

        reasons: set[str] = set()
        diagnostics: set[str] = set()
        content_reasons: set[str] = set()
        artifacts = _artifact_paths(row, archive_root)
        cue_count = 0
        valid_artifacts = 0
        transcript: str | None = None
        # The best comparison source seen so far, as a rank: a cue-bearing
        # artifact (3) outranks a plain transcript (2), and both outrank the
        # published ``.md`` bundle (1), whose comparable text is its body rather
        # than the artifact it publishes.  Only a strictly better artifact
        # replaces the current source, so equal ranks keep the archived SRT.
        transcript_rank = 0
        if not artifacts:
            reasons.add("artifact_missing")
        for path in artifacts:
            if not _contained(path, archive_root) or not path.is_file():
                reasons.add("artifact_missing")
                continue
            try:
                if path.stat().st_size > _MAX_BYTES:
                    reasons.add("malformed")
                    diagnostics.add("file_too_large")
                    continue
                text = path.read_text(encoding="utf-8")
                cues, malformed, empty = _read_cues(path, text)
            except (OSError, UnicodeError):
                reasons.add("malformed")
                diagnostics.add("unreadable")
                continue
            valid_artifacts += 1
            cue_count = min(_MAX_CUES, cue_count + len(cues))
            rank = _transcript_rank(path, cues)
            if rank > transcript_rank:
                candidate = comparable_text(text, cues)
                if candidate:
                    transcript, transcript_rank = candidate, rank
            if malformed:
                reasons.add("malformed")
            if empty:
                reasons.add("empty")
            _check_cues(cues, row, reasons)
            _check_content(cues, content_reasons)
            _check_identity(path, text, row, reasons)
        agreement = (
            None
            if reference is None
            else _compare_reference(reference, transcript or "")
        )
        if agreement is not None and agreement.agreement < agreement.floor:
            content_reasons.add("reference_disagreement")
        return QualityResult(
            source=_text_value(row, "source", "subtitle_source"),
            language=_text_value(row, "language", "sub_lan", "subtitle_language"),
            status=_text_value(row, "status"),
            cue_count=cue_count,
            artifact_count=valid_artifacts,
            reasons=tuple(sorted(reasons, key=REASON_CODES.index)),
            diagnostics=tuple(sorted(diagnostics)[:8]),
            content_reasons=tuple(sorted(content_reasons, key=REASON_CODES.index)),
            reference=agreement,
        )


def _text_value(row: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _canonical_stem(row: Mapping[str, object]) -> str | None:
    bvid = _text_value(row, "bvid")
    if row.get("unresolved"):
        return bvid
    work_id = _text_value(row, "work_id")
    if work_id:
        try:
            bvid_part, page_index = parse_work_id(work_id)
            ident = page_identity(
                bvid_part,
                page_index,
                cid=int(row.get("cid") or 0),
                page_label=str(row.get("page_label") or ""),
            )
            return artifact_stem(ident)
        except ValueError:
            return work_id
    if bvid and row.get("cid") is not None:
        try:
            return archive_stem(dict(row))
        except (KeyError, TypeError, ValueError):
            pass
    return bvid


def _artifact_paths(row: Mapping[str, object], root: Path) -> list[Path]:
    values: list[object] = []
    for key in (
        "subtitle_path",
        "srt_path",
        "txt_path",
        "md_path",
        "raw_path",
        "artifact_path",
    ):
        if row.get(key) is not None:
            values.append(row[key])
    paths = row.get("artifact_paths")
    if isinstance(paths, (list, tuple)):
        values.extend(paths)
    inferred = not values
    if inferred:
        stem = _canonical_stem(row)
        if stem:
            values.extend(
                (
                    Path("transcripts/srt") / f"{stem}.srt",
                    Path("transcripts/txt") / f"{stem}.txt",
                    Path("transcripts/raw") / f"{stem}.json",
                    Path("subtitles/raw") / f"{stem}.json",
                )
            )
            # The derived ``.md`` bundle is appended last: its body is the
            # transcript, but a transcript artifact outranks it as the
            # comparison source.
            md_dir = root / "transcripts" / "md"
            if md_dir.is_dir():
                exact_md = md_dir / f"{stem}.md"
                if exact_md.is_file():
                    values.append(exact_md)
                pubdate = str(row.get("pubdate_str") or "")
                pattern = f"{pubdate}_{stem}_*.md" if pubdate else f"*_{stem}_*.md"
                for md_file in sorted(md_dir.glob(pattern)):
                    if md_file.is_file():
                        values.append(md_file)
    result: list[Path] = []
    for value in values:
        if isinstance(value, (str, Path)) and value:
            path = Path(value)
            resolved = path if path.is_absolute() else root / path
            if inferred and not resolved.exists():
                continue
            result.append(resolved)
    if inferred and not result and values:
        result.append(root / values[0])
    return list(dict.fromkeys(result))


def _contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def flatten_reference(text: str) -> str:
    """Strip punctuation and spacing so punctuation never reads as disagreement."""

    return _REFERENCE_STRIP.sub("", text).replace(" ", "").lower()


def _transcript_rank(path: Path, cues: list[Cue]) -> int:
    """How well one artifact serves as the row's transcript for comparison.

    Cue-bearing artifacts rank highest because their cue texts are the
    transcript itself; a plain transcript ranks next; the published ``.md``
    bundle ranks last, since its comparable text is its body rather than the
    artifact it publishes.  An artifact whose text is carried by cues — an SRT
    or a cue sidecar — that yielded none holds no transcript at all: its own
    source is timing lines and JSON structure, so it ranks zero and can never
    displace a real transcript.
    """

    if cues:
        return 3
    if path.suffix.lower() in {".srt", ".json"}:
        return 0
    if path.suffix.lower() == ".md":
        return 1
    return 2


def comparable_text(text: str, cues: list[Cue]) -> str:
    """One transcript's text, flattened for cross-transcript comparison.

    A cue-structured artifact contributes its cue texts through the same cue
    parser as everything else; a plain-text artifact (``.txt``/``.md``) has no
    cue structure, so its non-blank lines are its text — the reading the
    retired standalone quality report used for the same inputs.  A leading YAML
    frontmatter block is metadata rather than text and is dropped first, so a
    published ``.md`` bundle compares by its body rather than by its title and
    URL.
    """

    if cues:
        return flatten_reference("".join(cue.text for cue in cues))
    body = _FRONTMATTER.sub("", text, count=1)
    return flatten_reference(
        "".join(line.strip() for line in body.splitlines() if line.strip())
    )


def reference_basename(path: Path) -> str:
    """The reference's basename, or ``[redacted]`` when even that leaks.

    The operator's directory layout stays out of the report; a name that is
    itself URL- or credential-shaped is replaced too, so no path, URL, or
    credential-like value can reach the output.  The provenance marker alone is
    not enough for a *name*: its trailing ``\\b`` never fires after an
    underscore, which is how ``token_abc123.srt`` was published while
    ``token-abc123.srt`` was redacted, so a name-level scan treats both
    separators alike.
    """

    name = path.name
    if not name or _FORBIDDEN_MARKER.search(name) or _NAME_CREDENTIAL.search(name):
        return "[redacted]"
    return name


def _compare_reference(
    reference: Path, transcript: str
) -> ReferenceAgreement | None:
    """Compare the row's transcript against a second transcript of the same audio.

    Both sides are flattened before a bounded ratio is computed, and the
    reference's own text is never echoed — only its basename and the two
    character counts leave this function.  Returns ``None`` when the row has no
    comparable text: that is the row's own defect (``empty``/``artifact_missing``
    already reports it), not a fault of the supplied reference.

    ``_MAX_BYTES`` bounds the reference's bytes but not the *work* of comparing
    it, so the flattened pair is bounded too.  A pair whose flattened text
    exceeds :data:`_MAX_COMPARE_CHARS` per side is refused rather than compared:
    with ``autojunk`` off, a long low-entropy pair costs minutes to hours, and a
    ratio nobody can wait for is not a measurement.  The refusal reuses the
    reference path's own diagnostic — stderr plus exit 1, never a silent no-op —
    and names the side that tripped it, since either transcript can be the large
    one.
    """

    try:
        if reference.stat().st_size > _MAX_BYTES:
            raise ReferenceUnavailable("reference too large")
        text = reference.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReferenceUnavailable("reference unreadable") from exc
    other, malformed, empty = _read_cues(reference, text)
    if reference.suffix.lower() == ".json" and (malformed or empty):
        # A JSON reference is a cue sidecar: one that does not parse, or that
        # carries no segment, has no transcript to compare.  Comparing its own
        # source text would invent a near-zero ratio — the silent wrong answer
        # this exception exists to prevent — so it is refused like any other
        # unreadable reference.  A blank ``.txt``/``.srt`` is not a sidecar and
        # keeps its own, more precise diagnostic below.
        raise ReferenceUnavailable("reference unreadable")
    theirs = comparable_text(text, other)
    if not theirs:
        raise ReferenceUnavailable("reference has no comparable text")
    if not transcript:
        return None
    # The bound is checked per side and named for the side it caught: a row's
    # own flattened text is bounded separately (``_MAX_CUES`` caps cues, not the
    # ``.txt`` arm), so blaming the reference for a large row would send the
    # operator after the wrong file.
    if len(theirs) > _MAX_COMPARE_CHARS:
        raise ReferenceUnavailable("reference too large to compare")
    if len(transcript) > _MAX_COMPARE_CHARS:
        raise ReferenceUnavailable("transcript too large to compare")
    ratio = difflib.SequenceMatcher(
        None, transcript, theirs, autojunk=False
    ).ratio()
    return ReferenceAgreement(
        reference=reference_basename(reference),
        agreement=ratio,
        floor=REFERENCE_AGREEMENT_FLOOR,
        compared_chars=(len(transcript), len(theirs)),
    )


def _read_cues(path: Path, text: str) -> tuple[list[Cue], bool, bool]:
    if not text.strip():
        return [], False, True
    if path.suffix.lower() == ".srt":
        cues: list[Cue] = []
        malformed = False
        blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            timing = next((line for line in lines if "-->" in line), None)
            if timing is None:
                malformed = True
                continue
            parts = [part.strip() for part in timing.split("-->", 1)]
            if len(parts) != 2:
                malformed = True
                continue
            start, end = _parse_time(parts[0]), _parse_time(parts[1])
            if start is None or end is None:
                malformed = True
            else:
                cues.append(Cue(start, end, _cue_text(lines, timing), None))
        return cues[:_MAX_CUES], malformed, not cues
    if path.suffix.lower() == ".json":
        try:
            document = json.loads(text)
        except (ValueError, TypeError):
            return [], True, False
        if isinstance(document, dict):
            if "body" in document and isinstance(document["body"], list):
                items = document["body"]
            elif "segments" in document and isinstance(document["segments"], list):
                items = document["segments"]
            else:
                return [], True, False
        elif isinstance(document, list):
            items = document
        else:
            return [], True, False
        cues = []
        malformed = False
        for item in items[:_MAX_CUES]:
            if not isinstance(item, dict):
                malformed = True
                continue
            start_raw = item.get("from") if "from" in item else item.get("start")
            end_raw = item.get("to") if "to" in item else item.get("end")
            if start_raw is None or end_raw is None:
                malformed = True
                continue
            try:
                start, end = float(start_raw), float(end_raw)
            except (TypeError, ValueError):
                malformed = True
                continue
            if not (math.isfinite(start) and math.isfinite(end)):
                malformed = True
                continue
            cues.append(Cue(start, end, _text_of(item), _confidence_of(item)))
        return cues, malformed, not cues
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [], False, not lines


def _cue_text(lines: list[str], timing: str) -> str:
    """The cue's text: every line after the timing line, joined.

    Taking the lines *after* the timing line — rather than dropping digit-only
    lines — keeps a cue whose text is itself a number.
    """

    index = lines.index(timing)
    return " ".join(lines[index + 1 :])


def _text_of(item: Mapping[str, object]) -> str:
    value = item.get("text")
    if value is None:
        value = item.get("content")
    return "" if value is None else str(value)


def _confidence_of(item: Mapping[str, object]) -> float | None:
    value = item.get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    score = float(value)
    return score if math.isfinite(score) else None


def _parse_time(value: str) -> float | None:
    match = _SRT_TIME.match(value)
    if not match:
        return None
    return (
        int(match["h"]) * 3600
        + int(match["m"]) * 60
        + int(match["s"])
        + int(match["ms"].ljust(3, "0")) / 1000
    )


def _check_cues(
    cues: list[Cue], row: Mapping[str, object], reasons: set[str]
) -> None:
    duration = row.get("duration_s")
    maximum: float | None = None
    if isinstance(duration, (int, float)):
        try:
            d = float(duration)
            if d >= 0 and math.isfinite(d):
                maximum = d
        except (TypeError, ValueError):
            pass
    previous_start = -1.0
    previous_end = -1.0
    for cue in cues:
        start, end = cue.start, cue.end
        if not (math.isfinite(start) and math.isfinite(end)):
            reasons.add("malformed")
            reasons.add("out_of_range")
            continue
        if start < 0 or end < 0 or end <= start:
            reasons.add("out_of_range")
        if start < previous_start:
            reasons.add("non_monotonic")
        if start < previous_end:
            reasons.add("overlap")
        if maximum is not None and end > maximum + 0.001:
            reasons.add("out_of_range")
        previous_start, previous_end = start, end


def _check_content(cues: list[Cue], reasons: set[str]) -> None:
    """Record what the transcript's content measures.  Advisory, never a defect."""

    if any(
        cue.confidence is not None and cue.confidence <= LOW_CONFIDENCE
        for cue in cues
    ):
        reasons.add("low_confidence")
    if any(cue.text and cue.text[:1] in LEADING for cue in cues):
        reasons.add("leading_mark")
    if any(
        len(cue.text.strip(LEADING)) < FRAGMENT_MAX_CHARS
        and (cue.end - cue.start) < FRAGMENT_MAX_SECONDS
        for cue in cues
    ):
        reasons.add("fragment_cue")
    if any(len(cue.text) > OVERLONG_CHARS for cue in cues):
        reasons.add("overlong_cue")
    texts = [cue.text for cue in cues]
    if any(bool(text) and text == other for text, other in zip(texts, texts[1:])):
        reasons.add("duplicate_cue")
    joined = "".join(texts)
    grams = collections.Counter(
        joined[index : index + _NGRAM_CHARS]
        for index in range(max(0, len(joined) - _NGRAM_CHARS))
    )
    if any(count >= _NGRAM_MIN_REPEATS for count in grams.values()):
        reasons.add("repeated_ngram")


def _check_identity(
    path: Path, text: str, row: Mapping[str, object], reasons: set[str]
) -> None:
    stem = _canonical_stem(row)
    expected_work_id = _text_value(row, "work_id")
    expected_bvid = _text_value(row, "bvid")

    if stem and path.name:
        if path.suffix.lower() in {".srt", ".json", ".txt", ".md"}:
            if stem not in path.name:
                reasons.add("identity_mismatch")

    if path.suffix.lower() == ".md":
        work_id_match = re.search(
            r"^work_id:\s*[\"']?([^\"'\n\r]+)[\"']?", text, re.MULTILINE
        )
        if work_id_match:
            md_work_id = work_id_match.group(1).strip()
            if expected_work_id and md_work_id != expected_work_id:
                reasons.add("identity_mismatch")

        bvid_match = re.search(
            r"^bvid:\s*[\"']?([^\"'\n\r]+)[\"']?", text, re.MULTILINE
        )
        if bvid_match:
            md_bvid = bvid_match.group(1).strip()
            if expected_bvid and md_bvid != expected_bvid:
                reasons.add("identity_mismatch")
