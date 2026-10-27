# Faradix Modular Electrolyzer Products and Software Platform

Faradix sells modular physical water-electrolyzer products with local control software and a customer-facing web platform. Customers may own multiple devices or installations. Faradix also sells recurring software-service subscriptions; plan contents, pricing, billing intervals, and payment providers are undecided.

- **Current repository state:** a runnable local-development customer web shell and fixture-backed API are implemented. The equipment-control runtime, live telemetry, authentication, and commercial integrations are not.
- **Architecture document version:** 0.1, proposed. This is a document version, not a software release.

## System boundaries

The product architecture has three connected parts:

1. **Physical equipment and independent hardware safety:** modular electrolyzer devices, their sensors and actuators, and protective functions independent of application software.
2. **Local C++ control runtime near the equipment:** planned device access, acquisition, state estimation, modeling, policy, optimization, supervisory admission, and time-sensitive control. This runtime is not implemented in this repository.
3. **Central customer web platform:** customer-scoped device management, remote monitoring, history, alarms, and subscription-enabled services. This repository implements only an initial read-only development shell of that platform.

The proposed telemetry path is asynchronous from local equipment software to the central platform. The platform associates device identity with customer ownership before exposing data to the appropriate customer. No telemetry path or equipment-control link is implemented yet. Any future remote-command path must be separate from telemetry and pass backend authorization and local supervisory admission; this shell has no operational commands.

Independent hardware safety and basic local control must not depend on cloud availability, subscription expiry, or billing-service availability. Modeling, policy, optimization, supervisory control, and real-time control remain distinct planned local responsibilities. See [ARCHITECTURE_v0.1.md](ARCHITECTURE_v0.1.md) for the proposed architecture and open decisions.

## Implemented development shell

| Part | Present behavior |
| --- | --- |
| `frontend/` | React, TypeScript, and Vite customer workspace with Overview, My Devices, Device Details, and Subscription pages. It shows loading, empty, not-found, and API-unavailable states. |
| `backend/` | FastAPI versioned read-only API for health, the current development customer, authorized device inventory and details, and subscription integration status. |
| Development fixtures | Two customers and three device records exist on the server. The default development customer sees only its two devices. Every device is labeled as a development fixture with telemetry integration pending. |

Overview counts and integration summaries come from API responses. Device Details show identity and installation information when present, with explicit empty telemetry and history sections. Subscription reports **Not configured**. No sensor readings, hydrogen production, physical connection states, active subscriptions, payments, or optimization results are fabricated.

### API endpoints

| Endpoint | Response |
| --- | --- |
| `GET /api/v1/health` | Backend availability and development-demo status. |
| `GET /api/v1/me` | Current server-side development customer. |
| `GET /api/v1/devices` | Devices owned by that customer. |
| `GET /api/v1/devices/{device_id}` | One owned device, or `404` for unknown and other-customer IDs. |
| `GET /api/v1/subscription` | `not_configured`; no subscription or billing records. |

## Run locally

The setup was verified with Node.js 22.23.2 and Python 3.10.12. Vite also supports Node.js 20.19+ or 22.12+. From the repository root, create the local Python environment and install backend dependencies:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

Start the API in one terminal:

```bash
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal, from the repository root:

```bash
cd frontend
npm ci
npm run dev
```

Open the web application at **http://127.0.0.1:5173/**. The API health endpoint is **http://127.0.0.1:8000/api/v1/health**; the local API reference is at **http://127.0.0.1:8000/docs**. Vite proxies `/api` requests to the local API. Both development servers bind to `127.0.0.1`. The frontend header checks actual backend health and remains navigable when the API is unavailable.

For focused backend tests, install the development dependencies, then run:

```bash
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd backend
.venv/bin/python -m pytest -q
```

For a frontend production build, from the repository root:

```bash
cd frontend
npm ci
npm run build
```

## Development data and access limits

`backend/app/customer_context.py` selects the server-side development customer `demo-customer-01`. This single dependency is intended to be replaced by real authentication later. Browser-supplied customer IDs are not accepted as proof of authorization. The backend filters list and detail responses by the selected customer; a second customer's fixture record is present but hidden from the default customer.

**Real authentication is not implemented. This development shell is not ready for public deployment.** Customer names, installation labels, and devices are clearly labeled fixtures. There is no database, telemetry pipeline, alarm history, subscription entitlement enforcement, billing integration, or local C++ equipment runtime.

## Next planned equipment milestone

The local control architecture calls for an end-to-end simulated loop: virtual measurements, state estimation, a simple model and policy, optimization proposals, supervisory acceptance, control commands, and simulated plant response. This remains future work and does not establish production readiness, physical model accuracy, or hardware safety certification.

Subscription packaging, charging basis, expiry and offline behavior, historical-data access after expiry, remote commands, payment provider, currencies, and billing intervals remain open product decisions. No optimization capability has been assigned to a subscription tier.
