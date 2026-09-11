### Task 1: Characterize and lock mixed outcomes

**Files:** CLI/coordinator tests, iteration spec, README as needed.

- [ ] Build fake multi-row scenarios covering one success plus one failure/skip for each shipped batch command.
- [ ] Record the current observable state, output, ledger/coordinator sidecars, and exit code; identify any mismatch with the frozen exit taxonomy.
- [ ] Lock the result aggregation rules, including explicit selectors that resolve only terminal rows and risk interruption precedence.
- [ ] Confirm retryable rows remain eligible and successful rows are not duplicated on rerun.

Run: characterization tests are deterministic and expose any pre-fix mismatch without weakening assertions.

