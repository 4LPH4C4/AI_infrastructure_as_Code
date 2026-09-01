from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from macmini_ai_hub.domain.events import EventEnvelope, EventLevel, EventType
from macmini_ai_hub.domain.tasks import Task, TaskStatus
from macmini_ai_hub.observability import (
    REDACTED,
    ProjectionError,
    StructuredRecord,
    TaskProjector,
    redact_secrets,
    redact_text,
    replay_task,
)
from macmini_ai_hub.storage import SQLiteStore

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def task_event(
    event_type: EventType,
    status: TaskStatus,
    *,
    seconds: int,
    agent: str | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        timestamp=NOW + timedelta(seconds=seconds),
        task_id="TASK-1001",
        project="example-project",
        team="example-product",
        agent=agent,
        payload={"status": status.value},
    )


def test_recursive_redaction_handles_keys_and_embedded_credentials() -> None:
    raw: JsonValue = {
        "api_key": "top-secret",
        "nested": [
            {"slack-bot-token": "xoxb-123456789"},
            "Authorization: Bearer abc.def.ghi",
            "password=hunter2",
            "https://user:pass@example.com/path",
        ],
        "token_count": 42,
    }

    redacted = redact_secrets(raw)
    assert isinstance(redacted, dict)
    serialized = json.dumps(redacted)

    assert redacted["api_key"] == REDACTED
    assert redacted["token_count"] == 42
    for secret in ("top-secret", "xoxb-123456789", "abc.def.ghi", "hunter2", "user:pass"):
        assert secret not in serialized


def test_redact_text_covers_common_runtime_output_patterns() -> None:
    message = (
        "OPENAI_API_KEY=sk-abcdefgh12345678 Bearer abc123 xapp-123456-secret "
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 "
        "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ_1234567890\n"
        "-----BEGIN OPENSSH PRIVATE KEY-----\nprivate-material\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )

    redacted = redact_text(message)

    assert "sk-abcdefgh12345678" not in redacted
    assert "abc123" not in redacted
    assert "xapp-123456-secret" not in redacted
    assert "ghp_" not in redacted
    assert "github_pat_" not in redacted
    assert "private-material" not in redacted
    assert redacted.count(REDACTED) >= 6


def test_structured_record_is_versioned_json_and_redacts_event_text() -> None:
    event = EventEnvelope(
        event_type=EventType.TASK_FAILED,
        timestamp=NOW,
        task_id="TASK-1001",
        project="example-project",
        team="example-product",
        level=EventLevel.ERROR,
        message="Runtime failed with Authorization: Bearer abc123",
        payload={"status": "failed", "output": "password=hunter2"},
    )

    record = StructuredRecord.from_event(event)
    document = json.loads(record.to_json())

    assert document["schema_version"] == 1
    assert document["event_id"] == str(event.event_id)
    assert document["event_type"] == "task.failed"
    assert document["details"]["status"] == "failed"
    serialized = record.to_json()
    assert "abc123" not in serialized
    assert "hunter2" not in serialized


def test_replay_builds_terminal_projection_and_deduplicates_events() -> None:
    created = task_event(EventType.TASK_CREATED, TaskStatus.PENDING, seconds=0)
    queued = task_event(EventType.TASK_QUEUED, TaskStatus.QUEUED, seconds=1)
    assigned = task_event(
        EventType.AGENT_ASSIGNED,
        TaskStatus.QUEUED,
        seconds=2,
        agent="example-developer",
    )
    running = task_event(EventType.TASK_STARTED, TaskStatus.RUNNING, seconds=3)
    completed = task_event(EventType.TASK_COMPLETED, TaskStatus.COMPLETED, seconds=4)

    projection = replay_task([created, queued, assigned, assigned, running, completed])

    assert projection.status is TaskStatus.COMPLETED
    assert projection.is_terminal
    assert projection.assigned_agents == ("example-developer",)
    assert projection.event_count == 5
    assert projection.last_event_id == completed.event_id


def test_projector_supports_incremental_idempotent_consumption() -> None:
    projector = TaskProjector()
    created = task_event(EventType.TASK_CREATED, TaskStatus.PENDING, seconds=0)

    first = projector.consume(created)
    second = projector.consume(created)

    assert first == second
    assert projector.projection == first

    conflict = EventEnvelope(
        event_id=created.event_id,
        event_type=EventType.TASK_CREATED,
        timestamp=created.timestamp,
        task_id=created.task_id,
        project=created.project,
        team=created.team,
        payload={"status": "pending", "different": True},
    )
    with pytest.raises(ProjectionError, match="reused with different content"):
        projector.consume(conflict)


def test_projection_rejects_missing_origin_illegal_transition_and_cross_task_event() -> None:
    with pytest.raises(ProjectionError, match="must begin"):
        replay_task([task_event(EventType.TASK_QUEUED, TaskStatus.QUEUED, seconds=1)])

    created = task_event(EventType.TASK_CREATED, TaskStatus.PENDING, seconds=0)
    completed = task_event(EventType.TASK_COMPLETED, TaskStatus.COMPLETED, seconds=1)
    with pytest.raises(ProjectionError, match="illegal projected transition"):
        replay_task([created, completed])

    other = EventEnvelope(
        event_type=EventType.TASK_QUEUED,
        timestamp=NOW + timedelta(seconds=1),
        task_id="TASK-2002",
        project="example-project",
        team="example-product",
        payload={"status": "queued"},
    )
    with pytest.raises(ProjectionError, match="different task"):
        replay_task([created, other])


def test_projection_rejects_backward_event_time_and_empty_replay() -> None:
    created = task_event(EventType.TASK_CREATED, TaskStatus.PENDING, seconds=2)
    queued = task_event(EventType.TASK_QUEUED, TaskStatus.QUEUED, seconds=1)

    with pytest.raises(ProjectionError, match="moved backwards"):
        replay_task([created, queued])
    with pytest.raises(ProjectionError, match="empty"):
        replay_task([])


def test_replay_rebuilds_projection_from_reopened_durable_event_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    task = Task(
        task_id="TASK-1001",
        source="test",
        project="example-project",
        team="example-product",
        request="Replay after restart.",
        created_at=NOW,
    )
    created = task_event(EventType.TASK_CREATED, TaskStatus.PENDING, seconds=0)
    queued = task_event(EventType.TASK_QUEUED, TaskStatus.QUEUED, seconds=1)
    running = task_event(EventType.TASK_STARTED, TaskStatus.RUNNING, seconds=2)

    with SQLiteStore(database) as store:
        store.create_task(task, created)
        store.transition_task(task.task_id, TaskStatus.QUEUED, queued)
        store.transition_task(task.task_id, TaskStatus.RUNNING, running)

    with SQLiteStore(database) as reopened:
        events = tuple(record.envelope for record in reopened.list_events(task_id=task.task_id))

    assert replay_task(events).status is TaskStatus.RUNNING
