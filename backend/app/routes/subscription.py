from fastapi import APIRouter, Depends

from ..customer_context import get_current_customer
from ..fixtures import CustomerRecord
from ..models import SubscriptionResponse

router = APIRouter(prefix="/api/v1", tags=["subscription"])


@router.get("/subscription", response_model=SubscriptionResponse)
def subscription_status(
    _customer: CustomerRecord = Depends(get_current_customer),
) -> SubscriptionResponse:
    return SubscriptionResponse()
