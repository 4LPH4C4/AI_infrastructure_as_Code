"""Adapters that wire stable application ports to Phase 1 implementations."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from macmini_ai_hub.config.models import ConfigBundle
from macmini_ai_hub.domain.events import EventEnvelope, EventType
from macmini_ai_hub.domain.tasks import Task, TaskId, TaskStatus
from macmini_ai_hub.gateway.models import CancelTaskCommand, CreateTaskCommand, TaskView
from macmini_ai_hub.gateway.ports import (
    DependencyUnavailableError,
    TaskConflictError,
    TaskNotFoundError,
)
from macmini_ai_hub.locks import LockTimeoutError, ProjectFileLock
from macmini_ai_hub.orchestrator.ports import (
    PreparedWorkspace,
    ProjectPreparationBlocked,
    ProjectPreparationError,
)
from macmini_ai_hub.projects import (
    BranchCollisionError,
    DirtyWorkingTreeError,
    ProjectNotFoundError,
    ProjectWorkspaceError,
    ProjectWorkspaceManager,
)
from macmini_ai_hub.storage import (
    DataIntegrityError,
    DuplicateTaskError,
    RecordNotFoundError,
    SQLiteStore,
    StorageError,
    TaskRoute,
)


class TaskCanceller(Protocol):
    async def cancel_task(self, task_id: TaskId) -> Task: ...


class TaskWakeup(Protocol):
    async def enqueue_task(self, task_id: TaskId) -> None: ...


class GatewayTaskAdapter:
    """Create/query/cancel durable tasks while translating safe port errors."""

    def __init__(
        self,
        *,
        store: SQLiteStore,
        bundle: ConfigBundle,
        canceller: TaskCanceller,
    ) -> None:
        self._store = store
        self._bundle = bundle
        self._canceller = canceller

    async def create_task(self, command: CreateTaskCommand) -> TaskView:
        project = self._bundle.projects.projects.get(command.project)
        if project is None:
            raise TaskNotFoundError("project is not registered")
        task = Task(
            task_id=command.task_id,
            source=command.source,
            project=command.project,
            team=project.team,
            request=command.instruction,
        )
        correlation_id = _correlation_id(task.task_id)
        created_event = EventEnvelope(
            event_type=EventType.TASK_CREATED,
            task_id=task.task_id,
            project=task.project,
            team=task.team,
            correlation_id=correlation_id,
            payload={"status": TaskStatus.PENDING.value},
        )
        queued_event = EventEnvelope(
            event_type=EventType.TASK_QUEUED,
            task_id=task.task_id,
            project=task.project,
            team=task.team,
            correlation_id=correlation_id,
            causation_id=created_event.event_id,
            payload={"status": TaskStatus.QUEUED.value},
        )
        route = (
            TaskRoute(
                task_id=task.task_id,
                source=command.source,
                target=command.reply_target,
            )
            if command.reply_target is not None
            else None
        )
        try:
            created = await asyncio.to_thread(
                self._store.create_queued_task,
                task,
                created_event,
                queued_event,
                route=route,
            )
        except DuplicateTaskError as error:
            existing = await asyncio.to_thread(self._store.get_task, task.task_id)
            existing_route = await asyncio.to_thread(self._store.get_task_route, task.task_id)
            if not _matches_replayed_task(existing, task) or existing_route != route:
                raise TaskConflictError("task already exists with different content") from error
            created = existing
        except StorageError as error:
            raise DependencyUnavailableError("task store is unavailable") from error
        return _task_view(created)

    async def cancel_task(self, command: CancelTaskCommand) -> TaskView:
        try:
            task = await self._canceller.cancel_task(command.task_id)
        except RecordNotFoundError as error:
            raise TaskNotFoundError("task not found") from error
        except (DataIntegrityError, ValueError) as error:
            raise TaskConflictError("task cannot be cancelled") from error
        except StorageError as error:
            raise DependencyUnavailableError("task store is unavailable") from error
        return _task_view(task)

    async def get_task(self, task_id: TaskId) -> TaskView | None:
        try:
            task = await asyncio.to_thread(self._store.get_task, task_id)
        except RecordNotFoundError:
            return None
        except StorageError as error:
            raise DependencyUnavailableError("task store is unavailable") from error
        return _task_view(task)

    async def list_tasks(self, *, limit: int) -> tuple[TaskView, ...]:
        try:
            tasks = await asyncio.to_thread(self._store.list_tasks, limit=limit)
        except StorageError as error:
            raise DependencyUnavailableError("task store is unavailable") from error
        return tuple(_task_view(task) for task in tasks)


class DurableTaskEnqueuer:
    """Atomically transition pending work to queued, then wake the polling worker."""

    def __init__(self, *, store: SQLiteStore, wakeup: TaskWakeup) -> None:
        self._store = store
        self._wakeup = wakeup

    async def enqueue_task(self, task_id: TaskId) -> TaskView:
        try:
            task = await asyncio.to_thread(self._store.get_task, task_id)
            if task.status is TaskStatus.PENDING:
                event = EventEnvelope(
                    event_type=EventType.TASK_QUEUED,
                    task_id=task.task_id,
                    project=task.project,
                    team=task.team,
                    correlation_id=_correlation_id(task.task_id),
                    payload={"status": TaskStatus.QUEUED.value},
                )
                task = await asyncio.to_thread(
                    self._store.transition_task,
                    task.task_id,
                    TaskStatus.QUEUED,
                    event,
                )
            if task.status is TaskStatus.QUEUED:
                await self._wakeup.enqueue_task(task.task_id)
        except RecordNotFoundError as error:
            raise TaskNotFoundError("task not found") from error
        except (DataIntegrityError, ValueError) as error:
            raise TaskConflictError("task cannot be queued") from error
        except StorageError as error:
            raise DependencyUnavailableError("task store is unavailable") from error
        return _task_view(task)


class ProjectExecutionAdapter:
    """Hold a per-project lock across branch preparation and runtime execution."""

    def __init__(
        self,
        *,
        manager: ProjectWorkspaceManager,
        lock_root: Path,
        lock_wait_seconds: float = 1.0,
    ) -> None:
        self._manager = manager
        self._lock_root = lock_root
        self._lock_wait_seconds = lock_wait_seconds

    @asynccontextmanager
    async def open_task_workspace(
        self,
        *,
        project_id: str,
        task_id: TaskId,
        description: str,
    ) -> AsyncIterator[PreparedWorkspace]:
        lock = ProjectFileLock(
            self._lock_root,
            project_id,
            task_id,
            wait_timeout=self._lock_wait_seconds,
        )
        acquired = False
        try:
            try:
                await asyncio.to_thread(lock.acquire)
                acquired = True
            except LockTimeoutError as error:
                raise ProjectPreparationBlocked("project is locked by another task") from error
            try:
                branch = await asyncio.to_thread(
                    self._manager.create_task_branch,
                    project_id,
                    task_id,
                    description,
                )
            except (BranchCollisionError, DirtyWorkingTreeError) as error:
                raise ProjectPreparationBlocked("project requires operator review") from error
            except (ProjectNotFoundError, ProjectWorkspaceError) as error:
                raise ProjectPreparationError("project workspace preparation failed") from error
            yield PreparedWorkspace(path=branch.workspace, branch=branch.branch)
        finally:
            if acquired:
                await asyncio.to_thread(lock.release)


class StorageReadinessProbe:
    name = "storage"

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    async def check(self) -> bool:
        try:
            return await asyncio.to_thread(lambda: self._store.schema_version > 0)
        except StorageError:
            return False


class WorkspaceReadinessProbe:
    name = "workspace"

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    async def check(self) -> bool:
        return await asyncio.to_thread(
            lambda: self._workspace.is_dir() and os.access(self._workspace, os.R_OK | os.W_OK)
        )


class RuntimeReadinessProbe:
    name = "runtime"

    def __init__(self, executable: str) -> None:
        self._executable = executable

    async def check(self) -> bool:
        return await asyncio.to_thread(self._is_available)

    def _is_available(self) -> bool:
        candidate = Path(self._executable)
        if candidate.is_absolute():
            return candidate.is_file() and os.access(candidate, os.X_OK)
        return shutil.which(self._executable) is not None


def _task_view(task: Task) -> TaskView:
    return TaskView(
        task_id=task.task_id,
        project=task.project,
        team=task.team,
        status=task.status,
        assigned_agents=task.assigned_agents,
    )


def _matches_replayed_task(existing: Task, expected: Task) -> bool:
    return (
        existing.task_id == expected.task_id
        and existing.source == expected.source
        and existing.project == expected.project
        and existing.team == expected.team
        and existing.request == expected.request
    )


def _correlation_id(task_id: TaskId) -> UUID:
    return uuid5(NAMESPACE_URL, f"macmini-ai-hub:{task_id}")
