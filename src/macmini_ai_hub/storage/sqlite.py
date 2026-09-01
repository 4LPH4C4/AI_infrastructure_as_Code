"""Single-machine durable SQLite store with transactional lifecycle events."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Self

from pydantic import BaseModel, JsonValue, ValidationError

from macmini_ai_hub.domain.events import EventEnvelope, EventLevel, EventType
from macmini_ai_hub.domain.tasks import Task, TaskStatus
from macmini_ai_hub.domain.tasks import transition_task as apply_task_transition
from macmini_ai_hub.storage.errors import (
    DataIntegrityError,
    DuplicateArtifactError,
    DuplicateRunError,
    DuplicateTaskError,
    IdempotencyConflictError,
    RecordNotFoundError,
    StorageBusyError,
    StorageCorruptionError,
    StorageError,
    StorageUnavailableError,
)
from macmini_ai_hub.storage.migrations import LATEST_SCHEMA_VERSION, apply_migrations
from macmini_ai_hub.storage.models import (
    ArtifactMetadata,
    DeliveryReceipt,
    DeliveryState,
    GatewayRequestRecord,
    ReconciliationResult,
    RunRecord,
    RunStatus,
    StoredEvent,
    TaskRoute,
)

_EVENT_FOR_STATUS: dict[TaskStatus, EventType] = {
    TaskStatus.PENDING: EventType.TASK_CREATED,
    TaskStatus.QUEUED: EventType.TASK_QUEUED,
    TaskStatus.PLANNING: EventType.TASK_STARTED,
    TaskStatus.RUNNING: EventType.TASK_STARTED,
    TaskStatus.REVIEW: EventType.REVIEW_STARTED,
    TaskStatus.QA: EventType.QA_STARTED,
    TaskStatus.BLOCKED: EventType.TASK_BLOCKED,
    TaskStatus.COMPLETED: EventType.TASK_COMPLETED,
    TaskStatus.FAILED: EventType.TASK_FAILED,
    TaskStatus.CANCELLED: EventType.TASK_CANCELLED,
}
_ATOMIC_TASK_EVENT_TYPES = frozenset({*_EVENT_FOR_STATUS.values(), EventType.AGENT_ASSIGNED})


def _canonical_model_json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _database_error(error: sqlite3.Error, operation: str) -> StorageError:
    code = getattr(error, "sqlite_errorcode", None)
    corrupt_codes = {
        getattr(sqlite3, "SQLITE_CORRUPT", 11),
        getattr(sqlite3, "SQLITE_NOTADB", 26),
    }
    if code in corrupt_codes or "not a database" in str(error).lower():
        return StorageCorruptionError(f"database is corrupt during {operation}")
    if code in {getattr(sqlite3, "SQLITE_BUSY", 5), getattr(sqlite3, "SQLITE_LOCKED", 6)}:
        return StorageBusyError(f"database remained busy during {operation}")
    return StorageUnavailableError(f"database unavailable during {operation}")


class SQLiteStore:
    """Thread-bounded SQLite adapter. Call ``close`` before replacing the database file."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        if isinstance(busy_timeout_ms, bool) or not 1 <= busy_timeout_ms <= 60_000:
            raise ValueError("busy_timeout_ms must be an integer between 1 and 60000")
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms
        self._lock = RLock()
        self._closed = False

        if self.path.name == ":memory:":
            raise StorageUnavailableError("durable store does not accept an in-memory database")
        if not self.path.parent.is_dir():
            raise StorageUnavailableError("database parent directory does not exist")
        if self.path.exists() and not self.path.is_file():
            raise StorageUnavailableError("database path is not a regular file")

        try:
            self._connection = sqlite3.connect(
                self.path,
                timeout=busy_timeout_ms / 1_000,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
            self._connection.execute("PRAGMA synchronous = FULL")
            journal_mode = str(self._connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])
            if journal_mode.lower() != "wal":
                raise StorageUnavailableError("database could not enable WAL journal mode")
            apply_migrations(self._connection)
        except StorageError:
            self._close_after_failed_initialization()
            raise
        except sqlite3.Error as error:
            self._close_after_failed_initialization()
            raise _database_error(error, "initialization") from error

    def _close_after_failed_initialization(self) -> None:
        connection = getattr(self, "_connection", None)
        if connection is not None:
            connection.close()
        self._closed = True

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        with self._lock:
            self._ensure_open()
            row = self._execute("PRAGMA user_version", operation="read schema version").fetchone()
            return int(row[0])

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise StorageUnavailableError("database store is closed")

    def _execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
        *,
        operation: str,
    ) -> sqlite3.Cursor:
        try:
            return self._connection.execute(statement, parameters)
        except sqlite3.IntegrityError as error:
            raise DataIntegrityError(f"database integrity violation during {operation}") from error
        except sqlite3.Error as error:
            raise _database_error(error, operation) from error

    @contextmanager
    def _transaction(self, operation: str) -> Iterator[None]:
        with self._lock:
            self._ensure_open()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield
                self._connection.commit()
            except StorageError:
                self._connection.rollback()
                raise
            except sqlite3.IntegrityError as error:
                self._connection.rollback()
                raise DataIntegrityError(
                    f"database integrity violation during {operation}"
                ) from error
            except sqlite3.Error as error:
                self._connection.rollback()
                raise _database_error(error, operation) from error
            except Exception:
                self._connection.rollback()
                raise

    def create_task(self, task: Task, event: EventEnvelope) -> Task:
        if task.status is not TaskStatus.PENDING:
            raise DataIntegrityError("new tasks must have pending status")
        self._validate_lifecycle_event(task, TaskStatus.PENDING, event)
        task_json = _canonical_model_json(task)
        with self._transaction("create task"):
            if self._connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone():
                raise DuplicateTaskError(f"task already exists: {task.task_id}")
            self._connection.execute(
                """
                INSERT INTO tasks(
                    task_id, status, project, team, created_at, updated_at, version, task_json
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    task.task_id,
                    task.status.value,
                    task.project,
                    task.team,
                    task.created_at.isoformat(),
                    event.timestamp.isoformat(),
                    task_json,
                ),
            )
            self._append_event_locked(event)
        return task

    def create_queued_task(
        self,
        task: Task,
        created_event: EventEnvelope,
        queued_event: EventEnvelope,
        *,
        route: TaskRoute | None = None,
    ) -> Task:
        """Atomically create, optionally route, and queue one gateway task."""

        if task.status is not TaskStatus.PENDING:
            raise DataIntegrityError("new tasks must have pending status")
        self._validate_lifecycle_event(task, TaskStatus.PENDING, created_event)
        self._validate_lifecycle_event(task, TaskStatus.QUEUED, queued_event)
        if queued_event.timestamp < created_event.timestamp:
            raise DataIntegrityError("queued event must not precede created event")
        if route is not None and route.task_id != task.task_id:
            raise DataIntegrityError("task route does not match created task")
        queued = apply_task_transition(task, TaskStatus.QUEUED, at=queued_event.timestamp)

        with self._transaction("create queued task"):
            if self._connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone():
                raise DuplicateTaskError(f"task already exists: {task.task_id}")
            self._connection.execute(
                """
                INSERT INTO tasks(
                    task_id, status, project, team, created_at, updated_at, version, task_json
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    task.task_id,
                    task.status.value,
                    task.project,
                    task.team,
                    task.created_at.isoformat(),
                    created_event.timestamp.isoformat(),
                    _canonical_model_json(task),
                ),
            )
            self._append_event_locked(created_event)
            if route is not None:
                self._connection.execute(
                    "INSERT INTO task_routes(task_id, source, target) VALUES (?, ?, ?)",
                    (route.task_id, route.source, route.target),
                )
            self._connection.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, version = 2, task_json = ?
                WHERE task_id = ? AND version = 1
                """,
                (
                    queued.status.value,
                    queued_event.timestamp.isoformat(),
                    _canonical_model_json(queued),
                    queued.task_id,
                ),
            )
            self._append_event_locked(queued_event)
        return queued

    def get_task(self, task_id: str) -> Task:
        with self._lock:
            self._ensure_open()
            row = self._execute(
                "SELECT task_json FROM tasks WHERE task_id = ?",
                (task_id,),
                operation="read task",
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"task not found: {task_id}")
            return self._decode_model(Task, str(row["task_json"]), "task")

    def list_queued_tasks(self, *, limit: int = 100) -> tuple[Task, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 1_000:
            raise ValueError("limit must be an integer between 1 and 1000")
        with self._lock:
            self._ensure_open()
            rows = self._execute(
                """
                SELECT task_json FROM tasks
                WHERE status = ?
                ORDER BY created_at, task_id
                LIMIT ?
                """,
                (TaskStatus.QUEUED.value, limit),
                operation="list queued tasks",
            ).fetchall()
            return tuple(self._decode_model(Task, str(row["task_json"]), "task") for row in rows)

    def list_tasks(
        self,
        *,
        limit: int = 100,
        status: TaskStatus | None = None,
    ) -> tuple[Task, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 1_000:
            raise ValueError("limit must be an integer between 1 and 1000")
        with self._lock:
            self._ensure_open()
            if status is None:
                rows = self._execute(
                    """
                    SELECT task_json FROM tasks ORDER BY created_at DESC, task_id LIMIT ?
                    """,
                    (limit,),
                    operation="list tasks",
                ).fetchall()
            else:
                rows = self._execute(
                    """
                    SELECT task_json FROM tasks
                    WHERE status = ? ORDER BY created_at DESC, task_id LIMIT ?
                    """,
                    (status.value, limit),
                    operation="list tasks by status",
                ).fetchall()
            return tuple(self._decode_model(Task, str(row["task_json"]), "task") for row in rows)

    def transition_task(
        self,
        task_id: str,
        target: TaskStatus,
        event: EventEnvelope,
    ) -> Task:
        with self._transaction("transition task"):
            row = self._connection.execute(
                "SELECT task_json, version FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"task not found: {task_id}")
            current = self._decode_model(Task, str(row["task_json"]), "task")
            self._validate_lifecycle_event(current, target, event)

            existing_json = self._event_json_locked(str(event.event_id))
            event_json = _canonical_model_json(event)
            if existing_json is not None:
                if existing_json != event_json:
                    raise IdempotencyConflictError(
                        f"event_id was reused with different content: {event.event_id}"
                    )
                return current

            updated = apply_task_transition(current, target, at=event.timestamp)
            self._connection.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, version = ?, task_json = ?
                WHERE task_id = ? AND version = ?
                """,
                (
                    updated.status.value,
                    event.timestamp.isoformat(),
                    int(row["version"]) + 1,
                    _canonical_model_json(updated),
                    task_id,
                    int(row["version"]),
                ),
            )
            self._append_event_locked(event)
            return updated

    def assign_task(self, task_id: str, agent: str, event: EventEnvelope) -> Task:
        """Assign one agent and append ``agent.assigned`` in the same transaction."""

        with self._transaction("assign task"):
            row = self._connection.execute(
                "SELECT task_json, version FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"task not found: {task_id}")
            current = self._decode_model(Task, str(row["task_json"]), "task")
            if event.event_type is not EventType.AGENT_ASSIGNED:
                raise DataIntegrityError("task assignment requires event type agent.assigned")
            if event.task_id != current.task_id or event.agent != agent:
                raise DataIntegrityError("assignment event task_id/agent does not match assignment")
            if event.project != current.project or event.team != current.team:
                raise DataIntegrityError("assignment event project/team does not match task")

            existing_json = self._event_json_locked(str(event.event_id))
            event_json = _canonical_model_json(event)
            if existing_json is not None:
                if existing_json != event_json:
                    raise IdempotencyConflictError(
                        f"event_id was reused with different content: {event.event_id}"
                    )
                return current
            if event.payload.get("status") != current.status.value:
                raise DataIntegrityError(
                    f"assignment event payload.status must be {current.status.value!r}"
                )
            if agent in current.assigned_agents:
                raise DataIntegrityError(f"agent is already assigned to task: {agent}")

            updated = Task.model_validate(
                {
                    **current.model_dump(),
                    "assigned_agents": (*current.assigned_agents, agent),
                }
            )
            self._connection.execute(
                """
                UPDATE tasks SET updated_at = ?, version = ?, task_json = ?
                WHERE task_id = ? AND version = ?
                """,
                (
                    event.timestamp.isoformat(),
                    int(row["version"]) + 1,
                    _canonical_model_json(updated),
                    task_id,
                    int(row["version"]),
                ),
            )
            self._append_event_locked(event)
            return updated

    def cancel_task(self, task_id: str, event: EventEnvelope) -> Task:
        return self.transition_task(task_id, TaskStatus.CANCELLED, event)

    def append_event(self, event: EventEnvelope) -> bool:
        if event.event_type in _ATOMIC_TASK_EVENT_TYPES:
            raise DataIntegrityError(
                f"{event.event_type.value} must be appended through an atomic task operation"
            )
        with self._transaction("append event"):
            return self._append_event_locked(event)

    def _append_event_locked(self, event: EventEnvelope) -> bool:
        event_json = _canonical_model_json(event)
        existing_json = self._event_json_locked(str(event.event_id))
        if existing_json is not None:
            if existing_json == event_json:
                return False
            raise IdempotencyConflictError(
                f"event_id was reused with different content: {event.event_id}"
            )
        self._connection.execute(
            """
            INSERT INTO events(
                event_id, schema_version, event_type, timestamp, task_id, project, team,
                agent, correlation_id, causation_id, envelope_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event.event_id),
                event.schema_version,
                event.event_type.value,
                event.timestamp.isoformat(),
                event.task_id,
                event.project,
                event.team,
                event.agent,
                str(event.correlation_id) if event.correlation_id else None,
                str(event.causation_id) if event.causation_id else None,
                event_json,
            ),
        )
        return True

    def _event_json_locked(self, event_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT envelope_json FROM events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return None if row is None else str(row["envelope_json"])

    def list_events(
        self,
        *,
        task_id: str | None = None,
        after_sequence: int = 0,
        limit: int = 1_000,
    ) -> tuple[StoredEvent, ...]:
        if isinstance(after_sequence, bool) or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        if isinstance(limit, bool) or not 1 <= limit <= 10_000:
            raise ValueError("limit must be an integer between 1 and 10000")
        with self._lock:
            self._ensure_open()
            if task_id is None:
                rows = self._execute(
                    """
                    SELECT sequence, envelope_json FROM events
                    WHERE sequence > ? ORDER BY sequence LIMIT ?
                    """,
                    (after_sequence, limit),
                    operation="list events",
                ).fetchall()
            else:
                rows = self._execute(
                    """
                    SELECT sequence, envelope_json FROM events
                    WHERE task_id = ? AND sequence > ? ORDER BY sequence LIMIT ?
                    """,
                    (task_id, after_sequence, limit),
                    operation="list task events",
                ).fetchall()
            return tuple(
                StoredEvent(
                    sequence=int(row["sequence"]),
                    envelope=self._decode_model(EventEnvelope, str(row["envelope_json"]), "event"),
                )
                for row in rows
            )

    def create_run(self, run: RunRecord) -> RunRecord:
        with self._transaction("create run"):
            if self._connection.execute(
                "SELECT 1 FROM runs WHERE run_id = ?", (run.run_id,)
            ).fetchone():
                raise DuplicateRunError(f"run already exists: {run.run_id}")
            if not self._connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?", (run.task_id,)
            ).fetchone():
                raise RecordNotFoundError(f"task not found: {run.task_id}")
            self._write_run_locked(run, insert=True)
        return run

    def get_run(self, run_id: str) -> RunRecord:
        with self._lock:
            self._ensure_open()
            row = self._execute(
                "SELECT run_json FROM runs WHERE run_id = ?",
                (run_id,),
                operation="read run",
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"run not found: {run_id}")
            return self._decode_model(RunRecord, str(row["run_json"]), "run")

    def list_runs(self, task_id: str) -> tuple[RunRecord, ...]:
        with self._lock:
            self._ensure_open()
            rows = self._execute(
                """
                SELECT run_json FROM runs WHERE task_id = ? ORDER BY created_at, run_id
                """,
                (task_id,),
                operation="list runs",
            ).fetchall()
            return tuple(self._decode_model(RunRecord, str(row["run_json"]), "run") for row in rows)

    def start_run(self, run_id: str, *, at: datetime | None = None) -> RunRecord:
        started_at = self._aware_time(at)
        with self._transaction("start run"):
            current = self._get_run_locked(run_id)
            if current.status is not RunStatus.QUEUED:
                raise DataIntegrityError(f"run is not queued: {run_id}")
            updated = RunRecord.model_validate(
                {**current.model_dump(), "status": RunStatus.RUNNING, "started_at": started_at}
            )
            self._write_run_locked(updated)
            return updated

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        *,
        at: datetime | None = None,
        exit_code: int | None = None,
        error_code: str | None = None,
    ) -> RunRecord:
        if not status.is_terminal:
            raise ValueError("finish status must be terminal")
        completed_at = self._aware_time(at)
        with self._transaction("finish run"):
            current = self._get_run_locked(run_id)
            if current.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                raise DataIntegrityError(f"run is not active: {run_id}")
            updated = RunRecord.model_validate(
                {
                    **current.model_dump(),
                    "status": status,
                    "started_at": current.started_at or current.created_at,
                    "completed_at": completed_at,
                    "exit_code": exit_code,
                    "error_code": error_code,
                }
            )
            self._write_run_locked(updated)
            return updated

    def _get_run_locked(self, run_id: str) -> RunRecord:
        row = self._connection.execute(
            "SELECT run_json FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"run not found: {run_id}")
        return self._decode_model(RunRecord, str(row["run_json"]), "run")

    def _write_run_locked(self, run: RunRecord, *, insert: bool = False) -> None:
        values = (
            run.run_id,
            run.task_id,
            run.status.value,
            run.created_at.isoformat(),
            run.started_at.isoformat() if run.started_at else None,
            run.completed_at.isoformat() if run.completed_at else None,
            _canonical_model_json(run),
        )
        if insert:
            self._connection.execute(
                """
                INSERT INTO runs(
                    run_id, task_id, status, created_at, started_at, completed_at, run_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        else:
            self._connection.execute(
                """
                UPDATE runs SET status = ?, started_at = ?, completed_at = ?, run_json = ?
                WHERE run_id = ?
                """,
                (
                    run.status.value,
                    run.started_at.isoformat() if run.started_at else None,
                    run.completed_at.isoformat() if run.completed_at else None,
                    _canonical_model_json(run),
                    run.run_id,
                ),
            )

    def create_artifact(self, artifact: ArtifactMetadata) -> ArtifactMetadata:
        with self._transaction("create artifact"):
            if self._connection.execute(
                "SELECT 1 FROM artifacts WHERE artifact_id = ?", (artifact.artifact_id,)
            ).fetchone():
                raise DuplicateArtifactError(f"artifact already exists: {artifact.artifact_id}")
            if not self._connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?", (artifact.task_id,)
            ).fetchone():
                raise RecordNotFoundError(f"task not found: {artifact.task_id}")
            if (
                artifact.run_id is not None
                and not self._connection.execute(
                    "SELECT 1 FROM runs WHERE run_id = ? AND task_id = ?",
                    (artifact.run_id, artifact.task_id),
                ).fetchone()
            ):
                raise DataIntegrityError("artifact run must exist and belong to the same task")
            self._connection.execute(
                """
                INSERT INTO artifacts(artifact_id, task_id, run_id, created_at, artifact_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.task_id,
                    artifact.run_id,
                    artifact.created_at.isoformat(),
                    _canonical_model_json(artifact),
                ),
            )
        return artifact

    def get_artifact(self, artifact_id: str) -> ArtifactMetadata:
        with self._lock:
            self._ensure_open()
            row = self._execute(
                "SELECT artifact_json FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
                operation="read artifact",
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"artifact not found: {artifact_id}")
            return self._decode_model(ArtifactMetadata, str(row["artifact_json"]), "artifact")

    def list_artifacts(self, task_id: str) -> tuple[ArtifactMetadata, ...]:
        with self._lock:
            self._ensure_open()
            rows = self._execute(
                """
                SELECT artifact_json FROM artifacts
                WHERE task_id = ? ORDER BY created_at, artifact_id
                """,
                (task_id,),
                operation="list artifacts",
            ).fetchall()
            return tuple(
                self._decode_model(ArtifactMetadata, str(row["artifact_json"]), "artifact")
                for row in rows
            )

    def reserve_gateway_request(self, idempotency_key: str, *, at: datetime | None = None) -> bool:
        record = GatewayRequestRecord(
            idempotency_key=idempotency_key,
            created_at=self._aware_time(at),
        )
        with self._transaction("reserve gateway request"):
            if self._connection.execute(
                "SELECT 1 FROM gateway_requests WHERE idempotency_key = ?",
                (record.idempotency_key,),
            ).fetchone():
                return False
            self._connection.execute(
                """
                INSERT INTO gateway_requests(idempotency_key, response_json, created_at)
                VALUES (?, NULL, ?)
                """,
                (record.idempotency_key, record.created_at.isoformat()),
            )
            return True

    def get_gateway_request(self, idempotency_key: str) -> GatewayRequestRecord | None:
        key = GatewayRequestRecord(idempotency_key=idempotency_key).idempotency_key
        with self._lock:
            self._ensure_open()
            row = self._execute(
                """
                SELECT idempotency_key, response_json, created_at
                FROM gateway_requests WHERE idempotency_key = ?
                """,
                (key,),
                operation="read gateway request",
            ).fetchone()
            if row is None:
                return None
            response_json = row["response_json"]
            try:
                response = None if response_json is None else json.loads(str(response_json))
                return GatewayRequestRecord(
                    idempotency_key=str(row["idempotency_key"]),
                    response=response,
                    created_at=str(row["created_at"]),
                )
            except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as error:
                raise DataIntegrityError("persisted gateway request is invalid") from error

    def remember_gateway_response(
        self,
        idempotency_key: str,
        response: dict[str, JsonValue],
    ) -> GatewayRequestRecord:
        validated_response = GatewayRequestRecord(
            idempotency_key=idempotency_key, response=response
        ).response
        if validated_response is None:
            raise ValueError("gateway response must not be null")
        response_json = json.dumps(
            validated_response, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        with self._transaction("remember gateway response"):
            row = self._connection.execute(
                """
                SELECT response_json, created_at FROM gateway_requests WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(
                    f"gateway request reservation not found: {idempotency_key}"
                )
            existing = row["response_json"]
            if existing is not None and str(existing) != response_json:
                raise IdempotencyConflictError(
                    f"gateway request response already differs: {idempotency_key}"
                )
            if existing is None:
                self._connection.execute(
                    """
                    UPDATE gateway_requests SET response_json = ? WHERE idempotency_key = ?
                    """,
                    (response_json, idempotency_key),
                )
            return GatewayRequestRecord(
                idempotency_key=idempotency_key,
                response=validated_response,
                created_at=str(row["created_at"]),
            )

    def release_gateway_request(self, idempotency_key: str) -> bool:
        key = GatewayRequestRecord(idempotency_key=idempotency_key).idempotency_key
        with self._transaction("release gateway request"):
            row = self._connection.execute(
                "SELECT response_json FROM gateway_requests WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if row is None:
                return False
            if row["response_json"] is not None:
                raise DataIntegrityError("cannot release a gateway request with a durable response")
            self._connection.execute(
                "DELETE FROM gateway_requests WHERE idempotency_key = ?", (key,)
            )
            return True

    def reconcile_incomplete_gateway_requests(self) -> tuple[str, ...]:
        """Release only reservations that never stored a replayable response."""

        with self._transaction("reconcile incomplete gateway requests"):
            rows = self._connection.execute(
                """
                SELECT idempotency_key FROM gateway_requests
                WHERE response_json IS NULL ORDER BY idempotency_key
                """
            ).fetchall()
            keys = tuple(str(row["idempotency_key"]) for row in rows)
            self._connection.execute(
                "DELETE FROM gateway_requests WHERE response_json IS NULL"
            )
            return keys

    def save_task_route(self, task_id: str, source: str, target: str) -> TaskRoute:
        route = TaskRoute(task_id=task_id, source=source, target=target)
        with self._transaction("save task route"):
            if not self._connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?", (route.task_id,)
            ).fetchone():
                raise RecordNotFoundError(f"task not found: {route.task_id}")
            row = self._connection.execute(
                "SELECT source, target FROM task_routes WHERE task_id = ?", (route.task_id,)
            ).fetchone()
            if row is not None:
                if str(row["source"]) == route.source and str(row["target"]) == route.target:
                    return route
                raise IdempotencyConflictError(
                    f"task route already differs for task: {route.task_id}"
                )
            self._connection.execute(
                "INSERT INTO task_routes(task_id, source, target) VALUES (?, ?, ?)",
                (route.task_id, route.source, route.target),
            )
            return route

    def get_task_route(self, task_id: str) -> TaskRoute | None:
        with self._lock:
            self._ensure_open()
            row = self._execute(
                "SELECT task_id, source, target FROM task_routes WHERE task_id = ?",
                (task_id,),
                operation="read task route",
            ).fetchone()
            if row is None:
                return None
            try:
                return TaskRoute(
                    task_id=str(row["task_id"]),
                    source=str(row["source"]),
                    target=str(row["target"]),
                )
            except ValidationError as error:
                raise DataIntegrityError("persisted task route is invalid") from error

    def list_task_routes(self, *, limit: int = 1_000) -> tuple[TaskRoute, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 1_000:
            raise ValueError("limit must be an integer between 1 and 1000")
        with self._lock:
            self._ensure_open()
            rows = self._execute(
                """
                SELECT task_id, source, target FROM task_routes ORDER BY task_id LIMIT ?
                """,
                (limit,),
                operation="list task routes",
            ).fetchall()
            try:
                return tuple(
                    TaskRoute(
                        task_id=str(row["task_id"]),
                        source=str(row["source"]),
                        target=str(row["target"]),
                    )
                    for row in rows
                )
            except ValidationError as error:
                raise DataIntegrityError("persisted task route is invalid") from error

    def reserve_delivery(self, delivery_id: str, *, at: datetime | None = None) -> bool:
        receipt = DeliveryReceipt(
            delivery_id=delivery_id,
            created_at=self._aware_time(at),
        )
        with self._transaction("reserve delivery"):
            if self._connection.execute(
                "SELECT 1 FROM delivery_receipts WHERE delivery_id = ?",
                (receipt.delivery_id,),
            ).fetchone():
                return False
            self._connection.execute(
                """
                INSERT INTO delivery_receipts(delivery_id, state, created_at, delivered_at)
                VALUES (?, ?, ?, NULL)
                """,
                (receipt.delivery_id, receipt.state.value, receipt.created_at.isoformat()),
            )
            return True

    def get_delivery_receipt(self, delivery_id: str) -> DeliveryReceipt | None:
        key = DeliveryReceipt(delivery_id=delivery_id).delivery_id
        with self._lock:
            self._ensure_open()
            row = self._execute(
                """
                SELECT delivery_id, state, created_at, delivered_at
                FROM delivery_receipts WHERE delivery_id = ?
                """,
                (key,),
                operation="read delivery receipt",
            ).fetchone()
            if row is None:
                return None
            try:
                return DeliveryReceipt.model_validate(
                    {
                        "delivery_id": row["delivery_id"],
                        "state": row["state"],
                        "created_at": row["created_at"],
                        "delivered_at": row["delivered_at"],
                    }
                )
            except ValidationError as error:
                raise DataIntegrityError("persisted delivery receipt is invalid") from error

    def is_delivery_delivered(self, delivery_id: str) -> bool:
        receipt = self.get_delivery_receipt(delivery_id)
        return receipt is not None and receipt.state is DeliveryState.DELIVERED

    def mark_delivery_delivered(
        self, delivery_id: str, *, at: datetime | None = None
    ) -> DeliveryReceipt:
        delivered_at = self._aware_time(at)
        key = DeliveryReceipt(delivery_id=delivery_id).delivery_id
        with self._transaction("mark delivery delivered"):
            row = self._connection.execute(
                """
                SELECT state, created_at, delivered_at
                FROM delivery_receipts WHERE delivery_id = ?
                """,
                (key,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"delivery reservation not found: {key}")
            if str(row["state"]) == DeliveryState.DELIVERED.value:
                return DeliveryReceipt.model_validate(
                    {
                        "delivery_id": key,
                        "state": row["state"],
                        "created_at": row["created_at"],
                        "delivered_at": row["delivered_at"],
                    }
                )
            receipt = DeliveryReceipt(
                delivery_id=key,
                state=DeliveryState.DELIVERED,
                created_at=str(row["created_at"]),
                delivered_at=delivered_at,
            )
            self._connection.execute(
                """
                UPDATE delivery_receipts SET state = ?, delivered_at = ?
                WHERE delivery_id = ?
                """,
                (receipt.state.value, delivered_at.isoformat(), receipt.delivery_id),
            )
            return receipt

    def release_delivery(self, delivery_id: str) -> bool:
        key = DeliveryReceipt(delivery_id=delivery_id).delivery_id
        with self._transaction("release delivery"):
            row = self._connection.execute(
                "SELECT state FROM delivery_receipts WHERE delivery_id = ?", (key,)
            ).fetchone()
            if row is None:
                return False
            if str(row["state"]) == DeliveryState.DELIVERED.value:
                raise DataIntegrityError("cannot release a delivered receipt")
            self._connection.execute("DELETE FROM delivery_receipts WHERE delivery_id = ?", (key,))
            return True

    def reconcile_reserved_deliveries(self) -> tuple[str, ...]:
        """Release only incomplete delivery reservations after a process restart."""

        with self._transaction("reconcile reserved deliveries"):
            rows = self._connection.execute(
                """
                SELECT delivery_id FROM delivery_receipts
                WHERE state = ? ORDER BY delivery_id
                """,
                (DeliveryState.RESERVED.value,),
            ).fetchall()
            delivery_ids = tuple(str(row["delivery_id"]) for row in rows)
            self._connection.execute(
                "DELETE FROM delivery_receipts WHERE state = ?",
                (DeliveryState.RESERVED.value,),
            )
            return delivery_ids

    def reconcile_interrupted_running(self, *, at: datetime | None = None) -> ReconciliationResult:
        reconciled_at = self._aware_time(at)
        interrupted_runs: list[RunRecord] = []
        blocked_tasks: list[Task] = []
        emitted_events: list[StoredEvent] = []
        with self._transaction("reconcile interrupted work"):
            run_rows = self._connection.execute(
                """
                SELECT run_json FROM runs WHERE status IN (?, ?) ORDER BY run_id
                """,
                (RunStatus.QUEUED.value, RunStatus.RUNNING.value),
            ).fetchall()
            for row in run_rows:
                current_run = self._decode_model(RunRecord, str(row["run_json"]), "run")
                interrupted = RunRecord.model_validate(
                    {
                        **current_run.model_dump(),
                        "status": RunStatus.INTERRUPTED,
                        "started_at": current_run.started_at or current_run.created_at,
                        "completed_at": reconciled_at,
                        "error_code": "process-restart",
                    }
                )
                self._write_run_locked(interrupted)
                interrupted_runs.append(interrupted)

            task_rows = self._connection.execute(
                """
                SELECT task_json, version FROM tasks
                WHERE status IN (?, ?) ORDER BY task_id
                """,
                (TaskStatus.PLANNING.value, TaskStatus.RUNNING.value),
            ).fetchall()
            for row in task_rows:
                current_task = self._decode_model(Task, str(row["task_json"]), "task")
                event = EventEnvelope(
                    event_type=EventType.TASK_BLOCKED,
                    timestamp=reconciled_at,
                    task_id=current_task.task_id,
                    project=current_task.project,
                    team=current_task.team,
                    level=EventLevel.WARNING,
                    message="Task execution was interrupted by a process restart.",
                    payload={"status": "blocked", "reason": "process-restart"},
                )
                blocked = apply_task_transition(current_task, TaskStatus.BLOCKED, at=reconciled_at)
                self._connection.execute(
                    """
                    UPDATE tasks SET status = ?, updated_at = ?, version = ?, task_json = ?
                    WHERE task_id = ? AND version = ?
                    """,
                    (
                        blocked.status.value,
                        reconciled_at.isoformat(),
                        int(row["version"]) + 1,
                        _canonical_model_json(blocked),
                        blocked.task_id,
                        int(row["version"]),
                    ),
                )
                self._append_event_locked(event)
                sequence_row = self._connection.execute(
                    "SELECT sequence FROM events WHERE event_id = ?", (str(event.event_id),)
                ).fetchone()
                blocked_tasks.append(blocked)
                emitted_events.append(
                    StoredEvent(sequence=int(sequence_row["sequence"]), envelope=event)
                )

        return ReconciliationResult(
            interrupted_runs=tuple(interrupted_runs),
            blocked_tasks=tuple(blocked_tasks),
            emitted_events=tuple(emitted_events),
        )

    @staticmethod
    def _aware_time(value: datetime | None) -> datetime:
        result = value or datetime.now(UTC)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return result

    @staticmethod
    def _decode_model[ModelType: BaseModel](
        model_type: type[ModelType], raw_json: str, record_type: str
    ) -> ModelType:
        try:
            return model_type.model_validate_json(raw_json)
        except (ValidationError, ValueError, TypeError) as error:
            raise DataIntegrityError(f"persisted {record_type} record is invalid") from error

    @staticmethod
    def _validate_lifecycle_event(
        task: Task,
        target: TaskStatus,
        event: EventEnvelope,
    ) -> None:
        expected_type = _EVENT_FOR_STATUS[target]
        if event.event_type is not expected_type:
            raise DataIntegrityError(
                f"{target.value} requires event type {expected_type.value}, "
                f"not {event.event_type.value}"
            )
        if event.task_id != task.task_id:
            raise DataIntegrityError("lifecycle event task_id does not match task")
        if event.project != task.project or event.team != task.team:
            raise DataIntegrityError("lifecycle event project/team does not match task")
        if event.payload.get("status") != target.value:
            raise DataIntegrityError(f"lifecycle event payload.status must be {target.value!r}")


__all__ = ["LATEST_SCHEMA_VERSION", "SQLiteStore"]
