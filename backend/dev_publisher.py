"""Development publisher: synthetic values or an engine snapshot, never equipment control."""

import argparse
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.fixtures import SIMULATED_PUBLISHER_DEVICE_ID
from app.snapshot_bridge import SnapshotBridge


def sample_for_tick(tick: int) -> dict:
    # Repeating example values are deliberately synthetic, not operating limits.
    return {
        "schema_version": "1",
        "device_id": SIMULATED_PUBLISHER_DEVICE_ID,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "source": "simulated",
        "measurements": {
            "stack_voltage_v": 48.0 + (tick % 4) * 0.2,
            "stack_current_a": 12.0 + (tick % 5) * 0.1,
            "electrolyte_temperature_c": 31.0 + (tick % 3) * 0.1,
        },
    }


def post_sample(endpoint: str, token: str, payload: dict) -> int | None:
    body = json.dumps(payload).encode("utf-8")
    request = Request(endpoint, body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, method="POST")
    try:
        with urlopen(request, timeout=5) as response:
            return response.status
    except HTTPError as error:
        return error.code
    except (URLError, TimeoutError, OSError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("synthetic", "snapshot"), default="synthetic")
    parser.add_argument("--snapshot", type=Path, help="atomic engine JSON file; required in snapshot mode")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between polls or synthetic samples (default: 2)")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="local backend origin")
    args = parser.parse_args()
    if args.interval <= 0 or not args.interval < float("inf"):
        parser.error("--interval must be positive and finite")
    if args.mode == "snapshot" and args.snapshot is None:
        parser.error("--snapshot is required in snapshot mode")
    if args.mode == "synthetic" and args.snapshot is not None:
        parser.error("--snapshot requires --mode snapshot")
    token = os.environ.get("FARADIX_DEV_TELEMETRY_TOKEN", "")
    if not token:
        print("Set FARADIX_DEV_TELEMETRY_TOKEN in this process environment.", file=sys.stderr)
        return 2
    endpoint = args.url.rstrip("/") + "/api/v1/dev/telemetry"
    tick = 0
    bridge = SnapshotBridge(args.snapshot, lambda payload: post_sample(endpoint, token, payload)) if args.mode == "snapshot" else None
    last_status = None
    try:
        while True:
            if bridge is None:
                status = post_sample(endpoint, token, sample_for_tick(tick))
                print(f"Synthetic sample {tick}: HTTP {status if status is not None else 'backend unavailable'}", flush=True)
                tick += 1
            else:
                outcome = bridge.poll_once()
                if outcome != last_status or outcome == "published":
                    print(f"Engine snapshot: {outcome}", flush=True)
                last_status = outcome
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
