"""Application-facing async adapters over the synchronous SQLite core."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import uuid4

from macmini_ai_hub.domain.events import EventEnvelope
from macmini_ai_hub.domain.tasks import Task, TaskId, TaskStatus
from macmini_ai_hub.orchestrator.ports import RunOutcome
from macmini_ai_hub.storage.models import RunRecord, RunStatus
from macmini_ai_hub.storage.sqlite import SQLiteStore


def _default_run_id() -> str:
    return f"RUN-{uuid4().hex.upper()}"


class AsyncSQLiteOrchestrationStore:
    """Non-blocking adapter satisfying the orchestrator's asynchronous storage port."""

    def __init__(
        self,
        store: SQLiteStore,
        *,
        run_id_factory: Callable[[], str] = _default_run_id,
    ) -> None:
        self._store = store
        self._run_id_factory = run_id_factory

    async def get_task(self, task_id: TaskId) -> Task:
        return await asyncio.to_thread(self._store.get_task, task_id)

    async def list_queued_tasks(self, *, limit: int) -> tuple[Task, ...]:
        return await asyncio.to_thread(self._store.list_queued_tasks, limit=limit)

    async def transition_task(
        self,
        task_id: TaskId,
        target: TaskStatus,
        event: EventEnvelope,
    ) -> Task:
        return await asyncio.to_thread(self._store.transition_task, task_id, target, event)

    async def assign_task(
        self,
        task_id: TaskId,
        agent_id: str,
        event: EventEnvelope,
    ) -> Task:
        return await asyncio.to_thread(self._store.assign_task, task_id, agent_id, event)

    async def cancel_task(self, task_id: TaskId, event: EventEnvelope) -> Task:
        return await asyncio.to_thread(self._store.cancel_task, task_id, event)

    async def create_run(self, *, task_id: TaskId, agent_id: str, runtime: str) -> str:
        run = RunRecord(
            run_id=self._run_id_factory(),
            task_id=task_id,
            agent=agent_id,
            runtime=runtime,
        )
        await asyncio.to_thread(self._store.create_run, run)
        return run.run_id

    async def start_run(self, run_id: str) -> None:
        await asyncio.to_thread(self._store.start_run, run_id)

    async def finish_run(
        self,
        run_id: str,
        outcome: RunOutcome,
        *,
        exit_code: int | None,
        error_code: str | None,
    ) -> None:
        await asyncio.to_thread(
            self._store.finish_run,
            run_id,
            RunStatus(outcome.value),
            exit_code=exit_code,
            error_code=error_code,
        )

    async def reconcile_interrupted(self) -> None:
        await asyncio.to_thread(self._store.reconcile_interrupted_running)


class AsyncSQLiteDeliveryReceipts:
    """Durable async receipt adapter for retrying outbound delivery."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    async def is_delivered(self, delivery_id: str) -> bool:
        return await asyncio.to_thread(self._store.is_delivery_delivered, delivery_id)

    async def reserve(self, delivery_id: str) -> bool:
        return await asyncio.to_thread(self._store.reserve_delivery, delivery_id)

    async def mark_delivered(self, delivery_id: str) -> None:
        await asyncio.to_thread(self._store.mark_delivery_delivered, delivery_id)

    async def release(self, delivery_id: str) -> None:
        await asyncio.to_thread(self._store.release_delivery, delivery_id)

    async def reconcile_interrupted(self) -> tuple[str, ...]:
        """Release reservations left in-flight by a previous process."""

        return await asyncio.to_thread(self._store.reconcile_reserved_deliveries)
