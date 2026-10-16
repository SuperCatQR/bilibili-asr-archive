# Editorial schedule on the UID 23191782 production server

The deployed scheduler has six editorial slots. It uses `Asia/Shanghai` explicitly,
regardless of the server's system timezone. On Monday through Friday it prohibits
new claims and new model calls during `[09:00, 12:00)` and `[14:00, 18:00)`.
Dates in the official holiday leave calendar are exempt. Weekends remain allowed,
including Saturdays and Sundays designated as makeup working days.

Each physical model call rechecks the calendar, free disk space and a recent
provider health snapshot. Calls already in flight finish normally and save their
response. If a task has another chunk, that chunk waits for admission while its
normal workflow lease heartbeat continues. Schedule transitions do not kill
requests or unload the ASR workers. Slot locks also prevent a restarted scheduler
from exceeding six concurrent calls while an orphaned request finishes.

The server directory is
`/root/autodl-tmp/production-ops-23191782/ai-schedule/`. Its `policy.json` records
the provider, model, six slots, original producer profile arguments, time windows,
and each year's official holiday source and leave dates. The verified 2026 notice
is 国办发明电〔2025〕7号, published on 2025-11-04. The controller checks the current
and following year daily using the maintained `NateScarlet/holiday-cn` dataset.
It imports only calendars with accessible State Council notices confirming the
year, validates ISO dates and retains the previous policy on any failure. Manual
updates should also verify the official notices; do not infer dates from lunar holidays or
treat makeup working weekends as ordinary weekdays. An unknown calendar year
retains the weekday blackout and reports `calendar_year_known: false`.

Use `bili-asr-ai-service start|stop|status`. Start is idempotent; stop requests a
workflow drain with a 180-second deadline; requests exceeding that shutdown
deadline retain their failed attempt evidence. Time-window transitions do not
invoke this shutdown path. Wait until the old controller has exited before
starting again. The production service also invokes this service when starting or
stopping. Inspect `state.json`, `provider-health.json`, `slot-1.json` through
`slot-6.json`, and `worker-*.log` for live evidence. Failed business jobs keep their
original attempts and are never automatically recovered by this scheduler.

When the provider is unreachable, slots wait before claiming tasks. Health is
checked every 60 seconds, expires after 120 seconds, and must match the configured
model and endpoint. Free space below 6 GiB also blocks new editorial activity.
Provider health checks use the models endpoint and do not submit paid completion
requests. The existing download controller retains its 12 GiB and backlog guards.

The controller incrementally plans editorial jobs for ASR results from this UID
using the existing producer profile, reusing the original audio and ASR jobs.
Installing these standalone deployment scripts does not replace the ASR runtime.
Copy `run_editorial_schedule.py` and `editorial_time_policy.py` into the operations
directory, and install `editorial_schedule_service.sh` as
`/usr/local/bin/bili-asr-ai-service` with executable permissions. The shell wrapper
is specific to the production paths above. Other deployments can invoke the
Python controller directly with `--project-root`, `--archive-root`, `--ops-root`,
`--policy`, and `--bin` pointing to their own project and production CLI wrapper.
Preserve the existing `policy.json` when upgrading. Its required structure is:

```json
{
  "schema": "editorial-time-policy/v1",
  "timezone": "Asia/Shanghai",
  "workers": 6,
  "weekday_blackout_minutes": [[540, 720], [840, 1080]],
  "holiday_calendars": {},
  "provider_base_url": "https://opencode.ai/inference/go/v1",
  "model": "deepseek-v4.1-flash",
  "uploader_mid": 23191782,
  "producer_planning_args": []
}
```

Populate `producer_planning_args` from the archive's existing producer profile
and verified holiday calendars before production use; an empty calendar keeps
the weekday blackout until the official-calendar refresh succeeds.
The CLI `--at <aware ISO timestamp>` checks calendar behavior offline without
claiming jobs or contacting the model provider.

If the server cannot reach OpenCode but the operator's machine can, the optional
`opencode_ssh_relay.py` runs on that machine with `--daemon`, SSH host/port,
the verified SSH fingerprint, and an absolute `--state-dir`. It reads the SSH
password interactively and passes it to the detached process over stdin; it does
not save the password. The relay binds only `127.0.0.1:18443` on the server,
accepts only CONNECT to `opencode.ai:443`, and carries the original verified TLS
connection. No API key or transcript is logged or decrypted by the relay.
Install the project's `remote` extra on this machine for Paramiko. Supply
`--fingerprint` as the verified SSH key fingerprint's lowercase hexadecimal
bytes, without colon separators. The relay admits at most 16 concurrent tunnels
and closes excess channels instead of accumulating an unbounded queue.

To opt in, save `network.json` beside the scheduler's `policy.json` containing
`{"opencode_https_proxy":"http://127.0.0.1:18443"}`. Both the provider probe and
editorial requests use this host-specific proxy. Other provider endpoints,
calendar downloads, and the ASR processes retain their existing networking.
The operator's machine must remain online. SSH reconnects automatically while
the relay process is alive. Its state directory contains `state.json`,
`relay.pid`, and `relay.log`; create its `STOP` file to drain and stop it.
When the relay becomes unavailable the scheduler's provider health gate blocks
new requests. Existing in-flight requests can still fail and retain their normal
workflow attempt evidence. Removing `network.json` also clears the relay on an
existing worker session before its next model call. To remove the relay, remove
`network.json` and stop
the local relay after the server's direct route has been verified.
