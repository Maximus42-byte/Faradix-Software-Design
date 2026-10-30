"""Development-only latest-snapshot bridge; no engine or backend file-reading dependency."""

from dataclasses import dataclass
from datetime import timedelta
import json
import math
from pathlib import Path
from typing import Callable

from pydantic import ValidationError

from .fixtures import SIMULATED_PUBLISHER_DEVICE_ID
from .models import TelemetrySample

MAX_ATTEMPTS_PER_SAMPLE = 3
SNAPSHOT_KEYS = {
    "snapshot_version", "run_id", "sample_sequence", "simulation_time_s",
    "measured_at", "source", "measurements",
}


@dataclass(frozen=True)
class EngineSnapshot:
    run_id: str
    sequence: int
    payload: dict


def parse_snapshot(raw: str) -> EngineSnapshot:
    """Validate a complete atomic snapshot and map it to the existing ingest contract."""
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != SNAPSHOT_KEYS:
            raise ValueError("Unexpected snapshot fields")
        run_id = data["run_id"]
        sequence = data["sample_sequence"]
        simulation_time = data["simulation_time_s"]
        if data["snapshot_version"] != "1" or not isinstance(run_id, str) or not 1 <= len(run_id) <= 128:
            raise ValueError("Invalid snapshot version or run ID")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ValueError("Invalid sample sequence")
        if not isinstance(simulation_time, (int, float)) or isinstance(simulation_time, bool) or not math.isfinite(simulation_time) or simulation_time < 0:
            raise ValueError("Invalid simulation time")
        sample = TelemetrySample.model_validate({
            "schema_version": "1",
            "device_id": SIMULATED_PUBLISHER_DEVICE_ID,
            "measured_at": data["measured_at"],
            "source": data["source"],
            "measurements": data["measurements"],
        })
        if sample.measured_at.utcoffset() != timedelta(0):
            raise ValueError("Snapshot measurement time must be UTC")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OverflowError, ValidationError) as error:
        raise ValueError("Invalid engine snapshot") from error
    return EngineSnapshot(run_id, sequence, {
        "schema_version": "1",
        "device_id": SIMULATED_PUBLISHER_DEVICE_ID,
        # Preserve the engine's original UTC timestamp, including its precision.
        "measured_at": data["measured_at"],
        "source": "simulated",
        "measurements": sample.measurements.model_dump(),
    })


class SnapshotBridge:
    """Keep only the newest candidate; retry each sample at most three times."""

    def __init__(self, path: Path, send: Callable[[dict], int | None]) -> None:
        self.path = path
        self.send = send
        self.completed: tuple[str, int] | None = None
        self.pending: EngineSnapshot | None = None
        self.attempts = 0

    def poll_once(self) -> str:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return "missing"
        except (OSError, UnicodeError):
            return "unreadable"
        try:
            snapshot = parse_snapshot(raw)
        except ValueError:
            return "invalid"
        key = (snapshot.run_id, snapshot.sequence)
        if self.completed and key[0] == self.completed[0] and key[1] <= self.completed[1]:
            return "unchanged"
        if self.pending and key[0] == self.pending.run_id and key[1] < self.pending.sequence:
            return "unchanged"
        if self.pending is None or key != (self.pending.run_id, self.pending.sequence):
            self.pending = snapshot
            self.attempts = 0
        # A newer atomic file replaces the pending candidate; there is no queue.
        self.attempts += 1
        status = self.send(self.pending.payload)
        if status == 204:
            outcome = "published"
        elif status == 409:
            outcome = "rejected_order"
        elif status in (401, 403, 404, 422):
            outcome = "rejected"
        elif self.attempts >= MAX_ATTEMPTS_PER_SAMPLE:
            outcome = "retry_exhausted"
        else:
            return "retry"
        self.completed = (self.pending.run_id, self.pending.sequence)
        self.pending = None
        return outcome
