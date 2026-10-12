"""Run a configured archive backup policy under a local process supervisor."""
import argparse
import json
import signal
import threading
from pathlib import Path


def main():
    from bili_asr.services.maintenance_backup import run_backup
    from bili_asr.services.maintenance_package import _json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()
    if args.poll_seconds < 1 or not args.policy.is_absolute():
        parser.error("policy must be absolute and poll interval positive")
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    while not stop.is_set():
        try:
            result = run_backup(_json(args.policy), trigger="time")
            print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        except (ValueError, OSError) as exc:
            print(json.dumps({"operation": "maintenance-backup", "valid": False,
                              "notification": "backup_configuration_failure", "error": str(exc)}), flush=True)
        stop.wait(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
