from __future__ import annotations

import asyncio
from pathlib import Path

from macmini_ai_hub.application import DurableTaskEnqueuer, GatewayTaskAdapter
from macmini_ai_hub.config import ConfigBundle, load_config_bundle
from macmini_ai_hub.domain.events import EventEnvelope, EventType
from macmini_ai_hub.domain.tasks import Task, TaskStatus
from macmini_ai_hub.gateway import CancelTaskCommand, CreateTaskCommand
from macmini_ai_hub.storage import SQLiteStore


class Canceller:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    async def cancel_task(self, task_id: str) -> Task:
        task = await asyncio.to_thread(self.store.get_task, task_id)
        event = EventEnvelope(
            event_type=EventType.TASK_CANCELLED,
            task_id=task.task_id,
            project=task.project,
            team=task.team,
            payload={"status": "cancelled"},
        )
        return await asyncio.to_thread(self.store.cancel_task, task_id, event)


class Wakeup:
    def __init__(self) -> None:
        self.task_ids: list[str] = []

    async def enqueue_task(self, task_id: str) -> None:
        self.task_ids.append(task_id)


def bundle() -> ConfigBundle:
    root = Path(__file__).resolve().parents[1]
    return load_config_bundle(root / "config")


def test_gateway_adapters_create_queue_query_and_cancel(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "hub.sqlite3") as store:
        commands = GatewayTaskAdapter(store=store, bundle=bundle(), canceller=Canceller(store))
        wakeup = Wakeup()
        enqueuer = DurableTaskEnqueuer(store=store, wakeup=wakeup)
        create = CreateTaskCommand(
            task_id="TASK-4001",
            source="slack",
            source_event_id="Ev4001",
            actor_id="U4001",
            reply_target="C4001",
            project="example-project",
            instruction="Create README_TEST.md.",
        )

        pending = asyncio.run(commands.create_task(create))
        queued = asyncio.run(enqueuer.enqueue_task(pending.task_id))
        queried = asyncio.run(commands.get_task(pending.task_id))
        cancelled = asyncio.run(
            commands.cancel_task(
                CancelTaskCommand(
                    task_id=pending.task_id,
                    source="slack",
                    source_event_id="Ev4002",
                    actor_id="U4001",
                )
            )
        )

        assert pending.status is TaskStatus.QUEUED
        assert queued.status is TaskStatus.QUEUED
        assert queried is not None and queried.status is TaskStatus.QUEUED
        assert cancelled.status is TaskStatus.CANCELLED
        assert wakeup.task_ids == ["TASK-4001"]
