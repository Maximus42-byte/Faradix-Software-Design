"""Focused checks for development-only simulation profiles and run records."""

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "dev.py"
spec = importlib.util.spec_from_file_location("faradix_profile_dev", SCRIPT)
dev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dev
spec.loader.exec_module(dev)


def profile_json(parameters=None, **changes):
    profile = {
        "schema_version": "1",
        "kind": "development_simulation",
        "parameters": parameters if parameters is not None else {},
    }
    profile.update(changes)
    return json.dumps(profile)


class ProfileTests(unittest.TestCase):
    def write_profile(self, directory, content):
        path = Path(directory) / "profile.json"
        path.write_text(content, encoding="utf-8")
        return path

    def assert_invalid(self, content, message_fragment):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_profile(directory, content)
            with self.assertRaises(dev.RunnerError) as caught:
                dev.load_profile(path)
        self.assertIn(message_fragment.lower(), str(caught.exception).lower())

    def test_bundled_default_preserves_previous_run_parameters(self):
        profile = dev.load_profile(None)
        parameters = dev.effective_parameters(profile)
        self.assertEqual(parameters.baseline_drive, 0.5)
        self.assertEqual(parameters.dt_s, 1.0)
        self.assertEqual(parameters.period_ms, 1000)
        self.assertEqual(len(profile.sha256), 64)

    def test_profile_rejects_invalid_structure_and_ambiguous_keys(self):
        cases = [
            ("{", "JSON"),
            ("[]", "object"),
            (profile_json({}), "parameters"),
            (profile_json(parameters=[]), "parameters"),
            (profile_json({"dt_s": "1"}), "dt_s"),
            (json.dumps({"kind": "development_simulation", "parameters": {"dt_s": 1}}),
             "schema_version"),
            (profile_json(schema_version="2"), "schema_version"),
            (profile_json(kind="equipment_operation"), "kind"),
            (profile_json(unexpected="value"), "unexpected"),
            (profile_json(parameters={"customer_id": "demo-customer-01"}), "customer_id"),
            ('{"schema_version":"1","schema_version":"1",'
             '"kind":"development_simulation","parameters":{}}', "duplicate"),
            ('{"schema_version":"1","kind":"development_simulation",'
             '"parameters":{"dt_s":1,"dt_s":2}}', "duplicate"),
        ]
        for content, expected in cases:
            with self.subTest(content=content):
                self.assert_invalid(content, expected)

    def test_profile_rejects_invalid_simulation_numbers(self):
        cases = [
            ({"baseline_drive": True}, "baseline_drive"),
            ({"baseline_drive": -0.01}, "baseline_drive"),
            ({"baseline_drive": 1.01}, "baseline_drive"),
            ({"dt_s": False}, "dt_s"),
            ({"dt_s": 0}, "dt_s"),
            ({"dt_s": -1}, "dt_s"),
            ({"period_ms": True}, "period_ms"),
            ({"period_ms": 0}, "period_ms"),
            ({"period_ms": 60001}, "period_ms"),
            ({"period_ms": 1.5}, "period_ms"),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                self.assert_invalid(profile_json(values), expected)
        self.assert_invalid(profile_json({"baseline_drive": math.nan}), "non-finite")
        self.assert_invalid(profile_json({"dt_s": math.inf}), "non-finite")

    def test_explicit_overrides_win_and_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_profile(directory, profile_json({
                "baseline_drive": 0.25, "dt_s": 2.0, "period_ms": 2000,
            }))
            profile = dev.load_profile(path)
            parameters = dev.effective_parameters(
                profile, baseline_drive=0.75, period_ms=500,
            )
            self.assertEqual(parameters.baseline_drive, 0.75)
            self.assertEqual(parameters.dt_s, 2.0)
            self.assertEqual(parameters.period_ms, 500)
            for overrides in (
                {"baseline_drive": True},
                {"baseline_drive": math.nan},
                {"baseline_drive": 1.1},
                {"dt_s": math.inf},
                {"dt_s": 0},
                {"period_ms": False},
                {"period_ms": 0},
                {"period_ms": 60001},
            ):
                with self.subTest(overrides=overrides):
                    with self.assertRaises(dev.RunnerError):
                        dev.effective_parameters(profile, **overrides)

    def test_engine_arguments_and_metadata_use_same_effective_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_profile(directory, profile_json({
                "baseline_drive": 0.3, "dt_s": 2, "period_ms": 2000,
            }))
            profile = dev.load_profile(path)
            parameters = dev.effective_parameters(profile, baseline_drive=0.7, period_ms=750)
            snapshot = Path(directory) / "run" / "latest.json"
            recording = snapshot.parent / "samples.jsonl"
            stop_file = snapshot.parent / "engine-stop.request"
            argv = dev.engine_command(parameters, snapshot, recording, stop_file)
            flag_values = {argv[index]: argv[index + 1] for index in range(1, len(argv), 2)}
            self.assertEqual(float(flag_values["--baseline-drive"]), 0.7)
            self.assertEqual(float(flag_values["--dt-s"]), 2.0)
            self.assertEqual(int(flag_values["--period-ms"]), 750)
            self.assertEqual(Path(flag_values["--snapshot"]), snapshot)
            self.assertEqual(Path(flag_values["--record-jsonl"]), recording)
            self.assertEqual(Path(flag_values["--stop-file"]), stop_file)

            token = "supersecret-development-credential"
            with patch.dict(os.environ, {dev.TOKEN_NAME: token}):
                metadata = dev.make_run_metadata(
                    "test-run-id", "2026-10-31T12:34:56Z", profile, parameters, "a" * 64,
                )
            self.assertEqual(set(metadata), {"metadata_version", "run_id", "started_at",
                                             "status", "profile", "effective_parameters", "engine",
                                             "engine_run_id", "outcome", "recording"})
            self.assertEqual(metadata["metadata_version"], "2")
            self.assertIsNone(metadata["engine_run_id"])
            self.assertEqual(metadata["outcome"], {"state": "running"})
            self.assertEqual(metadata["recording"]["integrity"], "unverified")
            self.assertEqual(metadata["run_id"], "test-run-id")
            self.assertEqual(metadata["started_at"], "2026-10-31T12:34:56Z")
            self.assertEqual(metadata["status"], "development_simulation_only")
            self.assertEqual(metadata["effective_parameters"], {
                "baseline_drive": float(flag_values["--baseline-drive"]),
                "dt_s": float(flag_values["--dt-s"]),
                "period_ms": int(flag_values["--period-ms"]),
            })
            self.assertEqual(Path(metadata["profile"]["path"]).resolve(), path.resolve())
            self.assertEqual(metadata["profile"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(metadata["engine"]["sha256"], "a" * 64)
            encoded = json.dumps(metadata)
            self.assertNotIn(token, encoded)
            self.assertNotIn(dev.TOKEN_NAME, encoded)
            self.assertNotIn("customer", encoded)

    def test_invalid_profile_does_not_start_processes_or_read_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_profile(directory, profile_json({"period_ms": 0}))
            args = argparse.Namespace(profile=path, baseline_drive=None, dt_s=None, period_ms=None)
            with patch.object(dev, "Child") as child, patch.object(dev, "ensure_credential") as credential:
                with self.assertRaises(dev.RunnerError):
                    dev.run(args)
            child.assert_not_called()
            credential.assert_not_called()

    def test_invalid_override_does_not_start_processes_or_read_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_profile(directory, profile_json({"dt_s": 1.0}))
            args = argparse.Namespace(profile=path, baseline_drive=None, dt_s=None, period_ms=0)
            with patch.object(dev, "Child") as child, patch.object(dev, "ensure_credential") as credential:
                with self.assertRaises(dev.RunnerError):
                    dev.run(args)
            child.assert_not_called()
            credential.assert_not_called()

    def test_profile_paths_are_repository_relative_or_absolute_outside_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            repository = temp / "repository with spaces"
            relative = Path("profiles/simulation/example.json")
            profile_path = repository / relative
            profile_path.parent.mkdir(parents=True)
            profile_path.write_text(profile_json({"period_ms": 1500}), encoding="utf-8")
            elsewhere = temp / "elsewhere"
            elsewhere.mkdir()
            previous_cwd = Path.cwd()
            try:
                os.chdir(elsewhere)
                with patch.object(dev, "ROOT", repository):
                    relative_selection = dev.load_profile(relative)
                    absolute_selection = dev.load_profile(profile_path)
            finally:
                os.chdir(previous_cwd)
            self.assertEqual(Path(relative_selection.path).resolve(), profile_path.resolve())
            self.assertEqual(Path(absolute_selection.path).resolve(), profile_path.resolve())
            self.assertEqual(relative_selection.sha256, absolute_selection.sha256)


if __name__ == "__main__":
    unittest.main()
