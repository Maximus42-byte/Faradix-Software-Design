from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, FiniteFloat, field_validator


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


class TelemetryMeasurements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stack_voltage_v: FiniteFloat
    stack_current_a: FiniteFloat
    electrolyte_temperature_c: FiniteFloat


class TelemetrySample(BaseModel):
    """Provisional version 1 transport contract; values are synthetic, not limits."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    device_id: str
    measured_at: AwareDatetime
    source: Literal["simulated"]
    measurements: TelemetryMeasurements

    @field_validator("measured_at", mode="before")
    @classmethod
    def require_explicit_timestamp_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("Measurement time must be a timezone-aware timestamp string")
        return value


class LatestTelemetryResponse(BaseModel):
    status: Literal["no_samples", "fresh", "stale"]
    freshness_seconds: int
    sample: TelemetrySample | None
