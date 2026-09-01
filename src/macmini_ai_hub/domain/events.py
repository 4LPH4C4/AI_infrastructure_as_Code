"""Observable event envelope for logs, dashboards, and future Pixel Office."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from macmini_ai_hub.config.models import Identifier
from macmini_ai_hub.domain.tasks import TaskId

EventMessage = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=2_000),
]


class EventType(StrEnum):
    TASK_CREATED = "task.created"
    TASK_QUEUED = "task.queued"
    TASK_STARTED = "task.started"
    TASK_BLOCKED = "task.blocked"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    TEAM_ACTIVATED = "team.activated"
    TEAM_IDLE = "team.idle"
    AGENT_ASSIGNED = "agent.assigned"
    AGENT_STARTED = "agent.started"
    AGENT_STATUS_CHANGED = "agent.status_changed"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    REVIEW_REQUESTED = "review.requested"
    REVIEW_STARTED = "review.started"
    REVIEW_COMPLETED = "review.completed"
    QA_REQUESTED = "qa.requested"
    QA_STARTED = "qa.started"
    QA_COMPLETED = "qa.completed"
    ARTIFACT_CREATED = "artifact.created"
    ARTIFACT_TRANSFERRED = "artifact.transferred"
    PROJECT_TASK_ROUTED = "project.task.routed"


class EventLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "authorization_header",
        "client_secret",
        "cookie",
        "credentials",
        "github_token",
        "openai_api_key",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "signing_secret",
        "slack_app_token",
        "slack_bot_token",
        "token",
    }
)


def _find_forbidden_payload_key(value: JsonValue, path: str = "payload") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = key.lower().replace("-", "_")
            if normalized_key in _FORBIDDEN_PAYLOAD_KEYS:
                return f"{path}.{key}"
            found = _find_forbidden_payload_key(child, f"{path}.{key}")
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_forbidden_payload_key(child, f"{path}[{index}]")
            if found is not None:
                return found
    return None


class EventEnvelope(BaseModel):
    """Immutable event carrying only observable state, never hidden reasoning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    timestamp: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    task_id: TaskId | None = None
    project: Identifier | None = None
    team: Identifier | None = None
    agent: Identifier | None = None
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    level: EventLevel = EventLevel.INFO
    message: EventMessage | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        category = self.event_type.value.split(".", maxsplit=1)[0]
        if category in {"task", "review", "qa", "artifact"} and self.task_id is None:
            raise ValueError(f"{self.event_type.value} requires task_id")
        if category == "team" and self.team is None:
            raise ValueError(f"{self.event_type.value} requires team")
        if category == "agent" and self.agent is None:
            raise ValueError(f"{self.event_type.value} requires agent")
        if self.event_type is EventType.PROJECT_TASK_ROUTED:
            missing = [
                field
                for field, value in (
                    ("task_id", self.task_id),
                    ("project", self.project),
                    ("team", self.team),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"{self.event_type.value} requires {', '.join(missing)}")
        if self.causation_id == self.event_id:
            raise ValueError("an event must not cause itself")
        forbidden_key = _find_forbidden_payload_key(self.payload)
        if forbidden_key is not None:
            raise ValueError(f"event payload must not contain secret field {forbidden_key!r}")
        return self
