#!/usr/bin/env python3
"""Exercise the simulated runner end to end on a fresh CI host."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "engine" / "run"
PROFILE = ROOT / "profiles" / "simulation" / "fast_pacing_demo.json"
HOST = "127.0.0.1"
PORTS = (8000, 5173)
DEVICE_ID = "demo-unit-001"
OPENER = build_opener(ProxyHandler({}))


class SmokeFailure(Exception):
    """A failed end-to-end development check."""


def _new_run_directory(previous: set[Path]) -> Path | None:
    current = {path for path in RUNS.glob("runner-*") if path.is_dir()}
    created = current - previous
    if len(created) > 1:
        raise SmokeFailure(f"Expected one new runner directory, found {len(created)}")
    return next(iter(created), None)


def _fresh_telemetry() -> bool:
    try:
        with OPENER.open(f"http://{HOST}:8000/api/v1/devices/{DEVICE_ID}/telemetry", timeout=1) as response:
            data = json.load(response)
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False
    sample = data.get("sample")
    return (data.get("status") == "fresh" and isinstance(sample, dict)
            and sample.get("device_id") == DEVICE_ID
            and sample.get("source") == "simulated"
            and isinstance(sample.get("measurements"), dict))


def _frontend_serves_panel() -> bool:
    try:
        with OPENER.open(f"http://{HOST}:5173/devices/{DEVICE_ID}", timeout=1) as response:
            return response.status == 200 and b'id="root"' in response.read(8192)
    except (OSError, URLError):
        return False


def _wait_for_telemetry_and_recording(process: subprocess.Popen, previous: set[Path]) -> Path:
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeFailure(f"Runner exited before telemetry arrived (status {process.returncode})")
        directory = _new_run_directory(previous)
        if (directory is not None and (directory / "samples.jsonl").is_file()
                and (directory / "samples.jsonl").stat().st_size > 0
                and _fresh_telemetry() and _frontend_serves_panel()):
            return directory
        time.sleep(0.25)
    raise SmokeFailure("Timed out waiting for customer telemetry, web panel, and engine recording")


def _port_released(port: int) -> bool:
    # First exclude a live listener. Windows can reject an exclusive bind for
    # a short time after shutdown while previous connections drain.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener_probe:
        listener_probe.settimeout(0.2)
        if listener_probe.connect_ex((HOST, port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bind_probe:
        if os.name == "nt":
            bind_probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            bind_probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            bind_probe.bind((HOST, port))
        except OSError:
            if os.name != "nt":
                return False
            # A default bind distinguishes a draining connection from another
            # process that has bound this port without listening on it.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as default_probe:
                try:
                    default_probe.bind((HOST, port))
                except OSError:
                    return False
            return True
    return True


def _wait_for_released_ports() -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if all(_port_released(port) for port in PORTS):
            return
        time.sleep(0.2)
    raise SmokeFailure("The runner did not release both local service ports")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_run(directory: Path) -> None:
    metadata_path = directory / "metadata.json"
    recording_path = directory / "samples.jsonl"
    metadata_bytes = metadata_path.read_bytes()
    recording_bytes = recording_path.read_bytes()
    metadata = json.loads(metadata_bytes)
    if metadata.get("status") != "development_simulation_only":
        raise SmokeFailure("Run metadata lacks its simulation-only status")
    if metadata.get("outcome", {}).get("state") != "cleanly_stopped":
        raise SmokeFailure("Run metadata does not report a clean stop")
    recording = metadata.get("recording", {})
    if recording.get("integrity") != "complete" or recording.get("sample_count", 0) < 1:
        raise SmokeFailure("Run metadata does not report a complete nonempty recording")
    if not metadata.get("engine_run_id"):
        raise SmokeFailure("Run metadata has no engine run identity")
    started = metadata.get("started_at", "")
    try:
        if (not started.endswith("Z") or
                datetime.fromisoformat(started.replace("Z", "+00:00")).utcoffset() != timedelta(0)):
            raise ValueError("not UTC")
    except ValueError as error:
        raise SmokeFailure("Run metadata has no valid UTC start time") from error
    if metadata.get("profile", {}).get("sha256") != _sha256(PROFILE):
        raise SmokeFailure("Run metadata profile hash differs from the selected profile")
    profile_parameters = json.loads(PROFILE.read_text(encoding="utf-8"))["parameters"]
    if metadata.get("effective_parameters") != profile_parameters:
        raise SmokeFailure("Effective metadata settings differ from the launched profile")
    executable = Path(metadata.get("engine", {}).get("path", ""))
    executable = executable if executable.is_absolute() else ROOT / executable
    if not executable.is_file() or metadata["engine"].get("sha256") != _sha256(executable):
        raise SmokeFailure("Run metadata engine hash differs from the built executable")

    credential_path = ROOT / "backend" / ".env.telemetry"
    credential_line = credential_path.read_text(encoding="utf-8").strip()
    if not credential_line.startswith("export FARADIX_DEV_TELEMETRY_TOKEN="):
        raise SmokeFailure("Runner did not create the expected local credential")
    token = credential_line.partition("=")[2]
    if not token or token.encode() in metadata_bytes or token.encode() in recording_bytes:
        raise SmokeFailure("Credential is missing or leaked into retained run data")

    subprocess.run([sys.executable, str(ROOT / "tools" / "experiments.py"), "inspect", str(directory)],
                   cwd=ROOT, check=True, timeout=20)
    csv_path = directory / "ci-export.csv"
    subprocess.run([sys.executable, str(ROOT / "tools" / "experiments.py"), "export",
                    str(directory), str(csv_path)], cwd=ROOT, check=True, timeout=20)
    with csv_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != recording["sample_count"] or any(row["source"] != "simulated" for row in rows):
        raise SmokeFailure("CSV export does not match the complete simulated recording")
    if token.encode() in csv_path.read_bytes():
        raise SmokeFailure("Credential leaked into the exported CSV")
    print(f"[ci-smoke] Fresh customer telemetry, {len(rows)} recorded/exported samples, clean metadata")


def _stop_owned_runner(process: subprocess.Popen, shutdown_file: Path) -> None:
    if process.poll() is not None:
        return
    shutdown_file.touch(exist_ok=True)
    try:
        process.wait(timeout=30)
        return
    except subprocess.TimeoutExpired:
        pass
    # This fallback addresses only the process started by this script.
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except OSError:
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, check=False, timeout=10)
        else:
            process.kill()
        process.wait(timeout=10)
    raise SmokeFailure("Runner ignored its shutdown file; forced cleanup was required")


def main() -> int:
    credential_path = ROOT / "backend" / ".env.telemetry"
    existing_credential = credential_path.read_bytes() if credential_path.exists() else None
    RUNS.mkdir(exist_ok=True)
    previous = {path for path in RUNS.glob("runner-*") if path.is_dir()}
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sentinel:
        sentinel.bind((HOST, 0))
        sentinel.listen(1)
        sentinel_port = sentinel.getsockname()[1]
        if sentinel_port in PORTS:
            raise SmokeFailure("Sentinel unexpectedly acquired a service port")
        with tempfile.TemporaryDirectory(prefix="faradix-ci-shutdown-") as temporary:
            shutdown_file = Path(temporary) / "stop.request"
            command = [sys.executable, str(ROOT / "tools" / "dev.py"), "run", "--profile",
                       str(PROFILE), "--shutdown-file", str(shutdown_file)]
            options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                       else {"start_new_session": True})
            process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, errors="replace",
                                       bufsize=1, **options)
            def relay() -> None:
                assert process.stdout is not None
                for line in process.stdout:
                    print(line.rstrip(), flush=True)
            reader = threading.Thread(target=relay, daemon=True)
            reader.start()
            try:
                directory = _wait_for_telemetry_and_recording(process, previous)
                shutdown_file.touch(exist_ok=False)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired as error:
                    raise SmokeFailure("Runner did not stop after its shutdown file appeared") from error
                if process.returncode != 0:
                    raise SmokeFailure(f"Runner exited with status {process.returncode}")
                _wait_for_released_ports()
                with socket.create_connection((HOST, sentinel_port), timeout=1):
                    pass
                _verify_run(directory)
                if existing_credential is not None and credential_path.read_bytes() != existing_credential:
                    raise SmokeFailure("Runner replaced an existing local credential")
                print("[ci-smoke] Runner stopped; service ports released; unrelated sentinel stayed available")
                return 0
            finally:
                cleanup_error = None
                try:
                    if process.poll() is None:
                        _stop_owned_runner(process, shutdown_file)
                except SmokeFailure as error:
                    cleanup_error = error
                try:
                    _wait_for_released_ports()
                except SmokeFailure as error:
                    cleanup_error = cleanup_error or error
                reader.join(timeout=3)
                if process.stdout is not None:
                    process.stdout.close()
                if cleanup_error is not None:
                    if sys.exc_info()[0] is None:
                        raise cleanup_error
                    print(f"[ci-smoke] Cleanup issue: {cleanup_error}", file=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SmokeFailure, OSError, subprocess.CalledProcessError) as error:
        print(f"[ci-smoke] {error}", file=sys.stderr)
        raise SystemExit(1)
