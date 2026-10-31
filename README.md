# Faradix Modular Electrolyzer Products and Software Platform

Faradix sells modular physical water-electrolyzer products with local control software and a customer-facing web platform. Customers may own multiple devices or installations. Faradix also sells recurring software-service subscriptions; plan contents, pricing, billing intervals, and payment providers are undecided.

- **Current repository state:** a runnable C++ engine foundation with an uncalibrated simulated device, an atomic snapshot bridge, local development experiment recording, and the customer web shell are implemented. Physical equipment control, real sensor telemetry, authentication, and commercial integrations are not.
- **Architecture document version:** 0.1, proposed. This is a document version, not a software release.

## System boundaries

The product architecture has three connected parts:

1. **Physical equipment and independent hardware safety:** modular electrolyzer devices, their sensors and actuators, and protective functions independent of application software.
2. **Local C++ control runtime near the equipment:** this repository now contains a standalone development engine, a replaceable device interface, one simulated-device adapter, and minimal command admission. State estimation, predictive modeling, policy, optimization, hardware adapters, and qualified real-time control remain planned.
3. **Central customer web platform:** customer-scoped device management, remote monitoring, history, alarms, and subscription-enabled services. This repository implements an initial development shell and an in-memory synthetic telemetry demonstration.

The implemented development telemetry path is **C++ toy engine → atomic JSON snapshot → Python bridge → credential-gated FastAPI ingestion → latest-sample memory store → customer-scoped read API → Device Details**. The executable can also record each logical simulation step directly to a separate local JSON Lines experiment file; it does not reconstruct history from snapshots. The original standalone Python synthetic publisher remains available as a separate transport demo. The toy plant is an uncalibrated development simulation, not a predictive physics model, digital twin, or equipment controller. The bridge maps engine output into the existing provisional telemetry contract; real integration remains unimplemented. Any future remote-command path must be separate from telemetry and pass backend authorization and local supervisory admission; this shell has no operational commands.

Independent hardware safety and basic local control must not depend on cloud availability, subscription expiry, or billing-service availability. Modeling, policy, optimization, supervisory control, and real-time control remain distinct responsibilities; only minimal development command admission is implemented. See [ARCHITECTURE_v0.1.md](ARCHITECTURE_v0.1.md) for the proposed architecture and open decisions.

## Implemented development shell

| Part | Present behavior |
| --- | --- |
| `frontend/` | React, TypeScript, and Vite customer workspace with Overview, My Devices, Device Details, and Subscription pages. Device Details polls for the latest authorized sample and distinguishes empty, fresh, stale, and API-unavailable states. |
| `backend/` | FastAPI API for health, customer-scoped inventory and latest telemetry, plus disabled-by-default development ingestion. `dev_publisher.py` supports explicit engine snapshot mode and the earlier standalone synthetic mode. |
| `engine/` | C++20 engine library, simulated-device adapter, separate snapshot and experiment-recording output adapters, executable, and focused tests. It runs without Python, HTTP, the backend, or a browser. |
| Development fixtures | Two customers and three device records exist on the server. The default development customer sees only its two devices. The bridge maps snapshots to the backend's existing `demo-unit-001` identity; other devices remain without samples. |

Overview counts and integration summaries come from API responses. Device Details shows identity, installation, and simulated telemetry when available. History and alarms remain empty; Subscription reports **Not configured**. Synthetic values are not operating limits. No real sensor readings, physical connection states, hydrogen production, active subscriptions, payments, or optimization results are represented.

### Telemetry contract and behavior

`POST /api/v1/dev/telemetry` accepts a provisional JSON contract with `schema_version: "1"`, a device ID, a timezone-aware `measured_at` timestamp, `source: "simulated"`, and three finite measurements: `stack_voltage_v` (volts, V), `stack_current_a` (amperes, A), and `electrolyte_temperature_c` (degrees Celsius, °C). The original Python synthetic mode generates repeating example values; snapshot mode carries the toy engine's measurements. Neither source supplies validated operating ranges or physical limits. Unknown fields, malformed or timezone-naive timestamps, unsupported versions or sources, and non-finite numbers are rejected. The publisher credential maps server-side to `demo-unit-001`; a submitted customer ID cannot grant access or change ownership. Samples with a measurement time no newer than the stored sample receive `409` and do not replace it.

`GET /api/v1/devices/{device_id}/telemetry` returns the latest sample only after the existing current-customer and device-ownership check. It returns `no_samples`, `fresh`, or `stale`; freshness is measured from `measured_at` against the backend clock, with a **15-second threshold**. The panel polls every **5 seconds** by default, schedules the next poll only after the previous request finishes, and can set `VITE_TELEMETRY_POLL_MS` to an integer from 1000 to 60000 before starting Vite. A stopped publisher leaves its last sample visible as **Stale simulated data**. If the backend is unavailable, the panel retains the browser's last reading with **Backend unavailable** and no freshness claim. Backend availability is not equipment connectivity.

Only the latest sample per device is held in one backend process's memory. **Samples disappear on backend restart** and are not shared across workers. The snapshot file is a separate ignored development artifact, not backend storage. The bridge publishes each newly observed run/sequence once after success, preserves the engine timestamp, retries a failed sample at most three times, and holds no backlog beyond the newest sample. If the engine stops, the bridge never changes the file or refreshes its timestamp. The backend has no history, queue, delivery guarantee, or persistence; the local experiment recording described below is a separate development artifact.

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

The development runner starts four independent local processes: FastAPI, Vite, the C++ toy engine, and the Python snapshot bridge. It is a process convenience for the simulated demo, **not** part of the engine's control loop or a production deployment system. The engine remains independently runnable. Both servers bind to `127.0.0.1`.

### Linux setup (Ubuntu)

Use Python 3.10+, CMake 3.22+, `g++-11` with C++20 support, Node.js 20.19+ or 22.12+, and npm. Install the Ubuntu build and Python prerequisites explicitly; install a supported Node.js distribution separately if needed:

```bash
sudo apt update
sudo apt install cmake g++-11 python3-venv python3-pip
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
(cd frontend && npm ci)
python3 tools/dev.py build
python3 tools/dev.py check
python3 tools/dev.py run
```

The Linux build keeps the `g++-11` compiler choice and writes ignored output under `engine/build/`. The runner can also be invoked by absolute script path from another working directory, including when the repository path contains spaces.

### Native Windows x64 setup (PowerShell)

Install Python 3.10+ (Python 3.12 is used by CI), CMake 3.22+, Node.js 22 with npm, and Visual Studio 2022 with the **Desktop development with C++** workload. Make `python`, `cmake`, `node`, and `npm` available on `PATH`. Use native PowerShell, not WSL. From the repository root:

```powershell
python --version
cmake --version
node --version
npm --version
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Push-Location frontend
npm ci
Pop-Location
python tools\dev.py build
python tools\dev.py check
python tools\dev.py run
```

The runner uses the installed CMake generator and its Debug executable location for either a single-configuration or multi-configuration build. Windows virtual environments use `Scripts\python.exe`; the runner discovers that path and launches Vite with Node using an argument list. All four development processes remain local to `127.0.0.1`.

`check` reports missing prerequisites, a missing engine binary, or occupied local ports without changing the system. `build` configures and builds the standalone C++ engine; it does not install tools or download fallback binaries. The runner creates or reuses the ignored `backend/.env.telemetry` file. On Linux it requires current-user ownership and mode `0600`. On Windows it protects a new empty file with a restricted ACL before writing the credential and verifies an existing file's owner and ACL without rewriting it; POSIX mode bits are not used as a Windows security check. Keep the credential secret and use this demo on a trusted local machine.

### One-command development run

Run `python3 tools/dev.py run` on Linux or `python tools\dev.py run` in native Windows PowerShell after setup. Both use the default development simulation profile; `--profile` and the existing explicit overrides work on either OS.

The runner checks runtime prerequisites and ports before starting anything. It reuses `backend/.env.telemetry`, or creates it once with a restricted random credential if missing. It reads the file as data, never executes it, and passes the credential only to the backend and snapshot bridge. An existing file must contain a single line in the form `export FARADIX_DEV_TELEMETRY_TOKEN=<token>`; invalid content or protection is rejected without overwriting it.

The runner uses a unique ignored run directory under `engine/run/` for its engine instance, snapshot, recording, and metadata. It waits for backend, frontend, engine snapshot, and end-to-end telemetry readiness with bounded timeouts, and labels each process's output. Open **http://127.0.0.1:5173/devices/demo-unit-001**. Press Ctrl+C to stop the processes and descendants started by this runner. If startup fails or a child exits unexpectedly, it stops its other children. It never stops an unrelated process that owns a port.

### Development simulation profiles

With no `--profile`, `run` selects [the default profile](profiles/simulation/default.json), matching the earlier runner values: baseline drive `0.5`, simulation timestep `1.0` second, and wall pacing `1000` milliseconds. Two additional **development simulation** examples are [lower drive](profiles/simulation/lower_drive_demo.json) and [faster pacing](profiles/simulation/fast_pacing_demo.json). These are software test inputs, not equipment operating points, safety limits, calibrated plant settings, or physical-fidelity claims.

```bash
python3 tools/dev.py run --profile profiles/simulation/lower_drive_demo.json
python3 tools/dev.py run --profile profiles/simulation/fast_pacing_demo.json --baseline-drive 0.4 --period-ms 500
```

Profile paths are resolved relative to the repository root, regardless of the current working directory. Absolute paths are also accepted, including from outside the repository (quote paths containing spaces):

```bash
cd /tmp
python3 "/home/maximus/Projects/Faradix Software Design/tools/dev.py" run --profile "/home/maximus/Projects/Faradix Software Design/profiles/simulation/fast_pacing_demo.json"
```

Version 1 JSON requires `schema_version: "1"`, `kind: "development_simulation"`, and a nonempty `parameters` object. Only `baseline_drive` (finite number from 0 to 1), `dt_s` (finite number greater than 0, in simulation seconds), and `period_ms` (integer from 1 to 60000, wall milliseconds) are allowed. The continuous runner cannot use the engine's `period_ms: 0` bounded-run option. Missing parameter fields inherit runner defaults. Unknown or duplicate fields, booleans used as numbers, nonfinite values, unsupported versions, and out-of-range values are rejected before launching the environment. Profiles cannot set credentials, customer identity, snapshot paths, step count, plant equations, or equipment limits.

**Precedence:** built-in defaults (`0.5`, `1.0`, `1000`) → selected profile → explicit `run` flags `--baseline-drive`, `--dt-s`, and `--period-ms`. The runner validates both the selected profile and the effective values. These flags map directly to the engine CLI; the C++ executable remains independently runnable without Python.

Each started run retains ignored version 2 `engine/run/runner-*/metadata.json`. It records the runner run ID and engine run ID, UTC start time, selected profile path and SHA-256 hash, effective parameters actually passed to the engine, engine executable path and SHA-256 hash, and `development_simulation_only` status. Its outcome progresses from `running` to `cleanly_stopped` or `failed`; recording integrity is reported separately as `unverified`, `complete`, or `incomplete`, with sample count and issues. The snapshot is removed at shutdown; metadata remains, along with any recording file the engine created. Metadata contains no credentials, full environment, customer identity, or operating limits. Matching these inputs helps reproduce a software demonstration, not establish physical validity. A wall period longer than the panel's 15-second freshness threshold can show a stale reading between valid simulation steps.

### Local simulation experiment recording

The runner passes `--record-jsonl` to the engine and retains one version 1 JSON Lines `samples.jsonl` in its ignored run directory. The C++ output adapter writes **one line per logical simulation step at its source**, independently of the replaceable latest-snapshot file and Python bridge. The engine also runs without recording when `--record-jsonl` is omitted. A recording write failure ends the development experiment with a diagnostic; it is not a physical equipment fault or protective action.

Every sample line has `record_version: "1"`, `record_type: "sample"`, the engine `run_id` tying samples to one execution, 1-based `sample_sequence`, `simulation_time_s` (elapsed simulation seconds), original UTC wall-clock `measured_at`, `source: "simulated"`, `provenance: "development_simulation"`, and `measurements`: `stack_voltage_v` (V), `stack_current_a` (A), and `electrolyte_temperature_c` (°C). A clean engine stop appends a `record_type: "completion"` line with the same version and run ID, `sample_count`, `last_sample_sequence`, and `status: "cleanly_stopped"`. These are synthetic outputs, not calibrated physical measurements or safe operating limits. The output file is created exclusively so an existing recording is never overwritten.

Copy the run directory printed by `tools/dev.py run`; after stopping the runner with Ctrl+C, inspect or export it. Set `RUN_DIR` to the printed directory; neither offline command starts the backend, frontend, or bridge:

```bash
RUN_DIR='engine/run/runner-<id-printed-by-runner>'
python3 tools/experiments.py inspect "$RUN_DIR"
python3 tools/experiments.py export "$RUN_DIR" "$RUN_DIR/samples.csv"
# Only when inspection reports incomplete data and its valid prefix is wanted:
python3 tools/experiments.py export "$RUN_DIR" "$RUN_DIR/partial-samples.csv" --allow-incomplete
```

In native Windows PowerShell, use the run directory printed by the runner:

```powershell
$RunDir = 'engine\run\runner-<id-printed-by-runner>'
python tools\experiments.py inspect $RunDir
python tools\experiments.py export $RunDir "$RunDir\samples.csv"
# Only for an incomplete valid prefix:
python tools\experiments.py export $RunDir "$RunDir\partial-samples.csv" --allow-incomplete
```

`inspect` reports the configuration and engine identity from metadata, engine run ID, valid sample count, simulation-time coverage, sequence gaps, run outcome, recording integrity, and validation issues. It exits nonzero for incomplete or unverified recordings. It detects malformed or unterminated final lines, mixed run IDs, duplicate or out-of-order sequences, sequence gaps, invalid timestamps, and nonfinite measurements. The valid prefix remains available after a damaged final record. `export` writes CSV columns `run_id`, `sample_sequence`, `simulation_time_s`, `measured_at_utc`, `stack_voltage_v`, `stack_current_a`, `electrolyte_temperature_c`, `source`, and `provenance`; the unit suffixes are seconds, volts, amperes, and degrees Celsius. It refuses incomplete data unless `--allow-incomplete` is explicit, never interpolates gaps, and never overwrites an existing CSV. An old profile-only metadata record without a recording is reported as unverified.

For a standalone bounded experiment, choose a new path under the ignored `engine/run/` directory:

```bash
engine/build/faradix_engine --steps 5 --period-ms 0 --record-jsonl engine/run/manual-5-samples.jsonl
python3 tools/experiments.py inspect engine/run/manual-5-samples.jsonl
python3 tools/experiments.py export engine/run/manual-5-samples.jsonl engine/run/manual-5-samples.csv
```

On native Windows with the usual Visual Studio multi-configuration generator, the equivalent bounded command is `engine\build\Debug\faradix_engine.exe --steps 5 --period-ms 0 --record-jsonl engine\run\manual-5-samples.jsonl`; then run `python tools\experiments.py inspect engine\run\manual-5-samples.jsonl` and `python tools\experiments.py export engine\run\manual-5-samples.jsonl engine\run\manual-5-samples.csv`. A single-configuration Windows generator instead places the executable at `engine\build\faradix_engine.exe`. Choose new output paths for each recording and CSV export.

The standalone JSONL can be inspected without runner metadata. These local recordings are development experiment artifacts, not the customer platform's planned persistent history, a validated digital twin, or evidence of physical fidelity.

### Manual startup (Linux)

The original four-process Linux workflow remains available. Create the same local credential only if `backend/.env.telemetry` does not already exist:

```bash
(set -C; umask 077; printf 'export FARADIX_DEV_TELEMETRY_TOKEN=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" > backend/.env.telemetry)
```

In separate terminals, each starting from the repository root:

```bash
# Terminal 1: development backend
source backend/.env.telemetry
FARADIX_DEV_TELEMETRY_INGEST=1 backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```bash
# Terminal 2: customer web application
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

```bash
# Terminal 3: C++ engine and atomic snapshot writer
engine/build/faradix_engine --baseline-drive 0.5 --dt-s 1 --period-ms 1000 --snapshot engine/run/latest.json
```

```bash
# Terminal 4: Python bridge
source backend/.env.telemetry
backend/.venv/bin/python backend/dev_publisher.py --mode snapshot --snapshot engine/run/latest.json --interval 1
```

For a bounded engine run without any backend or bridge, use `engine/build/faradix_engine --steps 5 --period-ms 0`. The earlier Python-only transport demo remains available with `backend/.venv/bin/python backend/dev_publisher.py --mode synthetic --interval 2` after sourcing the credential. The manual engine snapshot path differs from each runner-created path, so the runner never consumes or overwrites a manual instance's snapshot.

Stop only the engine to see the last reading become stale after 15 seconds (the next panel poll may add up to 5 seconds). Restart it to see fresh readings with a new run ID. Stop the backend to confirm that the engine continues stepping independently. `demo-unit-002` stays empty. The API health endpoint is **http://127.0.0.1:8000/api/v1/health**; the local API reference is **http://127.0.0.1:8000/docs**. Vite proxies `/api` requests to the local backend. Without `FARADIX_DEV_TELEMETRY_INGEST=1` and a configured token, ingestion returns `404`; customer reads still work.

To run focused development checks from the repository root:

```bash
python3 -m unittest discover -s tools/tests -v
(cd backend && .venv/bin/python -m pytest -q)
(cd frontend && npm run build)
ctest --test-dir engine/build -C Debug --output-on-failure
```

In native Windows PowerShell, use:

```powershell
python -m unittest discover -s tools/tests -v
Push-Location backend
.venv\Scripts\python.exe -m pytest -q
Pop-Location
Push-Location frontend
npm run build
Pop-Location
ctest --test-dir engine\build -C Debug --output-on-failure
```

The [development CI workflow](.github/workflows/development-ci.yml) runs these checks plus a full telemetry, recording, inspection/export, and shutdown smoke test on native Ubuntu 24.04 and Windows Server 2022 x64 runners. It checks out into a path containing spaces. The CI job uses Python 3.12, Node.js 22, GCC 11 on Ubuntu, and Visual Studio 2022 C++ on Windows. This matrix verifies the simulated development environment only.

## Development data and access limits

`backend/app/customer_context.py` selects the server-side development customer `demo-customer-01`. This dependency is intended to be replaced by real authentication. Browser-supplied customer IDs are not accepted as proof of authorization. The backend scopes inventory, detail, and latest-telemetry reads to that customer; another customer's fixture record stays hidden. The publisher bearer token is a local development transport credential for one demo device, **not production device authentication**. Keep the token out of Git and logs. Do not expose this API to untrusted networks.

**Real authentication is not implemented. This development shell is not ready for public deployment.** Customer names, installation labels, devices, and measurements are development fixtures or simulations. The engine has no physical device adapter, independent hardware safety implementation, validated operating limits, hard real-time guarantee, state estimator, predictive model, policy engine, or optimizer. There is no database, historical telemetry pipeline, alarm history, subscription entitlement enforcement, billing integration, or physical telemetry.

## Engine foundation and pending work

The reusable `faradix_core` library owns fixed simulation steps and a minimal supervisor that admits only finite dimensionless drive requests from 0 to 1. The CLI supplies a configurable baseline drive. The `faradix_simulated_device` adapter evolves a hidden toy temperature state and returns only public measurements through the `Device` interface. The separate `faradix_snapshot_adapter` writes a versioned JSON file by replacing it atomically. Run ID and sequence identify new samples; simulation time is advanced by `--dt-s`, while UTC measurement time comes from the wall clock when each step is observed. `--period-ms` controls wall pacing, not simulation time.

The **uncalibrated development plant** uses explicit Euler stepping: `I = 20u` A, `V = 40 + 0.5I + 0.01(T - 25)` V, and `T_next = T + dt × [0.002 I² - 0.08(T - 25)]` °C, where `u` is the dimensionless admitted drive and `dt` is simulation seconds. Initial temperature is 25 °C. These coefficients, the 0–1 software command bound, and all example values exist only to make behavior deterministic; they are **not validated equipment operating limits** or a predictive physical model. No actuator is connected.

State estimation, a separate predictive physics model, operating policy, optimization proposals, hardware-specific supervisory rules, real-time control, and physical safety remain pending. The next local milestone can add those collaborations through the current measurement and command boundaries. This foundation does not establish production readiness, physical accuracy, hardware safety certification, or hard real-time performance.

Subscription packaging, charging basis, expiry and offline behavior, historical-data access after expiry, remote commands, payment provider, currencies, and billing intervals remain open product decisions. No optimization capability has been assigned to a subscription tier.
