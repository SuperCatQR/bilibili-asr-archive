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
(identity, marker vocabulary, marker/record parity) and the verdict/closing lines;
seat 2a2 delivers the three route-dependent checks -- ``check_change_evidence``,
``check_containment`` and ``check_hotword_screen`` -- which take the two routes (and
the sidecar hotwords) as arguments. ``MAX_COMPARE_CHARS`` caps each compared side of
the hotword screen; ``FLOOR`` is its disagreement threshold.

The structural model (annex amendment 1, ruling R1) is the corpus's own, validated
against the six finished candidates' documented ``body_chars`` and ``corrections``:
the body is every prose line between the frontmatter and the ``## 校对记录`` heading
-- heading, ``>` legend, ``|`` table, ``<`` template and ``key: value`` lines are not
prose -- and the record table is the *first* markdown table at or after that heading,
reached across blank lines and up to ``_RECORD_PROSE_BUDGET`` lines of prose.

Route normalization (R4/R5) drops three annotation families before flattening:
``**[hh:mm:ss]**`` anchors, ``[...]`` brackets and ``‹...›``/``〔...〕`` marks. The
body flattening keeps a character -> body-line index, because a stateful regex cannot
report where a removed annotation started; the routes need no such map.
"""

from __future__ import annotations

import difflib
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

#: Route-comparison budget per side, consumed by ``check_hotword_screen``. The
#: local window is ``HOTWORD_WINDOW`` flattened characters either side of the token,
#: well inside the budget; the cap keeps a pathological route out of ``difflib``.
MAX_COMPARE_CHARS = 20_000
#: ``difflib`` ratio below which the two routes count as disagreeing.
FLOOR = 0.95
#: Flattened characters compared either side of a hotword token (R5).
HOTWORD_WINDOW = 20


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
    fail_closed: bool = False                  # a 校对记录 heading whose table is not in budget


class Verdict(NamedTuple):
    ok: bool
    violations: tuple[Violation, ...]
    body_chars: int
    marks: int
    record_rows: int


# --- document shape -----------------------------------------------------------------

#: The record table's columns, fixed by the candidate header
#: ``| # | 时间 | 原 ASR | AI 字幕 | 定稿 | 依据 |``.
ASR_COL = 2
CAPTION_COL = 3
FINAL_COL = 4
EVIDENCE_COL = 5
#: The two readings a row's 定稿 is compared against, to decide it asserts a change.
ROUTE_COLS: tuple[int, ...] = (ASR_COL, CAPTION_COL)

_FRONTMATTER_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
_RECORD_HEADING_RE = re.compile(r"^##\s*校对记录\s*$")
_RECORD_TABLE_RE = re.compile(r"^\s*\|")
_TABLE_CELL_RE = re.compile(r"^\s*\|(?:[^|]*\|)+\s*$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
_INTEGER_RE = re.compile(r"^[+-]?\d+$")

#: Route/body normalization, in the order the annotations are stripped: a
#: ``**[hh:mm:ss]**`` anchor, then a ``[...]`` bracket of at most 8 chars, then a
#: ``‹...›``/``〔...〕`` rejection mark of at most 3 chars.
_ANCHOR_RE = re.compile(r"\*\*\[\d{2}:\d{2}:\d{2}\]\*\*")
_BRACKET_RE = re.compile(r"\[[^\]]{1,8}\]")
_MARK_SPAN_RE = re.compile(r"[‹〔][^‹›〔〕]{0,3}[›〕]")
_FLAT_RE = re.compile(r"[\W_]+")

#: How many prose lines the parser will cross between the ``## 校对记录`` heading and
#: the first table row (R1). Real candidates carry one blank line or one prose
#: paragraph there; a long prose run means the table is somewhere else entirely.
_RECORD_PROSE_BUDGET = 10
#: Blank lines tolerated *inside* the table: a visual gap, not the table's end.
_RECORD_GAP_BUDGET = 4

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
    """Flatten: strip annotations, then drop whitespace and punctuation.

    The three annotation families come off first (R4): a ``**[hh:mm:ss]**`` anchor,
    a ``[...]`` bracket, a ``‹...›``/``〔...〕`` mark. ``[推定]`` therefore does not
    leak its brackets into the flattened route, and a mark does not leak its glyphs.
    """
    return _FLAT_RE.sub("", _MARK_SPAN_RE.sub("", _BRACKET_RE.sub("", _ANCHOR_RE.sub("", text))))


def _sub_keep_positions(pattern: re.Pattern[str], text: str,
                        positions: tuple[int, ...]) -> tuple[str, tuple[int, ...]]:
    """``pattern.sub("", text)`` that carries each survivor's position in ``text``.

    ``positions[i]`` is where the ``i``-th character of ``text`` came from in the
    string the *first* pattern saw. The map is a tuple, not a ``position -> block``
    dict: a dict keyed on the block would silently keep only the last character of
    each block, losing every body line but one (measured: 48 of 61 lines survived).
    """
    out: list[str] = []
    kept: list[int] = []
    cursor = 0
    for match in pattern.finditer(text):
        for position in range(cursor, match.start()):
            out.append(text[position])
            kept.append(positions[position])
        cursor = match.end()
    for position in range(cursor, len(text)):
        out.append(text[position])
        kept.append(positions[position])
    return "".join(out), tuple(kept)


def _normalise_blocks(blocks: Sequence[str]) -> tuple[str, tuple[int, ...]]:
    """Flatten ``blocks`` and say which block each surviving character came from.

    ``_normalise`` is a stateful chain, so it cannot report *where* a removed
    annotation started; this variant carries each character's source position through
    the chain instead, which is what lets ``check_containment`` name the body line.
    """
    text = "\n".join(blocks)
    source: list[int] = []
    owner: dict[int, int] = {}
    for block, content in enumerate(blocks):
        expected = len(source) + len(content)
        for position in range(len(source), expected):
            source.append(position)
            owner[position] = block
        if block + 1 < len(blocks):
            source.append(-1)  # the joining newline belongs to no block
    positions = tuple(source)
    for pattern in (_ANCHOR_RE, _BRACKET_RE, _MARK_SPAN_RE, _FLAT_RE):
        text, positions = _sub_keep_positions(pattern, text, positions)
    return text, tuple(owner[position] for position in positions)


def _plain(text: str) -> str:
    """Flatten an annotation-stripped comparison unit without dropping brackets.

    ``_normalise`` is right for routes, where the brackets are editorial scaffolding.
    A record cell is compared cell-to-cell, so stripping a *bracket* there would
    equate ``[推定]`` with a bare reading; only the marks come off.
    """
    return _FLAT_RE.sub("", _MARK_SPAN_RE.sub("", text))


def _path_prefix(candidate: CandidateFacts) -> str:
    return candidate.work_id or "candidate"


def _frontmatter_key_line(key: str) -> int:
    if key in _FRONTMATTER_KEY_ORDER:
        return _FIRST_FRONTMATTER_KEY_LINE + _FRONTMATTER_KEY_ORDER.index(key)
    return _FIRST_FRONTMATTER_KEY_LINE


def _split_frontmatter(lines: list[str]) -> tuple[dict[str, str], dict[str, int], int]:
    """Return (frontmatter strings, numeric counts, index of the first body line).

    A leading run of blank lines is skipped before looking for the fence: one real
    candidate (`BV1iddQYQE7D.p0.md`) opens with a blank line, and treating that as "no
    frontmatter" silently loses `work_id`/`bvid` and refuses the document with two
    spurious `identity_mismatch` errors.
    """
    first = 0
    while first < len(lines) and not lines[first].strip():
        first += 1
    if first >= len(lines) or lines[first].strip() != "---":
        return {}, {}, 0
    values: dict[str, str] = {}
    counts: dict[str, int] = {}
    index = first + 1
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


def _is_record_row(line: str) -> bool:
    """Is this a markdown table row -- leading ``|`` *and* a closing one (R1)?"""
    return bool(_RECORD_TABLE_RE.match(line)) and bool(_TABLE_CELL_RE.match(line))


def _record_heading_index(lines: list[str]) -> int | None:
    """The index of the ``## 校对记录`` heading, or ``None`` when there is none."""
    for index, line in enumerate(lines):
        if _RECORD_HEADING_RE.match(line):
            return index
    return None


def _record_table_start(lines: list[str], heading: int) -> int | None:
    """Index of the first table row at or after ``heading``, within the prose budget.

    Blank lines are free; each prose line spends one unit of
    ``_RECORD_PROSE_BUDGET``. ``BV1vNTqzFEve.p0.md:658-662`` is the real case: one
    prose paragraph sits between the heading and the table. A table row must both
    open and close with ``|``, so a prose line that merely starts with ``|`` does
    not end the search.
    """
    spent = 0
    index = heading + 1
    while index < len(lines):
        line = lines[index]
        if _is_record_row(line):
            return index
        if line.strip():
            spent += 1
            if spent > _RECORD_PROSE_BUDGET:
                return None
        index += 1
    return None


def _read_record_rows(lines: list[str], start: int) -> tuple[tuple[str, ...], ...]:
    """Read the table at ``start`` into data rows, tolerating blank lines inside it."""
    raw_rows: list[str] = []
    pending: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if _is_record_row(line):
            raw_rows.extend(pending)
            pending.clear()
            raw_rows.append(line)
            index += 1
            continue
        if line.strip():
            break  # the table ends at the first non-blank, non-row line
        following = index
        while following < len(lines) and not lines[following].strip():
            following += 1
        inside = (following < len(lines) and _is_record_row(lines[following])
                  and following - index <= _RECORD_GAP_BUDGET)
        if not inside:
            break
        pending.extend([""] * (following - index))
        index = following

    rows: list[tuple[str, ...]] = []
    for position, raw in enumerate(raw_rows):
        if position == 0:
            continue  # the header row, by construction the table's first row
        cells = tuple(cell.strip() for cell in raw.strip().strip("|").split("|"))
        if all(_SEPARATOR_CELL_RE.match(cell) for cell in cells if cell != ""):
            continue  # the header separator
        rows.append(cells)
    return tuple(rows)


def _split_body(lines: list[str], start: int) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...], bool]:
    """Return (body lines, record-table data rows, fail-closed flag).

    Body lines are the prose between the frontmatter and the ``## 校对记录`` heading:
    markdown structure (headings, the ``>`` legend, tables, ``---``), the ``<...>``
    template lines and frontmatter-style ``key: value`` lines are not prose. A
    timestamped ``key: value`` line is kept -- ``META`` only rejects a line whose key
    is an ASCII identifier and which carries no ``**[hh:mm:ss]**`` anchor.

    The fail-closed flag reports a heading whose table was not found within
    ``_RECORD_PROSE_BUDGET`` prose lines: the body is then everything before the
    heading, but the record is unread rather than absent, and a caller that cares
    about the difference must not read ``record_rows=0`` as "no changes recorded".
    """
    heading = _record_heading_index(lines[start:])
    heading = None if heading is None else heading + start
    body_end = len(lines) if heading is None else heading

    body: list[str] = []
    for line in lines[start:body_end]:
        stripped = line.strip()
        if not stripped or stripped == "---":
            continue
        if stripped[0] in "#>|<":
            continue
        if _FRONTMATTER_KV_RE.match(stripped) and not _ANCHOR_RE.search(stripped):
            continue
        body.append(line)

    if heading is None:
        return tuple(body), (), False
    table = _record_table_start(lines, heading)
    if table is None:
        return tuple(body), (), True
    return tuple(body), _read_record_rows(lines, table), False


def parse_candidate(text: str) -> CandidateFacts:
    """Read a candidate document into its facts. Never raises."""
    if not isinstance(text, str):
        text = ""
    lines = text.splitlines()
    values, counts, body_start = _split_frontmatter(lines)
    body_lines, record_rows, fail_closed = _split_body(lines, body_start)

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
        fail_closed=fail_closed,
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
    """Body marks and 校对记录 rows must pair up, in both directions.

    The record table is the *whole* proofreading log (68–194 rows), while only the rows
    that carry a rejection mark are pairing candidates — a row without a mark asserts no
    rejection, so it can never leave a body mark unmatched. Counting raw rows against body
    marks made this rule refuse all six real candidates; counting *marked* rows against body
    marks leaves exactly the two genuine leftovers (BV1iddQYQE7D 16 marks / 15 marked rows,
    BV1vNTqzFEve 11 / 10).
    """
    prefix = _path_prefix(candidate)
    sites = _mark_sites(candidate)
    marked_rows = [ordinal for ordinal, row in enumerate(candidate.record_rows, 1) if _row_has_mark(row)]
    counts = f"(body_marks={len(sites)}, marked_rows={len(marked_rows)})"

    violations: list[Violation] = []
    for line, mark in sites[len(marked_rows):]:
        violations.append(Violation("marker_parity", f"{prefix}:{line} mark {mark!r} {counts}", False))
    for ordinal in marked_rows[len(sites):]:
        violations.append(Violation("marker_parity", f"{prefix}:row {ordinal} {counts}", False))
    return tuple(violations)


def _cell(row: tuple[str, ...], index: int) -> str:
    """One record cell, ``""`` for a row too short to carry that column."""
    if 0 <= index < len(row):
        return row[index].strip()
    return ""


def check_change_evidence(candidate: CandidateFacts) -> tuple[Violation, ...]:
    """Every record row asserting a change must name its evidence.

    A row asserts a change only when its final (定稿) reading differs from **both**
    route cells (R3): the record table carries a filled 定稿 on every row, so "any
    non-empty 定稿 is a change" would refuse all 744 rows of the six real candidates.
    Equalities are compared after stripping the annotation families and flattening,
    because a route cell and the editor's final reading of the same utterance differ
    in punctuation, spacing and marks rather than in wording.
    """
    prefix = _path_prefix(candidate)
    violations: list[Violation] = []
    for ordinal, row in enumerate(candidate.record_rows):
        final = _plain(_cell(row, FINAL_COL))
        if not final:
            continue
        if any(final == _plain(_cell(row, column)) for column in ROUTE_COLS):
            continue  # the editor kept a route reading: nothing is asserted
        if _cell(row, EVIDENCE_COL):
            continue
        violations.append(
            Violation("evidence_missing", f"{prefix}:record row #{ordinal + 1}", False)
        )
    return tuple(violations)


def _as_text(value: object) -> str:
    """Coerce a caller-supplied route to text; anything that is not text is empty."""
    return value if isinstance(value, str) else ""


def _body_route_view(candidate: CandidateFacts) -> tuple[str, tuple[int, ...]]:
    """The flattened body for containment, outside-routes markers and excerpts."""
    return _normalise_blocks(candidate.body_lines)


def check_containment(candidate: CandidateFacts, asr_text: str,
                      caption_text: str) -> tuple[Violation, ...]:
    """Every body character must live in ASR or caption (R4).

    Membership, never a substring and never a ratio: the body is a reflowed prose
    edition, so paragraph boundaries do not follow route boundaries and legitimate
    editorial deletions open holes. Measured on the six real candidates, 43%-92% of
    body paragraphs are not contiguous substrings of the route union, while only 26
    characters out of 116k occur in neither route -- and those are the genuine
    editorial insertions the rule exists to catch. A location therefore names the
    character, the body line it came from, and a short excerpt of that line.
    """
    prefix = _path_prefix(candidate)
    asr_flat = _normalise(_as_text(asr_text))
    caption_flat = _normalise(_as_text(caption_text))
    route_chars = set(asr_flat) | set(caption_flat)

    flat, lines = _body_route_view(candidate)
    violations: list[Violation] = []
    for position, char in enumerate(flat):
        if char in route_chars:
            continue
        line = lines[position] + 1
        excerpt = _excerpt(flat, position)
        violations.append(
            Violation("char_outside_routes",
                      f"{prefix}:{line} char {char!r} (neither route) in {excerpt!r}", False)
        )
    return tuple(violations)


def _excerpt(flat: str, position: int, radius: int = 12) -> str:
    """A short window of flattened body around one character, for a reviewer."""
    return flat[max(0, position - radius):position + radius + 1]


def _hotword_windows(route_flat: str, flat_token: str) -> tuple[tuple[str, int, int], ...]:
    """Every ``HOTWORD_WINDOW`` character window of ``route_flat`` around the token.

    Each window is the token's occurrence plus ``HOTWORD_WINDOW`` flattened characters
    on either side, clipped to the route; the bounds travel with it so the location can
    name them (R5).
    """
    windows: list[tuple[str, int, int]] = []
    position = route_flat.find(flat_token)
    while position >= 0:
        start = max(0, position - HOTWORD_WINDOW)
        end = min(len(route_flat), position + len(flat_token) + HOTWORD_WINDOW)
        windows.append((route_flat[start:end], start, end))
        position = route_flat.find(flat_token, position + 1)
    return tuple(windows)


def _named_in_record(candidate: CandidateFacts, token: str) -> bool:
    """Does the record name this token as an inference, in its 依据 column?

    Only the 依据 column (R3): scanning every column makes the rule unfalsifiable,
    because a token like 感性 is a coincidental substring of unrelated 为/的 rows.
    """
    needle = token.casefold()
    if not needle:
        return False
    return any(needle in _cell(row, EVIDENCE_COL).casefold() for row in candidate.record_rows)


def check_hotword_screen(candidate: CandidateFacts, asr_text: str, caption_text: str,
                         hotwords: Sequence[str]) -> tuple[Violation, ...]:
    """Where the two routes disagree about a hotword, the record must name it (R5).

    A token only reaches the comparison when it occurs in **both** routes: the annex's
    "compare the two routes at that position" is undefined for a token in one route
    only, and the caller may not hand this module a bare sidecar string. Each
    occurrence pair is compared over its own bounded window; the pair that agrees best
    is the route-to-route reading, which keeps a token that recurs (感性) from being
    refused on its first, driftier occurrence. Below ``FLOOR`` the routes disagree --
    unless the record names the token as an inference.

    The screen is vacuous -- an advisory that never flips the verdict -- when it was
    given no hotword, or when no token occurs in *either* route (R6): for
    BV11p5qzAE6s 31 of 33 tokens occur in neither route, and a candidate whose screen
    was effectively skipped must not look clean.
    """
    prefix = _path_prefix(candidate)
    asr = _as_text(asr_text)
    caption = _as_text(caption_text)
    words = hotwords.split(",") if isinstance(hotwords, str) else (hotwords or ())
    given = tuple(word for word in (_as_text(word).strip() for word in words) if word)
    if not given:
        return (Violation("hotword_screen_vacuous", f"{prefix}:hotwords=0", True),)

    asr_flat = _normalise(asr)
    caption_flat = _normalise(caption)
    usable = tuple((token, flat) for token, flat in
                   ((token, _normalise(token)) for token in given) if flat)
    in_routes = any(flat in asr_flat or flat in caption_flat for _token, flat in usable)

    body_flat = tuple(_normalise(line) for line in candidate.body_lines)
    violations: list[Violation] = []
    for token, flat_token in usable:
        if flat_token not in asr_flat or flat_token not in caption_flat:
            continue  # one route only: the annex gives no comparison, so no refusal
        site = next(
            ((index + 1, flat_line.find(flat_token))
             for index, flat_line in enumerate(body_flat) if flat_token in flat_line),
            None,
        )
        if site is None:
            continue  # the body does not carry this token, so the screen has no site
        left = _hotword_windows(asr_flat, flat_token)
        right = _hotword_windows(caption_flat, flat_token)
        best = max((difflib.SequenceMatcher(None, one, two).ratio()
                    for one, _start, _end in left for two, _s, _e in right), default=0.0)
        if best >= FLOOR:
            continue  # the routes agree around the token
        if _named_in_record(candidate, token):
            continue  # the record names the token, so the editor declared it
        first_asr, first_caption = left[0], right[0]
        bounds = (f"asr[{first_asr[1]}:{first_asr[2]}]"
                  f" cap[{first_caption[1]}:{first_caption[2]}] ratio={best:.3f}")
        violations.append(
            Violation("hotword_disagreement",
                      f"{prefix}:{site[0]} token {token!r} at {site[1]} {bounds}", False)
        )

    if not in_routes:
        violations.append(
            Violation("hotword_screen_vacuous",
                      f"{prefix}:hotwords={len(given)} none_in_routes", True)
        )
    return tuple(violations)


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
    if candidate.fail_closed:
        # R1: the heading was there, the table was not within budget. An unread
        # record is not an absent record, and the advisory vocabulary has no id for
        # it, so it rides on the rule whose evidence it invalidates.
        violations.append(
            Violation("route_absent_for_part",
                      f"{_path_prefix(candidate)}:record_table_not_found"
                      f" (within {_RECORD_PROSE_BUDGET} prose lines of the 校对记录 heading)", True)
        )
    return Verdict(
        ok=not errors,
        violations=tuple(violations),
        body_chars=body_chars,
        marks=len(candidate.marks),
        record_rows=len(candidate.record_rows),
    )


def verdict_line(work_id: str, verdict: Verdict) -> str:
    """The report lines: the ok summary on an ok verdict, then errors, then warnings.

    The ok summary tracks the verdict itself -- ``verify_candidate`` sets ``ok`` to
    "no error violation", so a candidate that is ok and carries advisories prints its
    ok summary *and* its warning lines.
    """
    order = {rule: index for index, rule in enumerate(E_RULE_IDS)}
    rank = lambda violation: order.get(violation.rule, len(order))  # noqa: E731
    errors = sorted((v for v in verdict.violations if not v.advisory), key=rank)
    advisories = sorted((v for v in verdict.violations if v.advisory), key=rank)

    lines: list[str] = []
    if not errors:
        lines.append(
            f"{work_id}: ok (body_chars={verdict.body_chars} marks={verdict.marks} "
            f"record_rows={verdict.record_rows})"
        )
    lines.extend(f"{work_id}: refused ({v.rule}) at {v.location}" for v in errors)
    lines.extend(f"{work_id}: warning ({v.rule}) at {v.location}" for v in advisories)
    return "\n".join(lines)


def closing_line(command: str, total: int, ok: int, refused: int) -> str:
    """The run's summary line, e.g. ``verify-proofread: candidates=3 ok=2 refused=1``."""
    return f"{command}: candidates={total} ok={ok} refused={refused}"
