from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["development_demo"] = "development_demo"
    authentication_configured: bool = False


class CustomerResponse(BaseModel):
    id: str
    name: str
    fixture_label: Literal["Development fixture"] = "Development fixture"


class DeviceResponse(BaseModel):
    id: str
    name: str
    reference: str
    installation_name: str | None
    telemetry_status: Literal["pending_integration", "available"] = "pending_integration"
    fixture_label: Literal["Development fixture"] = "Development fixture"


class DeviceDetailResponse(DeviceResponse):
    telemetry_available: bool = False
    history_available: bool = False


class SubscriptionResponse(BaseModel):
    status: Literal["not_configured"] = "not_configured"
    message: str = "Subscription integration is pending. No plan or billing data is available."
