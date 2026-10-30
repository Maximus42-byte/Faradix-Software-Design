from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from app.customer_context import get_current_customer
from app.fixtures import CUSTOMERS, SIMULATED_PUBLISHER_DEVICE_ID
from app.main import app
from app.models import TelemetrySample
from app.telemetry import FRESHNESS_SECONDS, LatestTelemetryStore, latest_telemetry

TOKEN = "test-only-publisher-credential"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def isolated_telemetry(monkeypatch: pytest.MonkeyPatch):
    latest_telemetry.clear()
    app.dependency_overrides.clear()
    monkeypatch.setenv("FARADIX_DEV_TELEMETRY_INGEST", "1")
    monkeypatch.setenv("FARADIX_DEV_TELEMETRY_TOKEN", TOKEN)
    yield
    latest_telemetry.clear()
    app.dependency_overrides.clear()


def payload(measured_at: str | None = None, device_id: str = SIMULATED_PUBLISHER_DEVICE_ID) -> dict:
    return {
        "schema_version": "1", "device_id": device_id,
        "measured_at": measured_at or datetime.now(timezone.utc).isoformat(),
        "source": "simulated",
        "measurements": {"stack_voltage_v": 48.0, "stack_current_a": 12.0, "electrolyte_temperature_c": 31.0},
    }


def test_valid_sample_is_visible_only_to_owner() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/devices/demo-unit-001/telemetry").json()["status"] == "no_samples"
        assert client.post("/api/v1/dev/telemetry", json=payload(), headers=HEADERS).status_code == 204
        latest = client.get("/api/v1/devices/demo-unit-001/telemetry")
        assert latest.status_code == 200
        assert latest.json()["status"] == "fresh"
        assert latest.json()["sample"]["source"] == "simulated"
        assert latest.json()["sample"]["measurements"]["stack_voltage_v"] == 48.0
        assert client.get("/api/v1/devices/demo-unit-002/telemetry").json()["status"] == "no_samples"
        assert client.get("/api/v1/devices/demo-unit-003/telemetry").status_code == 404
        assert client.get("/api/v1/devices/unknown/telemetry").status_code == 404
        app.dependency_overrides[get_current_customer] = lambda: CUSTOMERS["demo-customer-02"]
        assert client.get("/api/v1/devices/demo-unit-001/telemetry").status_code == 404


def test_ingestion_is_disabled_unless_explicitly_enabled_and_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(app) as client:
        monkeypatch.delenv("FARADIX_DEV_TELEMETRY_INGEST")
        assert client.post("/api/v1/dev/telemetry", json=payload(), headers=HEADERS).status_code == 404
        monkeypatch.setenv("FARADIX_DEV_TELEMETRY_INGEST", "1")
        monkeypatch.delenv("FARADIX_DEV_TELEMETRY_TOKEN")
        assert client.post("/api/v1/dev/telemetry", json=payload(), headers=HEADERS).status_code == 404
        assert client.get("/api/v1/devices/demo-unit-001/telemetry").json()["status"] == "no_samples"


def test_credential_and_server_side_device_mapping() -> None:
    with TestClient(app) as client:
        assert client.post("/api/v1/dev/telemetry", json=payload()).status_code == 401
        assert client.post("/api/v1/dev/telemetry", json=payload(), headers={"Authorization": "Bearer wrong"}).status_code == 401
        for other_device in ("demo-unit-002", "demo-unit-003", "unknown"):
            assert client.post("/api/v1/dev/telemetry", json=payload(device_id=other_device), headers=HEADERS).status_code == 403
        claimed = payload()
        claimed["customer_id"] = "demo-customer-02"
        assert client.post("/api/v1/dev/telemetry", json=claimed, headers=HEADERS).status_code == 422
        assert client.get("/api/v1/devices/demo-unit-001/telemetry").json()["status"] == "no_samples"


@pytest.mark.parametrize("invalid_time", ["not-a-time", "2026-10-30T12:00:00"])
def test_malformed_or_naive_timestamp_is_rejected(invalid_time: str) -> None:
    with TestClient(app) as client:
        assert client.post("/api/v1/dev/telemetry", json=payload(invalid_time), headers=HEADERS).status_code == 422


def test_numeric_timestamp_without_explicit_timezone_is_rejected() -> None:
    bad = payload()
    bad["measured_at"] = 1793352000
    with TestClient(app) as client:
        assert client.post("/api/v1/dev/telemetry", json=bad, headers=HEADERS).status_code == 422


@pytest.mark.parametrize("invalid_value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_measurements_are_rejected(invalid_value: str) -> None:
    body = json.dumps(payload()).replace('"stack_voltage_v": 48.0', f'"stack_voltage_v": {invalid_value}')
    with TestClient(app) as client:
        response = client.post("/api/v1/dev/telemetry", content=body, headers={**HEADERS, "Content-Type": "application/json"})
        assert response.status_code == 422
        assert client.get("/api/v1/devices/demo-unit-001/telemetry").json()["status"] == "no_samples"


def test_older_and_equal_samples_cannot_replace_latest() -> None:
    now = datetime.now(timezone.utc)
    newer = payload(now.isoformat())
    older = payload((now - timedelta(seconds=2)).isoformat())
    with TestClient(app) as client:
        assert client.post("/api/v1/dev/telemetry", json=newer, headers=HEADERS).status_code == 204
        assert client.post("/api/v1/dev/telemetry", json=older, headers=HEADERS).status_code == 409
        assert client.post("/api/v1/dev/telemetry", json=newer, headers=HEADERS).status_code == 409
        measured_at = client.get("/api/v1/devices/demo-unit-001/telemetry").json()["sample"]["measured_at"]
        assert datetime.fromisoformat(measured_at.replace("Z", "+00:00")) == now


def test_freshness_keeps_last_sample_without_turning_it_into_zero() -> None:
    store = LatestTelemetryStore()
    measured_at = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    sample = TelemetrySample.model_validate(payload(measured_at.isoformat()))
    assert store.latest(sample.device_id, measured_at).status == "no_samples"
    assert store.put(sample)
    assert store.latest(sample.device_id, measured_at + timedelta(seconds=FRESHNESS_SECONDS)).status == "fresh"
    stale = store.latest(sample.device_id, measured_at + timedelta(seconds=FRESHNESS_SECONDS + 1))
    assert stale.status == "stale"
    assert stale.sample == sample
