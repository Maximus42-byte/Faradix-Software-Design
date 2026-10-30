from fastapi import FastAPI

from .routes import customer, devices, health, subscription, telemetry

app = FastAPI(title="Faradix Customer Platform Development API", version="development")
app.include_router(health.router)
app.include_router(customer.router)
app.include_router(devices.router)
app.include_router(subscription.router)
app.include_router(telemetry.router)
