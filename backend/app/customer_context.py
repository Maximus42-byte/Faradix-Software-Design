"""Single replaceable customer dependency for this local development shell.

No request header, cookie, path, or query parameter is accepted as proof of identity.
Replace this dependency with real authentication and authorization before deployment.
"""

from .fixtures import CUSTOMERS, CustomerRecord

DEVELOPMENT_CUSTOMER_ID = "demo-customer-01"


def get_current_customer() -> CustomerRecord:
    return CUSTOMERS[DEVELOPMENT_CUSTOMER_ID]
