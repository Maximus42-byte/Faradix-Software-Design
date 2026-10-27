from fastapi import APIRouter, Depends, HTTPException

from ..customer_context import get_current_customer
from ..fixtures import DEVICES, CustomerRecord, DeviceRecord
from ..models import DeviceDetailResponse, DeviceResponse

router = APIRouter(prefix="/api/v1", tags=["devices"])


def public_device(device: DeviceRecord) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        name=device.name,
        reference=device.reference,
        installation_name=device.installation_name,
    )


@router.get("/devices", response_model=list[DeviceResponse])
def list_devices(customer: CustomerRecord = Depends(get_current_customer)) -> list[DeviceResponse]:
    return [public_device(device) for device in DEVICES if device.customer_id == customer.id]


@router.get("/devices/{device_id}", response_model=DeviceDetailResponse)
def get_device(
    device_id: str, customer: CustomerRecord = Depends(get_current_customer)
) -> DeviceDetailResponse:
    device = next(
        (item for item in DEVICES if item.id == device_id and item.customer_id == customer.id),
        None,
    )
    if device is None:
        # Use the same response for an unknown ID and another customer's ID.
        raise HTTPException(status_code=404, detail="Device not found")
    return DeviceDetailResponse(**public_device(device).model_dump())
