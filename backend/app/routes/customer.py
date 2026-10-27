from fastapi import APIRouter, Depends

from ..customer_context import get_current_customer
from ..fixtures import CustomerRecord
from ..models import CustomerResponse

router = APIRouter(prefix="/api/v1", tags=["customer"])


@router.get("/me", response_model=CustomerResponse)
def current_customer(customer: CustomerRecord = Depends(get_current_customer)) -> CustomerResponse:
    return CustomerResponse(id=customer.id, name=customer.name)
