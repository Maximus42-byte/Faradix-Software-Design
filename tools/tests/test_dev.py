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
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(dev.ensure_credential(path), token)
            path.write_text("not a credential\n")
            with self.assertRaises(dev.RunnerError):
                dev.ensure_credential(path)
            self.assertEqual(path.read_text(), "not a credential\n")

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
            with self.assertRaisesRegex(dev.RunnerError, "failing exited during startup \(status 7\)"):
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
