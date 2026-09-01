"""Smallest sufficient Phase 1 workflow: one Developer and one runtime."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from macmini_ai_hub.config.models import ConfigBundle
from macmini_ai_hub.domain.events import EventEnvelope, EventLevel, EventType
from macmini_ai_hub.domain.tasks import Task, TaskId, TaskStatus
from macmini_ai_hub.orchestrator.ports import (
    OrchestrationStore,
    ProjectExecutionPort,
    ProjectPreparationBlocked,
    ProjectPreparationError,
    ResultNotifier,
    RunOutcome,
)
from macmini_ai_hub.orchestrator.selection import DeveloperSelectionError, select_developer
from macmini_ai_hub.runtime.base import RuntimeAdapter, RuntimeRequest, RuntimeResult, RuntimeStatus

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TaskProcessResult:
    task_id: TaskId
    status: TaskStatus
    error_code: str | None = None


class SingleDeveloperOrchestrator:
    """Poll durable queued work and execute only the approved one-Developer flow."""

    def __init__(
        self,
        *,
        bundle: ConfigBundle,
        store: OrchestrationStore,
        projects: ProjectExecutionPort,
        runtime: RuntimeAdapter,
        notifier: ResultNotifier | None = None,
        max_concurrent_tasks: int = 2,
        poll_interval_seconds: float = 1.0,
        runtime_timeout_seconds: int = 3_600,
    ) -> None:
        if not 1 <= max_concurrent_tasks <= 16:
            raise ValueError("max_concurrent_tasks must be between 1 and 16")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if not 1 <= runtime_timeout_seconds <= 86_400:
            raise ValueError("runtime_timeout_seconds must be between 1 and 86400")
        self._bundle = bundle
        self._store = store
        self._projects = projects
        self._runtime = runtime
        self._notifier = notifier
        self._max_concurrent_tasks = max_concurrent_tasks
        self._poll_interval_seconds = poll_interval_seconds
        self._runtime_timeout_seconds = runtime_timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self._wake = asyncio.Event()

    async def enqueue_task(self, task_id: TaskId) -> None:
        del task_id
        self._wake.set()

    async def run_once(self) -> tuple[TaskProcessResult, ...]:
        tasks = await self._store.list_queued_tasks(limit=self._max_concurrent_tasks)
        if not tasks:
            return ()
        return tuple(await asyncio.gather(*(self.process_task(task.task_id) for task in tasks)))

    async def run_forever(self, stop: asyncio.Event) -> None:
        await self._store.reconcile_interrupted()
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception:
                _LOGGER.exception("orchestrator polling iteration failed")
            self._wake.clear()
            wake_task = asyncio.create_task(self._wake.wait())
            stop_task = asyncio.create_task(stop.wait())
            done, pending = await asyncio.wait(
                {wake_task, stop_task},
                timeout=self._poll_interval_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            del done
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def process_task(self, task_id: TaskId) -> TaskProcessResult:
        async with self._semaphore:
            task = await self._store.get_task(task_id)
            if task.status is not TaskStatus.QUEUED:
                return TaskProcessResult(task_id=task.task_id, status=task.status)

            task = await self._transition(task, TaskStatus.PLANNING)
            try:
                developer = select_developer(self._bundle, task)
            except DeveloperSelectionError:
                return await self._fail(task, "developer-selection")

            assignment = self._event(
                task,
                EventType.AGENT_ASSIGNED,
                agent=developer.agent_id,
                payload={
                    "status": task.status.value,
                    "role": "developer",
                    "runtime": developer.definition.runtime.value,
                },
            )
            task = await self._store.assign_task(task.task_id, developer.agent_id, assignment)

            run_id: str | None = None
            run_finished = False
            try:
                async with self._projects.open_task_workspace(
                    project_id=task.project,
                    task_id=task.task_id,
                    description=task.request,
                ) as prepared:
                    task = await self._transition(
                        task,
                        TaskStatus.RUNNING,
                        agent=developer.agent_id,
                        payload={"branch": prepared.branch},
                    )
                    await self._notify(task)
                    run_id = await self._store.create_run(
                        task_id=task.task_id,
                        agent_id=developer.agent_id,
                        runtime=self._runtime.name,
                    )
                    await self._store.start_run(run_id)
                    result = await self._execute_runtime(task, developer.agent_id, prepared.path)
                    await self._finish_run(run_id, result)
                    run_finished = True
                    current = await self._store.get_task(task.task_id)
                    if current.status is TaskStatus.CANCELLED:
                        await self._notify(current)
                        return TaskProcessResult(task_id=current.task_id, status=current.status)
                    final = await self._finish_task(current, result, prepared.branch)
            except ProjectPreparationBlocked:
                return await self._block(task, "project-preparation")
            except ProjectPreparationError:
                return await self._fail(task, "project-preparation")
            except Exception:
                _LOGGER.exception("task execution failed", extra={"task_id": task.task_id})
                if run_id is not None and not run_finished:
                    try:
                        await self._store.finish_run(
                            run_id,
                            RunOutcome.FAILED,
                            exit_code=None,
                            error_code="runtime-exception",
                        )
                    except Exception:
                        _LOGGER.exception(
                            "failed to close interrupted run",
                            extra={"task_id": task.task_id},
                        )
                current = await self._store.get_task(task.task_id)
                if current.status.is_terminal:
                    return TaskProcessResult(task_id=current.task_id, status=current.status)
                return await self._fail(current, "runtime-exception")

            await self._notify(final)
            return TaskProcessResult(task_id=final.task_id, status=final.status)

    async def cancel_task(self, task_id: TaskId) -> Task:
        task = await self._store.get_task(task_id)
        if task.status.is_terminal:
            return task
        if task.status is TaskStatus.RUNNING:
            with suppress(LookupError):
                await self._runtime.cancel(task_id)
        cancelled = await self._store.cancel_task(
            task_id,
            self._event(
                task,
                EventType.TASK_CANCELLED,
                level=EventLevel.WARNING,
                payload={"status": TaskStatus.CANCELLED.value, "reason": "user-request"},
            ),
        )
        await self._notify(cancelled)
        return cancelled

    async def _execute_runtime(self, task: Task, agent_id: str, workspace: Path) -> RuntimeResult:
        return await self._runtime.execute(
            RuntimeRequest(
                task_id=task.task_id,
                agent=agent_id,
                project=task.project,
                workspace=workspace,
                prompt=task.request,
                timeout_seconds=self._runtime_timeout_seconds,
            )
        )

    async def _finish_run(self, run_id: str, result: RuntimeResult) -> None:
        outcome = RunOutcome(result.status.value)
        error_code = None if outcome is RunOutcome.SUCCEEDED else f"runtime-{outcome.value}"
        await self._store.finish_run(
            run_id,
            outcome,
            exit_code=result.exit_code,
            error_code=error_code,
        )

    async def _finish_task(self, task: Task, result: RuntimeResult, branch: str) -> Task:
        payload: dict[str, object] = {
            "branch": branch,
            "changed_files": list(result.changed_files),
        }
        if result.status is RuntimeStatus.SUCCEEDED:
            return await self._transition(
                task,
                TaskStatus.COMPLETED,
                payload={**payload, "status": TaskStatus.COMPLETED.value},
            )
        if result.status is RuntimeStatus.CANCELLED:
            return await self._store.cancel_task(
                task.task_id,
                self._event(
                    task,
                    EventType.TASK_CANCELLED,
                    level=EventLevel.WARNING,
                    payload={**payload, "status": TaskStatus.CANCELLED.value},
                ),
            )
        return await self._transition(
            task,
            TaskStatus.FAILED,
            level=EventLevel.ERROR,
            payload={
                **payload,
                "status": TaskStatus.FAILED.value,
                "reason": f"runtime-{result.status.value}",
            },
        )

    async def _transition(
        self,
        task: Task,
        target: TaskStatus,
        *,
        agent: str | None = None,
        level: EventLevel = EventLevel.INFO,
        payload: dict[str, object] | None = None,
    ) -> Task:
        event_types = {
            TaskStatus.PLANNING: EventType.TASK_STARTED,
            TaskStatus.RUNNING: EventType.TASK_STARTED,
            TaskStatus.BLOCKED: EventType.TASK_BLOCKED,
            TaskStatus.COMPLETED: EventType.TASK_COMPLETED,
            TaskStatus.FAILED: EventType.TASK_FAILED,
            TaskStatus.CANCELLED: EventType.TASK_CANCELLED,
        }
        event_payload = {"status": target.value, **(payload or {})}
        event = self._event(
            task,
            event_types[target],
            agent=agent,
            level=level,
            payload=event_payload,
        )
        return await self._store.transition_task(task.task_id, target, event)

    async def _block(self, task: Task, error_code: str) -> TaskProcessResult:
        current = await self._store.get_task(task.task_id)
        blocked = await self._transition(
            current,
            TaskStatus.BLOCKED,
            level=EventLevel.WARNING,
            payload={"reason": error_code},
        )
        await self._notify(blocked)
        return TaskProcessResult(blocked.task_id, blocked.status, error_code)

    async def _fail(self, task: Task, error_code: str) -> TaskProcessResult:
        current = await self._store.get_task(task.task_id)
        failed = await self._transition(
            current,
            TaskStatus.FAILED,
            level=EventLevel.ERROR,
            payload={"reason": error_code},
        )
        await self._notify(failed)
        return TaskProcessResult(failed.task_id, failed.status, error_code)

    def _event(
        self,
        task: Task,
        event_type: EventType,
        *,
        agent: str | None = None,
        level: EventLevel = EventLevel.INFO,
        payload: dict[str, object] | None = None,
    ) -> EventEnvelope:
        return EventEnvelope.model_validate(
            {
                "event_type": event_type,
                "task_id": task.task_id,
                "project": task.project,
                "team": task.team,
                "agent": agent,
                "correlation_id": _task_correlation_id(task.task_id),
                "level": level,
                "payload": payload or {},
            }
        )

    async def _notify(self, task: Task) -> None:
        if self._notifier is None:
            return
        try:
            await self._notifier.notify_task(task)
        except Exception:
            _LOGGER.exception(
                "task notification failed without changing task outcome",
                extra={"task_id": task.task_id},
            )


def _task_correlation_id(task_id: TaskId) -> UUID:
    return uuid5(NAMESPACE_URL, f"macmini-ai-hub:{task_id}")
