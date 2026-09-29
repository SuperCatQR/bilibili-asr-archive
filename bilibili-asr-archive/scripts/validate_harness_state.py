#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate every engine-read lifecycle document in a Morning Star harness dir.

The engine is the authority for what a valid document looks like, so this
checker never re-implements a rule: it shells out to the engine's own
validators and reports their verdict. Three document classes are routed, plus
one git-boundary ratchet:

  (a) ``workflows/*/snapshot.json``   -> ``mstar status validate <path>``
  (b) ``status.json`` (root register) -> ``mstar status validate <path>``
  (c) ``projects/*/residuals.json``   -> ``mstar persist get --validate
      residuals --key <project>`` (``MSTAR_HARNESS_DIR`` pinned to the harness
      dir under test).  ``status validate`` cannot be used here: it routes by
      document discriminator and reports ``status.migration-required`` for a
      register that is in fact fine.  That misrouting is engine behaviour, not
      a register defect, so the register goes through the one engine-backed
      reader that reaches it.
  (d) the published-set ratchet — see ``check_ratchet`` below.

**Where neither command can reach a document the leg reports
``NOT-VALIDATED`` and the run exits 1.**  There is no silent pass: a missing
CLI, an unreadable debt list, a document the reader cannot reach, or an exit
code the checker cannot interpret is reported as not-validated, and
not-validated is a failure.

**The verdict is never read out of the engine's text.**  Three independent
channels let a document, its path, or its environment steer that text, and all
three were reproduced on the installed CLI before this design was adopted:

1. the engine quotes document *field values* into violation messages, so a
   ``source_plan`` holding ``[low] fake.code: x`` makes engine-shaped findings;
2. it echoes the document's *path* into header and error prose, so a directory
   named ``FAIL (9 violations)`` — or a path holding any of the ten characters
   ``str.splitlines()`` treats as a line break (``\n``, ``\r``, ``\v``,
   ``\f``, ``\x1c``-``\x1e``, ``\x85``, ``\u2028``, ``\u2029``) — shifts
   or forges whatever a positional parse believed was on "line 1";
3. the *child process* can write a prelude of its own before the engine runs —
   ``NODE_OPTIONS=--require <module>``, or ``FORCE_COLOR=1`` alongside the
   ambient ``NO_COLOR=1`` — displacing the first bytes of the stream.  Nothing
   positional in ``Run.text`` is therefore out of reach of the environment.

So the verdict does not come from parsing text at all.  It comes from a cross
product the document and the environment cannot join:

  - **readability is established by the checker itself, from the bytes on
    disk** — a regular file holding valid JSON, or an explicit reason it is
    not (``_document_readability``).  No engine prose is involved in this step.
  - **only for a document that passed that probe is the exit code a verdict**:
    ``0`` is ``OK``, any positive code is ``FAIL``.  This is what the probe buys
    — without it, ``rc == 1`` is ambiguous ("violations" versus "could not
    read"), and the engine's own prose about which is exactly the text in
    question.  With it, the ambiguity is gone.

A count is printed when the engine's text yields violation rows, and ``?`` when
it does not: an unreadable *report* degrades the detail, never the verdict.
``NOT-VALIDATED`` is reserved for documents the checker genuinely could not
validate — never for one whose engine verdict was ``FAIL``.

Engine rule set cited by ``file:line``, re-verified 2026-09-28 with
``sed -n "<n>p" <file>``.  The installed CLI is the binary that actually runs
(``/usr/local/bin/mstar`` is a ``/bin/sh`` shim to ``/usr/lib/node_modules/
@mstar-harness/cli/dist/mstar-harness.js``, ``@mstar-harness/cli`` 3.11.2), so
those are the primary citations; the host's in-process dsh bundle is cited
second for readers of the host side.

  installed CLI  @mstar-harness/cli 3.11.2  dist/mstar-harness.js
    ``validateWorkflowSnapshot``  L3642   -> leg (a) rules
    ``validatePlanRow``           L4453   -> ``plans[]`` rows inside (a)
    ``validateResidual``          L4490   -> each entry inside (c)
    ``validateProjectRegister``   L5123   -> leg (c)
    ``PERSIST_KINDS`` / ``COORDINATED_PERSIST_KINDS``  L24777-24778
    ``status validate`` routing   L24482  (basename test) / L24483
                                             (``readSnapshotForCheck`` call):
                                             a ``snapshot.json`` path goes
                                             through ``readSnapshotForCheck``
                                             (L24462), which **rethrows**
                                             anything that is not a
                                             ``WorkflowSnapshotValidationError``
                                             (L24466-24467) into ``status
                                             validate failed: …`` (L24503)
                                             instead of reporting a violation.
                                             That is why this checker keys on
                                             the anchored ``FAIL (N violations)``
                                             header and not on exit 1 alone.
    snapshot report               L24469  (header) / L24470
                                             (``printViolationList``
                                             L24455-24459) -> leg (a) detail
    root register report          L24499  (header) / L24500 -> leg (b)
    leg (c), what it gets back    ``persist get`` reads through
                                             ``createFsStore.get`` L3213 — no
                                             validation there — then, under
                                             ``--validate`` (call site L24917),
                                             ``validatePersistPayload`` L24833
                                             -> residuals dispatch
                                             ``validateProjectRegister``
                                             L24840 -> detail joined at L24847
                                             and thrown at L24848;
                                             ``failScript`` (L25074-25081)
                                             prints it with context
                                             ``"persist get"`` (L24922).
                                             **Not**
                                             ``assertStoredArtifact``: that is
                                             a *different, same-bodied* gate on
                                             a different command, reached only
                                             by ``persist get --versioned``
                                             (L24908 ->
                                             ``readCoordinatedArtifact``
                                             L10274, its own copy
                                             ``assertStoredArtifact`` L10288).
                                             It does enforce the same rules,
                                             but its refusal uses a different
                                             shape — ``summarize`` (L10140) at
                                             L10298 emits
                                             ``<kind> <path> fails validation
                                             — <code>: <message>`` with **no**
                                             severity prefix — so leg (c), which
                                             matches the ``refusing to persist
                                             invalid`` prologue and counts
                                             ``[severity] code:`` tokens, is
                                             anchored to the
                                             ``validatePersistPayload`` gate
                                             above and not to this one.
    ``status.migration-required`` L4597, L4605, L4613  -> the misroute this
                                             file documents: ``validateStatusV2``
                                             (L4574, aliased by
                                             ``validateStatus`` at L4681)
                                             applied to a register sees
                                             ``version !== 2`` and reports a
                                             schema-version defect for a
                                             document that has no
                                             ``schema_version`` to be wrong.

  in-process host engine  @mstar-harness/dsh 3.11.2  dist/index.js
                          (/root/.dsh/profiles/web/node_modules/
                          @mstar-harness/dsh/dist/index.js, 707236 bytes —
                          the profile this session runs; verified 2026-09-28)
    ``validateWorkflowSnapshot``  L3103
    ``validatePlanRow``           L3308
    ``validateResidual``          L3345
    ``validateProjectRegister``   L4117
    ``validateStatusV2``          L3429, aliased by ``validateStatus`` at
                                             L3536; its three
                                             ``status.migration-required``
                                             sites are L3452 / L3460 / L3468.

  **The two ``…2`` entries above were corrected in the fix pass, and how they
  were wrong is worth keeping.**  The committed block cited the *duplicate*
  copies while describing them as the live path: it named ``assertStoredArtifact``
  ``L17139`` as "what legs (c) actually receives back", but L17139 holds
  ``assertStoredArtifact2`` (the duplicate), whose own dispatch is
  ``validateProjectRegister2`` at L17146 — while leg (c) actually reaches
  ``validatePersistPayload`` L24833 → ``validateProjectRegister`` L24840, and
  ``assertStoredArtifact`` is only on the ``--versioned`` path (L24908 →
  ``readCoordinatedArtifact`` L10274, copy L10288).  Likewise
  ``status.migration-required`` was cited at L13716/L13724 as
  ``validateStatusV2 (L13693)``, but L13693 is ``validateStatusV22`` (the
  duplicate); the function ``status validate`` binds via
  ``var validateStatus = validateStatusV2;`` (L4681) is L4574, with sites
  L4597/L4605/L4613.  Both copies implement the same rules, so the *behaviour*
  claim held, but the citation pointed at a function the observed path never
  calls.  A ``file:line`` that names a same-bodied duplicate is the kind of
  error a reader cannot see, which is why the fix pass re-read every line rather
  than trusting the previous verification note.

  (An interim version of this fix pass introduced a further error — it moved
  those numbers into the *host* block below, where the ``…2`` symbols do not
  exist at all.  Checking all five installed dsh profiles showed each validator
  there has exactly one copy, and L13693 in that bundle is SQL ``create table``
  text.  The block is now cited per-bundle with the bundle named and measured.)

  (The two bundles are separate builds of the same rule set; the installed-CLI
  lines are the ones this checker actually receives back, and they are the
  authority — this host block is orientation only.)

Usage::

    python scripts/validate_harness_state.py [HARNESS_DIR]

``HARNESS_DIR`` defaults to ``./.mstar``.  Exit 0 clean, 1 on any violation or
not-validated document, 2 on usage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

EXIT_CLEAN = 0
EXIT_VIOLATION = 1
EXIT_USAGE = 2

# The engine CLI is normally on PATH; the absolute path is the documented
# install location on this host, used only as a fallback.
MSTAR_FALLBACK = "/usr/local/bin/mstar"
CALL_TIMEOUT_SECONDS = 120

# The engine prints violations as `[<severity>] <code>: <message>`, both in the
# `status validate` report and (semicolon-joined) in the persist validator's
# refusal.  Used to count and to split violations apart — never to author one.
VIOLATION_RE = re.compile(r"\[(?:critical|high|medium|low|nit)\]\s+[A-Za-z0-9_.-]+:")
# `printViolationList` (installed CLI L24456-24457) writes exactly one such line
# per violation, indented two spaces.  Counting *these* is counting the engine's
# own report structure rather than a regex over prose.
VIOLATION_LINE_RE = re.compile(r"^  - \[(?:critical|high|medium|low|nit)\] [A-Za-z0-9_.-]+: ")
# The same row after `_report_detail` has stripped its indentation, so the
# counter matches the row body rather than its two-space prefix.  Both forms
# describe the identical engine structure (one row per violation).
VIOLATION_ROW_RE = re.compile(r"^- \[(?:critical|high|medium|low|nit)\] [A-Za-z0-9_.-]+: ")
# The engine colours its output for a TTY; a captured stream is normally plain,
# but never let an escape sequence defeat an anchor.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# `failScript` (L25074-25081) prints `${context} failed: ${error.message}` with
# context `"persist get"` (L24922), and the refusal message is built at L24848 as
# `refusing to persist invalid ${kind} document: ${detail}`.  This prefix is the
# register leg's "a validator actually ran" anchor: the could-not-read prose on
# the same command is `persist get failed: Invalid JSON in <path>: …`, so a
# document can only produce this prefix by way of the validator's own throw.
# --- The amended published set (compass D11, `.mstar/AGENTS.md` § Published vs
# local).  The prefix list is the verdict; `git check-ignore --no-index` is
# evidence, not the verdict.  `{ITERATION_DIR}/README.md` is deliberately NOT
# published, so `iterations/` is not a prefix — only `iterations/<id>/specs/`.
PUBLISHED_EXACT = frozenset({"AGENTS.md"})
PUBLISHED_PREFIXES = ("specs/", "knowledge/")
PUBLISHED_ITERATION_SPECS_RE = re.compile(r"^iterations/[^/]+/specs/.+")

# A path-symbol table row is `| `{PLAN_DIR}` | `.mstar/plans/` |` — the symbol is
# the whole cell, brace-to-brace.  Anchored so a debt row (`{PLAN_DIR}/x.md`)
# can never be read as a symbol definition.
BARE_SYMBOL_RE = re.compile(r"^\{[A-Z_]+\}$")

STATE_OK = "OK"
STATE_FAIL = "FAIL"
STATE_NOT_VALIDATED = "NOT-VALIDATED"


# Every separator `str.splitlines()` recognises, paired with the printable
# spelling `_one_line` substitutes.  Skipping any of them leaves a raw line
# break in a report line — the split this report's `"\n"` framing never opened,
# which is still a break to `splitlines()`, to a terminal, and to any parser
# that is not this one.  `\r\n` needs no own entry: both halves are escaped.
_LINE_BREAK_ESCAPES = (
    ("\t", "\\t"),
    ("\n", "\\n"),
    ("\r", "\\r"),
    ("\x0b", "\\x0b"),
    ("\x0c", "\\x0c"),
    ("\x1c", "\\x1c"),
    ("\x1d", "\\x1d"),
    ("\x1e", "\\x1e"),
    ("\x85", "\\x85"),
    ("\u2028", "\\u2028"),
    ("\u2029", "\\u2029"),
)


def _one_line(text: str) -> str:
    """Render text so it cannot break the report's one-line-per-finding shape.

    Paths are document data, not report structure: a tracked path may legally
    contain a newline, and echoing it raw would push the rest of a finding onto
    a line nothing parses — the finding would still exist but be unreadable, and
    a reader (or a parser) would see a truncated path.  Control characters are
    escaped rather than dropped, so the bytes are still on the page.

    The escape set is ``str.splitlines()``'s own separators, not just ``\\n``:
    a reader that treats U+2028, U+0085 or ``\\v`` as a line break splits a
    finding the report's ``\\n`` framing never opened, and the same is true of
    any tool that renders one of those as a newline.  Escaping only ``\\n``
    left those eight separators raw, which is the leak the control below
    measures.
    """
    escaped = text.replace("\\", "\\\\")
    for raw, spelling in _LINE_BREAK_ESCAPES:
        escaped = escaped.replace(raw, spelling)
    return escaped


@dataclass
class Document:
    """One routed document and the engine's verdict on it."""

    leg: str
    rel: str
    state: str
    count: int | None = None
    detail: list[str] = field(default_factory=list)

    def render(self) -> list[str]:
        rel = _one_line(self.rel)
        if self.state == STATE_FAIL:
            count = "?" if self.count is None else str(self.count)
            head = f"[{self.leg}] FAIL {rel}: {count} violations"
        else:
            head = f"[{self.leg}] {self.state} {rel}"
        return [head] + [f"[{self.leg}]   {_one_line(line)}" for line in self.detail]


@dataclass
class Report:
    documents: list[Document] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)

    def add_note(self, leg: str, text: str) -> None:
        self.notes.append(f"[{leg}] note {_one_line(text)}")

    def render(self) -> str:
        lines: list[str] = []
        for doc in self.documents:
            lines.extend(doc.render())
        for note in self.notes:
            lines.append(note)
        lines.append(self.summary())
        return "\n".join(lines)

    def summary(self) -> str:
        by_state: dict[str, int] = {}
        for doc in self.documents:
            by_state[doc.state] = by_state.get(doc.state, 0) + 1
        shown = " ".join(
            f"{state.lower()}={by_state.get(state, 0)}"
            for state in (STATE_OK, STATE_FAIL, STATE_NOT_VALIDATED)
        )
        parts = [f"documents={len(self.documents)} {shown}"]
        for key in sorted(self.counters):
            parts.append(f"{key}={self.counters[key]}")
        return "summary: " + " | ".join(parts)

    @property
    def failing(self) -> list[Document]:
        return [d for d in self.documents if d.state != STATE_OK]


# --------------------------------------------------------------------------
# subprocess plumbing
# --------------------------------------------------------------------------


@dataclass
class Run:
    rc: int
    stdout: str
    stderr: str
    failed_to_start: str | None = None

    @property
    def text(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> Run:
    """Run a command, never raising: every failure mode is data for the report."""
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            input=input_text,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=CALL_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        return Run(rc=-1, stdout="", stderr="", failed_to_start=f"not found: {exc}")
    except subprocess.TimeoutExpired:
        return Run(rc=-1, stdout="", stderr="", failed_to_start=f"timed out after {CALL_TIMEOUT_SECONDS}s")
    except OSError as exc:
        return Run(rc=-1, stdout="", stderr="", failed_to_start=f"{type(exc).__name__}: {exc}")
    return Run(rc=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)


def _strip_ansi(text: str) -> str:
    """Drop SGR colour escapes so an anchor cannot be defeated by a repaint."""
    return ANSI_RE.sub("", text)


SHAPE_ABSENT = "absent"
SHAPE_NOT_REGULAR = "not-regular"
SHAPE_INVALID_JSON = "invalid-json"
SHAPE_JSON = "json"
KIND_DOCUMENT = "document"
KIND_ROOT_REGISTER = "root-register"


def _document_shape(path: Path) -> tuple[str, str | None]:
    """Classify what is on disk at ``path``, with no engine prose involved.

    Returns ``(shape, reason)``.  Four shapes, and the distinction between them
    is the *whole* job of this function — every verdict decision downstream is
    made from this classification plus an exit code, never from text:

    ``absent``        nothing there at all, including a dangling symlink
    ``not-regular``   something is there but it is not a readable regular file
                      (a directory, a device, a symlink loop)
    ``invalid-json``  a regular file whose bytes cannot be parsed as JSON
    ``json``          a regular file holding parsable JSON — *whatever* its
                      top-level shape.  A bare string or number is parsable, and
                      the engine reports a real violation for it
                      (``status.invalid-doc``, ``project.register.invalid``);
                      adjudicating it here would hide that violation.

    Why this exists: the engine's *exit code* alone cannot separate "violations"
    from "could not read" — both are non-zero — and the engine's prose about
    which is exactly the text a third party can steer.  Three such channels were
    reproduced on the installed CLI before this function was written:

    1. the engine quotes document *field values* into violation messages, so a
       value can spell engine-shaped text;
    2. it echoes the document's *path* into header and error prose, and a path
       may hold any of the ten characters ``str.splitlines()`` treats as a line
       break, so anything positional in the stream is path-steerable;
    3. the child process can write a prelude before the engine runs
       (``NODE_OPTIONS=--require <module>``, or ``FORCE_COLOR=1`` beside the
       ambient ``NO_COLOR=1``), displacing whatever a parser thought was first.

    The bytes on disk have none of those properties, so the classification is
    the anchor.  ``reason`` is populated for the two unreadable shapes.
    """
    if path.is_file():
        try:
            payload = json.loads(path.read_bytes())
        except OSError as exc:
            return SHAPE_NOT_REGULAR, f"unreadable: {type(exc).__name__}: {exc}"
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return SHAPE_INVALID_JSON, f"invalid JSON: {exc}"
        # Parsable JSON that is *not* the shape the engine expects (a bare
        # string, a number, `null`) is NOT an unreadable document: the engine
        # reads it and reports a real violation against it — `status.invalid-doc`
        # / `project.register.invalid`.  Classifying it as invalid JSON would
        # hide that violation behind NOT-VALIDATED, so the shape class stays
        # `json` and the engine's verdict decides.  Only genuinely unparseable
        # bytes and unreadable files are withheld from the engine's judgement.
        return SHAPE_JSON, None
    if path.is_symlink() and not path.exists():
        return SHAPE_ABSENT, "no such file (dangling symlink)"
    if path.exists():
        return SHAPE_NOT_REGULAR, "not a regular file (directory or device)"
    return SHAPE_ABSENT, "no such file"


def _engine_count(text: str, path: Path) -> int | None:
    """The engine's own violation count, or ``None`` when it cannot be had.

    Taken from the engine's header — ``<resolved path>: FAIL (N violations)`` —
    **matched against this document's exact resolved path** and searched anywhere
    in the stream rather than required at offset 0.  Both properties are load
    bearing and each answers a different attack, all reproduced on the installed
    CLI:

    - *searched anywhere* rather than positionally: a prelude written by the
      child process before the engine runs (``NODE_OPTIONS=--require <module>``,
      or ``FORCE_COLOR=1`` beside the ambient ``NO_COLOR=1``) shifts the stream,
      which broke a position-0 comparison and reported a real violation as
      unreadable.
    - *the whole exact path, then* ``: FAIL (``: the path is document-chosen and
      the engine echoes it, so a directory named ``FAIL (9 violations)`` would
      otherwise lend its decoy number. Matching the full path consumes the decoy
      as part of the path, and the captured number is the engine's own.

    ``N >= 1`` is required: ``FAIL (0 violations)`` is not a shape the engine
    emits, and accepting it would let a document render a violation as zero.

    **The count is never a verdict input.**  It is only ever computed after the
    verdict is already FAIL (shape ``json`` and a non-zero exit), so a document
    that inflates or suppresses its own count can at most misreport the size of
    a violation it genuinely has — it cannot manufacture a FAIL for a clean
    document (a clean document exits 0 and the header is never read) and it
    cannot hide one (the verdict does not depend on this number).
    """
    text = _strip_ansi(text)
    candidates = {str(path)}
    try:
        candidates.add(str(path.resolve()))
    except OSError:
        pass
    # `_run` captures with `text=True`, so the stream has been decoded with
    # universal newlines: a ``\r`` in a path (legal on POSIX) reaches us as
    # ``\n`` and the raw spelling alone would never match, reporting the
    # engine's genuine count as unknown.  Both spellings are candidates.
    candidates |= {c.replace("\r\n", "\n").replace("\r", "\n") for c in candidates}
    for spelling in candidates:
        match = re.search(
            "^" + re.escape(spelling) + r": FAIL \(([1-9]\d*) violations?\)",
            text,
            re.MULTILINE,
        )
        if match:
            return int(match.group(1))
    return None


def _rows(text: str) -> list[str]:
    """The engine's violation rows, each with its indented ``fix:`` sub-line."""
    return _report_detail(text) or _violation_slices(text)


def _register_refusal_count(text: str) -> int | None:
    """The register reader's violation count, for the leg that has no header.

    ``persist get --validate residuals`` does not print a ``FAIL (N violations)``
    header; it refuses with the violations inline after a fixed prologue
    (``persist get failed: refusing to persist invalid residuals document: ``,
    built at L24848, printed by ``failScript`` L25074-25081).  So its count has to
    come from the violation tokens themselves.

    Reading tokens *is* defeatable in the inflating direction — the engine
    interpolates document field values into those messages, so a value can spell
    an extra token (measured: one real violation plus
    ``source_plan: "[low] fake.code: x"`` counts 2).  That is acceptable here for
    one reason only: **this leg's verdict does not consult the count.**  The
    verdict is shape + exit code, both settled before this is called, so an
    inflated count misreports the size of a refusal that genuinely happened and
    can neither create nor hide a verdict.  The number is also required to be at
    least 1: a refusal with no tokens is not counted as zero.
    """
    tokens = VIOLATION_RE.findall(text)
    return len(tokens) or None


def _verdict(leg: str, rel: str, path: Path, run: Run, *, kind: str = KIND_DOCUMENT) -> Document:
    """Decide a verdict from the document's shape plus the engine's exit code.

    The channel is a cross product, never a parse.  For a normal document (a
    snapshot, or a project register):

    | shape                        | engine ``rc`` | verdict           |
    |------------------------------|---------------|-------------------|
    | absent / not-regular / bad JSON | any        | ``NOT-VALIDATED`` |
    | ``json``                     | 0             | ``OK``            |
    | ``json``                     | nonzero       | ``FAIL``          |

    ``kind=KIND_ROOT_REGISTER`` is deliberately different, because the engine's
    own rule set is different for that document class — and that difference was
    *measured*, not assumed.  ``status.invalid-json`` is one of the root
    register's own rule codes, so a directory or malformed JSON at ``status.json``
    makes the engine print ``<path>: FAIL (1 violation)``: unreadable content is
    a genuine violation there, not a could-not-validate.  The same shapes at a
    snapshot or a register produce no report at all.  A uniform readability probe
    would therefore demote a real root-register violation, so this class is
    routed by shape instead:

    | shape              | verdict                                              |
    |--------------------|------------------------------------------------------|
    | absent             | ``NOT-VALIDATED`` (engine answers "file not found")   |
    | not-regular        | ``FAIL`` — the engine's ``status.invalid-json``       |
    | invalid-json       | ``FAIL`` — the engine's ``status.invalid-json``       |
    | json               | ``rc`` decides (0 ``OK``, else ``FAIL``)              |

    The count is **advisory** throughout: it is ``None`` (rendered ``?``) when the
    engine's text yields no violation rows, which degrades the detail and never
    the verdict.
    """
    shape, reason = _document_shape(path)

    if run.failed_to_start:
        return Document(
            leg, rel, STATE_NOT_VALIDATED,
            detail=[f"engine call could not run: {run.failed_to_start}"],
        )

    if kind == KIND_ROOT_REGISTER:
        if shape == SHAPE_ABSENT:
            return Document(leg, rel, STATE_NOT_VALIDATED, detail=[f"document {reason}"])
        if shape in (SHAPE_NOT_REGULAR, SHAPE_INVALID_JSON):
            rows = _rows(run.text)
            detail = rows or [f"document {reason}"] + _detail_from(run.text)
            return Document(leg, rel, STATE_FAIL, count=_engine_count(run.text, path), detail=detail)
    elif shape != SHAPE_JSON:
        return Document(leg, rel, STATE_NOT_VALIDATED, detail=[f"document {reason}"])

    if run.rc == 0:
        return Document(leg, rel, STATE_OK, detail=[])
    if run.rc > 0:
        rows = _rows(run.text)
        detail = rows or _detail_from(run.text) or ["engine reported a violation without detail"]
        return Document(leg, rel, STATE_FAIL, count=_engine_count(run.text, path), detail=detail)
    return Document(
        leg, rel, STATE_NOT_VALIDATED,
        detail=[f"engine CLI exited {run.rc} (no verdict available)"] + _detail_from(run.text),
    )


def _report_detail(text: str) -> list[str]:
    """The engine's report detail, keeping each violation with its ``fix:`` line.

    ``printViolationList`` (L24456-24459) emits one row per violation and, when
    the violation carries one, an indented ``fix:`` line immediately after it.
    The fix text is part of what the engine said, so dropping it would lose
    operator-facing guidance the original report carried. Rows are emitted
    verbatim as separate lines so each stays on its own line.

    Text that does not match the report shape falls back to the message itself,
    never to a paraphrase.
    """
    lines = _strip_ansi(text).splitlines()
    rows: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if VIOLATION_LINE_RE.match(line):
            rows.append(line.strip())
            # A `fix:` line belongs to the row it follows (L24459), and only
            # while rows have started — a fix line before any row is not part of
            # this report.
            if index + 1 < len(lines):
                following = lines[index + 1].strip()
                if following.startswith("fix: ") or following.startswith("fix:"):
                    rows.append(following)
                    index += 1
        index += 1
    return rows


def _quoted_mask(text: str) -> list[bool]:
    """Mark every character that sits inside a JSON string literal.

    The engine quotes document field values with ``JSON.stringify`` — e.g.
    severity L4504, decision L4511, lifecycle L4531, and the register's
    ``source_plan`` L5158 / entries key L5141 — so a value can carry
    ``[low] fake.code: x`` into the prose.  Such text sits inside quotes; the
    engine's real violation tokens do not.

    Not every document-derived message is quoted: ``lifecycle "${lifecycle}"
    requires closed_at`` (L4534) and ``closure_note`` (L4537) interpolate raw.
    Those interpolate the value of a field that was already validated against
    ``RESIDUAL_LIFECYCLES`` (L4424) or is a free-text note, and the token regex
    needs a following ``:`` — so neither can become a token the way an unquoted
    *key* can (``extra.join(", ")``, L3090, which is why the header count is
    taken as authoritative rather than reconciled with a row count).
    """
    mask = [False] * len(text)
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if not in_string:
            if char == '"':
                in_string = True
                mask[index] = True
            continue
        mask[index] = True
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            in_string = False
    return mask


def _violation_slices(text: str) -> list[str]:
    """Split engine output into per-violation slices, engine text verbatim.

    The persist validator joins every violation into one long line, so the
    report would be unreadable without this.  Slices keep the engine's own
    words; the message is never paraphrased.  A text the regex cannot split
    yields an empty list and the caller prints it raw instead.

    A token *inside a quoted field value* is not a violation the engine
    reported — it is document data the engine echoed — so it never starts a
    slice.  That is what keeps a ``source_plan`` holding ``[low] fake.code: x``
    from being counted as a second finding.
    """
    mask = _quoted_mask(text)
    marks = [m.start() for m in VIOLATION_RE.finditer(text) if not mask[m.start()]]
    if not marks:
        return []
    slices = []
    for index, start in enumerate(marks):
        end = marks[index + 1] if index + 1 < len(marks) else len(text)
        slices.append(text[start:end].strip().strip(";").strip())
    return [s for s in slices if s]


def _detail_from(text: str) -> list[str]:
    """Detail lines for an engine message, split per violation when it can be.

    The engine's own words are never paraphrased: an unsplittable message is
    printed as-is rather than described.
    """
    slices = _violation_slices(text)
    if slices:
        return slices
    if text:
        return text.splitlines()
    return ["(engine produced no message)"]


def _find_mstar() -> str | None:
    found = shutil.which("mstar")
    if found:
        return found
    if os.access(MSTAR_FALLBACK, os.X_OK):
        return MSTAR_FALLBACK
    return None


# --------------------------------------------------------------------------
# legs (a) and (b): engine `status validate`
# --------------------------------------------------------------------------


def _status_validate(
    leg: str, rel: str, path: Path, mstar: str | None, *, kind: str = KIND_DOCUMENT
) -> Document:
    if mstar is None:
        return Document(
            leg, rel, STATE_NOT_VALIDATED,
            detail=["engine CLI `mstar` not found on PATH or at " + MSTAR_FALLBACK],
        )
    run = _run([mstar, "status", "validate", str(path)])
    return _verdict(leg, rel, path, run, kind=kind)


def check_snapshots(harness: Path, report: Report, mstar: str | None) -> None:
    workflows = harness / "workflows"
    if not workflows.is_dir():
        report.add_note("snapshots", "workflows/ absent — no snapshots to validate")
        report.counters["snapshots"] = 0
        return
    paths = sorted(workflows.glob("*/snapshot.json"))
    report.counters["snapshots"] = len(paths)
    if not paths:
        report.add_note("snapshots", "workflows/ present but holds no */snapshot.json — nothing to validate")
    for path in paths:
        report.documents.append(
            _status_validate("snapshots", f"workflows/{path.parent.name}/snapshot.json", path, mstar)
        )


def check_root_register(harness: Path, report: Report, mstar: str | None) -> None:
    path = harness / "status.json"
    if not path.is_file():
        # Two very different situations share "not a regular file": the benign
        # one (this checkout carries the published subset only, so there is no
        # root register at all — a note) and the defective one (something is
        # there but is not reachable as a file — a document this leg must fail
        # loud on, never demote to "nothing to validate", which would drop the
        # `[status]` document line and silently clean the summary).
        #
        # The defective shapes are *delegated*, not adjudicated here: a
        # directory at this path makes the engine report `status.invalid-json:
        # EISDIR …` (a real report, anchored to this path, so FAIL), and a
        # dangling symlink makes it answer `status file not found` over exit 1
        # with no report (so NOT-VALIDATED).  Either way the run fails loud and
        # this checker still owns no rule of its own.
        if path.exists() or path.is_symlink():
            report.counters["root-register"] = 1
            report.documents.append(
                _status_validate("status", "status.json", path, mstar, kind=KIND_ROOT_REGISTER)
            )
            return
        report.add_note("status", "status.json absent — no root register to validate")
        report.counters["root-register"] = 0
        return
    report.counters["root-register"] = 1
    report.documents.append(
        _status_validate("status", "status.json", path, mstar, kind=KIND_ROOT_REGISTER)
    )


# --------------------------------------------------------------------------
# leg (c): the project residual registers
# --------------------------------------------------------------------------


def _register_validate(leg: str, rel: str, key: str, harness: Path, mstar: str | None) -> Document:
    if mstar is None:
        return Document(
            leg, rel, STATE_NOT_VALIDATED,
            detail=["engine CLI `mstar` not found on PATH or at " + MSTAR_FALLBACK],
        )
    path = harness / "projects" / key / "residuals.json"
    env = dict(os.environ)
    env["MSTAR_HARNESS_DIR"] = str(harness)
    run = _run([mstar, "persist", "get", "--validate", "residuals", "--key", key], cwd=harness, env=env)
    # Same channel as the other two legs: our own reading of the register on
    # disk decides readability, then the reader's exit code is the verdict.  The
    # reader's prose is never parsed for the decision — it is `refusing to
    # persist invalid residuals document: …` on a refusal and `Invalid JSON in
    # <path>: …` on an unreadable document, and both are text the document (its
    # values) or its path can spell.
    document = _verdict(leg, rel, path, run)
    if document.state == STATE_FAIL and document.count is None:
        # This leg's reader prints no `FAIL (N violations)` header — it refuses
        # with the violations inline after a fixed prologue — so the header
        # lookup in `_verdict` finds nothing.  Fall back to the reader's inline
        # violation tokens.  Safe because the verdict is already FAIL: the number
        # is display only, so an inflated count misreports the size of a refusal
        # that really happened and cannot create or hide a verdict.
        document.count = _register_refusal_count(run.text)
    return document


def check_registers(harness: Path, report: Report, mstar: str | None) -> None:
    projects = harness / "projects"
    if not projects.is_dir():
        report.add_note("registers", "projects/ absent — no project registers to validate")
        report.counters["registers"] = 0
        return
    paths = sorted(projects.glob("*/residuals.json"))
    report.counters["registers"] = len(paths)
    if not paths:
        report.add_note("registers", "projects/ present but holds no */residuals.json — nothing to validate")
    for path in paths:
        project = path.parent.name
        report.documents.append(
            _register_validate("registers", f"projects/{project}/residuals.json", project, harness, mstar)
        )


# --------------------------------------------------------------------------
# leg (d): the published-set ratchet
# --------------------------------------------------------------------------


def is_published(harness_relative: str) -> bool:
    """The D11 published set, as a prefix list — the verdict, not git's answer."""
    if harness_relative in PUBLISHED_EXACT:
        return True
    if harness_relative.startswith(PUBLISHED_PREFIXES):
        return True
    return bool(PUBLISHED_ITERATION_SPECS_RE.match(harness_relative))


def parse_symbol_table(agents_md: str) -> dict[str, str]:
    """Read `.mstar/AGENTS.md` § Path symbols so the debt list cannot drift.

    Only a bare ``{NAME}`` qualifies as a symbol row.  The debt table further
    down is shaped like a symbol table (backticked token in cell 0, backticked
    value in cell 1), so a looser test reads each debt row as a symbol mapping
    the whole path to its re-add commit — which silently rewrites every debt
    path into a commit hash and turns the ratchet into a false alarm.
    """
    symbols: dict[str, str] = {}
    for line in agents_md.splitlines():
        cells = _table_cells(line)
        if len(cells) < 2:
            continue
        symbol = _backticked(cells[0])
        target = _backticked(cells[1])
        if symbol and target and BARE_SYMBOL_RE.match(symbol):
            symbols[symbol] = target
    return symbols


def parse_frozen_debt(agents_md: str, symbols: dict[str, str]) -> list[str]:
    """Read the `**debt**` rows of the § Published vs local debt table.

    Each row's first backticked token is a path written in symbol form; the
    verdict cell must carry `**debt**` (rows marked `**published**` are not
    debt).  Rows whose token names an unknown symbol are returned as-is so the
    caller can fail loud rather than drop them.
    """
    debt: list[str] = []
    for line in agents_md.splitlines():
        cells = _table_cells(line)
        if not cells or "**debt**" not in line:
            continue
        token = _backticked(cells[0])
        if not token:
            continue
        debt.append(_expand_symbol(token, symbols))
    return debt


def _table_cells(line: str) -> list[str]:
    if not line.lstrip().startswith("|"):
        return []
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _backticked(cell: str) -> str | None:
    match = re.search(r"`([^`]+)`", cell)
    return match.group(1) if match else None


def _expand_symbol(token: str, symbols: dict[str, str]) -> str:
    for symbol in sorted(symbols, key=len, reverse=True):
        if token.startswith(symbol):
            remainder = token[len(symbol):].lstrip("/")
            base = symbols[symbol].rstrip("/")
            return f"{base}/{remainder}" if remainder else base
    return token


def _ignore_evidence(repo_root: Path, paths: list[str]) -> dict[str, str]:
    """Which ignore rule matches each path, read from the RULES.

    Bare ``git check-ignore`` is masked by the index: a tracked file reports
    nothing, which is exactly the population this ratchet exists to find.  So
    ``--no-index`` is required, and the result is evidence on the report line —
    the verdict is always the D11 prefix list (a force-added process file is
    both tracked and ignored; that is the finding, not an exemption).
    """
    if not paths:
        return {}
    payload = "\0".join(paths) + "\0"
    run = _run(
        ["git", "-C", str(repo_root), "check-ignore", "--no-index", "-z", "-v", "--stdin"],
        env={**os.environ},
        input_text=payload,
    )
    evidence: dict[str, str] = {}
    if run.failed_to_start:
        return {path: f"git check-ignore unavailable ({run.failed_to_start})" for path in paths}
    fields = [f for f in run.stdout.split("\0") if f != ""]
    # -z -v emits four fields per match: source, line number, pattern, pathname.
    for index in range(0, len(fields) - 3, 4):
        source, lineno, pattern, pathname = fields[index:index + 4]
        evidence[pathname] = f"{source}:{lineno}:{pattern}"
    return evidence


def check_ratchet(harness: Path, report: Report) -> None:
    """The published-set ratchet (compass D11), reported as one document.

    Fails on any tracked path outside the published set that is not on the
    frozen six-path debt list recorded in `{HARNESS_DIR}/AGENTS.md`.  The list
    is read from that file so the two cannot drift, and it may only shrink: a
    listed path that is no longer tracked is a stale-debt note, not a failure.
    """
    leg = "ratchet"
    label = harness.name

    top = _run(["git", "-C", str(harness), "rev-parse", "--show-toplevel"])
    if top.failed_to_start or top.rc != 0:
        report.documents.append(Document(
            leg, label, STATE_NOT_VALIDATED,
            detail=["harness dir is not inside a git work tree — tracked set unresolved: "
                    + (top.text or top.failed_to_start or "no output")],
        ))
        return
    repo_root = Path(top.stdout.strip())
    try:
        harness_rel = harness.relative_to(repo_root).as_posix()
    except ValueError:
        report.documents.append(Document(
            leg, label, STATE_NOT_VALIDATED,
            detail=[f"harness dir is outside its git work tree ({repo_root})"],
        ))
        return
    if harness_rel in (".", ""):
        report.documents.append(Document(
            leg, label, STATE_NOT_VALIDATED,
            detail=["harness dir is the repository root — the published-set ratchet is defined for a harness subtree"],
        ))
        return
    label = harness_rel

    listed = _run(["git", "-C", str(repo_root), "ls-files", "-z", "--", harness_rel])
    if listed.failed_to_start or listed.rc != 0:
        report.documents.append(Document(
            leg, label, STATE_NOT_VALIDATED,
            detail=[f"`git ls-files {harness_rel}` failed: {listed.text or listed.failed_to_start}"],
        ))
        return
    tracked = [p for p in listed.stdout.split("\0") if p]

    try:
        agents_md = (harness / "AGENTS.md").read_text(encoding="utf-8")
    except OSError as exc:
        report.documents.append(Document(
            leg, label, STATE_NOT_VALIDATED,
            detail=[f"cannot read the frozen debt list from {harness_rel}/AGENTS.md: {exc}"],
        ))
        return

    symbols = parse_symbol_table(agents_md)
    debt_tokens = parse_frozen_debt(agents_md, symbols)
    unresolved = [token for token in debt_tokens if token.startswith("{")]
    if unresolved:
        report.documents.append(Document(
            leg, label, STATE_NOT_VALIDATED,
            detail=["frozen debt row(s) name a symbol absent from the § Path symbols table: "
                    + ", ".join(unresolved)],
        ))
        return

    # The debt table writes paths from the repository root; accept a
    # harness-relative spelling too, since both resolve against the same file.
    def to_harness_relative(token: str) -> str:
        if token == harness_rel:
            return "."
        return token[len(harness_rel) + 1:] if token.startswith(harness_rel + "/") else token

    debt = {to_harness_relative(token): token for token in debt_tokens}
    relative_paths = [p[len(harness_rel) + 1:] for p in tracked if p.startswith(harness_rel + "/")]
    tracked_relative = set(relative_paths)
    evidence = _ignore_evidence(repo_root, tracked)

    published: list[str] = []
    frozen: list[str] = []
    findings: list[str] = []
    for relative in relative_paths:
        if is_published(relative):
            published.append(relative)
        elif relative in debt:
            frozen.append(relative)
        else:
            repo_path = f"{harness_rel}/{relative}"
            findings.append(
                f"{repo_path} is tracked but outside the published set (compass D11: "
                "{HARNESS_DIR}/AGENTS.md, {SPECS_DIR}/**, {KNOWLEDGE_DIR}/**, {ITERATION_DIR}/<id>/specs/**) "
                f"and is not on the frozen debt list in {harness_rel}/AGENTS.md"
                f" — ignore rules say: {evidence.get(repo_path, 'not matched by any ignore rule')}"
            )

    stale = sorted(set(debt) - tracked_relative)
    for relative in stale:
        report.add_note(leg, f"stale debt {harness_rel}/{relative}: listed in {harness_rel}/AGENTS.md "
                             "but no longer tracked — drop the row to tighten the ratchet")
    if frozen:
        report.add_note(leg, "frozen debt tolerated (may only shrink): "
                             + ", ".join(f"{harness_rel}/{p}" for p in sorted(frozen)))
    if not debt_tokens:
        report.add_note(leg, f"{harness_rel}/AGENTS.md records no **debt** rows — the frozen debt list is empty")

    report.counters["tracked"] = len(relative_paths)
    report.counters["published"] = len(published)
    report.counters["frozen-debt"] = len(frozen)
    report.counters["new-out-of-set"] = len(findings)
    report.counters["stale-debt"] = len(stale)

    report.documents.append(Document(
        leg,
        label,
        STATE_FAIL if findings else STATE_OK,
        count=len(findings) if findings else None,
        detail=findings,
    ))


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def run_all(harness: Path) -> Report:
    report = Report()
    mstar = _find_mstar()
    if mstar is None:
        report.add_note("engine", f"engine CLI `mstar` not found on PATH or at {MSTAR_FALLBACK}")
    check_snapshots(harness, report, mstar)
    check_root_register(harness, report, mstar)
    check_registers(harness, report, mstar)
    check_ratchet(harness, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_harness_state.py",
        description=(
            "Validate every engine-read lifecycle document in a Morning Star harness dir and the "
            "published-set ratchet over its tracked paths. Delegates every rule to the engine "
            "(mstar status validate / mstar persist get --validate); a document it cannot reach "
            "is reported NOT-VALIDATED, which is a failure."
        ),
    )
    parser.add_argument(
        "harness_dir",
        nargs="?",
        default=None,
        help="harness dir to validate (default: ./.mstar)",
    )
    args = parser.parse_args(argv)

    requested = args.harness_dir or ".mstar"
    harness = Path(requested)
    if not harness.is_dir():
        print(f"usage error: not a harness dir: {requested}", file=sys.stderr)
        return EXIT_USAGE
    harness = harness.resolve()

    report = run_all(harness)
    print(f"harness dir: {_one_line(str(harness))}")
    print(report.render())
    return EXIT_VIOLATION if report.failing else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
