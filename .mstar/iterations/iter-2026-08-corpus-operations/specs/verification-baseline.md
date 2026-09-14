# Installed CLI verification baseline delta

The supported delivery surface is the installed `bili-asr` console script on Python 3.12, with module invocation as supplemental coverage.

## Contract to lock

- Isolated installation tests exercise `bili-asr --help` and `bili-asr status --archive-root <temporary-root>` through the declared console script.
- Python 3.12 verification runs the full fake-only suite without live Bilibili traffic or model downloads.
- Dependency/security inspection has a repeatable tool/version policy and reports unavailable advisory data honestly.
- CI/local artifacts record versions, results, and prerequisites but never environment cookie values, signed URLs, raw exceptions, models, or media.
