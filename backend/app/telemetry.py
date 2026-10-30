"""Process-local latest-sample storage for the development transport demo."""

from datetime import datetime, timezone
from threading import Lock

from .models import LatestTelemetryResponse, TelemetrySample

FRESHNESS_SECONDS = 15


class LatestTelemetryStore:
    def __init__(self) -> None:
        self._samples: dict[str, TelemetrySample] = {}
        self._lock = Lock()

    def put(self, sample: TelemetrySample) -> bool:
        with self._lock:
            previous = self._samples.get(sample.device_id)
            if previous is not None and sample.measured_at <= previous.measured_at:
                return False
            self._samples[sample.device_id] = sample
            return True

    def latest(self, device_id: str, now: datetime | None = None) -> LatestTelemetryResponse:
        with self._lock:
            sample = self._samples.get(device_id)
        if sample is None:
            return LatestTelemetryResponse(status="no_samples", freshness_seconds=FRESHNESS_SECONDS, sample=None)
        age = ((now or datetime.now(timezone.utc)) - sample.measured_at).total_seconds()
        status = "fresh" if 0 <= age <= FRESHNESS_SECONDS else "stale"
        return LatestTelemetryResponse(status=status, freshness_seconds=FRESHNESS_SECONDS, sample=sample)

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()


latest_telemetry = LatestTelemetryStore()
