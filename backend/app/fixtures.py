"""Clearly labeled local development inventory fixtures."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CustomerRecord:
    id: str
    name: str


@dataclass(frozen=True)
class DeviceRecord:
    id: str
    customer_id: str
    name: str
    reference: str
    installation_name: str | None


CUSTOMERS = {
    "demo-customer-01": CustomerRecord("demo-customer-01", "Northstar Hydrogen (demo)"),
    "demo-customer-02": CustomerRecord("demo-customer-02", "Bluehaven Energy (demo)"),
}

DEVICES = (
    DeviceRecord("demo-unit-001", "demo-customer-01", "Electrolyzer Module 01", "DEMO-001", "Demo Installation A"),
    DeviceRecord("demo-unit-002", "demo-customer-01", "Electrolyzer Module 02", "DEMO-002", None),
    DeviceRecord("demo-unit-003", "demo-customer-02", "Electrolyzer Module 03", "DEMO-003", "Other Demo Installation"),
)

# The standalone transport demo publishes only for this existing fixture.
SIMULATED_PUBLISHER_DEVICE_ID = DEVICES[0].id
