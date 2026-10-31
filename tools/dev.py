#!/usr/bin/env python3
"""Run the local simulated engine-to-panel development environment."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ENGINE = ROOT / "engine"
PYTHON = BACKEND / ".venv" / "bin" / "python"
ENGINE_BINARY = ENGINE / "build" / "faradix_engine"
CREDENTIAL = BACKEND / ".env.telemetry"
DEVICE_ID = "demo-unit-001"
HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_PORT = 5173
TOKEN_NAME = "FARADIX_DEV_TELEMETRY_TOKEN"
TOKEN_PATTERN = re.compile(r"export FARADIX_DEV_TELEMETRY_TOKEN=([A-Za-z0-9_-]+)\n?")
DEFAULT_PROFILE = ROOT / "profiles" / "simulation" / "default.json"
PROFILE_KEYS = {"schema_version", "kind", "parameters"}
PARAMETER_KEYS = {"baseline_drive", "dt_s", "period_ms"}


class RunnerError(Exception):
    """A checked development setup or startup failure."""


@dataclass(frozen=True)
class ProfileSelection:
    path: Path
    sha256: str
    parameters: dict[str, float | int]


@dataclass(frozen=True)
class SimulationParameters:
    baseline_drive: float
    dt_s: float
    period_ms: int


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate field '{key}'")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON value {value}")


def _validate_parameter(name: str, value: object, context: str) -> None:
    if name == "period_ms":
        if type(value) is not int or not 1 <= value <= 60000:
            raise RunnerError(f"{context}: period_ms must be an integer from 1 to 60000 for a continuous run")
        return
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        finite = False
    if not finite:
        raise RunnerError(f"{context}: {name} must be a finite number")
    if name == "baseline_drive" and not 0 <= value <= 1:
        raise RunnerError(f"{context}: baseline_drive must be from 0 to 1 (development command fraction)")
    if name == "dt_s" and value <= 0:
        raise RunnerError(f"{context}: dt_s must be greater than 0 seconds")


def load_profile(path: Path | None) -> ProfileSelection:
    """Resolve relative paths at the repository root and validate version 1 JSON."""
    selected = DEFAULT_PROFILE if path is None else path
    resolved = (selected if selected.is_absolute() else ROOT / selected).resolve()
    try:
        raw = resolved.read_bytes()
    except OSError as error:
        raise RunnerError(f"Cannot read simulation profile {resolved}: {error.strerror or error}") from error
    if len(raw) > 65536:
        raise RunnerError(f"Simulation profile {resolved} is too large (maximum 64 KiB)")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys,
                          parse_constant=_reject_constant)
    except (UnicodeError, ValueError) as error:
        raise RunnerError(f"Invalid simulation profile {resolved}: {error}") from error
    if not isinstance(data, dict):
        raise RunnerError(f"Simulation profile {resolved}: root must be a JSON object")
    unknown = sorted(set(data) - PROFILE_KEYS)
    missing = sorted(PROFILE_KEYS - set(data))
    if unknown or missing:
        raise RunnerError(f"Simulation profile {resolved}: unknown fields {unknown}; missing fields {missing}")
    if data["schema_version"] != "1":
        raise RunnerError(f"Simulation profile {resolved}: unsupported schema_version; expected '1'")
    if data["kind"] != "development_simulation":
        raise RunnerError(f"Simulation profile {resolved}: kind must be 'development_simulation'")
    parameters = data["parameters"]
    if not isinstance(parameters, dict) or not parameters:
        raise RunnerError(f"Simulation profile {resolved}: parameters must be a nonempty JSON object")
    unknown = sorted(set(parameters) - PARAMETER_KEYS)
    if unknown:
        raise RunnerError(f"Simulation profile {resolved}: unsupported parameter(s): {', '.join(unknown)}")
    for name, value in parameters.items():
        _validate_parameter(name, value, f"Simulation profile {resolved}")
    return ProfileSelection(resolved, hashlib.sha256(raw).hexdigest(), parameters)


def effective_parameters(profile: ProfileSelection, baseline_drive: float | None = None,
                         dt_s: float | None = None, period_ms: int | None = None) -> SimulationParameters:
    """Apply engine defaults, selected profile, then explicit runner CLI flags."""
    values = {"baseline_drive": 0.5, "dt_s": 1.0, "period_ms": 1000}
    values.update(profile.parameters)
    for name, override in (("baseline_drive", baseline_drive), ("dt_s", dt_s), ("period_ms", period_ms)):
        if override is not None:
            values[name] = override
    for name, value in values.items():
        _validate_parameter(name, value, "Effective simulation settings")
    return SimulationParameters(float(values["baseline_drive"]), float(values["dt_s"]), values["period_ms"])


def engine_command(parameters: SimulationParameters, snapshot: Path,
                   recording: Path | None = None) -> list[str]:
    command = [str(ENGINE_BINARY), "--baseline-drive", repr(parameters.baseline_drive),
               "--dt-s", repr(parameters.dt_s), "--period-ms", str(parameters.period_ms),
               "--snapshot", str(snapshot)]
    if recording is not None:
        command.extend(("--record-jsonl", str(recording)))
    return command


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def make_run_metadata(run_id: str, started_at: str, profile: ProfileSelection,
                      parameters: SimulationParameters, engine_sha256: str) -> dict:
    """Allowlist-only record: no environment, tokens, customer ID, or equipment limits."""
    return {
        "metadata_version": "2",
        "run_id": run_id,
        "started_at": started_at,
        "status": "development_simulation_only",
        "profile": {"path": _profile_label(profile.path), "sha256": profile.sha256},
        "effective_parameters": asdict(parameters),
        "engine": {"path": "engine/build/faradix_engine", "sha256": engine_sha256},
        "engine_run_id": None,
        "outcome": {"state": "running"},
        "recording": {"path": "samples.jsonl", "integrity": "unverified", "sample_count": 0,
                      "issues": []},
    }


def write_run_metadata(path: Path, metadata: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(metadata, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def replace_run_metadata(path: Path, metadata: dict) -> None:
    """Atomically update the owned run record after startup or shutdown."""
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(metadata, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def version_tuple(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(value or 0) for value in match.groups()) if match else ()


def command_version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=True)
        return (result.stdout or result.stderr).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def build_requirements() -> list[str]:
    issues = []
    cmake = shutil.which("cmake")
    if not cmake or version_tuple(command_version([cmake, "--version"])) < (3, 22, 0):
        issues.append("CMake 3.22+ is required for build; install it explicitly (for example: sudo apt install cmake).")
    if not shutil.which("g++-11"):
        issues.append("g++-11 is required for build; install it explicitly (for example: sudo apt install g++-11).")
    return issues


def runtime_requirements() -> list[str]:
    issues = []
    if sys.version_info < (3, 10):
        issues.append("Python 3.10+ is required for tools/dev.py.")
    if not PYTHON.is_file() or not os.access(PYTHON, os.X_OK):
        issues.append("Backend environment missing; create backend/.venv and install backend/requirements-dev.txt.")
    elif not command_version([str(PYTHON), "-c", "import fastapi, uvicorn, pydantic; print('ok')"]):
        issues.append("Backend dependencies missing; install backend/requirements-dev.txt into backend/.venv.")
    if not ENGINE_BINARY.is_file() or not os.access(ENGINE_BINARY, os.X_OK):
        issues.append("Engine binary missing; run python3 tools/dev.py build after installing build prerequisites.")
    node = shutil.which("node")
    node_version = version_tuple(command_version([node, "--version"])) if node else ()
    if not node_version or not (node_version >= (22, 12, 0) or (20, 19, 0) <= node_version < (21, 0, 0)):
        issues.append("Node.js 20.19+ or 22.12+ is required for Vite.")
    if not shutil.which("npm"):
        issues.append("npm is required; install Node.js and npm explicitly.")
    if not (FRONTEND / "node_modules" / ".bin" / "vite").exists():
        issues.append("Frontend dependencies missing; run npm ci in frontend/.")
    return issues


def check_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # Match server reuse behavior so closed connections in TIME_WAIT do not
        # make a stopped runner look as though it still owns the port.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
        except OSError as error:
            raise RunnerError(f"{HOST}:{port} is unavailable ({error.strerror}); stop its owner or free the port manually.") from error


def check() -> int:
    print(f"Repository: {ROOT}")
    issues = build_requirements() + runtime_requirements()
    for port in (BACKEND_PORT, FRONTEND_PORT):
        try:
            check_port_available(port)
        except RunnerError as error:
            issues.append(str(error))
    if issues:
        for issue in issues:
            print(f"[check] {issue}")
        return 1
    print("[check] Build tools, runtime dependencies, engine binary, and local ports are ready.")
    return 0


def build() -> int:
    issues = build_requirements()
    if issues:
        raise RunnerError("\n".join(issues))
    cmake = shutil.which("cmake")
    assert cmake is not None
    subprocess.run([cmake, "-S", str(ENGINE), "-B", str(ENGINE / "build"),
                    "-DCMAKE_CXX_COMPILER=g++-11", "-DCMAKE_BUILD_TYPE=Debug"], cwd=ROOT, check=True)
    subprocess.run([cmake, "--build", str(ENGINE / "build"), "--parallel"], cwd=ROOT, check=True)
    print(f"[build] Engine binary: {ENGINE_BINARY}")
    return 0


def ensure_credential(path: Path = CREDENTIAL) -> str:
    """Reuse a restricted plaintext token file or create it exclusively; never source it."""
    if path.is_symlink():
        raise RunnerError(f"Credential path is a symlink: {path}")
    if not path.exists():
        token = secrets.token_urlsafe(32)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(f"export {TOKEN_NAME}={token}\n")
            print(f"[runner] Created restricted local credential file: {path}")
            return token
    if path.is_symlink():
        raise RunnerError(f"Credential path is a symlink: {path}")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RunnerError(f"Credential file must be owned by this user and mode 0600: {path}")
    match = TOKEN_PATTERN.fullmatch(path.read_text(encoding="utf-8"))
    if not match or len(match.group(1)) < 32:
        raise RunnerError(f"Credential file has an invalid format: {path}")
    print(f"[runner] Reusing local credential file: {path}")
    return match.group(1)


class Child:
    def __init__(self, name: str, args: list[str], cwd: Path, env: dict[str, str]) -> None:
        self.name = name
        self.process = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1,
                                        start_new_session=True)
        threading.Thread(target=self._relay, daemon=True).start()

    def _relay(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            print(f"[{self.name}] {line.rstrip()}", flush=True)


def stop_children(children: list[Child], timeout: float = 5.0) -> None:
    """Signal only process groups created by this runner, including spawned descendants."""
    for child in reversed(children):
        try:
            os.killpg(child.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    for child in reversed(children):
        remaining = max(0.0, deadline - time.monotonic())
        try:
            child.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            pass
    for child in reversed(children):
        try:
            os.killpg(child.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            child.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        if child.process.stdout is not None:
            child.process.stdout.close()


def wait_ready(label: str, probe, children: list[Child], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for child in children:
            code = child.process.poll()
            if code is not None:
                raise RunnerError(f"{child.name} exited during startup (status {code}); see its labeled output.")
        try:
            if probe():
                print(f"[runner] {label} ready")
                return
        except (OSError, ValueError, json.JSONDecodeError, HTTPError, URLError):
            pass
        time.sleep(0.2)
    raise RunnerError(f"Timed out waiting for {label} after {timeout:g} seconds.")


def get_json(url: str) -> dict:
    with urlopen(url, timeout=1) as response:
        return json.load(response)


def frontend_ready() -> bool:
    with urlopen(f"http://{HOST}:{FRONTEND_PORT}/", timeout=1) as response:
        return response.status == 200 and b"<div id=\"root\"" in response.read(8192)


def telemetry_ready() -> bool:
    data = get_json(f"http://{HOST}:{BACKEND_PORT}/api/v1/devices/{DEVICE_ID}/telemetry")
    sample = data.get("sample")
    return (data.get("status") == "fresh" and isinstance(sample, dict) and
            sample.get("device_id") == DEVICE_ID and sample.get("source") == "simulated")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def finalize_run_metadata(path: Path, metadata: dict, recording: Path,
                          clean_stop: bool) -> None:
    """Keep runner outcome separate from the recorder's verified integrity."""
    from experiments import inspect_recording

    expected_id = metadata["engine_run_id"]
    inspection = inspect_recording(recording, expected_run_id=expected_id)
    if metadata["engine_run_id"] is None:
        metadata["engine_run_id"] = inspection["run_id"]
    metadata["outcome"] = {"state": "cleanly_stopped" if clean_stop else "failed",
                           "ended_at": _utc_now()}
    metadata["recording"] = {
        "path": recording.name,
        "integrity": inspection["integrity"],
        "sample_count": inspection["sample_count"],
        "issues": inspection["issues"],
    }
    replace_run_metadata(path, metadata)


def run(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    parameters = effective_parameters(profile, args.baseline_drive, args.dt_s, args.period_ms)
    issues = runtime_requirements()
    if issues:
        raise RunnerError("\n".join(issues))
    for port in (BACKEND_PORT, FRONTEND_PORT):
        check_port_available(port)
    token = ensure_credential()
    engine_sha256 = _file_sha256(ENGINE_BINARY)
    run_id = uuid.uuid4().hex
    started_at = _utc_now()
    base_env = os.environ.copy()
    base_env.pop(TOKEN_NAME, None)
    base_env.pop("FARADIX_DEV_TELEMETRY_INGEST", None)
    secret_env = {**base_env, TOKEN_NAME: token}
    children: list[Child] = []
    snapshot: Path | None = None
    recording: Path | None = None
    metadata_path: Path | None = None
    metadata: dict | None = None
    engine_child: Child | None = None
    stopped_by_user = False
    try:
        (ENGINE / "run").mkdir(exist_ok=True)
        snapshot_dir = Path(tempfile.mkdtemp(prefix=f"runner-{run_id}-", dir=ENGINE / "run"))
        snapshot = snapshot_dir / "latest.json"
        recording = snapshot_dir / "samples.jsonl"
        metadata_path = snapshot_dir / "metadata.json"
        metadata = make_run_metadata(run_id, started_at, profile, parameters, engine_sha256)
        write_run_metadata(metadata_path, metadata)
        print(f"[runner] Development simulation profile: {_profile_label(profile.path)}")
        print(f"[runner] Effective engine settings: baseline_drive={parameters.baseline_drive}, "
              f"dt_s={parameters.dt_s}, period_ms={parameters.period_ms}")
        print(f"[runner] Run metadata: {metadata_path}")
        print(f"[runner] Step recording: {recording}")
        children.append(Child("backend", [str(PYTHON), "-m", "uvicorn", "app.main:app", "--app-dir", str(BACKEND),
                                          "--host", HOST, "--port", str(BACKEND_PORT)], ROOT,
                              {**secret_env, "FARADIX_DEV_TELEMETRY_INGEST": "1"}))
        wait_ready("backend", lambda: get_json(f"http://{HOST}:{BACKEND_PORT}/api/v1/health").get("status") == "ok", children)
        children.append(Child("frontend", ["npm", "run", "dev", "--", "--host", HOST, "--port", str(FRONTEND_PORT), "--strictPort"], FRONTEND, base_env))
        wait_ready("frontend", frontend_ready, children)
        engine_child = Child("engine", engine_command(parameters, snapshot, recording), ROOT, base_env)
        children.append(engine_child)
        wait_ready("engine snapshot", lambda: snapshot.is_file() and json.loads(snapshot.read_text(encoding="utf-8")).get("sample_sequence", 0) >= 1, children)
        snapshot_run_id = json.loads(snapshot.read_text(encoding="utf-8")).get("run_id")
        if not isinstance(snapshot_run_id, str) or not snapshot_run_id:
            raise RunnerError("Engine snapshot has no run identity")
        metadata["engine_run_id"] = snapshot_run_id
        replace_run_metadata(metadata_path, metadata)
        children.append(Child("bridge", [str(PYTHON), str(BACKEND / "dev_publisher.py"), "--mode", "snapshot",
                                         "--snapshot", str(snapshot), "--interval", "1", "--url", f"http://{HOST}:{BACKEND_PORT}"], ROOT, secret_env))
        wait_ready("simulated telemetry", telemetry_ready, children)
        print(f"[runner] Open http://{HOST}:{FRONTEND_PORT}/devices/{DEVICE_ID} (Ctrl+C stops owned processes).")
        while True:
            for child in children:
                code = child.process.poll()
                if code is not None:
                    raise RunnerError(f"{child.name} exited unexpectedly (status {code}); stopping the development environment.")
            time.sleep(0.3)
    except KeyboardInterrupt:
        stopped_by_user = True
        print("\n[runner] Stopping the development environment.")
    finally:
        stop_children(children)
        engine_stopped_cleanly = engine_child is None or engine_child.process.returncode == 0
        if metadata_path is not None and metadata is not None and recording is not None:
            finalize_run_metadata(metadata_path, metadata, recording,
                                  stopped_by_user and engine_stopped_cleanly)
        if snapshot is not None:
            snapshot.unlink(missing_ok=True)
        print("[runner] Owned processes stopped; run metadata and recording retained.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="check build and run prerequisites")
    commands.add_parser("build", help="configure and build the C++ engine")
    run_parser = commands.add_parser("run", help="start the local simulated development environment")
    run_parser.add_argument("--profile", type=Path, help="versioned JSON path; relative paths use the repository root")
    run_parser.add_argument("--baseline-drive", type=float, help="override development drive fraction, 0 to 1")
    run_parser.add_argument("--dt-s", type=float, help="override positive simulation seconds per step")
    run_parser.add_argument("--period-ms", type=int, help="override wall pacing in milliseconds, 1 to 60000")
    args = parser.parse_args()
    try:
        if args.command == "run":
            return run(args)
        return {"check": check, "build": build}[args.command]()
    except (RunnerError, OSError, subprocess.CalledProcessError) as error:
        print(f"[runner] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
