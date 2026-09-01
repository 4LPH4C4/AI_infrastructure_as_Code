from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from macmini_ai_hub.domain.events import EventEnvelope, EventType


def test_task_event_envelope_serializes_observable_context() -> None:
    event = EventEnvelope(
        event_type=EventType.TASK_STARTED,
        task_id="TASK-1042",
        project="example-project",
        team="example-product",
        agent="example-developer",
        correlation_id=uuid4(),
        payload={"status": "running", "attempt": 1},
    )

    document = event.model_dump(mode="json")

    assert document["schema_version"] == 1
    assert document["event_type"] == "task.started"
    assert document["payload"] == {"status": "running", "attempt": 1}
    assert document["timestamp"].endswith("Z")


@pytest.mark.parametrize(
    "event_type",
    [
        EventType.TASK_CREATED,
        EventType.REVIEW_REQUESTED,
        EventType.QA_STARTED,
        EventType.ARTIFACT_CREATED,
    ],
)
def test_task_scoped_events_require_task_id(event_type: EventType) -> None:
    with pytest.raises(ValidationError, match="requires task_id"):
        EventEnvelope(event_type=event_type)


def test_agent_event_requires_agent() -> None:
    with pytest.raises(ValidationError, match="requires agent"):
        EventEnvelope(event_type=EventType.AGENT_STATUS_CHANGED)


def test_team_event_requires_team() -> None:
    with pytest.raises(ValidationError, match="requires team"):
        EventEnvelope(event_type=EventType.TEAM_IDLE)


def test_project_routing_event_requires_full_routing_context() -> None:
    with pytest.raises(ValidationError, match="project, team"):
        EventEnvelope(event_type=EventType.PROJECT_TASK_ROUTED, task_id="TASK-1042")


def test_event_rejects_naive_timestamp_unknown_fields_and_self_causation() -> None:
    event_id = uuid4()
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(
            {
                "event_id": event_id,
                "event_type": EventType.TASK_CREATED,
                "task_id": "TASK-1042",
                "timestamp": datetime(2026, 1, 1),
                "causation_id": event_id,
                "hidden_reasoning": "not allowed",
            }
        )


@pytest.mark.parametrize(
    "secret_key",
    ["api_key", "access-token", "authorization_header", "client_secret", "slack_bot_token"],
)
def test_event_payload_rejects_nested_secret_fields(secret_key: str) -> None:
    with pytest.raises(ValidationError, match="must not contain secret field"):
        EventEnvelope(
            event_type=EventType.TASK_FAILED,
            task_id="TASK-1042",
            payload={"diagnostic": {secret_key: "do-not-log"}},
        )
