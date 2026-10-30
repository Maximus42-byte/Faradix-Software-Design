"""Development ingestion and customer-scoped latest telemetry reads."""

import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import ValidationError

from ..customer_context import get_current_customer
from ..fixtures import DEVICES, SIMULATED_PUBLISHER_DEVICE_ID, CustomerRecord
from ..models import LatestTelemetryResponse, TelemetrySample
from ..telemetry import latest_telemetry

router = APIRouter(prefix="/api/v1", tags=["telemetry"])


@router.post("/dev/telemetry", status_code=204)
async def ingest_development_telemetry(
    request: Request, authorization: str | None = Header(default=None)
) -> Response:
    configured_token = os.environ.get("FARADIX_DEV_TELEMETRY_TOKEN", "")
    if os.environ.get("FARADIX_DEV_TELEMETRY_INGEST") != "1" or not configured_token:
        raise HTTPException(status_code=404, detail="Not found")
    supplied_token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not supplied_token or not secrets.compare_digest(supplied_token, configured_token):
        raise HTTPException(status_code=401, detail="Invalid development publisher credential")
    try:
        sample = TelemetrySample.model_validate_json(await request.body())
    except ValidationError:
        raise HTTPException(status_code=422, detail="Invalid telemetry sample") from None
    # Device identity comes from the server-side credential mapping, never a customer claim.
    if sample.device_id != SIMULATED_PUBLISHER_DEVICE_ID:
        raise HTTPException(status_code=403, detail="Publisher is not permitted for this device")
    if not latest_telemetry.put(sample):
        raise HTTPException(status_code=409, detail="Sample is not newer than the latest reading")
    return Response(status_code=204)


@router.get("/devices/{device_id}/telemetry", response_model=LatestTelemetryResponse)
def get_latest_device_telemetry(
    device_id: str, customer: CustomerRecord = Depends(get_current_customer)
) -> LatestTelemetryResponse:
    if not any(device.id == device_id and device.customer_id == customer.id for device in DEVICES):
        raise HTTPException(status_code=404, detail="Device not found")
    return latest_telemetry.latest(device_id)
