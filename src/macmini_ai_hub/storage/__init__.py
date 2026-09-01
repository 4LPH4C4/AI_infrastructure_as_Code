"""Durable storage contracts and the Phase 1 SQLite adapter."""

from macmini_ai_hub.storage.adapters import (
    AsyncSQLiteDeliveryReceipts,
    AsyncSQLiteOrchestrationStore,
)
from macmini_ai_hub.storage.errors import (
    DataIntegrityError,
    DuplicateArtifactError,
    DuplicateRunError,
    DuplicateTaskError,
    IdempotencyConflictError,
    MigrationError,
    RecordNotFoundError,
    StorageBusyError,
    StorageCorruptionError,
    StorageError,
    StorageUnavailableError,
)
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
from macmini_ai_hub.storage.sqlite import SQLiteStore

__all__ = [
    "ArtifactMetadata",
    "AsyncSQLiteDeliveryReceipts",
    "AsyncSQLiteOrchestrationStore",
    "DataIntegrityError",
    "DeliveryReceipt",
    "DeliveryState",
    "DuplicateArtifactError",
    "DuplicateRunError",
    "DuplicateTaskError",
    "GatewayRequestRecord",
    "IdempotencyConflictError",
    "MigrationError",
    "ReconciliationResult",
    "RecordNotFoundError",
    "RunRecord",
    "RunStatus",
    "SQLiteStore",
    "StorageBusyError",
    "StorageCorruptionError",
    "StorageError",
    "StorageUnavailableError",
    "StoredEvent",
    "TaskRoute",
]
