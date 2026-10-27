from fastapi.testclient import TestClient

from app.customer_context import get_current_customer
from app.fixtures import CUSTOMERS
from app.main import app


def test_development_customer_sees_only_its_devices() -> None:
    with TestClient(app) as client:
        devices = client.get("/api/v1/devices")
        assert devices.status_code == 200
        assert {device["id"] for device in devices.json()} == {
            "demo-unit-001",
            "demo-unit-002",
        }
        assert client.get("/api/v1/devices/demo-unit-001").status_code == 200
        assert client.get("/api/v1/devices/demo-unit-003").status_code == 404
        assert client.get("/api/v1/devices/unknown").status_code == 404
        # Browser-supplied customer IDs cannot change the server-side context.
        spoofed = client.get(
            "/api/v1/devices?customer_id=demo-customer-02",
            headers={"X-Customer-ID": "demo-customer-02"},
        )
        assert {device["id"] for device in spoofed.json()} == {
            "demo-unit-001",
            "demo-unit-002",
        }


def test_customer_dependency_scopes_inventory_when_replaced() -> None:
    app.dependency_overrides[get_current_customer] = lambda: CUSTOMERS["demo-customer-02"]
    try:
        with TestClient(app) as client:
            devices = client.get("/api/v1/devices")
            assert {device["id"] for device in devices.json()} == {"demo-unit-003"}
            assert client.get("/api/v1/devices/demo-unit-003").status_code == 200
            assert client.get("/api/v1/devices/demo-unit-001").status_code == 404
    finally:
        app.dependency_overrides.clear()
