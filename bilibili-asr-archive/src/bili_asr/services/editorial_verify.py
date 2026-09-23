"""Pure candidate verifier: strings in, verdict out.

No I/O of any kind: the caller reads the candidate document, the two routes and the
sidecar hotwords and passes them in as strings; this module only inspects them. Two
consequences worth knowing:

* a malformed candidate is a ``Verdict``, never an exception -- the CLI must never
  fail hard on a bad artifact;
* everything is parsed from the text alone, so the path-site prefix in a
  ``Violation.location`` is the candidate's own ``work_id`` (or ``candidate`` when it
  declares none), because no file name reaches this module.

Line numbering, 1-based, each site reporting its own space:

* frontmatter key sites (identity) -- counted in the document, opening ``---`` on
  line 1, so ``work_id`` sits on line 2 in the canonical shape;
* body sites -- the line's index within ``CandidateFacts.body_lines`` plus one;
* record-table sites -- ``row <n>``, the 1-based index of the data row.

Seat 2a1 delivers the rule vocabulary, ``parse_candidate``, the text-only checks
(identity, marker vocabulary, marker/record parity) and the verdict/closing lines.
The three remaining checks -- ``check_change_evidence``, ``check_containment`` and
``check_hotword_screen`` -- are stubs returning ``()``, implemented in the next seat;
``MAX_COMPARE_CHARS`` and ``FLOOR`` are already declared for them.
"""

from __future__ import annotations

import re
from typing import NamedTuple, Sequence

__all__ = [
    "ADVISORY_RULE_IDS",
    "CandidateFacts",
    "ERROR_RULE_IDS",
    "E_RULE_IDS",
    "FLOOR",
    "MAX_COMPARE_CHARS",
    "Verdict",
    "Violation",
    "check_change_evidence",
    "check_containment",
    "check_hotword_screen",
    "check_identity",
    "check_marker_record_parity",
    "check_marker_vocabulary",
    "closing_line",
    "parse_candidate",
    "verdict_line",
    "verify_candidate",
]

#: The whole refusal vocabulary, in report order (errors first, advisories last).
E_RULE_IDS: tuple[str, ...] = (
    "accounting_invalid",
    "marker_parity",
    "evidence_missing",
    "char_outside_routes",
    "hotword_disagreement",
    "timestamp_in_body",
    "insertion_unexplained",
    "deletion_unclassified",
    "term_guard_tripped",
    "twin_not_retained",
    "seam_break",
    "concat_mismatch",
    "identity_mismatch",
    "part_missing",
    "route_absent_for_part",
    "hotword_screen_vacuous",
)

#: 14 ids flip the verdict; the 2 advisories print a warning line and are ignored.
ERROR_RULE_IDS: tuple[str, ...] = E_RULE_IDS[:14]
ADVISORY_RULE_IDS: tuple[str, ...] = E_RULE_IDS[14:]

#: Route-comparison budget per side, consumed by ``check_hotword_screen``.
MAX_COMPARE_CHARS = 20_000
#: ``difflib`` ratio below which the two routes count as disagreeing.
FLOOR = 0.95


class Violation(NamedTuple):
    rule: str          # one of E_RULE_IDS
    location: str      # "<basename>:<line>" for path sites; "[hh:mm:ss]" or "cue #<i>" for route sites
    advisory: bool     # True = warning line, does not affect verdict/exit


class CandidateFacts(NamedTuple):
    work_id: str | None
    bvid: str | None
    body_lines: tuple[str, ...]                # body only, 1-based line numbers = index+1
    marks: tuple[str, ...]                     # every rejection mark found in the body, in order
    record_rows: tuple[tuple[str, ...], ...]   # the 校对记录 data rows, cells stripped
    counts: dict[str, int]                     # the numeric frontmatter keys actually present


class Verdict(NamedTuple):
    ok: bool
    violations: tuple[Violation, ...]
    body_chars: int
    marks: int
    record_rows: int


# --- document shape -----------------------------------------------------------------

#: The record table's columns, fixed by the candidate header
#: ``| # | 时间 | 原 ASR | AI 字幕 | 定稿 | 依据 |``.
FINAL_COL = 4
EVIDENCE_COL = 5

_FRONTMATTER_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
_H1_RE = re.compile(r"^#(?!#)\s+\S")
_LEGEND_RE = re.compile(r"^>")
_RECORD_HEADING_RE = re.compile(r"^##\s*校对记录\s*$")
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
_INTEGER_RE = re.compile(r"^[+-]?\d+$")

#: Canonical frontmatter order (see the candidate shape). The identity check can only
#: see parsed facts, so it locates a key by this declared order rather than by the
#: text; reorder the frontmatter of a candidate and the reported line follows the
#: canonical shape, not the file -- known limitation, see the task report.
_FRONTMATTER_KEY_ORDER: tuple[str, ...] = (
    "work_id",
    "bvid",
    "title",
    "blocks",
    "asr_segments",
    "caption_cues",
)
_FIRST_FRONTMATTER_KEY_LINE = 2  # line 1 is the opening fence

MARK_GLYPHS: tuple[str, ...] = ("‹", "›", "〔", "〕")
_MARK_PAIR_RE = re.compile(r"[‹〔]([^‹›〔〕\n]*)[›〕]")
_MARK_MATE = {"‹": "›", "〔": "〕"}


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    return raw


def _scan_marks(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split one line/cell into (rejection marks, unlisted mark-like tokens)."""
    marks: list[str] = []
    unlisted: list[str] = []
    for match in _MARK_PAIR_RE.finditer(text):
        whole = match.group(0)
        if _MARK_MATE[whole[0]] != whole[-1]:
            unlisted.append(whole)   # a mixed pair is not one normalised vocabulary
        else:
            marks.append(whole)
    leftover = _MARK_PAIR_RE.sub("", text)
    unlisted.extend(ch for ch in leftover if ch in MARK_GLYPHS)
    return tuple(marks), tuple(unlisted)


def _normalise_mark(token: str) -> str:
    """One internal form for both glyph families, for comparisons only."""
    if len(token) >= 2 and token[0] in MARK_GLYPHS and token[-1] in MARK_GLYPHS:
        return f"‹{token[1:-1]}›"
    return token


def _normalise(text: str) -> str:
    """Flatten: drop whitespace and punctuation, keep letters and digits."""
    return re.sub(r"[\W_]+", "", text)


def _path_prefix(candidate: CandidateFacts) -> str:
    return candidate.work_id or "candidate"


def _frontmatter_key_line(key: str) -> int:
    if key in _FRONTMATTER_KEY_ORDER:
        return _FIRST_FRONTMATTER_KEY_LINE + _FRONTMATTER_KEY_ORDER.index(key)
    return _FIRST_FRONTMATTER_KEY_LINE


def _split_frontmatter(lines: list[str]) -> tuple[dict[str, str], dict[str, int], int]:
    """Return (frontmatter strings, numeric counts, index of the first body line)."""
    if not lines or lines[0].strip() != "---":
        return {}, {}, 0
    values: dict[str, str] = {}
    counts: dict[str, int] = {}
    index = 1
    while index < len(lines) and lines[index].strip() != "---":
        match = _FRONTMATTER_KV_RE.match(lines[index])
        if match:
            key, raw = match.group(1), match.group(2).strip()
            values[key] = _unquote(raw)
            plain = _unquote(raw)
            if _INTEGER_RE.match(plain):
                counts[key] = int(plain)
        index += 1
    if index < len(lines):
        index += 1  # step over the closing fence
    return values, counts, index


def _split_body(lines: list[str], start: int) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Return (body lines, record-table data rows)."""
    index = start
    while index < len(lines) and not _H1_RE.match(lines[index]):
        index += 1
    if index < len(lines):
        index += 1  # step over the H1
    while index < len(lines) and (not lines[index].strip() or _LEGEND_RE.match(lines[index])):
        index += 1

    body: list[str] = []
    while index < len(lines) and not _RECORD_HEADING_RE.match(lines[index]):
        body.append(lines[index])
        index += 1
    while body and not body[-1].strip():
        body.pop()

    rows: list[tuple[str, ...]] = []
    if index < len(lines):
        index += 1  # step over the record heading
        table: list[str] = []
        while index < len(lines) and _TABLE_ROW_RE.match(lines[index]):
            table.append(lines[index])
            index += 1
        for position, raw in enumerate(table):
            if position == 0:
                continue  # the header row, by construction the table's first row
            cells = tuple(cell.strip() for cell in raw.strip().strip("|").split("|"))
            if all(_SEPARATOR_CELL_RE.match(cell) for cell in cells if cell != ""):
                continue  # the header separator
            rows.append(cells)
    return tuple(body), tuple(rows)


def parse_candidate(text: str) -> CandidateFacts:
    """Read a candidate document into its facts. Never raises."""
    if not isinstance(text, str):
        text = ""
    lines = text.splitlines()
    values, counts, body_start = _split_frontmatter(lines)
    body_lines, record_rows = _split_body(lines, body_start)

    marks: list[str] = []
    for line in body_lines:
        line_marks, _unlisted = _scan_marks(line)
        marks.extend(line_marks)

    return CandidateFacts(
        work_id=values.get("work_id"),
        bvid=values.get("bvid"),
        body_lines=body_lines,
        marks=tuple(marks),
        record_rows=record_rows,
        counts=counts,
    )


def _mark_sites(candidate: CandidateFacts) -> tuple[tuple[int, str], ...]:
    """Every body mark with its 1-based body line, in order."""
    sites: list[tuple[int, str]] = []
    for index, line in enumerate(candidate.body_lines):
        line_marks, _unlisted = _scan_marks(line)
        for mark in line_marks:
            sites.append((index + 1, mark))
    return tuple(sites)


def _row_has_mark(row: tuple[str, ...]) -> bool:
    if len(row) <= FINAL_COL:
        return False
    marks, _unlisted = _scan_marks(row[FINAL_COL])
    return bool(marks)


# --- the text-only checks -----------------------------------------------------------


def check_identity(candidate: CandidateFacts, *, work_id: str, bvid: str) -> tuple[Violation, ...]:
    """The candidate's own frontmatter ids must equal the selector."""
    prefix = _path_prefix(candidate)
    selector_id = work_id or ""
    selector_bvid = bvid or (selector_id.split(":", 1)[0] if selector_id else "")
    own_id = candidate.work_id or ""
    own_bvid = candidate.bvid or ""

    violations: list[Violation] = []
    id_ok = own_id == selector_id or (":" not in selector_id and own_id == selector_bvid)
    if selector_id and not id_ok:
        violations.append(
            Violation("identity_mismatch", f"{prefix}:{_frontmatter_key_line('work_id')}", False)
        )
    if selector_bvid and own_bvid != selector_bvid:
        violations.append(
            Violation("identity_mismatch", f"{prefix}:{_frontmatter_key_line('bvid')}", False)
        )
    return tuple(violations)


def check_marker_vocabulary(candidate: CandidateFacts) -> tuple[Violation, ...]:
    """Every mark-like token in the body must be one normalised vocabulary."""
    prefix = _path_prefix(candidate)
    violations: list[Violation] = []
    for index, line in enumerate(candidate.body_lines):
        _marks, unlisted = _scan_marks(line)
        for _token in unlisted:
            violations.append(Violation("marker_parity", f"{prefix}:{index + 1}", False))
    return tuple(violations)


def check_marker_record_parity(candidate: CandidateFacts) -> tuple[Violation, ...]:
    """Body marks and 校对记录 rows must pair up, in both directions."""
    prefix = _path_prefix(candidate)
    sites = _mark_sites(candidate)
    rows = candidate.record_rows
    counts = f"(body_marks={len(sites)}, record_rows={len(rows)})"

    if len(sites) > len(rows):
        line = sites[len(rows)][0]
        return (Violation("marker_parity", f"{prefix}:{line} {counts}", False),)

    violations: list[Violation] = []
    for ordinal in range(len(sites), len(rows)):
        if _row_has_mark(rows[ordinal]):
            violations.append(
                Violation("marker_parity", f"{prefix}:row {ordinal + 1} {counts}", False)
            )
    if not violations and len(rows) > len(sites):
        violations.append(
            Violation("marker_parity", f"{prefix}:row {len(sites) + 1} {counts}", False)
        )
    return tuple(violations)


def check_change_evidence(candidate: CandidateFacts) -> tuple[Violation, ...]:
    """Every record row asserting a change must name its evidence. Stub -- implemented in the next seat."""
    return ()  # implemented in the next seat


def check_containment(candidate: CandidateFacts, asr_text: str,
                      caption_text: str) -> tuple[Violation, ...]:
    """Every body character must live in ASR or caption. Stub -- implemented in the next seat."""
    return ()  # implemented in the next seat


def check_hotword_screen(candidate: CandidateFacts, asr_text: str, caption_text: str,
                         hotwords: Sequence[str]) -> tuple[Violation, ...]:
    """Where the routes disagree, a hotword token must be named as an inference. Stub -- next seat."""
    return ()  # implemented in the next seat


# --- assembly -----------------------------------------------------------------------


def verify_candidate(candidate_text: str, *, work_id: str, bvid: str, reference: str,
                     asr_text: str, caption_text: str, hotwords: Sequence[str]) -> Verdict:
    """Run every check and reduce them to a verdict. Never raises for a bad candidate."""
    candidate = parse_candidate(candidate_text)
    selector_id = reference or work_id
    selector_bvid = bvid or (selector_id.split(":", 1)[0] if selector_id else "")

    violations: list[Violation] = []
    for check in (
        lambda: check_identity(candidate, work_id=selector_id, bvid=selector_bvid),
        lambda: check_marker_vocabulary(candidate),
        lambda: check_marker_record_parity(candidate),
        lambda: check_change_evidence(candidate),
        lambda: check_containment(candidate, asr_text, caption_text),
        lambda: check_hotword_screen(candidate, asr_text, caption_text, hotwords),
    ):
        try:
            violations.extend(check())
        except Exception:  # a bad candidate degrades to a verdict, never an exception
            continue

    errors = [v for v in violations if not v.advisory]
    body_chars = len(_normalise("\n".join(candidate.body_lines)))
    return Verdict(
        ok=not errors,
        violations=tuple(violations),
        body_chars=body_chars,
        marks=len(candidate.marks),
        record_rows=len(candidate.record_rows),
    )


def verdict_line(work_id: str, verdict: Verdict) -> str:
    """One report line: the ok summary, or one line per violation, errors first."""
    if not verdict.violations:
        return (
            f"{work_id}: ok (body_chars={verdict.body_chars} marks={verdict.marks} "
            f"record_rows={verdict.record_rows})"
        )

    order = {rule: index for index, rule in enumerate(E_RULE_IDS)}
    rank = lambda violation: order.get(violation.rule, len(order))  # noqa: E731
    errors = sorted((v for v in verdict.violations if not v.advisory), key=rank)
    advisories = sorted((v for v in verdict.violations if v.advisory), key=rank)

    lines = [f"{work_id}: refused ({v.rule}) at {v.location}" for v in errors]
    lines.extend(f"{work_id}: warning ({v.rule}) at {v.location}" for v in advisories)
    return "\n".join(lines)


def closing_line(command: str, total: int, ok: int, refused: int) -> str:
    """The run's summary line, e.g. ``verify-proofread: candidates=3 ok=2 refused=1``."""
    return f"{command}: candidates={total} ok={ok} refused={refused}"
