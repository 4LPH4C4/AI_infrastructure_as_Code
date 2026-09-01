"""Ordered, transactional SQLite schema migrations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from macmini_ai_hub.storage.errors import MigrationError


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="task-and-event-store",
        statements=(
            """
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                project TEXT NOT NULL,
                team TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
                task_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                schema_version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                task_id TEXT REFERENCES tasks(task_id) ON UPDATE CASCADE ON DELETE RESTRICT,
                project TEXT,
                team TEXT,
                agent TEXT,
                correlation_id TEXT,
                causation_id TEXT,
                envelope_json TEXT NOT NULL
            )
            """,
            "CREATE INDEX events_task_sequence_idx ON events(task_id, sequence)",
            "CREATE INDEX tasks_status_created_idx ON tasks(status, created_at, task_id)",
        ),
    ),
    Migration(
        version=2,
        name="runs-and-artifact-metadata",
        statements=(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id)
                    ON UPDATE CASCADE ON DELETE RESTRICT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                run_json TEXT NOT NULL
            )
            """,
            "CREATE INDEX runs_task_created_idx ON runs(task_id, created_at, run_id)",
            "CREATE INDEX runs_status_idx ON runs(status, run_id)",
            """
            CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id)
                    ON UPDATE CASCADE ON DELETE RESTRICT,
                run_id TEXT REFERENCES runs(run_id) ON UPDATE CASCADE ON DELETE RESTRICT,
                created_at TEXT NOT NULL,
                artifact_json TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX artifacts_task_created_idx
            ON artifacts(task_id, created_at, artifact_id)
            """,
        ),
    ),
    Migration(
        version=3,
        name="gateway-request-idempotency",
        statements=(
            """
            CREATE TABLE gateway_requests (
                idempotency_key TEXT PRIMARY KEY,
                response_json TEXT,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX gateway_requests_created_idx ON gateway_requests(created_at)",
        ),
    ),
    Migration(
        version=4,
        name="task-routes-and-delivery-receipts",
        statements=(
            """
            CREATE TABLE task_routes (
                task_id TEXT PRIMARY KEY REFERENCES tasks(task_id)
                    ON UPDATE CASCADE ON DELETE RESTRICT,
                source TEXT NOT NULL,
                target TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE delivery_receipts (
                delivery_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                delivered_at TEXT
            )
            """,
            "CREATE INDEX delivery_receipts_state_idx ON delivery_receipts(state, created_at)",
        ),
    ),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def apply_migrations(connection: sqlite3.Connection) -> None:
    """Apply every pending migration, rolling back a failed version completely."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied_rows = connection.execute(
        "SELECT version, name FROM schema_migrations ORDER BY version"
    ).fetchall()
    applied = {int(row[0]): str(row[1]) for row in applied_rows}

    if applied and max(applied) > LATEST_SCHEMA_VERSION:
        raise MigrationError(
            f"database schema version {max(applied)} is newer than supported "
            f"version {LATEST_SCHEMA_VERSION}"
        )

    known = {migration.version: migration.name for migration in MIGRATIONS}
    if applied and sorted(applied) != list(range(1, max(applied) + 1)):
        raise MigrationError("database migration history contains a version gap")
    for version, name in applied.items():
        if known.get(version) != name:
            raise MigrationError(f"database migration {version} does not match application history")

    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, datetime.now(UTC).isoformat()),
            )
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise MigrationError(
                f"failed to apply database migration {migration.version} ({migration.name})"
            ) from error
