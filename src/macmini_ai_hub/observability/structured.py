"""Versioned JSON records derived from validated domain events."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from macmini_ai_hub.config.models import Identifier
from macmini_ai_hub.domain.events import EventEnvelope, EventLevel, EventType
from macmini_ai_hub.domain.tasks import TaskId
from macmini_ai_hub.observability.redaction import redact_secrets, redact_text

LoggerName = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_.-]+$",
    ),
]


class StructuredRecord(BaseModel):
    """A bounded, secret-redacted operational record suitable for JSONL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    timestamp: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    level: EventLevel
    logger: LoggerName
    message: str
    event_id: UUID | None = None
    event_type: EventType | None = None
    task_id: TaskId | None = None
    project: Identifier | None = None
    team: Identifier | None = None
    agent: Identifier | None = None
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @classmethod
    def from_event(
        cls, event: EventEnvelope, *, logger: str = "macmini_ai_hub.events"
    ) -> StructuredRecord:
        message = event.message or event.event_type.value
        redacted_payload = redact_secrets(event.payload)
        if not isinstance(redacted_payload, dict):
            raise TypeError("event payload redaction must preserve a mapping")
        return cls(
            timestamp=event.timestamp,
            level=event.level,
            logger=logger,
            message=redact_text(message),
            event_id=event.event_id,
            event_type=event.event_type,
            task_id=event.task_id,
            project=event.project,
            team=event.team,
            agent=event.agent,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            details=redacted_payload,
        )

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
