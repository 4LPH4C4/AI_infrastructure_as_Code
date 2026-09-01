from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macmini_ai_hub.locks import (
    LockMetadata,
    LockOwnershipError,
    LockTimeoutError,
    ProjectFileLock,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_same_project_is_exclusive_and_metadata_is_complete(tmp_path: Path) -> None:
    first = ProjectFileLock(tmp_path, "example", "TASK-1", now=lambda: NOW)
    second = ProjectFileLock(tmp_path, "example", "TASK-2", now=lambda: NOW)

    with first:
        on_disk = json.loads(first.path.read_text(encoding="utf-8"))
        assert on_disk["project"] == "example"
        assert on_disk["task"] == "TASK-1"
        assert on_disk["created_at"].endswith("Z")
        assert on_disk["pid"] == os.getpid()
        assert on_disk["owner_token"]
        with pytest.raises(LockTimeoutError, match="TASK-1"):
            second.acquire()

    assert not first.path.exists()


def test_different_projects_can_lock_concurrently(tmp_path: Path) -> None:
    first = ProjectFileLock(tmp_path, "first", "TASK-1")
    second = ProjectFileLock(tmp_path, "second", "TASK-2")

    with first, second:
        assert first.path.exists()
        assert second.path.exists()


def test_context_manager_releases_after_failure(tmp_path: Path) -> None:
    lock = ProjectFileLock(tmp_path, "example", "TASK-1")

    with pytest.raises(RuntimeError, match="task failed"), lock:
        raise RuntimeError("task failed")

    assert not lock.path.exists()


def test_expired_dead_owner_is_recovered_deterministically(tmp_path: Path) -> None:
    stale = LockMetadata(
        project="example",
        task="TASK-OLD",
        created_at="2026-09-01T10:00:00.000000Z",
        pid=999_999,
        owner_token="old-owner",
    )
    path = tmp_path / "example.lock"
    path.write_text(json.dumps(asdict(stale)), encoding="utf-8")
    lock = ProjectFileLock(
        tmp_path,
        "example",
        "TASK-NEW",
        now=lambda: NOW,
        stale_after=timedelta(minutes=30),
        process_alive=lambda _pid: False,
    )

    with lock:
        assert lock.metadata is not None
        assert lock.metadata.task == "TASK-NEW"
        assert lock.recovered_metadata == stale


def test_old_live_owner_is_not_recovered(tmp_path: Path) -> None:
    existing = LockMetadata(
        project="example",
        task="TASK-LIVE",
        created_at="2026-09-01T10:00:00.000000Z",
        pid=os.getpid(),
        owner_token="live-owner",
    )
    path = tmp_path / "example.lock"
    path.write_text(json.dumps(asdict(existing)), encoding="utf-8")
    lock = ProjectFileLock(
        tmp_path,
        "example",
        "TASK-NEW",
        now=lambda: NOW,
        stale_after=timedelta(minutes=30),
        process_alive=lambda _pid: True,
    )

    inspection = lock.inspect()
    assert not inspection.stale
    with pytest.raises(LockTimeoutError, match="TASK-LIVE"):
        lock.acquire()
    assert path.exists()


def test_malformed_lock_is_never_automatically_removed(tmp_path: Path) -> None:
    path = tmp_path / "example.lock"
    path.write_text("not-json", encoding="utf-8")
    lock = ProjectFileLock(tmp_path, "example", "TASK-NEW")

    inspection = lock.inspect()
    assert inspection.error
    assert not inspection.recoverable
    with pytest.raises(LockTimeoutError, match="unknown"):
        lock.acquire()
    assert path.read_text(encoding="utf-8") == "not-json"


def test_release_refuses_to_remove_replaced_owner(tmp_path: Path) -> None:
    lock = ProjectFileLock(tmp_path, "example", "TASK-1")
    metadata = lock.acquire()
    replacement = LockMetadata(
        project=metadata.project,
        task="TASK-2",
        created_at=metadata.created_at,
        pid=metadata.pid,
        owner_token="replacement-owner",
    )
    lock.path.write_text(json.dumps(asdict(replacement)), encoding="utf-8")

    with pytest.raises(LockOwnershipError, match="another task"):
        lock.release()
    assert lock.path.exists()
