"""Source-neutral request and response contracts for the Agent Gateway."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from macmini_ai_hub.config.models import Identifier
from macmini_ai_hub.domain.tasks import TaskId, TaskStatus

OpaqueId = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=255,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]
ReplyTarget = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
SourceEventId = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=135,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
SafeMessage = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4_000),
]
TaskInstruction = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100_000),
]


class GatewayCommand(StrEnum):
    HELP = "help"
    DEV = "dev"
    STATUS = "status"
    TASK = "task"
    TASKS = "tasks"
    STOP = "stop"


class GatewayCode(StrEnum):
    OK = "ok"
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    UNAUTHORIZED = "unauthorized"
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    INTERNAL_ERROR = "internal_error"


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GatewayRequest(StrictFrozenModel):
    """One authenticated-source candidate request before authorization."""

    source: Identifier
    source_event_id: SourceEventId
    actor_id: OpaqueId
    reply_target: ReplyTarget | None = None
    command: GatewayCommand
    project: Identifier | None = None
    task_id: TaskId | None = None
    instruction: TaskInstruction | None = None

    @property
    def idempotency_key(self) -> str:
        return f"{self.source}:{self.source_event_id}"

    @model_validator(mode="after")
    def validate_command_arguments(self) -> Self:
        if self.command is GatewayCommand.DEV:
            if self.project is None or self.instruction is None:
                raise ValueError("dev requires project and instruction")
            if self.task_id is not None:
                raise ValueError("dev must not include task_id")
        elif self.command in {GatewayCommand.TASK, GatewayCommand.STOP}:
            if self.task_id is None:
                raise ValueError(f"{self.command.value} requires task_id")
            if self.project is not None or self.instruction is not None:
                raise ValueError(f"{self.command.value} accepts only task_id")
        elif any(value is not None for value in (self.project, self.task_id, self.instruction)):
            raise ValueError(f"{self.command.value} does not accept task arguments")
        return self


class CreateTaskCommand(StrictFrozenModel):
    task_id: TaskId
    source: Identifier
    source_event_id: SourceEventId
    actor_id: OpaqueId
    reply_target: ReplyTarget | None = None
    project: Identifier
    instruction: TaskInstruction


class CancelTaskCommand(StrictFrozenModel):
    task_id: TaskId
    source: Identifier
    source_event_id: SourceEventId
    actor_id: OpaqueId


class TaskView(StrictFrozenModel):
    """Safe task projection suitable for an interface response."""

    task_id: TaskId
    project: Identifier
    team: Identifier
    status: TaskStatus
    assigned_agents: tuple[Identifier, ...] = ()


class GatewayResponse(StrictFrozenModel):
    success: bool
    code: GatewayCode
    message: SafeMessage
    task: TaskView | None = None
    tasks: tuple[TaskView, ...] = Field(default=(), max_length=100)
    replayed: bool = False
