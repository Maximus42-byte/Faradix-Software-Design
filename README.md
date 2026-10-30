# Faradix Modular Electrolyzer Products and Software Platform

Faradix sells modular physical water-electrolyzer products with local control software and a customer-facing web platform. Customers may own multiple devices or installations. Faradix also sells recurring software-service subscriptions; plan contents, pricing, billing intervals, and payment providers are undecided.

- **Current repository state:** a runnable C++ engine foundation with an uncalibrated simulated device, an atomic snapshot bridge, and the customer web shell are implemented. Physical equipment control, real sensor telemetry, authentication, and commercial integrations are not.
- **Architecture document version:** 0.1, proposed. This is a document version, not a software release.

## System boundaries

The product architecture has three connected parts:

1. **Physical equipment and independent hardware safety:** modular electrolyzer devices, their sensors and actuators, and protective functions independent of application software.
2. **Local C++ control runtime near the equipment:** this repository now contains a standalone development engine, a replaceable device interface, one simulated-device adapter, and minimal command admission. State estimation, predictive modeling, policy, optimization, hardware adapters, and qualified real-time control remain planned.
3. **Central customer web platform:** customer-scoped device management, remote monitoring, history, alarms, and subscription-enabled services. This repository implements an initial development shell and an in-memory synthetic telemetry demonstration.

The implemented development path is **C++ toy engine → atomic JSON snapshot → Python bridge → credential-gated FastAPI ingestion → latest-sample memory store → customer-scoped read API → Device Details**. The original standalone Python synthetic publisher remains available as a separate transport demo. The toy plant is an uncalibrated development simulation, not a predictive physics model, digital twin, or equipment controller. The bridge maps engine output into the existing provisional telemetry contract; real integration remains unimplemented. Any future remote-command path must be separate from telemetry and pass backend authorization and local supervisory admission; this shell has no operational commands.

Independent hardware safety and basic local control must not depend on cloud availability, subscription expiry, or billing-service availability. Modeling, policy, optimization, supervisory control, and real-time control remain distinct responsibilities; only minimal development command admission is implemented. See [ARCHITECTURE_v0.1.md](ARCHITECTURE_v0.1.md) for the proposed architecture and open decisions.

## Implemented development shell

| Part | Present behavior |
| --- | --- |
| `frontend/` | React, TypeScript, and Vite customer workspace with Overview, My Devices, Device Details, and Subscription pages. Device Details polls for the latest authorized sample and distinguishes empty, fresh, stale, and API-unavailable states. |
| `backend/` | FastAPI API for health, customer-scoped inventory and latest telemetry, plus disabled-by-default development ingestion. `dev_publisher.py` supports explicit engine snapshot mode and the earlier standalone synthetic mode. |
| `engine/` | C++20 engine library, simulated-device adapter, snapshot writer adapter, executable, and focused tests. It runs without Python, HTTP, the backend, or a browser. |
| Development fixtures | Two customers and three device records exist on the server. The default development customer sees only its two devices. The bridge maps snapshots to the backend's existing `demo-unit-001` identity; other devices remain without samples. |

Overview counts and integration summaries come from API responses. Device Details shows identity, installation, and simulated telemetry when available. History and alarms remain empty; Subscription reports **Not configured**. Synthetic values are not operating limits. No real sensor readings, physical connection states, hydrogen production, active subscriptions, payments, or optimization results are represented.

### Telemetry contract and behavior

`POST /api/v1/dev/telemetry` accepts a provisional JSON contract with `schema_version: "1"`, a device ID, a timezone-aware `measured_at` timestamp, `source: "simulated"`, and three finite measurements: `stack_voltage_v` (volts, V), `stack_current_a` (amperes, A), and `electrolyte_temperature_c` (degrees Celsius, °C). The original Python synthetic mode generates repeating example values; snapshot mode carries the toy engine's measurements. Neither source supplies validated operating ranges or physical limits. Unknown fields, malformed or timezone-naive timestamps, unsupported versions or sources, and non-finite numbers are rejected. The publisher credential maps server-side to `demo-unit-001`; a submitted customer ID cannot grant access or change ownership. Samples with a measurement time no newer than the stored sample receive `409` and do not replace it.

`GET /api/v1/devices/{device_id}/telemetry` returns the latest sample only after the existing current-customer and device-ownership check. It returns `no_samples`, `fresh`, or `stale`; freshness is measured from `measured_at` against the backend clock, with a **15-second threshold**. The panel polls every **5 seconds** by default, schedules the next poll only after the previous request finishes, and can set `VITE_TELEMETRY_POLL_MS` to an integer from 1000 to 60000 before starting Vite. A stopped publisher leaves its last sample visible as **Stale simulated data**. If the backend is unavailable, the panel retains the browser's last reading with **Backend unavailable** and no freshness claim. Backend availability is not equipment connectivity.

Only the latest sample per device is held in one backend process's memory. **Samples disappear on backend restart** and are not shared across workers. The snapshot file is a separate ignored development artifact, not backend storage. The bridge publishes each newly observed run/sequence once after success, preserves the engine timestamp, retries a failed sample at most three times, and holds no backlog beyond the newest sample. If the engine stops, the bridge never changes the file or refreshes its timestamp. There is no history, queue, delivery guarantee, or persistence.

### API endpoints

| Endpoint | Response |
| --- | --- |
| `GET /api/v1/health` | Backend availability and development-demo status. |
| `GET /api/v1/me` | Current server-side development customer. |
| `GET /api/v1/devices` | Devices owned by that customer. |
| `GET /api/v1/devices/{device_id}` | One owned device, or `404` for unknown and other-customer IDs. |
| `GET /api/v1/devices/{device_id}/telemetry` | Latest sample and freshness for an owned device; `404` otherwise. |
| `POST /api/v1/dev/telemetry` | Development-only credential-gated synthetic ingestion; disabled by default. |
| `GET /api/v1/subscription` | `not_configured`; no subscription or billing records. |

## Run locally

Setup was verified with GCC 11.4, CMake 3.22.1, Node.js 22.23.2, and Python 3.10.12. CMake 3.22+ and a C++20 compiler are required for the engine; Vite supports Node.js 20.19+ or 22.12+. From the repository root:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd frontend && npm ci && cd ..
```

Create a local credential file once from the repository root. It is ignored by Git; do not commit or paste its contents into logs. Use only on a trusted local development machine:

```bash
umask 077
printf 'export FARADIX_DEV_TELEMETRY_TOKEN=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" > backend/.env.telemetry
```

Build and test the engine from the repository root:

```bash
cmake -S engine -B engine/build -DCMAKE_CXX_COMPILER=g++-11 -DCMAKE_BUILD_TYPE=Debug
cmake --build engine/build --parallel
ctest --test-dir engine/build --output-on-failure
```

Start these **four processes** in separate terminals, each from the repository root. Terminal 1, backend with ingestion explicitly enabled:

```bash
source backend/.env.telemetry
FARADIX_DEV_TELEMETRY_INGEST=1 backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Terminal 2, customer web application:

```bash
cd frontend
npm run dev
```

Terminal 3, continuous C++ engine and atomic snapshot writer:

```bash
engine/build/faradix_engine --baseline-drive 0.5 --dt-s 1 --period-ms 1000 --snapshot engine/run/latest.json
```

Terminal 4, Python snapshot bridge to the existing ingestion endpoint:

```bash
source backend/.env.telemetry
backend/.venv/bin/python backend/dev_publisher.py --mode snapshot --snapshot engine/run/latest.json --interval 1
```

For a bounded engine run without any backend or bridge, use `engine/build/faradix_engine --steps 5 --period-ms 0`. The earlier Python-only transport demo remains available with `backend/.venv/bin/python backend/dev_publisher.py --mode synthetic --interval 2` after sourcing the same credential.

Open **http://127.0.0.1:5173/devices/demo-unit-001**. Stop only Terminal 3 to see the last reading become stale after 15 seconds (the next poll may add up to 5 seconds), even while the bridge stays running. Restart the engine to see fresh readings with a new run ID. Stop the backend to confirm that the engine continues stepping independently. `demo-unit-002` stays empty. The API health endpoint is **http://127.0.0.1:8000/api/v1/health**; the local API reference is at **http://127.0.0.1:8000/docs**. Vite proxies `/api` requests to the local backend. Both servers bind to `127.0.0.1`. Without `FARADIX_DEV_TELEMETRY_INGEST=1` and a configured token, ingestion returns `404`; customer reads still work.

To verify from the repository root:

```bash
cd backend && .venv/bin/python -m pytest -q
cd ../frontend && npm run build
```

## Development data and access limits

`backend/app/customer_context.py` selects the server-side development customer `demo-customer-01`. This dependency is intended to be replaced by real authentication. Browser-supplied customer IDs are not accepted as proof of authorization. The backend scopes inventory, detail, and latest-telemetry reads to that customer; another customer's fixture record stays hidden. The publisher bearer token is a local development transport credential for one demo device, **not production device authentication**. Keep the token out of Git and logs. Do not expose this API to untrusted networks.

**Real authentication is not implemented. This development shell is not ready for public deployment.** Customer names, installation labels, devices, and measurements are development fixtures or simulations. The engine has no physical device adapter, independent hardware safety implementation, validated operating limits, hard real-time guarantee, state estimator, predictive model, policy engine, or optimizer. There is no database, historical telemetry pipeline, alarm history, subscription entitlement enforcement, billing integration, or physical telemetry.

## Engine foundation and pending work

The reusable `faradix_core` library owns fixed simulation steps and a minimal supervisor that admits only finite dimensionless drive requests from 0 to 1. The CLI supplies a configurable baseline drive. The `faradix_simulated_device` adapter evolves a hidden toy temperature state and returns only public measurements through the `Device` interface. The separate `faradix_snapshot_adapter` writes a versioned JSON file by replacing it atomically. Run ID and sequence identify new samples; simulation time is advanced by `--dt-s`, while UTC measurement time comes from the wall clock when each step is observed. `--period-ms` controls wall pacing, not simulation time.

The **uncalibrated development plant** uses explicit Euler stepping: `I = 20u` A, `V = 40 + 0.5I + 0.01(T - 25)` V, and `T_next = T + dt × [0.002 I² - 0.08(T - 25)]` °C, where `u` is the dimensionless admitted drive and `dt` is simulation seconds. Initial temperature is 25 °C. These coefficients, the 0–1 software command bound, and all example values exist only to make behavior deterministic; they are **not validated equipment operating limits** or a predictive physical model. No actuator is connected.

State estimation, a separate predictive physics model, operating policy, optimization proposals, hardware-specific supervisory rules, real-time control, and physical safety remain pending. The next local milestone can add those collaborations through the current measurement and command boundaries. This foundation does not establish production readiness, physical accuracy, hardware safety certification, or hard real-time performance.

Subscription packaging, charging basis, expiry and offline behavior, historical-data access after expiry, remote commands, payment provider, currencies, and billing intervals remain open product decisions. No optimization capability has been assigned to a subscription tier.
