"""Safe runtime interface and deliberately disabled Phase 0 implementation."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Protocol, runtime_checkable

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from macmini_ai_hub.config.models import Identifier
from macmini_ai_hub.domain.tasks import TaskId

Prompt = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100_000),
]


class RuntimeStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed-out"
    CANCELLED = "cancelled"


class RuntimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: TaskId
    agent: Identifier
    project: Identifier
    workspace: Path
    prompt: Prompt
    timeout_seconds: Annotated[StrictInt, Field(ge=1, le=86_400)] = 3_600

    @field_validator("workspace")
    @classmethod
    def validate_workspace(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("runtime workspace must be an absolute path")
        return value


class RuntimeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: RuntimeStatus
    started_at: AwareDatetime
    completed_at: AwareDatetime
    exit_code: StrictInt | None = None
    stdout: str = ""
    stderr: str = ""
    changed_files: tuple[str, ...] = ()

    @field_validator("changed_files")
    @classmethod
    def validate_changed_files(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("changed_files must not contain duplicates")
        for file_name in value:
            path = Path(file_name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("changed_files must contain safe relative paths")
        return value

    @model_validator(mode="after")
    def validate_timestamps(self) -> RuntimeResult:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        return self


class RuntimeExecutionDisabled(RuntimeError):
    """Raised when execution is attempted before a runtime is implemented."""


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Boundary all future agent runtimes must implement."""

    @property
    def name(self) -> str: ...

    async def execute(self, request: RuntimeRequest) -> RuntimeResult: ...

    async def cancel(self, task_id: TaskId) -> None: ...


class DisabledRuntime:
    """Phase 0 fail-closed adapter that never starts a subprocess or network call."""

    @property
    def name(self) -> str:
        return "disabled"

    async def execute(self, request: RuntimeRequest) -> RuntimeResult:
        del request
        raise RuntimeExecutionDisabled(
            "runtime execution is disabled in Phase 0; no Codex adapter is installed"
        )

    async def cancel(self, task_id: TaskId) -> None:
        del task_id
        raise RuntimeExecutionDisabled(
            "runtime execution is disabled in Phase 0; there is nothing to cancel"
        )
