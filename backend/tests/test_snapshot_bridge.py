import json
import os
from pathlib import Path

import pytest

from app.fixtures import SIMULATED_PUBLISHER_DEVICE_ID
from app.snapshot_bridge import MAX_ATTEMPTS_PER_SAMPLE, SnapshotBridge, parse_snapshot

STAMP_1 = "2026-10-30T12:00:00.123456Z"
STAMP_2 = "2026-10-30T12:00:01.123456Z"


def snapshot(run="run-a", sequence=1, measured_at=STAMP_1):
    return {
        "snapshot_version": "1", "run_id": run, "sample_sequence": sequence,
        "simulation_time_s": float(sequence), "measured_at": measured_at,
        "source": "simulated",
        "measurements": {"stack_voltage_v": 45.0, "stack_current_a": 10.0, "electrolyte_temperature_c": 25.2},
    }


def replace_snapshot(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temporary, path)


def test_unchanged_snapshot_is_not_republished_or_retimestampted(tmp_path: Path) -> None:
    path = tmp_path / "latest.json"
    sent = []
    bridge = SnapshotBridge(path, lambda payload: sent.append(payload) or 204)
    assert bridge.poll_once() == "missing"
    replace_snapshot(path, snapshot())
    assert bridge.poll_once() == "published"
    assert bridge.poll_once() == "unchanged"
    assert bridge.poll_once() == "unchanged"
    assert len(sent) == 1
    assert sent[0]["measured_at"] == STAMP_1
    assert sent[0]["device_id"] == SIMULATED_PUBLISHER_DEVICE_ID


def test_new_run_with_reset_sequence_is_recognized(tmp_path: Path) -> None:
    path = tmp_path / "latest.json"
    sent = []
    bridge = SnapshotBridge(path, lambda payload: sent.append(payload) or 204)
    replace_snapshot(path, snapshot(sequence=4))
    assert bridge.poll_once() == "published"
    replace_snapshot(path, snapshot(run="run-b", sequence=1, measured_at=STAMP_2))
    assert bridge.poll_once() == "published"
    assert bridge.poll_once() == "unchanged"
    assert [item["measured_at"] for item in sent] == [STAMP_1, STAMP_2]
    assert bridge.completed == ("run-b", 1)


def test_malformed_snapshot_and_older_sequence_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "latest.json"
    sent = []
    bridge = SnapshotBridge(path, lambda payload: sent.append(payload) or 204)
    path.write_text("{broken", encoding="utf-8")
    assert bridge.poll_once() == "invalid"
    bad = snapshot()
    bad["measured_at"] = "2026-10-30T12:00:00"
    replace_snapshot(path, bad)
    assert bridge.poll_once() == "invalid"
    bad["measured_at"] = "2026-10-30T15:30:00+03:30"
    replace_snapshot(path, bad)
    assert bridge.poll_once() == "invalid"
    replace_snapshot(path, snapshot(sequence=2))
    assert bridge.poll_once() == "published"
    replace_snapshot(path, snapshot(sequence=1))
    assert bridge.poll_once() == "unchanged"
    assert len(sent) == 1


def test_outage_retries_are_bounded_and_newer_sample_replaces_pending(tmp_path: Path) -> None:
    path = tmp_path / "latest.json"
    sent = []
    responses = iter((None, None, 204, None, None, None))
    bridge = SnapshotBridge(path, lambda payload: sent.append(payload["measured_at"]) or next(responses))
    replace_snapshot(path, snapshot())
    assert bridge.poll_once() == "retry"
    replace_snapshot(path, snapshot(sequence=2, measured_at=STAMP_2))
    assert bridge.poll_once() == "retry"
    assert bridge.poll_once() == "published"
    assert sent == [STAMP_1, STAMP_2, STAMP_2]
    replace_snapshot(path, snapshot(run="run-c", sequence=1, measured_at="2026-10-30T12:00:02Z"))
    for _ in range(MAX_ATTEMPTS_PER_SAMPLE - 1):
        assert bridge.poll_once() == "retry"
    assert bridge.poll_once() == "retry_exhausted"
    assert bridge.poll_once() == "unchanged"
    assert len(sent) == 3 + MAX_ATTEMPTS_PER_SAMPLE


def test_snapshot_contract_rejects_nonfinite_and_claimed_device() -> None:
    invalid = snapshot()
    invalid["measurements"]["stack_voltage_v"] = float("nan")
    with pytest.raises(ValueError):
        parse_snapshot(json.dumps(invalid))
    invalid = snapshot()
    invalid["device_id"] = "demo-unit-003"
    with pytest.raises(ValueError):
        parse_snapshot(json.dumps(invalid))
