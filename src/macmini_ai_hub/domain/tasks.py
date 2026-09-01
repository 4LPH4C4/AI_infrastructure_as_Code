"""Task snapshot and explicit lifecycle transition rules."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from macmini_ai_hub.config.models import Identifier

TaskId = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=6,
        max_length=69,
        pattern=r"^TASK-[A-Z0-9][A-Z0-9-]*$",
    ),
]
TaskRequest = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100_000),
]


class TaskStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    REVIEW = "review"
    QA = "qa"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


LEGAL_TASK_TRANSITIONS: Mapping[TaskStatus, frozenset[TaskStatus]] = MappingProxyType(
    {
        TaskStatus.PENDING: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
        TaskStatus.QUEUED: frozenset(
            {TaskStatus.PLANNING, TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}
        ),
        TaskStatus.PLANNING: frozenset(
            {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        ),
        TaskStatus.RUNNING: frozenset(
            {
                TaskStatus.REVIEW,
                TaskStatus.QA,
                TaskStatus.BLOCKED,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }
        ),
        TaskStatus.REVIEW: frozenset(
            {
                TaskStatus.RUNNING,
                TaskStatus.QA,
                TaskStatus.BLOCKED,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }
        ),
        TaskStatus.QA: frozenset(
            {
                TaskStatus.RUNNING,
                TaskStatus.REVIEW,
                TaskStatus.BLOCKED,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }
        ),
        TaskStatus.BLOCKED: frozenset(
            {
                TaskStatus.QUEUED,
                TaskStatus.PLANNING,
                TaskStatus.RUNNING,
                TaskStatus.REVIEW,
                TaskStatus.QA,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }
        ),
        TaskStatus.COMPLETED: frozenset(),
        TaskStatus.FAILED: frozenset(),
        TaskStatus.CANCELLED: frozenset(),
    }
)


class InvalidTaskTransition(ValueError):
    def __init__(self, current: TaskStatus, target: TaskStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"illegal task transition: {current.value} -> {target.value}")


def allowed_transitions(status: TaskStatus) -> frozenset[TaskStatus]:
    return LEGAL_TASK_TRANSITIONS[status]


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in allowed_transitions(current)


class Task(BaseModel):
    """Immutable task-state snapshot; persistence arrives in a later phase."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: TaskId
    source: Identifier
    project: Identifier
    team: Identifier
    request: TaskRequest
    status: TaskStatus = TaskStatus.PENDING
    assigned_agents: tuple[Identifier, ...] = ()
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None

    @field_validator("assigned_agents")
    @classmethod
    def validate_unique_agents(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("assigned_agents must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_timestamps(self) -> Task:
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at must not precede created_at")
        if self.completed_at is not None:
            if self.completed_at < self.created_at:
                raise ValueError("completed_at must not precede created_at")
            if self.started_at is not None and self.completed_at < self.started_at:
                raise ValueError("completed_at must not precede started_at")
        if self.status.is_terminal and self.completed_at is None:
            raise ValueError("terminal tasks require completed_at")
        if not self.status.is_terminal and self.completed_at is not None:
            raise ValueError("non-terminal tasks must not have completed_at")
        return self


def transition_task(
    task: Task,
    target: TaskStatus,
    *,
    at: datetime | None = None,
) -> Task:
    """Return a new task snapshot after enforcing lifecycle and timestamp rules."""

    if not can_transition(task.status, target):
        raise InvalidTaskTransition(task.status, target)
    transition_time = at or datetime.now(UTC)
    if transition_time.tzinfo is None or transition_time.utcoffset() is None:
        raise ValueError("transition time must be timezone-aware")
    if transition_time < task.created_at:
        raise ValueError("transition time must not precede task creation")
    if task.started_at is not None and transition_time < task.started_at:
        raise ValueError("transition time must not precede task start")

    updates: dict[str, object] = {"status": target}
    active_states = {
        TaskStatus.PLANNING,
        TaskStatus.RUNNING,
        TaskStatus.REVIEW,
        TaskStatus.QA,
        TaskStatus.BLOCKED,
    }
    if target in active_states and task.started_at is None:
        updates["started_at"] = transition_time
    if target.is_terminal:
        updates["completed_at"] = transition_time
    return Task.model_validate({**task.model_dump(), **updates})
