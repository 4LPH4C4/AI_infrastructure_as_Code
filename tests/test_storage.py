from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from macmini_ai_hub.domain.events import EventEnvelope, EventType
from macmini_ai_hub.domain.tasks import Task, TaskStatus
from macmini_ai_hub.integrations.slack import DeliveryReceiptStore
from macmini_ai_hub.orchestrator.ports import OrchestrationStore, RunOutcome
from macmini_ai_hub.storage import (
    ArtifactMetadata,
    AsyncSQLiteDeliveryReceipts,
    AsyncSQLiteOrchestrationStore,
    DataIntegrityError,
    DeliveryState,
    DuplicateArtifactError,
    DuplicateRunError,
    DuplicateTaskError,
    IdempotencyConflictError,
    MigrationError,
    RecordNotFoundError,
    RunRecord,
    RunStatus,
    SQLiteStore,
    StorageBusyError,
    StorageCorruptionError,
    StorageUnavailableError,
    TaskRoute,
)
from macmini_ai_hub.storage import migrations as migration_module
from macmini_ai_hub.storage.migrations import LATEST_SCHEMA_VERSION, Migration

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def make_task(task_id: str = "TASK-1001", *, created_at: datetime = NOW) -> Task:
    return Task(
        task_id=task_id,
        source="test",
        project="example-project",
        team="example-product",
        request="Persist this task safely.",
        created_at=created_at,
    )


def lifecycle_event(
    task: Task,
    event_type: EventType,
    status: TaskStatus,
    *,
    at: datetime = NOW,
    event_id: UUID | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id or uuid4(),
        event_type=event_type,
        timestamp=at,
        task_id=task.task_id,
        project=task.project,
        team=task.team,
        payload={"status": status.value},
    )


def create_task(store: SQLiteStore, task: Task | None = None) -> Task:
    task = task or make_task()
    store.create_task(
        task,
        lifecycle_event(task, EventType.TASK_CREATED, TaskStatus.PENDING, at=task.created_at),
    )
    return task


def queue_task(store: SQLiteStore, task: Task | None = None) -> Task:
    task = create_task(store, task)
    return store.transition_task(
        task.task_id,
        TaskStatus.QUEUED,
        lifecycle_event(
            task,
            EventType.TASK_QUEUED,
            TaskStatus.QUEUED,
            at=task.created_at + timedelta(seconds=1),
        ),
    )


def test_migrations_enable_required_sqlite_options(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    with SQLiteStore(database, busy_timeout_ms=1_234) as store:
        assert store.schema_version == LATEST_SCHEMA_VERSION
        assert store._connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert store._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store._connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1_234
        versions = store._connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [row[0] for row in versions] == list(range(1, LATEST_SCHEMA_VERSION + 1))


def test_task_event_history_and_queue_survive_reopen(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    first = make_task("TASK-1001", created_at=NOW)
    second = make_task("TASK-1002", created_at=NOW + timedelta(seconds=2))

    with SQLiteStore(database) as store:
        queue_task(store, first)
        queue_task(store, second)
        store.transition_task(
            second.task_id,
            TaskStatus.RUNNING,
            lifecycle_event(
                second,
                EventType.TASK_STARTED,
                TaskStatus.RUNNING,
                at=NOW + timedelta(seconds=4),
            ),
        )

    with SQLiteStore(database) as reopened:
        assert reopened.get_task(first.task_id).status is TaskStatus.QUEUED
        assert [task.task_id for task in reopened.list_queued_tasks()] == [first.task_id]
        assert [task.task_id for task in reopened.list_tasks()] == [second.task_id, first.task_id]
        assert len(reopened.list_events(task_id=second.task_id)) == 3


def test_gateway_task_route_and_queue_are_one_transaction(tmp_path: Path) -> None:
    task = make_task()
    created = lifecycle_event(task, EventType.TASK_CREATED, TaskStatus.PENDING)
    queued = lifecycle_event(
        task,
        EventType.TASK_QUEUED,
        TaskStatus.QUEUED,
        at=NOW + timedelta(seconds=1),
    )
    route = TaskRoute(task_id=task.task_id, source="slack", target="C123456")

    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        stored = store.create_queued_task(task, created, queued, route=route)

        assert stored.status is TaskStatus.QUEUED
        assert store.get_task_route(task.task_id) == route
        assert [item.envelope.event_type for item in store.list_events(task_id=task.task_id)] == [
            EventType.TASK_CREATED,
            EventType.TASK_QUEUED,
        ]


def test_gateway_task_transaction_rolls_back_every_record_on_event_conflict(
    tmp_path: Path,
) -> None:
    task = make_task()
    event_id = uuid4()
    created = lifecycle_event(
        task,
        EventType.TASK_CREATED,
        TaskStatus.PENDING,
        event_id=event_id,
    )
    queued = lifecycle_event(
        task,
        EventType.TASK_QUEUED,
        TaskStatus.QUEUED,
        at=NOW + timedelta(seconds=1),
        event_id=event_id,
    )

    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        with pytest.raises(IdempotencyConflictError):
            store.create_queued_task(task, created, queued)

        with pytest.raises(RecordNotFoundError):
            store.get_task(task.task_id)
        assert store.list_events() == ()
        assert store.list_task_routes() == ()


def test_transition_and_matching_event_are_atomic(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    task = create_task(store)
    conflicting_id = uuid4()
    store.append_event(
        EventEnvelope(
            event_id=conflicting_id,
            event_type=EventType.TEAM_IDLE,
            timestamp=NOW,
            team=task.team,
        )
    )

    with pytest.raises(IdempotencyConflictError):
        store.transition_task(
            task.task_id,
            TaskStatus.QUEUED,
            lifecycle_event(
                task,
                EventType.TASK_QUEUED,
                TaskStatus.QUEUED,
                at=NOW + timedelta(seconds=1),
                event_id=conflicting_id,
            ),
        )

    assert store.get_task(task.task_id).status is TaskStatus.PENDING
    assert len(store.list_events(task_id=task.task_id)) == 1
    store.close()


def test_transition_retry_with_same_event_id_is_idempotent(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        task = create_task(store)
        event = lifecycle_event(
            task,
            EventType.TASK_QUEUED,
            TaskStatus.QUEUED,
            at=NOW + timedelta(seconds=1),
        )

        first = store.transition_task(task.task_id, TaskStatus.QUEUED, event)
        second = store.transition_task(task.task_id, TaskStatus.QUEUED, event)

        assert first == second
        assert len(store.list_events(task_id=task.task_id)) == 2


def test_lifecycle_event_must_match_target_and_task_context(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        task = create_task(store)
        wrong_type = lifecycle_event(
            task,
            EventType.TASK_STARTED,
            TaskStatus.QUEUED,
            at=NOW + timedelta(seconds=1),
        )
        with pytest.raises(DataIntegrityError, match=r"requires event type task.queued"):
            store.transition_task(task.task_id, TaskStatus.QUEUED, wrong_type)

        wrong_context = EventEnvelope(
            event_type=EventType.TASK_QUEUED,
            timestamp=NOW + timedelta(seconds=1),
            task_id=task.task_id,
            project="different-project",
            team=task.team,
            payload={"status": "queued"},
        )
        with pytest.raises(DataIntegrityError, match="project/team"):
            store.transition_task(task.task_id, TaskStatus.QUEUED, wrong_context)

        assert store.get_task(task.task_id).status is TaskStatus.PENDING


def test_event_idempotency_rejects_reused_id_with_new_content(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        event_id = uuid4()
        event = EventEnvelope(
            event_id=event_id,
            event_type=EventType.TEAM_IDLE,
            timestamp=NOW,
            team="example-product",
        )
        assert store.append_event(event) is True
        assert store.append_event(event) is False

        conflict = EventEnvelope(
            event_id=event_id,
            event_type=EventType.TEAM_ACTIVATED,
            timestamp=NOW,
            team="example-product",
        )
        with pytest.raises(IdempotencyConflictError):
            store.append_event(conflict)


def test_lifecycle_events_cannot_bypass_atomic_task_operations(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        task = create_task(store)
        with pytest.raises(DataIntegrityError, match="atomic task operation"):
            store.append_event(
                lifecycle_event(
                    task,
                    EventType.TASK_QUEUED,
                    TaskStatus.QUEUED,
                    at=NOW + timedelta(seconds=1),
                )
            )


def test_task_assignment_and_cancellation_are_atomic_and_idempotent(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        task = queue_task(store)
        assigned = EventEnvelope(
            event_type=EventType.AGENT_ASSIGNED,
            timestamp=NOW + timedelta(seconds=2),
            task_id=task.task_id,
            project=task.project,
            team=task.team,
            agent="example-developer",
            payload={"status": "queued"},
        )
        first = store.assign_task(task.task_id, "example-developer", assigned)
        second = store.assign_task(task.task_id, "example-developer", assigned)
        assert first == second
        assert first.assigned_agents == ("example-developer",)

        cancelled = lifecycle_event(
            task,
            EventType.TASK_CANCELLED,
            TaskStatus.CANCELLED,
            at=NOW + timedelta(seconds=3),
        )
        assert store.cancel_task(task.task_id, cancelled).status is TaskStatus.CANCELLED


def test_runs_and_artifact_metadata_are_durable(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    with SQLiteStore(database) as store:
        task = queue_task(store)
        run = store.create_run(
            RunRecord(
                run_id="RUN-1001",
                task_id=task.task_id,
                agent="example-developer",
                runtime="codex",
                created_at=NOW + timedelta(seconds=2),
            )
        )
        store.start_run(run.run_id, at=NOW + timedelta(seconds=3))
        finished = store.finish_run(
            run.run_id,
            RunStatus.SUCCEEDED,
            at=NOW + timedelta(seconds=4),
            exit_code=0,
        )
        artifact = store.create_artifact(
            ArtifactMetadata(
                artifact_id="ART-1001",
                task_id=task.task_id,
                run_id=run.run_id,
                kind="patch",
                path="tasks/TASK-1001/changes.patch",
                content_type="text/plain",
                size_bytes=12,
                sha256="0" * 64,
                created_at=NOW + timedelta(seconds=5),
            )
        )
        assert finished.status is RunStatus.SUCCEEDED
        assert artifact.run_id == run.run_id

    with SQLiteStore(database) as reopened:
        assert reopened.get_run("RUN-1001").status is RunStatus.SUCCEEDED
        assert reopened.get_artifact("ART-1001").sha256 == "0" * 64
        assert len(reopened.list_runs("TASK-1001")) == 1
        assert len(reopened.list_artifacts("TASK-1001")) == 1


def test_duplicate_records_fail_explicitly(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        task = create_task(store)
        event = lifecycle_event(task, EventType.TASK_CREATED, TaskStatus.PENDING)
        with pytest.raises(DuplicateTaskError):
            store.create_task(task, event)

        run = RunRecord(
            run_id="RUN-1001",
            task_id=task.task_id,
            agent="example-developer",
            runtime="codex",
            created_at=NOW,
        )
        store.create_run(run)
        with pytest.raises(DuplicateRunError):
            store.create_run(run)

        artifact = ArtifactMetadata(
            artifact_id="ART-1001",
            task_id=task.task_id,
            kind="report",
            path="tasks/TASK-1001/report.txt",
            content_type="text/plain",
            size_bytes=0,
            sha256="a" * 64,
            created_at=NOW,
        )
        store.create_artifact(artifact)
        with pytest.raises(DuplicateArtifactError):
            store.create_artifact(artifact)


def test_running_work_is_reconciled_after_restart(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    with SQLiteStore(database) as store:
        task = queue_task(store)
        store.transition_task(
            task.task_id,
            TaskStatus.RUNNING,
            lifecycle_event(
                task,
                EventType.TASK_STARTED,
                TaskStatus.RUNNING,
                at=NOW + timedelta(seconds=2),
            ),
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

    with SQLiteStore(database) as restarted:
        result = restarted.reconcile_interrupted_running(at=NOW + timedelta(seconds=4))
        assert [run.status for run in result.interrupted_runs] == [RunStatus.INTERRUPTED]
        assert [task.status for task in result.blocked_tasks] == [TaskStatus.BLOCKED]
        assert result.emitted_events[0].envelope.event_type is EventType.TASK_BLOCKED
        assert restarted.get_task("TASK-1001").status is TaskStatus.BLOCKED
        assert restarted.get_run("RUN-1001").status is RunStatus.INTERRUPTED
        assert restarted.reconcile_interrupted_running().blocked_tasks == ()


def test_planning_task_and_queued_run_are_reconciled_after_restart(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    with SQLiteStore(database) as store:
        task = queue_task(store)
        store.transition_task(
            task.task_id,
            TaskStatus.PLANNING,
            lifecycle_event(
                task,
                EventType.TASK_STARTED,
                TaskStatus.PLANNING,
                at=NOW + timedelta(seconds=2),
            ),
        )
        store.create_run(
            RunRecord(
                run_id="RUN-QUEUED-1",
                task_id=task.task_id,
                agent="example-developer",
                runtime="codex",
                created_at=NOW + timedelta(seconds=2),
            )
        )

    with SQLiteStore(database) as restarted:
        result = restarted.reconcile_interrupted_running(at=NOW + timedelta(seconds=3))

        assert result.interrupted_runs[0].status is RunStatus.INTERRUPTED
        assert result.interrupted_runs[0].started_at == NOW + timedelta(seconds=2)
        assert restarted.get_task(task.task_id).status is TaskStatus.BLOCKED


def test_gateway_request_dedupe_survives_restart(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    with SQLiteStore(database) as store:
        assert store.reserve_gateway_request("slack:Ev123", at=NOW) is True
        assert store.reserve_gateway_request("slack:Ev123", at=NOW) is False
        remembered = store.remember_gateway_response(
            "slack:Ev123", {"task_id": "TASK-1001", "status": "queued"}
        )
        assert remembered.response == {"task_id": "TASK-1001", "status": "queued"}
        assert (
            store.remember_gateway_response(
                "slack:Ev123", {"status": "queued", "task_id": "TASK-1001"}
            )
            == remembered
        )
        with pytest.raises(IdempotencyConflictError):
            store.remember_gateway_response("slack:Ev123", {"status": "failed"})
        with pytest.raises(DataIntegrityError, match="cannot release"):
            store.release_gateway_request("slack:Ev123")

    with SQLiteStore(database) as reopened:
        assert reopened.get_gateway_request("slack:Ev123") == remembered
        assert reopened.reserve_gateway_request("retryable", at=NOW) is True
        assert reopened.release_gateway_request("retryable") is True
        assert reopened.get_gateway_request("retryable") is None


def test_gateway_request_reconciliation_releases_only_incomplete_reservations_after_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    with SQLiteStore(database) as store:
        assert store.reserve_gateway_request("slack:incomplete", at=NOW) is True
        assert store.reserve_gateway_request("slack:completed", at=NOW) is True
        completed = store.remember_gateway_response(
            "slack:completed",
            {"task_id": "TASK-1001", "status": "queued"},
        )

    with SQLiteStore(database) as restarted:
        assert restarted.reconcile_incomplete_gateway_requests() == ("slack:incomplete",)
        assert restarted.get_gateway_request("slack:incomplete") is None
        assert restarted.get_gateway_request("slack:completed") == completed

    with SQLiteStore(database) as reopened:
        assert reopened.reconcile_incomplete_gateway_requests() == ()
        assert reopened.get_gateway_request("slack:completed") == completed


def test_gateway_response_rejects_secret_shaped_fields(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        store.reserve_gateway_request("safe-request", at=NOW)
        with pytest.raises(ValidationError, match="secret field"):
            store.remember_gateway_response(
                "safe-request", {"diagnostic": {"api_key": "must-not-persist"}}
            )


def test_missing_relationships_and_closed_store_fail_explicitly(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    with pytest.raises(RecordNotFoundError, match="task not found"):
        store.create_run(
            RunRecord(
                run_id="RUN-4040",
                task_id="TASK-4040",
                agent="example-developer",
                runtime="codex",
                created_at=NOW,
            )
        )
    store.close()
    with pytest.raises(StorageUnavailableError, match="closed"):
        store.get_task("TASK-4040")


def test_unavailable_corrupt_and_future_schema_fail_explicitly(tmp_path: Path) -> None:
    with pytest.raises(StorageUnavailableError, match="parent directory"):
        SQLiteStore(tmp_path / "missing" / "state.sqlite3")

    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"this is not sqlite")
    with pytest.raises(StorageCorruptionError):
        SQLiteStore(corrupt)

    future = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(future)
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (999, 'future', '2026-09-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()

    with pytest.raises(MigrationError, match="newer than supported"):
        SQLiteStore(future)


def test_failed_migration_rolls_back_its_entire_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "migration.sqlite3"
    SQLiteStore(database).close()
    failing = Migration(
        version=LATEST_SCHEMA_VERSION + 1,
        name="intentional-test-failure",
        statements=(
            "CREATE TABLE migration_probe(value TEXT)",
            "THIS IS NOT VALID SQL",
        ),
    )
    monkeypatch.setattr(
        migration_module,
        "MIGRATIONS",
        (*migration_module.MIGRATIONS, failing),
    )
    connection = sqlite3.connect(database, isolation_level=None)
    with pytest.raises(MigrationError, match="failed to apply"):
        migration_module.apply_migrations(connection)

    assert (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_probe'"
        ).fetchone()
        is None
    )
    assert (
        connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?", (failing.version,)
        ).fetchone()
        is None
    )
    connection.close()


def test_busy_timeout_bounds_concurrent_writes(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    first = SQLiteStore(database, busy_timeout_ms=20)
    second = SQLiteStore(database, busy_timeout_ms=20)
    first._connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(StorageBusyError):
            second.reserve_gateway_request("blocked-writer", at=NOW)
    finally:
        first._connection.rollback()
        first.close()
        second.close()


def test_async_orchestration_adapter_maps_runs_and_uses_durable_store(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    task = queue_task(store)
    adapter = AsyncSQLiteOrchestrationStore(
        store,
        run_id_factory=lambda: "RUN-ASYNC-1001",
    )
    compatible: OrchestrationStore = adapter

    async def exercise() -> None:
        assert (await compatible.get_task(task.task_id)).status is TaskStatus.QUEUED
        assert len(await compatible.list_queued_tasks(limit=10)) == 1
        run_id = await compatible.create_run(
            task_id=task.task_id,
            agent_id="example-developer",
            runtime="codex",
        )
        assert run_id == "RUN-ASYNC-1001"
        await compatible.start_run(run_id)
        await compatible.finish_run(
            run_id,
            RunOutcome.SUCCEEDED,
            exit_code=0,
            error_code=None,
        )

    asyncio.run(exercise())
    assert store.get_run("RUN-ASYNC-1001").status is RunStatus.SUCCEEDED
    store.close()


def test_async_orchestration_adapter_reconciles_interrupted_work(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    task = queue_task(store)
    store.transition_task(
        task.task_id,
        TaskStatus.RUNNING,
        lifecycle_event(
            task,
            EventType.TASK_STARTED,
            TaskStatus.RUNNING,
            at=NOW + timedelta(seconds=2),
        ),
    )
    store.create_run(
        RunRecord(
            run_id="RUN-ASYNC-2002",
            task_id=task.task_id,
            agent="example-developer",
            runtime="codex",
            created_at=NOW + timedelta(seconds=2),
        )
    )
    store.start_run("RUN-ASYNC-2002", at=NOW + timedelta(seconds=3))
    adapter = AsyncSQLiteOrchestrationStore(store)

    asyncio.run(adapter.reconcile_interrupted())

    assert store.get_task(task.task_id).status is TaskStatus.BLOCKED
    assert store.get_run("RUN-ASYNC-2002").status is RunStatus.INTERRUPTED
    store.close()


def test_task_route_and_delivery_receipt_survive_reopen(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    with SQLiteStore(database) as store:
        task = create_task(store)
        route = store.save_task_route(task.task_id, "slack", "channel:C123456")
        assert store.save_task_route(task.task_id, "slack", "channel:C123456") == route
        with pytest.raises(IdempotencyConflictError, match="route already differs"):
            store.save_task_route(task.task_id, "slack", "channel:C999999")

        assert store.reserve_delivery("slack:TASK-1001:completed", at=NOW) is True
        assert store.reserve_delivery("slack:TASK-1001:completed", at=NOW) is False
        assert store.is_delivery_delivered("slack:TASK-1001:completed") is False
        delivered = store.mark_delivery_delivered(
            "slack:TASK-1001:completed", at=NOW + timedelta(seconds=1)
        )
        assert delivered.state is DeliveryState.DELIVERED
        assert (
            store.mark_delivery_delivered(
                "slack:TASK-1001:completed", at=NOW + timedelta(seconds=2)
            )
            == delivered
        )
        with pytest.raises(DataIntegrityError, match="cannot release"):
            store.release_delivery("slack:TASK-1001:completed")

    with SQLiteStore(database) as reopened:
        assert reopened.get_task_route("TASK-1001") == route
        assert reopened.is_delivery_delivered("slack:TASK-1001:completed") is True
        assert reopened.get_delivery_receipt("slack:TASK-1001:completed") == delivered
        assert reopened.reserve_delivery("retry-delivery", at=NOW) is True
        assert reopened.release_delivery("retry-delivery") is True
        assert reopened.get_delivery_receipt("retry-delivery") is None


def test_route_and_delivery_identifiers_reject_secret_shaped_values(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "state.sqlite3") as store:
        task = create_task(store)
        with pytest.raises(ValidationError, match="secret-shaped"):
            store.save_task_route(task.task_id, "slack", "xoxb-123456789-secret")
        with pytest.raises(ValidationError, match="secret-shaped"):
            store.reserve_delivery("sk-abcdefgh12345678", at=NOW)


def test_async_delivery_receipts_preserve_completed_and_recover_reserved(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "state.sqlite3")
    adapter = AsyncSQLiteDeliveryReceipts(store)
    compatible: DeliveryReceiptStore = adapter

    async def exercise() -> None:
        assert await compatible.reserve("delivery-complete") is True
        await compatible.mark_delivered("delivery-complete")
        assert await compatible.is_delivered("delivery-complete") is True
        assert await compatible.reserve("delivery-interrupted") is True
        assert await adapter.reconcile_interrupted() == ("delivery-interrupted",)
        assert await compatible.reserve("delivery-interrupted") is True
        await compatible.release("delivery-interrupted")

    asyncio.run(exercise())
    assert store.is_delivery_delivered("delivery-complete") is True
    assert store.get_delivery_receipt("delivery-interrupted") is None
    store.close()
