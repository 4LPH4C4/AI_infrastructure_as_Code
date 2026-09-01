"""Technology-neutral ports used by the Phase 1 orchestrator."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from macmini_ai_hub.domain.events import EventEnvelope
from macmini_ai_hub.domain.tasks import Task, TaskId, TaskStatus


class RunOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed-out"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class PreparedWorkspace:
    path: Path
    branch: str


class ProjectPreparationError(RuntimeError):
    """Base error for safe project preparation."""


class ProjectPreparationBlocked(ProjectPreparationError):
    """Preparation requires operator action and should block the task."""


class OrchestrationStore(Protocol):
    async def get_task(self, task_id: TaskId) -> Task: ...

    async def list_queued_tasks(self, *, limit: int) -> tuple[Task, ...]: ...

    async def transition_task(
        self,
        task_id: TaskId,
        target: TaskStatus,
        event: EventEnvelope,
    ) -> Task: ...

    async def assign_task(
        self,
        task_id: TaskId,
        agent_id: str,
        event: EventEnvelope,
    ) -> Task: ...

    async def cancel_task(self, task_id: TaskId, event: EventEnvelope) -> Task: ...

    async def create_run(self, *, task_id: TaskId, agent_id: str, runtime: str) -> str: ...

    async def start_run(self, run_id: str) -> None: ...

    async def finish_run(
        self,
        run_id: str,
        outcome: RunOutcome,
        *,
        exit_code: int | None,
        error_code: str | None,
    ) -> None: ...

    async def reconcile_interrupted(self) -> None: ...


class ProjectExecutionPort(Protocol):
    def open_task_workspace(
        self,
        *,
        project_id: str,
        task_id: TaskId,
        description: str,
    ) -> AbstractAsyncContextManager[PreparedWorkspace]: ...


class ResultNotifier(Protocol):
    async def notify_task(self, task: Task) -> None: ...
