from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from macmini_ai_hub.application.notifications import StoredRouteResultNotifier
from macmini_ai_hub.domain.events import EventEnvelope, EventType
from macmini_ai_hub.domain.tasks import Task, TaskStatus
from macmini_ai_hub.integrations.slack import (
    DeliveryReceiptStore,
    RetryingSlackDelivery,
    SlackDeliveryFailed,
    SlackMessageSender,
    SlackRoute,
    SlackTaskNotifier,
    encode_slack_route_target,
)
from macmini_ai_hub.storage import (
    AsyncSQLiteDeliveryReceipts,
    RunRecord,
    RunStatus,
    SQLiteStore,
)

NOW = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


@dataclass
class CapturingSender:
    messages: list[tuple[str, str, str | None, str]] = field(default_factory=list)

    async def send(
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None,
        client_message_id: str,
    ) -> None:
        self.messages.append((channel, text, thread_ts, client_message_id))


@dataclass
class FailsOnceSender:
    attempts: int = 0
    messages: list[tuple[str, str, str | None, str]] = field(default_factory=list)

    async def send(
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None,
        client_message_id: str,
    ) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("temporary Slack failure")
        self.messages.append((channel, text, thread_ts, client_message_id))


def pending_task(task_id: str) -> Task:
    return Task(
        task_id=task_id,
        source="slack",
        project="example-project",
        team="example-product",
        request=(
            "private prompt password=never-send hidden reasoning and stdout must stay internal"
        ),
        created_at=NOW,
    )


def store_task(store: SQLiteStore, task: Task) -> None:
    store.create_task(
        task,
        EventEnvelope(
            event_type=EventType.TASK_CREATED,
            timestamp=NOW,
            task_id=task.task_id,
            project=task.project,
            team=task.team,
            payload={"status": TaskStatus.PENDING.value},
        ),
    )


def make_notifier(
    store: SQLiteStore,
    sender: SlackMessageSender,
) -> StoredRouteResultNotifier:
    receipts = AsyncSQLiteDeliveryReceipts(store)
    compatible_receipts: DeliveryReceiptStore = receipts
    slack = SlackTaskNotifier(
        RetryingSlackDelivery(
            sender,
            receipts=compatible_receipts,
            max_attempts=1,
            base_delay_seconds=0,
        )
    )
    notifier = StoredRouteResultNotifier(store=store, slack=slack)
    return notifier


def transition_stored_task(
    store: SQLiteStore,
    task: Task,
    status: TaskStatus,
    event_type: EventType,
    *,
    at: datetime,
    payload: dict[str, JsonValue] | None = None,
) -> Task:
    return store.transition_task(
        task.task_id,
        status,
        EventEnvelope(
            event_type=event_type,
            timestamp=at,
            task_id=task.task_id,
            project=task.project,
            team=task.team,
            payload={"status": status.value, **(payload or {})},
        ),
    )


def test_slack_route_delivers_once_across_reopen_without_private_content(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    sender = CapturingSender()
    task = pending_task("TASK-1001")

    with SQLiteStore(database) as store:
        store_task(store, task)
        store.save_task_route(
            task.task_id,
            "slack",
            encode_slack_route_target(SlackRoute(channel="C123456", thread_ts="171.42")),
        )
        queued = transition_stored_task(
            store,
            task,
            TaskStatus.QUEUED,
            EventType.TASK_QUEUED,
            at=NOW + timedelta(seconds=1),
        )
        running = transition_stored_task(
            store,
            queued,
            TaskStatus.RUNNING,
            EventType.TASK_STARTED,
            at=NOW + timedelta(seconds=2),
            payload={"branch": "agent/TASK-1001-readme"},
        )
        store.create_run(
            RunRecord(
                run_id="RUN-1001",
                task_id=task.task_id,
                agent="example-developer",
                runtime="codex",
                created_at=NOW + timedelta(seconds=2),
            )
        )
        store.start_run("RUN-1001", at=NOW + timedelta(seconds=3))
        store.finish_run(
            "RUN-1001",
            RunStatus.SUCCEEDED,
            exit_code=0,
            at=NOW + timedelta(seconds=4),
        )
        completed = transition_stored_task(
            store,
            running,
            TaskStatus.COMPLETED,
            EventType.TASK_COMPLETED,
            at=NOW + timedelta(seconds=5),
            payload={
                "branch": "agent/TASK-1001-readme",
                "changed_files": ["README_TEST.md"],
            },
        )
        notifier = make_notifier(store, sender)
        asyncio.run(notifier.notify_task(completed))
        asyncio.run(notifier.notify_task(completed))

        assert store.is_delivery_delivered("task-update:TASK-1001:completed")

    assert len(sender.messages) == 1
    channel, text, thread_ts, client_message_id = sender.messages[0]
    assert channel == "C123456"
    assert thread_ts == "171.42"
    assert client_message_id
    assert "TASK-1001 completed" in text
    assert "example-project" in text
    assert "example-product" in text
    assert "Changed files:\n- README_TEST.md" in text
    assert "Runtime: codex: succeeded" in text
    assert "Branch: agent/TASK-1001-readme" in text
    assert "Tests:" not in text
    assert "private prompt" not in text
    assert "never-send" not in text
    assert "hidden reasoning" not in text
    assert "stdout" not in text

    restarted_sender = CapturingSender()
    with SQLiteStore(database) as reopened:
        restarted = make_notifier(reopened, restarted_sender)
        asyncio.run(restarted.notify_task(reopened.get_task(task.task_id)))
    assert restarted_sender.messages == []


def test_terminal_notification_is_replayed_once_after_failure_and_deduped_after_reopen(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    sender = FailsOnceSender()
    task = pending_task("TASK-REPLAY-1")

    with SQLiteStore(database) as store:
        store_task(store, task)
        store.save_task_route(task.task_id, "slack", "channel:C123456")
        queued = transition_stored_task(
            store,
            task,
            TaskStatus.QUEUED,
            EventType.TASK_QUEUED,
            at=NOW + timedelta(seconds=1),
        )
        running = transition_stored_task(
            store,
            queued,
            TaskStatus.RUNNING,
            EventType.TASK_STARTED,
            at=NOW + timedelta(seconds=2),
        )
        completed = transition_stored_task(
            store,
            running,
            TaskStatus.COMPLETED,
            EventType.TASK_COMPLETED,
            at=NOW + timedelta(seconds=3),
        )

        with pytest.raises(SlackDeliveryFailed):
            asyncio.run(make_notifier(store, sender).notify_task(completed))
        assert not store.is_delivery_delivered("task-update:TASK-REPLAY-1:completed")

    with SQLiteStore(database) as restarted:
        replayed = make_notifier(restarted, sender)
        assert asyncio.run(replayed.reconcile_pending()) == ()
        assert restarted.is_delivery_delivered("task-update:TASK-REPLAY-1:completed")

    assert sender.attempts == 2
    assert len(sender.messages) == 1

    duplicate_sender = CapturingSender()
    with SQLiteStore(database) as reopened:
        replayed = make_notifier(reopened, duplicate_sender)
        assert asyncio.run(replayed.reconcile_pending()) == ()
    assert duplicate_sender.messages == []


def test_missing_or_non_slack_route_is_a_no_op(tmp_path: Path) -> None:
    sender = CapturingSender()
    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        missing = pending_task("TASK-2001")
        other_source = pending_task("TASK-2002")
        store_task(store, missing)
        store_task(store, other_source)
        store.save_task_route(other_source.task_id, "cli", "terminal:local")
        notifier = make_notifier(store, sender)

        asyncio.run(notifier.notify_task(missing))
        asyncio.run(notifier.notify_task(other_source))

    assert sender.messages == []


def test_raw_slack_channel_target_is_supported(tmp_path: Path) -> None:
    sender = CapturingSender()
    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        task = pending_task("TASK-3001")
        store_task(store, task)
        store.save_task_route(task.task_id, "slack", "C654321")
        notifier = make_notifier(store, sender)

        asyncio.run(notifier.notify_task(task))

    assert sender.messages[0][0] == "C654321"
    assert "TASK-3001 pending" in sender.messages[0][1]


def test_failed_result_uses_only_persisted_runtime_outcome_and_safe_error_code(
    tmp_path: Path,
) -> None:
    sender = CapturingSender()
    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        task = pending_task("TASK-FAILED-1")
        store_task(store, task)
        store.save_task_route(
            task.task_id,
            "slack",
            encode_slack_route_target(SlackRoute(channel="C999", thread_ts="172.1")),
        )
        queued = transition_stored_task(
            store,
            task,
            TaskStatus.QUEUED,
            EventType.TASK_QUEUED,
            at=NOW + timedelta(seconds=1),
        )
        running = transition_stored_task(
            store,
            queued,
            TaskStatus.RUNNING,
            EventType.TASK_STARTED,
            at=NOW + timedelta(seconds=2),
            payload={"branch": "agent/TASK-FAILED-1-timeout"},
        )
        store.create_run(
            RunRecord(
                run_id="RUN-FAILED-1",
                task_id=task.task_id,
                agent="example-developer",
                runtime="codex",
                created_at=NOW + timedelta(seconds=2),
            )
        )
        store.start_run("RUN-FAILED-1", at=NOW + timedelta(seconds=3))
        store.finish_run(
            "RUN-FAILED-1",
            RunStatus.TIMED_OUT,
            exit_code=143,
            error_code="runtime-timed-out",
            at=NOW + timedelta(seconds=4),
        )
        failed = transition_stored_task(
            store,
            running,
            TaskStatus.FAILED,
            EventType.TASK_FAILED,
            at=NOW + timedelta(seconds=5),
            payload={
                "branch": "agent/TASK-FAILED-1-timeout",
                "changed_files": [],
                "reason": "runtime-timed-out",
            },
        )

        asyncio.run(make_notifier(store, sender).notify_task(failed))

    _, text, thread_ts, _ = sender.messages[0]
    assert thread_ts == "172.1"
    assert "Runtime: codex: timed-out" in text
    assert "Error: runtime-timed-out" in text
    assert "Tests:" not in text
    assert "private prompt" not in text
    assert "stdout" not in text
