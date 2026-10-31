"""Focused checks for the local development process runner."""

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "dev.py"
spec = importlib.util.spec_from_file_location("faradix_dev", SCRIPT)
dev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dev
spec.loader.exec_module(dev)


class RunnerTests(unittest.TestCase):
    def test_existing_credential_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.telemetry"
            token = "a" * 40
            original = f"export FARADIX_DEV_TELEMETRY_TOKEN={token}\n"
            if dev.WINDOWS:
                dev.ensure_credential(path)
                path.write_text(original, encoding="utf-8", newline="\n")
            else:
                path.write_text(original)
                path.chmod(0o600)
            before = path.stat()
            self.assertEqual(dev.ensure_credential(path), token)
            self.assertEqual(path.read_text(), original)
            self.assertEqual(path.stat().st_ino, before.st_ino)
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_new_credential_is_restricted_and_invalid_existing_file_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.telemetry"
            token = dev.ensure_credential(path)
            self.assertGreaterEqual(len(token), 32)
            if dev.WINDOWS:
                dev.credential_acl(path, protect=False)
            else:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(dev.ensure_credential(path), token)
            path.write_text("not a credential\n")
            with self.assertRaises(dev.RunnerError):
                dev.ensure_credential(path)
            self.assertEqual(path.read_text(), "not a credential\n")

    def test_platform_executable_paths_and_tool_names(self):
        if dev.WINDOWS:
            self.assertEqual(dev.PYTHON.name, "python.exe")
            self.assertEqual(dev.PYTHON.parent.name, "Scripts")
            self.assertEqual(dev.engine_binary_path().name, "faradix_engine.exe")
            self.assertIn(dev.engine_binary_path().parent.name, ("Debug", "build"))
            self.assertEqual(dev.NPM, "npm.cmd")
        else:
            self.assertEqual(dev.PYTHON.name, "python")
            self.assertEqual(dev.PYTHON.parent.name, "bin")
            self.assertEqual(dev.engine_binary_path().name, "faradix_engine")
            self.assertEqual(dev.NPM, "npm")

    def test_cmake_cache_selects_exact_single_or_multi_config_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "engine" / "build"
            build.mkdir(parents=True)
            cache = build / "CMakeCache.txt"
            with patch.object(dev, "ENGINE", root / "engine"), patch.object(dev, "WINDOWS", True):
                cache.write_text("CMAKE_CONFIGURATION_TYPES:STRING=Debug;Release\n", encoding="utf-8")
                self.assertEqual(dev.engine_binary_path(), build / "Debug" / "faradix_engine.exe")
                cache.write_text("CMAKE_BUILD_TYPE:STRING=Debug\n", encoding="utf-8")
                self.assertEqual(dev.engine_binary_path(), build / "faradix_engine.exe")

    def test_windows_credential_acl_failure_leaves_no_token_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.telemetry"
            observed = []

            def fail_acl(candidate, *, protect):
                observed.append((candidate, protect, candidate.read_bytes()))
                raise dev.PlatformError("ACL unavailable")

            with patch.object(dev, "WINDOWS", True), patch.object(dev, "credential_acl", side_effect=fail_acl):
                with self.assertRaises(dev.PlatformError):
                    dev.ensure_credential(path)
            self.assertEqual(observed, [(path, True, b"")])
            self.assertFalse(path.exists())

    def test_windows_frontend_uses_node_entrypoint_without_cmd_wrapper(self):
        with patch.object(dev, "WINDOWS", True), patch.object(dev.shutil, "which", return_value="C:/Program Files/nodejs/node.exe"):
            command = dev.frontend_command()
        self.assertEqual(command[0], "C:/Program Files/nodejs/node.exe")
        self.assertEqual(Path(command[1]), dev.FRONTEND / "node_modules/vite/bin/vite.js")
        self.assertEqual(command[2:], ["--host", dev.HOST, "--port", str(dev.FRONTEND_PORT), "--strictPort"])

    def test_windows_metadata_replace_retries_transient_sharing_violation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            path.write_text('{"version":"old"}', encoding="utf-8")
            real_replace = os.replace
            attempts = []

            def temporarily_locked(source, destination):
                attempts.append((source, destination))
                if len(attempts) < 3:
                    raise PermissionError("sharing violation")
                real_replace(source, destination)

            with patch.object(dev, "WINDOWS", True), patch.object(dev.os, "replace", side_effect=temporarily_locked):
                dev.replace_run_metadata(path, {"version": "new"})
            self.assertEqual(len(attempts), 3)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"version": "new"})
            self.assertFalse(path.with_name("metadata.json.tmp").exists())

    def test_windows_credential_verification_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.telemetry"
            token = "a" * 40
            path.write_text(f"export {dev.TOKEN_NAME}={token}\n", encoding="utf-8")
            before = path.read_bytes()
            with patch.object(dev, "WINDOWS", True), patch.object(dev, "credential_acl") as acl:
                self.assertEqual(dev.ensure_credential(path), token)
            acl.assert_called_once_with(path, protect=False)
            self.assertEqual(path.read_bytes(), before)

    def test_shutdown_path_rejects_preexisting_file_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shutdown.request"
            path.touch()
            args = type("Args", (), {"shutdown_file": path})()
            with patch.object(dev, "Child") as child, patch.object(dev, "ensure_credential") as credential:
                with self.assertRaisesRegex(dev.RunnerError, "already exists"):
                    dev.run(args)
            child.assert_not_called()
            credential.assert_not_called()

    def test_stop_file_is_written_for_owned_engine_and_removed_after_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            stop_file = Path(directory) / "stop.request"
            script = "import pathlib,sys,time; path=pathlib.Path(sys.argv[1]); " \
                     "exec('while not path.exists(): time.sleep(0.01)'); print('stopped', flush=True)"
            child = dev.Child("engine", [sys.executable, "-c", script, str(stop_file)],
                              Path.cwd(), os.environ.copy())
            try:
                dev.stop_children([child], timeout=3, engine_stop_file=stop_file)
                self.assertEqual(child.process.returncode, 0)
                self.assertFalse(stop_file.exists())
            finally:
                if child.process.poll() is None:
                    dev.stop_children([child])

    def test_windows_refused_connect_still_checks_for_bound_nonlistener(self):
        class Socket:
            def __init__(self, *, bind_fails=False, connect_result=0):
                self.bind_fails = bind_fails
                self.connect_result = connect_result
                self.bind_calls = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def setsockopt(self, *_args):
                pass

            def settimeout(self, _timeout):
                pass

            def bind(self, _address):
                self.bind_calls += 1
                if self.bind_fails:
                    raise OSError("already bound")

            def connect_ex(self, _address):
                return self.connect_result

        for ordinary_fails in (True, False):
            with self.subTest(ordinary_fails=ordinary_fails):
                exclusive = Socket(bind_fails=True)
                probe = Socket(connect_result=111)
                ordinary = Socket(bind_fails=ordinary_fails)
                with patch.object(dev, "WINDOWS", True), \
                     patch.object(dev.socket, "SO_EXCLUSIVEADDRUSE", 0x4, create=True), \
                     patch.object(dev.socket, "socket", side_effect=[exclusive, probe, ordinary]):
                    if ordinary_fails:
                        with self.assertRaisesRegex(dev.RunnerError, "unavailable"):
                            dev.check_port_available(8000)
                    else:
                        dev.check_port_available(8000)
                self.assertEqual(ordinary.bind_calls, 1)

    def test_occupied_port_is_reported_without_stopping_owner(self):
        with socket.socket() as owner:
            owner.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            owner.bind((dev.HOST, 0))
            owner.listen()
            with self.assertRaisesRegex(dev.RunnerError, "unavailable"):
                dev.check_port_available(owner.getsockname()[1])
            self.assertIsNotNone(owner.fileno())

    def test_startup_timeout_stops_owned_process_and_descendant(self):
        with socket.socket() as temporary:
            temporary.bind((dev.HOST, 0))
            port = temporary.getsockname()[1]
        script = ("import subprocess,sys,time; "
                  "subprocess.Popen([sys.executable,'-m','http.server',sys.argv[1],"
                  "'--bind','127.0.0.1'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                  "time.sleep(60)")
        child = dev.Child("test", [sys.executable, "-c", script, str(port)], Path.cwd(), os.environ.copy())
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    dev.check_port_available(port)
                except dev.RunnerError:
                    break
                time.sleep(0.05)
            else:
                self.fail("Test child server did not start")
            with self.assertRaisesRegex(dev.RunnerError, "Timed out"):
                dev.wait_ready("impossible probe", lambda: False, [child], timeout=0.3)
        finally:
            dev.stop_children([child])
        self.assertIsNotNone(child.process.poll())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                dev.check_port_available(port)
                break
            except dev.RunnerError:
                time.sleep(0.05)
        else:
            self.fail("Owned descendant did not release its port")

    def test_child_exit_during_startup_is_reported(self):
        child = dev.Child("failing", [sys.executable, "-c", "raise SystemExit(7)"],
                          Path.cwd(), os.environ.copy())
        try:
            with self.assertRaisesRegex(dev.RunnerError, r"failing exited during startup \(status 7\)"):
                dev.wait_ready("never ready", lambda: False, [child], timeout=2)
        finally:
            dev.stop_children([child])

    def test_recording_outcome_and_engine_identity_are_saved_with_run_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            metadata_path = run_dir / "metadata.json"
            recording = run_dir / "samples.jsonl"
            profile = dev.load_profile(None)
            metadata = dev.make_run_metadata(
                "runner-1", "2026-10-31T12:00:00Z", profile,
                dev.effective_parameters(profile), "a" * 64,
            )
            dev.write_run_metadata(metadata_path, metadata)
            sample = {
                "record_version": "1", "record_type": "sample", "run_id": "engine-1",
                "sample_sequence": 1, "simulation_time_s": 1.0,
                "measured_at": "2026-10-31T12:00:01Z", "source": "simulated",
                "provenance": "development_simulation",
                "measurements": {"stack_voltage_v": 45.0, "stack_current_a": 10.0,
                                 "electrolyte_temperature_c": 25.0},
            }
            footer = {
                "record_version": "1", "record_type": "completion", "run_id": "engine-1",
                "sample_count": 1, "last_sample_sequence": 1, "status": "cleanly_stopped",
            }
            recording.write_text(json.dumps(sample) + "\n" + json.dumps(footer) + "\n", encoding="utf-8")
            dev.finalize_run_metadata(metadata_path, metadata, recording, clean_stop=True)
            saved = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["engine_run_id"], "engine-1")
            self.assertEqual(saved["outcome"]["state"], "cleanly_stopped")
            self.assertEqual(saved["recording"]["integrity"], "complete")
            self.assertEqual(saved["recording"]["sample_count"], 1)
            self.assertEqual(saved["recording"]["issues"], [])

            recording.write_text(json.dumps(sample) + "\n", encoding="utf-8")
            dev.finalize_run_metadata(metadata_path, metadata, recording, clean_stop=False)
            saved = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["outcome"]["state"], "failed")
            self.assertEqual(saved["recording"]["integrity"], "incomplete")
            self.assertIn("completion", " ".join(saved["recording"]["issues"]))

    def test_invocation_outside_repository_resolves_repo_root(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(SCRIPT), "check"], cwd=directory,
                                    text=True, capture_output=True, timeout=15)
        self.assertIn(f"Repository: {dev.ROOT}", result.stdout)
        self.assertIn(result.returncode, (0, 1))


if __name__ == "__main__":
    unittest.main()
