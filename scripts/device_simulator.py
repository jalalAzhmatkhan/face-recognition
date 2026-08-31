#!/usr/bin/env python3
"""Device heartbeat simulator -- dev/testing convenience only.

`POST /devices/{id}/heartbeat` (BE-09) is the ONLY code path anywhere in
this codebase that sets a device's `status` to `ONLINE` -- see
`backend/app/services/device_service.py::record_heartbeat`. It is meant to
be called periodically by the physical door-camera device's own firmware,
using the device credential (`<credential_id>.<secret>`) minted once at
`POST /devices` registration time. That firmware does not exist anywhere in
this monorepo (real hardware is out of scope for this repo, per TSD) -- so
without something calling this endpoint, every registered device sits at
`OFFLINE` forever in a dev environment, no matter what the frontend does.

This script is a stand-in for that firmware: it sends the SAME heartbeat
call, on a loop, using a real device credential. It is deliberately a
standalone, zero-dependency script (stdlib only, no `uv sync` needed
anywhere) since it doesn't belong to any one service's own dependency
tree -- run it directly with `python3`.

Usage:
    python3 scripts/device_simulator.py \\
        --device-id <uuid> --credential <credential_id>.<secret>

    # single heartbeat then exit, instead of looping
    python3 scripts/device_simulator.py --device-id <uuid> --credential ... --once

Never use this against a real deployment with a real device's credential --
it exists purely to make a dev/test device's status reflect something
realistic without physical hardware.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

# Must stay comfortably below backend's `Settings.device_heartbeat_stale_
# after_seconds` (90s, `backend/app/core/config.py`) -- a device is still
# reported ONLINE past that point (there's no cron job flipping it back),
# but `DeviceResponse.is_stale` starts reading True, which the frontend
# surfaces as an amber "ONLINE but stale" badge rather than a clean online
# state. 30s leaves a wide margin even if one heartbeat is dropped.
DEFAULT_INTERVAL_SECONDS = 30.0
STALE_AFTER_SECONDS = 90


def send_heartbeat(base_url: str, device_id: str, credential: str, *, timeout: float) -> dict:
    url = f"{base_url.rstrip('/')}/api/v1/devices/{device_id}/heartbeat"
    request = urllib.request.Request(
        url, method="POST", headers={"Authorization": f"Bearer {credential}"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode())


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


def beat(*, base_url: str, device_id: str, credential: str, timeout: float) -> bool:
    """One heartbeat attempt. Never raises -- prints the outcome and returns
    whether it succeeded, so a transient failure (backend restarting,
    network blip) doesn't kill the loop."""
    try:
        result = send_heartbeat(base_url, device_id, credential, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"[{_timestamp()}] heartbeat FAILED -- HTTP {exc.code}: {body}", file=sys.stderr)
        return False
    except urllib.error.URLError as exc:
        print(
            f"[{_timestamp()}] heartbeat FAILED -- cannot reach {base_url}: {exc.reason}",
            file=sys.stderr,
        )
        return False
    print(
        f"[{_timestamp()}] heartbeat ok -- status={result.get('status')} "
        f"last_heartbeat_at={result.get('last_heartbeat_at')}"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simulate a physical device's periodic heartbeat (dev/testing only).",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Backend base URL (default: %(default)s -- the host-mapped port from "
        "docker-compose.dev.yml, not the Docker-internal 'backend' hostname).",
    )
    parser.add_argument(
        "--device-id", required=True, help="Device UUID (path segment, from POST /devices)."
    )
    parser.add_argument(
        "--credential",
        required=True,
        help="Device credential, exact `<credential_id>.<secret>` string shown ONCE at "
        "registration/rotation time (POST /devices or POST /devices/{id}/rotate-credential).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between heartbeats (default: %(default)s). Keep well under "
        f"{STALE_AFTER_SECONDS}s (the backend's staleness threshold) or the device will "
        f"flicker to an amber 'stale' badge between beats.",
    )
    parser.add_argument(
        "--once", action="store_true", help="Send a single heartbeat and exit, instead of looping."
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Per-request timeout in seconds."
    )
    args = parser.parse_args()

    if args.once:
        succeeded = beat(
            base_url=args.base_url,
            device_id=args.device_id,
            credential=args.credential,
            timeout=args.timeout,
        )
        return 0 if succeeded else 1

    if args.interval >= STALE_AFTER_SECONDS:
        print(
            f"warning: --interval {args.interval}s is >= the backend's {STALE_AFTER_SECONDS}s "
            "staleness threshold; the device will show as stale between most beats.",
            file=sys.stderr,
        )

    print(
        f"Simulating device {args.device_id} -- heartbeat every {args.interval}s against "
        f"{args.base_url} (Ctrl+C to stop)"
    )
    try:
        while True:
            beat(
                base_url=args.base_url,
                device_id=args.device_id,
                credential=args.credential,
                timeout=args.timeout,
            )
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
