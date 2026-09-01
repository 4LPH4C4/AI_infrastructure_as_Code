"""Idempotent task projection rebuilt exclusively from observable events."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from macmini_ai_hub.config.models import Identifier
from macmini_ai_hub.domain.events import EventEnvelope, EventType
from macmini_ai_hub.domain.tasks import TaskId, TaskStatus, can_transition

_FIXED_STATUS_EVENTS: dict[EventType, TaskStatus] = {
    EventType.TASK_CREATED: TaskStatus.PENDING,
    EventType.TASK_QUEUED: TaskStatus.QUEUED,
    EventType.TASK_BLOCKED: TaskStatus.BLOCKED,
    EventType.TASK_COMPLETED: TaskStatus.COMPLETED,
    EventType.TASK_FAILED: TaskStatus.FAILED,
    EventType.TASK_CANCELLED: TaskStatus.CANCELLED,
    EventType.REVIEW_STARTED: TaskStatus.REVIEW,
    EventType.QA_STARTED: TaskStatus.QA,
}


class ProjectionError(ValueError):
    """An event stream cannot produce a truthful task projection."""


class TaskProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: TaskId
    project: Identifier
    team: Identifier
    status: TaskStatus
    assigned_agents: tuple[Identifier, ...] = ()
    created_at: AwareDatetime
    updated_at: AwareDatetime
    last_event_id: UUID
    last_event_type: EventType
    event_count: int = Field(ge=1)

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal


class TaskProjector:
    """Stateful idempotent consumer; construct a new instance for each replay."""

    def __init__(self) -> None:
        self._projection: TaskProjection | None = None
        self._seen_events: dict[UUID, EventEnvelope] = {}

    @property
    def projection(self) -> TaskProjection | None:
        return self._projection

    def consume(self, event: EventEnvelope) -> TaskProjection:
        previous = self._seen_events.get(event.event_id)
        if previous is not None:
            if previous != event:
                raise ProjectionError("event_id was reused with different content")
            if self._projection is None:
                raise ProjectionError("duplicate event encountered before task creation")
            return self._projection

        if self._projection is None:
            projection = self._create(event)
        else:
            projection = self._apply(self._projection, event)
        self._seen_events[event.event_id] = event
        self._projection = projection
        return projection

    @staticmethod
    def _create(event: EventEnvelope) -> TaskProjection:
        if event.event_type is not EventType.TASK_CREATED:
            raise ProjectionError("task projection must begin with task.created")
        if event.task_id is None or event.project is None or event.team is None:
            raise ProjectionError("task.created requires task_id, project, and team")
        if event.payload.get("status") != TaskStatus.PENDING.value:
            raise ProjectionError("task.created payload.status must be 'pending'")
        return TaskProjection(
            task_id=event.task_id,
            project=event.project,
            team=event.team,
            status=TaskStatus.PENDING,
            created_at=event.timestamp,
            updated_at=event.timestamp,
            last_event_id=event.event_id,
            last_event_type=event.event_type,
            event_count=1,
        )

    @staticmethod
    def _apply(projection: TaskProjection, event: EventEnvelope) -> TaskProjection:
        if event.task_id != projection.task_id:
            raise ProjectionError("event belongs to a different task")
        if event.project is not None and event.project != projection.project:
            raise ProjectionError("event project changed within a task stream")
        if event.team is not None and event.team != projection.team:
            raise ProjectionError("event team changed within a task stream")
        if event.timestamp < projection.updated_at:
            raise ProjectionError("event timestamp moved backwards")
        if event.event_type is EventType.TASK_CREATED:
            raise ProjectionError("task.created may appear only once")

        status = TaskProjector._status_for(event)
        if status is not None and not can_transition(projection.status, status):
            raise ProjectionError(
                f"illegal projected transition: {projection.status.value} -> {status.value}"
            )

        assigned_agents = projection.assigned_agents
        if event.event_type is EventType.AGENT_ASSIGNED:
            if event.agent is None:
                raise ProjectionError("agent.assigned requires agent")
            if event.agent not in assigned_agents:
                assigned_agents = (*assigned_agents, event.agent)

        return TaskProjection(
            **{
                **projection.model_dump(),
                "status": status or projection.status,
                "assigned_agents": assigned_agents,
                "updated_at": event.timestamp,
                "last_event_id": event.event_id,
                "last_event_type": event.event_type,
                "event_count": projection.event_count + 1,
            }
        )

    @staticmethod
    def _status_for(event: EventEnvelope) -> TaskStatus | None:
        if event.event_type is EventType.TASK_STARTED:
            raw_status = event.payload.get("status")
            if raw_status not in {TaskStatus.PLANNING.value, TaskStatus.RUNNING.value}:
                raise ProjectionError("task.started status must be 'planning' or 'running'")
            return TaskStatus(str(raw_status))
        status = _FIXED_STATUS_EVENTS.get(event.event_type)
        if status is not None and event.payload.get("status") != status.value:
            raise ProjectionError(
                f"{event.event_type.value} payload.status must be {status.value!r}"
            )
        return status


def replay_task(events: Iterable[EventEnvelope]) -> TaskProjection:
    projector = TaskProjector()
    for event in events:
        projector.consume(event)
    if projector.projection is None:
        raise ProjectionError("cannot replay an empty event stream")
    return projector.projection
