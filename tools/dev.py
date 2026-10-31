#!/usr/bin/env python3
"""Run the local simulated engine-to-panel development environment."""

from __future__ import annotations

import argparse
import json
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
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
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


class RunnerError(Exception):
    """A checked development setup or startup failure."""


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


def run() -> int:
    issues = runtime_requirements()
    if issues:
        raise RunnerError("\n".join(issues))
    for port in (BACKEND_PORT, FRONTEND_PORT):
        check_port_available(port)
    token = ensure_credential()
    base_env = os.environ.copy()
    base_env.pop(TOKEN_NAME, None)
    base_env.pop("FARADIX_DEV_TELEMETRY_INGEST", None)
    secret_env = {**base_env, TOKEN_NAME: token}
    children: list[Child] = []
    snapshot_dir: Path | None = None
    try:
        (ENGINE / "run").mkdir(exist_ok=True)
        snapshot_dir = Path(tempfile.mkdtemp(prefix="runner-", dir=ENGINE / "run"))
        snapshot = snapshot_dir / "latest.json"
        children.append(Child("backend", [str(PYTHON), "-m", "uvicorn", "app.main:app", "--app-dir", str(BACKEND),
                                          "--host", HOST, "--port", str(BACKEND_PORT)], ROOT,
                              {**secret_env, "FARADIX_DEV_TELEMETRY_INGEST": "1"}))
        wait_ready("backend", lambda: get_json(f"http://{HOST}:{BACKEND_PORT}/api/v1/health").get("status") == "ok", children)
        children.append(Child("frontend", ["npm", "run", "dev", "--", "--host", HOST, "--port", str(FRONTEND_PORT), "--strictPort"], FRONTEND, base_env))
        wait_ready("frontend", frontend_ready, children)
        children.append(Child("engine", [str(ENGINE_BINARY), "--baseline-drive", "0.5", "--dt-s", "1", "--period-ms", "1000",
                                         "--snapshot", str(snapshot)], ROOT, base_env))
        wait_ready("engine snapshot", lambda: snapshot.is_file() and json.loads(snapshot.read_text(encoding="utf-8")).get("sample_sequence", 0) >= 1, children)
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
        print("\n[runner] Stopping the development environment.")
        return 0
    finally:
        stop_children(children)
        if snapshot_dir is not None:
            shutil.rmtree(snapshot_dir)
        print("[runner] Owned processes stopped.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "build", "run"))
    args = parser.parse_args()
    try:
        return {"check": check, "build": build, "run": run}[args.command]()
    except (RunnerError, OSError, subprocess.CalledProcessError) as error:
        print(f"[runner] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
