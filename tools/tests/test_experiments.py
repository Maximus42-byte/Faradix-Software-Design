"""Focused checks for local simulation recording inspection and export."""

import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "experiments.py"
spec = importlib.util.spec_from_file_location("faradix_experiments", SCRIPT)
experiments = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = experiments
spec.loader.exec_module(experiments)


def sample(sequence: int, run_id: str = "engine-1", simulation_time_s: float | None = None) -> dict:
    return {
        "record_version": "1", "record_type": "sample", "run_id": run_id,
        "sample_sequence": sequence,
        "simulation_time_s": float(sequence) if simulation_time_s is None else simulation_time_s,
        "measured_at": f"2026-10-31T00:00:{sequence:02d}.000001Z",
        "source": "simulated", "provenance": "development_simulation",
        "measurements": {
            "stack_voltage_v": 24.0 + sequence,
            "stack_current_a": 3.0 + sequence,
            "electrolyte_temperature_c": 25.0 + sequence,
        },
    }


def completion(count: int, last_sequence: int, run_id: str = "engine-1") -> dict:
    return {
        "record_version": "1", "record_type": "completion", "run_id": run_id,
        "sample_count": count, "last_sample_sequence": last_sequence,
        "status": "cleanly_stopped",
    }


def write_lines(path: Path, records: list[dict | str]) -> None:
    path.write_text("".join((record if isinstance(record, str) else json.dumps(record)) + "\n"
                            for record in records), encoding="utf-8")


class ExperimentTests(unittest.TestCase):
    def test_complete_recording_is_associated_with_runner_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "metadata.json").write_text(json.dumps({
                "metadata_version": "2", "run_id": "runner-1", "engine_run_id": "engine-1",
                "profile": {"path": "profiles/simulation/default.json", "sha256": "abc"},
                "engine": {"path": "engine/build/faradix_engine", "sha256": "def"},
                "effective_parameters": {"baseline_drive": 0.5, "dt_s": 1.0, "period_ms": 1000},
                "outcome": {"state": "cleanly_stopped"},
            }), encoding="utf-8")
            write_lines(run_dir / "samples.jsonl", [sample(1), sample(2), completion(2, 2)])
            result = experiments.inspect_recording(run_dir, expected_run_id="engine-1")
            self.assertEqual(result["integrity"], "complete")
            self.assertEqual(result["sample_count"], 2)
            self.assertEqual(result["valid_prefix_samples"], 2)
            self.assertEqual((result["first_simulation_time_s"], result["last_simulation_time_s"]), (1.0, 2.0))
            self.assertEqual(result["sequence_gaps"], [])
            self.assertEqual(result["metadata"]["run_id"], "runner-1")
            self.assertEqual(result["issues"], [])

    def test_missing_recording_from_old_metadata_is_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "metadata.json").write_text('{"metadata_version":"1","run_id":"runner-1"}\n')
            result = experiments.inspect_recording(run_dir)
            self.assertEqual(result["integrity"], "unverified")
            self.assertEqual(result["sample_count"], 0)
            self.assertEqual(result["metadata"]["metadata_version"], "1")
            self.assertIn("missing", " ".join(result["issues"]))

    def test_truncated_final_record_keeps_valid_prefix_and_requires_explicit_export(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            path = run_dir / "samples.jsonl"
            write_lines(path, [sample(1), sample(2), '{"record_version":"1","record_type":"completion"'])
            result = experiments.inspect_recording(run_dir)
            self.assertEqual(result["integrity"], "incomplete")
            self.assertEqual(result["sample_count"], 2)
            self.assertIn("line 3", " ".join(result["issues"]))
            output = run_dir / "export.csv"
            with self.assertRaisesRegex(experiments.ExperimentError, "--allow-incomplete"):
                experiments.export_csv(run_dir, output)
            self.assertFalse(output.exists())
            exported = experiments.export_csv(run_dir, output, allow_incomplete=True)
            self.assertEqual(exported["integrity"], "incomplete")
            with output.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["sample_sequence"], "1")
            self.assertEqual(rows[1]["stack_voltage_v"], "26.0")
            self.assertIn("stack_voltage_v", rows[0])
            self.assertIn("measured_at_utc", rows[0])
            with self.assertRaisesRegex(experiments.ExperimentError, "already exists"):
                experiments.export_csv(run_dir, output, allow_incomplete=True)
            self.assertEqual(output.read_text().count("\n"), 3)

    def test_unterminated_final_record_is_incomplete_and_valid_prefix_can_export(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            path = run_dir / "samples.jsonl"
            path.write_text(json.dumps(sample(1)) + "\n" + json.dumps(completion(1, 1)), encoding="utf-8")
            result = experiments.inspect_recording(run_dir)
            self.assertEqual(result["integrity"], "incomplete")
            self.assertEqual(result["sample_count"], 1)
            self.assertIn("unterminated final record", " ".join(result["issues"]))
            output = run_dir / "partial.csv"
            experiments.export_csv(run_dir, output, allow_incomplete=True)
            with output.open(newline="", encoding="utf-8") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1)

    def test_invalid_utf8_final_record_does_not_hide_valid_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.jsonl"
            path.write_bytes((json.dumps(sample(1)) + "\n").encode("utf-8") + b"\xff\n")
            result = experiments.inspect_recording(path)
            self.assertEqual(result["integrity"], "incomplete")
            self.assertEqual(result["sample_count"], 1)
            self.assertIn("line 2", " ".join(result["issues"]))

    def test_gaps_mixed_ids_and_duplicate_or_out_of_order_sequences_are_reported(self):
        cases = [
            ("gap", [sample(1), sample(3), completion(2, 3)], "sequence gaps", 2),
            ("mixed", [sample(1), sample(2, "engine-2"), completion(2, 2)], "mixed run identities", 1),
            ("duplicate", [sample(1), sample(1), completion(2, 1)], "duplicate or out-of-order", 1),
            ("out of order", [sample(2), sample(1), completion(2, 2)], "duplicate or out-of-order", 1),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.jsonl"
            for name, records, issue, count in cases:
                with self.subTest(name=name):
                    write_lines(path, records)
                    result = experiments.inspect_recording(path)
                    self.assertEqual(result["integrity"], "incomplete")
                    self.assertEqual(result["sample_count"], count)
                    self.assertIn(issue, " ".join(result["issues"]))
                    if name == "gap":
                        self.assertEqual(result["sequence_gaps"], [{"after": 1, "before": 3, "missing": 1}])

    def test_nonfinite_measurements_invalid_time_and_footer_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.jsonl"
            invalid = sample(1)
            invalid["measurements"]["stack_current_a"] = float("nan")
            write_lines(path, [invalid, completion(1, 1)])
            self.assertIn("non-finite", " ".join(experiments.inspect_recording(path)["issues"]))
            invalid = sample(1)
            invalid["measured_at"] = "2026-10-31T00:00:00"
            write_lines(path, [invalid, completion(1, 1)])
            self.assertIn("UTC timestamp", " ".join(experiments.inspect_recording(path)["issues"]))
            write_lines(path, [sample(1), completion(2, 1)])
            self.assertIn("sample_count", " ".join(experiments.inspect_recording(path)["issues"]))

    def test_expected_and_metadata_run_identity_mismatches_are_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "metadata.json").write_text('{"engine_run_id":"engine-2"}')
            write_lines(run_dir / "samples.jsonl", [sample(1), completion(1, 1)])
            result = experiments.inspect_recording(run_dir, expected_run_id="engine-3")
            self.assertEqual(result["integrity"], "incomplete")
            self.assertIn("metadata engine_run_id", " ".join(result["issues"]))
            self.assertIn("expected engine run_id", " ".join(result["issues"]))

    def test_cli_works_outside_repository_using_absolute_run_path(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            write_lines(run_dir / "samples.jsonl", [sample(1), completion(1, 1)])
            inspected = subprocess.run([sys.executable, str(SCRIPT), "inspect", str(run_dir)],
                                       cwd=directory, capture_output=True, text=True)
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            self.assertIn("Integrity: complete", inspected.stdout)
            self.assertIn("Completion record: cleanly_stopped", inspected.stdout)
            output = Path(directory) / "export.csv"
            exported = subprocess.run([sys.executable, str(SCRIPT), "export", str(run_dir), str(output)],
                                      cwd=directory, capture_output=True, text=True)
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertIn("recording integrity: complete", exported.stdout)
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
