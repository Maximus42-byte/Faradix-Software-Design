#!/usr/bin/env python3
"""Inspect and export local, uncalibrated development-simulation recordings."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

RECORDING_NAME = "samples.jsonl"
MEASUREMENT_KEYS = {
    "stack_voltage_v", "stack_current_a", "electrolyte_temperature_c"
}
SAMPLE_KEYS = {
    "record_version", "record_type", "run_id", "sample_sequence",
    "simulation_time_s", "measured_at", "source", "provenance", "measurements"
}
COMPLETION_KEYS = {
    "record_version", "record_type", "run_id", "sample_count",
    "last_sample_sequence", "status"
}
CSV_COLUMNS = [
    "run_id", "sample_sequence", "simulation_time_s", "measured_at_utc",
    "stack_voltage_v", "stack_current_a", "electrolyte_temperature_c",
    "source", "provenance"
]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
UTC_TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$")


class ExperimentError(Exception):
    """An invalid path, recording, or export request."""


def recording_path(path: Path) -> Path:
    """Resolve a run directory to its recording; leave explicit paths unchanged."""
    return path / RECORDING_NAME if path.is_dir() else path


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate field '{key}'")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _parse_json(raw: str) -> Any:
    return json.loads(raw, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)


def _finite_number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _validate_run_id(value: Any) -> str:
    if not isinstance(value, str) or not RUN_ID_PATTERN.fullmatch(value):
        raise ValueError("run_id must be 1 to 128 ASCII letters, digits, underscores, or hyphens")
    return value


def _validate_record(record: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(record, dict):
        raise ValueError("record must be a JSON object")
    kind = record.get("record_type")
    if kind == "sample":
        expected = SAMPLE_KEYS
    elif kind == "completion":
        expected = COMPLETION_KEYS
    else:
        raise ValueError("record_type must be 'sample' or 'completion'")
    if set(record) != expected:
        missing = sorted(expected - set(record))
        unknown = sorted(set(record) - expected)
        raise ValueError(f"{kind} fields mismatch (missing: {missing}; unknown: {unknown})")
    if record["record_version"] != "1":
        raise ValueError("unsupported record_version; expected '1'")
    _validate_run_id(record["run_id"])
    if kind == "sample":
        if not _positive_int(record["sample_sequence"]):
            raise ValueError("sample_sequence must be a positive integer")
        if not _finite_number(record["simulation_time_s"]) or record["simulation_time_s"] < 0:
            raise ValueError("simulation_time_s must be a finite nonnegative number")
        stamp = record["measured_at"]
        if not isinstance(stamp, str) or not UTC_TIME_PATTERN.fullmatch(stamp):
            raise ValueError("measured_at must be an ISO 8601 UTC timestamp")
        try:
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("measured_at is not a valid UTC timestamp") from error
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("measured_at must use UTC")
        if record["source"] != "simulated" or record["provenance"] != "development_simulation":
            raise ValueError("sample must identify simulated development provenance")
        measurements = record["measurements"]
        if not isinstance(measurements, dict) or set(measurements) != MEASUREMENT_KEYS:
            raise ValueError("measurements must contain exactly voltage, current, and temperature")
        for name in sorted(MEASUREMENT_KEYS):
            if not _finite_number(measurements[name]):
                raise ValueError(f"measurements.{name} must be finite")
    else:
        if not _nonnegative_int(record["sample_count"]):
            raise ValueError("completion sample_count must be a nonnegative integer")
        if not _nonnegative_int(record["last_sample_sequence"]):
            raise ValueError("completion last_sample_sequence must be a nonnegative integer")
        if record["status"] != "cleanly_stopped":
            raise ValueError("completion status must be 'cleanly_stopped'")
    return kind, record


def _read_metadata(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    metadata_path = path.parent / "metadata.json"
    if not metadata_path.exists():
        return None, None
    try:
        metadata = _parse_json(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        return None, f"metadata.json cannot be read or parsed: {error}"
    if not isinstance(metadata, dict):
        return None, "metadata.json must be a JSON object"
    return metadata, None


def _scan(path: Path, expected_run_id: str | None = None,
          collect_samples: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = recording_path(path)
    metadata, metadata_issue = _read_metadata(path)
    result: dict[str, Any] = {
        "path": str(path),
        "integrity": "unverified",
        "sample_count": 0,
        "valid_prefix_samples": 0,
        "first_simulation_time_s": None,
        "last_simulation_time_s": None,
        "sequence_gaps": [],
        "issues": [],
        "run_id": None,
        "completion": None,
        "metadata": metadata,
    }
    samples: list[dict[str, Any]] = []
    if metadata_issue:
        result["issues"].append(metadata_issue)
    if expected_run_id is not None:
        try:
            _validate_run_id(expected_run_id)
        except ValueError as error:
            raise ExperimentError(f"Invalid expected run ID: {error}") from error
    if not path.exists():
        result["issues"].append(f"recording is missing: {path}")
        return result, samples
    if not path.is_file():
        result["issues"].append(f"recording is not a regular file: {path}")
        return result, samples
    result["integrity"] = "incomplete"
    last_sequence = 0
    last_simulation_time: float | int | None = None
    completion: dict[str, Any] | None = None
    try:
        with path.open("rb") as stream:
            for line_number, raw_line in enumerate(stream, 1):
                if len(raw_line) > 65536:
                    result["issues"].append(f"line {line_number}: record exceeds 64 KiB")
                    break
                if not raw_line.endswith(b"\n"):
                    result["issues"].append(f"line {line_number}: unterminated final record")
                    break
                try:
                    kind, record = _validate_record(_parse_json(raw_line.decode("utf-8")))
                except (ValueError, UnicodeError) as error:
                    result["issues"].append(f"line {line_number}: malformed or invalid record: {error}")
                    break
                if completion is not None:
                    result["issues"].append(f"line {line_number}: data follows completion record")
                    break
                run_id = record["run_id"]
                if result["run_id"] is None:
                    result["run_id"] = run_id
                elif run_id != result["run_id"]:
                    result["issues"].append(f"line {line_number}: mixed run identities ({run_id} != {result['run_id']})")
                    break
                if kind == "completion":
                    completion = record
                    result["completion"] = record
                    continue
                sequence = record["sample_sequence"]
                if sequence <= last_sequence:
                    result["issues"].append(f"line {line_number}: duplicate or out-of-order sample_sequence {sequence} after {last_sequence}")
                    break
                if last_simulation_time is not None and record["simulation_time_s"] <= last_simulation_time:
                    result["issues"].append(f"line {line_number}: simulation_time_s is not increasing")
                    break
                if sequence > last_sequence + 1:
                    result["sequence_gaps"].append({
                        "after": last_sequence,
                        "before": sequence,
                        "missing": sequence - last_sequence - 1,
                    })
                last_sequence = sequence
                last_simulation_time = record["simulation_time_s"]
                if result["first_simulation_time_s"] is None:
                    result["first_simulation_time_s"] = last_simulation_time
                result["last_simulation_time_s"] = last_simulation_time
                result["sample_count"] += 1
                result["valid_prefix_samples"] += 1
                if collect_samples:
                    samples.append(record)
    except (OSError, UnicodeError) as error:
        result["issues"].append(f"recording cannot be read fully: {error}")
    if expected_run_id is not None and result["run_id"] is not None and result["run_id"] != expected_run_id:
        result["issues"].append(f"recording run_id {result['run_id']} differs from expected engine run_id {expected_run_id}")
    if metadata is not None:
        metadata_run_id = metadata.get("engine_run_id")
        if metadata_run_id is not None and result["run_id"] is not None and metadata_run_id != result["run_id"]:
            result["issues"].append(f"recording run_id {result['run_id']} differs from metadata engine_run_id {metadata_run_id}")
    if completion is None:
        result["issues"].append("completion record is missing or invalid")
    else:
        if completion["sample_count"] != result["sample_count"]:
            result["issues"].append(f"completion sample_count {completion['sample_count']} differs from {result['sample_count']} valid samples")
        if completion["last_sample_sequence"] != last_sequence:
            result["issues"].append(f"completion last_sample_sequence {completion['last_sample_sequence']} differs from {last_sequence}")
    if result["sequence_gaps"]:
        result["issues"].append(f"sequence gaps: {sum(gap['missing'] for gap in result['sequence_gaps'])} missing sample(s)")
    if not result["issues"]:
        result["integrity"] = "complete"
    return result, samples


def inspect_recording(path: Path, expected_run_id: str | None = None) -> dict[str, Any]:
    """Validate a JSONL recording and return its integrity and valid-prefix summary."""
    return _scan(path, expected_run_id)[0]


def export_csv(source: Path, output: Path, allow_incomplete: bool = False) -> dict[str, Any]:
    """Export only validated prefix samples, never replacing an existing output."""
    summary, samples = _scan(source, collect_samples=True)
    if summary["integrity"] == "unverified":
        raise ExperimentError("Recording is unavailable or unverified; no samples can be exported")
    if summary["integrity"] != "complete" and not allow_incomplete:
        raise ExperimentError("Recording is incomplete; inspect it and pass --allow-incomplete to export its valid prefix")
    if not samples:
        raise ExperimentError("Recording contains no valid sample prefix to export")
    try:
        with output.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for sample in samples:
                writer.writerow({
                    "run_id": sample["run_id"],
                    "sample_sequence": sample["sample_sequence"],
                    "simulation_time_s": sample["simulation_time_s"],
                    "measured_at_utc": sample["measured_at"],
                    "stack_voltage_v": sample["measurements"]["stack_voltage_v"],
                    "stack_current_a": sample["measurements"]["stack_current_a"],
                    "electrolyte_temperature_c": sample["measurements"]["electrolyte_temperature_c"],
                    "source": sample["source"],
                    "provenance": sample["provenance"],
                })
    except FileExistsError as error:
        raise ExperimentError(f"Export already exists and will not be overwritten: {output}") from error
    except OSError as error:
        # A failed new export must not masquerade as a complete CSV.
        output.unlink(missing_ok=True)
        raise ExperimentError(f"Could not write CSV export {output}: {error}") from error
    return summary


def _print_inspection(summary: dict[str, Any]) -> None:
    metadata = summary["metadata"] or {}
    print(f"Recording: {summary['path']}")
    print(f"Integrity: {summary['integrity']}")
    completion = summary["completion"]
    if completion is None:
        print("Completion record: missing or invalid")
    else:
        print(f"Completion record: {completion['status']} "
              f"(sample_count={completion['sample_count']}, "
              f"last_sample_sequence={completion['last_sample_sequence']})")
    print(f"Engine run ID: {summary['run_id'] or 'unknown'}")
    print(f"Valid prefix samples: {summary['valid_prefix_samples']}")
    print(f"Simulation time coverage (s): {summary['first_simulation_time_s']} to {summary['last_simulation_time_s']}")
    print(f"Sequence gaps: {summary['sequence_gaps'] or 'none'}")
    print(f"Runner run ID: {metadata.get('run_id', 'unavailable')}")
    print(f"UTC start: {metadata.get('started_at', 'unavailable')}")
    print(f"Profile: {metadata.get('profile', 'unavailable')}")
    print(f"Effective parameters: {metadata.get('effective_parameters', 'unavailable')}")
    print(f"Engine executable: {metadata.get('engine', 'unavailable')}")
    print(f"Run outcome: {metadata.get('outcome', 'unavailable')}")
    for issue in summary["issues"]:
        print(f"Issue: {issue}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="validate a local recording and show its metadata")
    inspect.add_argument("recording", type=Path, help="run directory or JSONL recording path")
    export = commands.add_parser("export", help="export validated measurement samples as CSV")
    export.add_argument("recording", type=Path, help="run directory or JSONL recording path")
    export.add_argument("output", type=Path, help="new CSV path; existing files are never overwritten")
    export.add_argument("--allow-incomplete", action="store_true", help="explicitly export the valid prefix of an incomplete recording")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            summary = inspect_recording(args.recording)
            _print_inspection(summary)
            return 0 if summary["integrity"] == "complete" else 1
        summary = export_csv(args.recording, args.output, args.allow_incomplete)
        print(f"Exported {summary['sample_count']} valid sample(s) to {args.output} (recording integrity: {summary['integrity']}).")
        return 0
    except ExperimentError as error:
        print(f"[experiments] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
