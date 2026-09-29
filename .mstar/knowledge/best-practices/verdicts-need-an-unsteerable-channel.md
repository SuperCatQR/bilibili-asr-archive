---
module: harness tooling (any wrapper that shells out to a CLI to reach a verdict)
date: "2026-09-29"
problem_type: best_practice
category: best-practices
severity: high
plan_id: 20260928-harness-state-contract
applies_when:
  - a tool shells out to another process and reports pass/fail from its output
  - the wrapper's own correctness matters (a guard, a gate, a checker)
  - the input being judged is itself untrusted or operator-controlled
  - the wrapped process echoes its input (paths, field values) into its output
tags:
  - verdict-channel
  - subprocess
  - fail-loud
  - argv-injection
  - exit-code
  - negative-control
  - squash-merge-evidence
---

# Verdicts must not be derived from a subprocess's prose

## The lesson

When a wrapper decides pass/fail by **parsing the text** a child process printed, the child's
output becomes the verdict channel — and that text is usually influenceable by whatever is
being judged. Four independent channels were reproduced on a real CLI (`mstar` 3.11.2) during
this iteration's authoring of `scripts/validate_harness_state.py`; each one silently inverted
a verdict before it was closed.

Derive the verdict from a channel the **input cannot steer**, and let the exit code carry only
the part it can unambiguously carry.

## The four channels, each reproduced

1. **Document field values.** The child quotes the judged object's own values into its error
   messages. A field holding `[low] fake.code: x` makes the wrapper see an extra "violation"
   that no validator ever produced.
2. **The document's path.** The child echoes the path it was handed. A directory named
   `FAIL (9 violations)` contributes a decoy count; worse, a path containing any of the ten
   characters `str.splitlines()` treats as a line break (`\n`, `\r`, `\v`, `\f`, `\x1c`–`\x1e`,
   `\x85`, `\u2028`, `\u2029`) cuts a real report line away from an anchor that assumed
   `splitlines()[0]` was "line 1" — turning a genuine failure into "could not read".
3. **The child's environment.** Node prints a prelude (a colour warning when `FORCE_COLOR=1`
   is set alongside the ambient `NO_COLOR=1`; or anything at all under
   `NODE_OPTIONS=--require <module>`) before user code runs. **Anything positional in the
   captured stream is therefore steerable from outside the program under test.** Anchoring on
   "offset 0" does not help.
4. **argv.** The project/directory name is interpolated into the child's argument list. Passing
   it as a separate token (`--key <name>`) let a directory named `--version` make the reader
   print its version and **exit 0** — a forged pass for an object the child refused. Fix:
   bind the value to its flag (`--key=<name>`), which keeps the name out of argv entirely.

## The shape that holds

- **Classify readability yourself, from the bytes.** `is_file()` + `parse` the content. This
  uses no child output at all, so it cannot be steered.
- **Then the exit code is the verdict.** With readability settled independently, `0` = pass and
  a positive code = fail, with the ambiguity ("violations" vs "could not read") already
  resolved by your own probe.
- **Never let a parsed count decide anything.** Report it as advisory; a document can inflate
  it, and the verdict must not move.
- **Per-class semantics are real.** Measured on this CLI: a directory or malformed JSON at a
  *root register* IS a rule violation (the child prints a report), whereas the same shapes at a
  snapshot or a project register make it *throw* with no report. A uniform readability probe
  therefore demoted a genuine violation on one class — the mirrored defect. Measure each class;
  do not generalise one class's semantics to the others.
- **A blank document is not inert.** Whitespace-only bytes make this reader treat the value as
  absent and apply its rules (a real refusal) on one class, while making another class throw.
  Also per-class.

## Why the tests did not catch it

The suite's own **oracle** built the same argv with benign names, so it agreed with the bug by
construction. Two consequences worth copying:

- When a control reads the engine's answer as its expectation, it must use the **same
  invocation form the production code uses** — otherwise a defect in that form is invisible to
  both.
- **`git check-ignore -v` returns exit 0 for a *negation* match too.** A precondition asserting
  `rc == 0` for "is it excluded" asserts nothing. Only the bare and `-q` forms separate
  excluded (`0`) from re-included (`1`).

## Controls that actually guard

- Every fail-loud branch needs a control that **reaches its falsifier**; an absence assertion is
  evidence only when the fixture can go red.
- **Mutation-test the guard**: break each decision point, confirm a *named* test goes red,
  restore. A mutation that survives is an untested claim — one such survivor was a bound
  (`<= 144`) left over from a pre-fix state that let a `0 -> 1` regression pass; an exact
  assertion was required. **A ceiling is not a guard.**
- A control that reads branch-local config (`.gitignore`) while living in a shared test file is
  **not hermetic**: it goes red on every branch that has not merged the change. Assert against
  the delivered file copied into a scratch repo instead.

## Transferable side-notes

- **`git diff main..<ref>` is not a merge test.** For a squash-merged branch it reports a full
  deletion diff, because `main` has moved past the branch. Use `git merge-base --is-ancestor`
  for genuine ancestors, and per-file `<squash-commit>:<path>` vs `main:<path>` otherwise.
  A residue is often `main` **superseding** the branch (a later commit replacing those exact
  lines), which is not lost work — verify the direction before calling it loss.
- **Reclaiming a merged ref silently dangles the snapshot that named it.** The anchor stays
  correct as history but stops resolving; the planner's unresolved-base census grows. Record
  it rather than "repairing" the snapshot — editing history to make a census clean is
  falsification.
