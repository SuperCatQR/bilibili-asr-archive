# Production OperationalError investigation, 2026-10-15

Verified at 2026-10-15 17:40:46 +08:00 on the production server for uploader 23191782.

## Finding and evidence

The subtitle/publish worker PID 8037 had 1019 open file descriptors against a
soft limit of 1024: 635 sockets, 379 eventfds, and 5 other descriptors. The first
recorded OperationalError in the examined timeline occurred at 08:26:48 +08:00.
Production workflow attempts retained the exception class, not its message.

An isolated SQLite copy reproduced `OperationalError: unable to open database
file` (SQLITE_CANTOPEN, code 14) when its process exhausted file descriptors.
The identical update succeeded after releasing descriptors and was rolled back.
This message is the controlled reproduction, not a recovered production traceback.

The actual publish handler succeeded on an isolated database and output directory
for both examined jobs. Raising only the live worker's soft limit from 1024 to
8192 then allowed the original production worker to publish the failed ASR
transcript without restarting it or the ASR workers.

The pinned Bilibili SDK retains HTTP clients keyed by event loop in global
`session_pool` and `lazy_settings` dictionaries. Subtitle harvest uses
`asyncio.run` for each job, leaving clients associated with discarded loops.
With the production curl backend and no HTTP requests, allocating transport
resources in 20 successive loops increased descriptors from 4 to 24 and retained
20 clients. This independently reproduces the resource lifetime defect.

## Recovery

- Retried 296 failed publish jobs classified OperationalError: one sample and
  then a batch of 295. Every job succeeded; historical attempts remain readable.
- The remaining OSError publish job also passed isolated publication and then
  succeeded on production retry. Its original message was not retained, so its
  precise original cause is not independently established.
- Verified all 297 recovered jobs and 1485 nonempty SRT/VTT/TXT/MD/raw files.
- No new OperationalError attempts appeared after the limit change at
  2026-10-15 16:52:01 +08:00 through the verification snapshot.
- Publication totals at the snapshot: 624 succeeded, no failed publish jobs.

The sample that originally triggered this investigation was BV1ck4y1N7pQ P1,
transcript 834, publish job `a1b59ae3-02a1-427a-9f50-c9a417285d29`.
Its failed attempt `7d799404-52be-48ea-99d1-aac92f9e8b5d` is preserved;
the succeeding retry is `eba4e703-d4b0-48f1-a507-b6805152ddf1`.

## Code correction and activation boundary

The SDK settings scope now closes clients created within its owning request
before its event loop exits and removes the corresponding SDK pool entries.
Nested scopes reuse the outer owner; preexisting clients remain owned by their
creator. Cleanup failures pass through the existing bounded gateway error mapper.

The local source and the server runtime files were patched. Server changes were
limited to the compatible request scope and gateway request wrapper; the newer
local gateway module was not copied over the older server runtime wholesale.
Original server files were backed up under the diagnostic directory.

PID 8037 was not restarted. Its currently loaded code still predates the cleanup
patch and uses the increased soft limit; new processes load the corrected code.
At the snapshot it had 1021 descriptors, a soft limit of 8192, and no queued
subtitle jobs. A future controlled restart loads the permanent cleanup fix.

## Validation and review

- Focused suites: 433 passed, 1 skipped:
  `test_source_request_scope.py`, `test_bilibili_api_gateway.py`,
  `test_subtitle_candidates.py`, `test_source_workflow_ports.py`.
- Tests cover repeated loops, success, failure, cancellation, nested ownership,
  preexisting clients, gateway wiring, and safe cleanup failure classification.
- Inverting the client ownership condition caused four regression tests to fail;
  the original source was restored before the final successful test run.
- A new server process exercised the patched gateway with the real installed
  SDK and curl backend for 100 event loops, without HTTP requests: descriptors
  remained 4 and both SDK pools were empty afterward.
- `git diff --check` passed. Ruff passed on the request scope and its focused
  tests; the wider files have existing lint findings and are not lint-clean.
- The broader legacy subtitle test selection was not green: `test_subtitles.py`
  imports a removed module, and `test_subtitle_e2e.py` calls removed CLI commands.
  These unrelated migration failures were not changed as part of this repair.
- Manual review covered ownership, error mapping, concurrency lock release,
  secret handling, SDK import boundaries, and the cost of closing request clients.
  The patch adds no dependency or upstream request.
- The existing 3-5 second metadata pacing change was preserved, and two outdated
  pacing assertions were aligned with that configured interval.

## Separate subtitle authentication blocker

A single formerly OperationalError subtitle job was retried after database
recovery: `fe748784-b5ae-4666-b5f7-760177f65e00`, part 854. It now reaches the
upstream request and fails with auth_error. Its original failed attempt remains.
A fresh patched process checked the same worker credential independently and
received API code -101 from `validate_subtitle_credentials`.

The remaining subtitle jobs were not retried in bulk against the rejected
credential. At the snapshot, 485 retained OperationalError failures and 83 had
auth_error. These are unresolved subtitle acquisition jobs, not evidence of
silent audio and not newly recurring database failures. Continuing those jobs
requires a valid replacement SESSDATA.

ASR remained active: 625 succeeded, 4 running, 236 queued. The one historical
inference_timeout failure has its previously completed replacement. GPU
utilization was 100 percent, with 31794 / 32760 MiB allocated. Free data disk
space was 17.49 GiB; all values are snapshot measurements.

## Evidence locations

Server: `/root/autodl-tmp/production-ops-23191782/publish-diagnostic-20261015/`.
Local JSON copies: `.tmp/publish-diagnostic-20261015/`.
`final-report.json` contains the recovered job list, validation counts, process
limits, isolated reproduction, credential diagnostic, and patch deployment facts.
No credential values are included in these reports.
