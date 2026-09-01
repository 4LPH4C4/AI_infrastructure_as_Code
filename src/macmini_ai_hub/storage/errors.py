"""Explicit persistence errors safe for service-boundary handling."""


class StorageError(RuntimeError):
    """Base error for durable storage operations."""


class StorageUnavailableError(StorageError):
    """The configured database cannot be opened or used."""


class StorageBusyError(StorageUnavailableError):
    """SQLite remained locked beyond the configured busy timeout."""


class StorageCorruptionError(StorageError):
    """SQLite reported a corrupt or non-database file."""


class MigrationError(StorageError):
    """The on-disk schema cannot be migrated safely."""


class DataIntegrityError(StorageError):
    """Persisted data or a requested relationship violates an invariant."""


class RecordNotFoundError(StorageError):
    """The requested durable record does not exist."""


class DuplicateTaskError(DataIntegrityError):
    """A task identifier is already present."""


class DuplicateRunError(DataIntegrityError):
    """A run identifier is already present."""


class DuplicateArtifactError(DataIntegrityError):
    """An artifact identifier is already present."""


class IdempotencyConflictError(DataIntegrityError):
    """An event identifier was reused for a different envelope."""
