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

Engine rule set cited by ``file:line`` — the installed CLI is the binary that
actually runs (``/usr/local/bin/mstar`` -> ``/usr/lib/node_modules/
@mstar-harness/cli/dist/mstar-harness.js``, ``@mstar-harness/cli`` 3.11.2), so
those are the primary citations; the in-process dsh engine bundle is cited
second for readers of the host side.  Line numbers verified 2026-09-28 with
``grep -n 'function validate<X>' <file>``:

  installed CLI  @mstar-harness/cli 3.11.2  dist/mstar-harness.js
    ``validateWorkflowSnapshot``  L3642   -> leg (a), leg (b) snapshot rows
    ``validatePlanRow``           L4453   -> ``plans[]`` rows inside (a)
    ``validateResidual``          L4490   -> each entry inside (c)
    ``validateProjectRegister``   L5123   -> leg (c)
    ``PERSIST_KINDS`` / ``COORDINATED_PERSIST_KINDS``  L24777-24778
    ``status validate`` routing   L24482   -> by basename: a ``snapshot.json``
                                             path goes through
                                             ``readSnapshotForCheck``, which
                                             throws on unreadable JSON instead
                                             of reporting a violation.  That is
                                             why this checker keys on the
                                             engine's ``FAIL (N violations)``
                                             header and not on exit 1 alone.
    ``assertStoredArtifact``      L17139  -> the persist gate that dispatches
                                             ``kind === "residuals"`` (L17145) to
                                             ``validateProjectRegister`` at
                                             L17146, i.e. what legs (c) actually
                                             receives back.
    ``status.migration-required`` L13716, L13724  -> the misroute this file
                                             documents: ``validateStatusV2``
                                             (L13693) applied to a register sees
                                             ``version !== 2`` and reports a
                                             schema-version defect for a
                                             document that has no
                                             ``schema_version`` to be wrong.

  in-process engine   @mstar-harness/dsh 3.11.2  dist/index.js
    ``validateWorkflowSnapshot``  L3103
    ``validatePlanRow``           L3308
    ``validateResidual``          L3345
    ``validateProjectRegister``   L4117

  (The two bundles are separate builds of the same rule set; a reader
  re-deriving a rule should read the installed-CLI line for what this checker
  actually receives back.)

Usage::

    python scripts/validate_harness_state.py [HARNESS_DIR]

``HARNESS_DIR`` defaults to ``./.mstar``.  Exit 0 clean, 1 on any violation or
not-validated document, 2 on usage.
"""

from __future__ import annotations

import argparse
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
# `status validate` heads a failing report with `<path>: FAIL (N violations)`.
# That header is the authoritative "these are violations" signal: exit 1 without
# it means the engine could not read the document at all (`status file not
# found`), which is a not-validated document, not a violation.
FAIL_HEADER_RE = re.compile(r"FAIL \((\d+) violations?\)")

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


@dataclass
class Document:
    """One routed document and the engine's verdict on it."""

    leg: str
    rel: str
    state: str
    count: int | None = None
    detail: list[str] = field(default_factory=list)

    def render(self) -> list[str]:
        if self.state == STATE_FAIL:
            count = "?" if self.count is None else str(self.count)
            head = f"[{self.leg}] FAIL {self.rel}: {count} violations"
        else:
            head = f"[{self.leg}] {self.state} {self.rel}"
        return [head] + [f"[{self.leg}]   {line}" for line in self.detail]


@dataclass
class Report:
    documents: list[Document] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)

    def add_note(self, leg: str, text: str) -> None:
        self.notes.append(f"[{leg}] note {text}")

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


def _violation_slices(text: str) -> list[str]:
    """Split engine output into per-violation slices, engine text verbatim.

    The persist validator joins every violation into one long line, so the
    report would be unreadable without this.  Slices keep the engine's own
    words; the message is never paraphrased.  A text the regex cannot split
    yields an empty list and the caller prints it raw instead.
    """
    marks = [m.start() for m in VIOLATION_RE.finditer(text)]
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


def _status_validate(leg: str, rel: str, path: Path, mstar: str | None) -> Document:
    if mstar is None:
        return Document(
            leg, rel, STATE_NOT_VALIDATED,
            detail=["engine CLI `mstar` not found on PATH or at " + MSTAR_FALLBACK],
        )
    run = _run([mstar, "status", "validate", str(path)])
    if run.failed_to_start:
        return Document(leg, rel, STATE_NOT_VALIDATED, detail=[f"engine CLI could not run: {run.failed_to_start}"])
    if run.rc == 0:
        return Document(leg, rel, STATE_OK, detail=[])
    if run.rc == 1:
        header = FAIL_HEADER_RE.search(run.text)
        if header is None:
            # Exit 1 without a violation report is the engine saying it could
            # not read the document (`status file not found`), not a verdict on
            # its contents.  Claiming FAIL here would invent a violation.
            detail = _detail_from(run.text)
            return Document(
                leg, rel, STATE_NOT_VALIDATED,
                detail=["engine could not read the document (exit 1, no violation report)"] + detail,
            )
        slices = _violation_slices(run.text)
        detail = slices or run.text.splitlines()
        return Document(leg, rel, STATE_FAIL, count=int(header.group(1)), detail=detail)
    # Any other exit code means the checker cannot interpret the verdict; that
    # is a not-validated document, never a silent pass.
    detail = _detail_from(run.text)
    return Document(
        leg, rel, STATE_NOT_VALIDATED,
        detail=[f"engine CLI exited {run.rc} (expected 0 or 1)"] + detail,
    )


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
        report.add_note("status", "status.json absent — no root register to validate")
        report.counters["root-register"] = 0
        return
    report.counters["root-register"] = 1
    report.documents.append(_status_validate("status", "status.json", path, mstar))


# --------------------------------------------------------------------------
# leg (c): the project residual registers
# --------------------------------------------------------------------------


def _register_validate(leg: str, rel: str, key: str, harness: Path, mstar: str | None) -> Document:
    if mstar is None:
        return Document(
            leg, rel, STATE_NOT_VALIDATED,
            detail=["engine CLI `mstar` not found on PATH or at " + MSTAR_FALLBACK],
        )
    env = dict(os.environ)
    env["MSTAR_HARNESS_DIR"] = str(harness)
    run = _run([mstar, "persist", "get", "--validate", "residuals", "--key", key], cwd=harness, env=env)
    if run.failed_to_start:
        return Document(leg, rel, STATE_NOT_VALIDATED, detail=[f"engine reader could not run: {run.failed_to_start}"])
    if run.rc == 0:
        return Document(leg, rel, STATE_OK, detail=[])
    if run.rc == 1:
        slices = _violation_slices(run.text)
        if not slices:
            # Exit 1 with no parseable violation is the reader saying it could
            # not reach or could not validate the document — not a violation.
            return Document(
                leg, rel, STATE_NOT_VALIDATED,
                detail=["engine reader exited 1 without a violation list (document unreachable?)"]
                + _detail_from(run.text),
            )
        return Document(leg, rel, STATE_FAIL, count=len(slices), detail=slices)
    detail = _detail_from(run.text)
    return Document(
        leg, rel, STATE_NOT_VALIDATED,
        detail=[f"engine reader exited {run.rc} (expected 0 or 1)"] + detail,
    )


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
    print(f"harness dir: {harness}")
    print(report.render())
    return EXIT_VIOLATION if report.failing else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
