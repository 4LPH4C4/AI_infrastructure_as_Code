"""O_EXCL project locks with bounded waiting and conservative stale recovery."""

from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self

_LOCK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class LockError(RuntimeError):
    """Base error for project lock operations."""


class LockTimeoutError(LockError):
    """Raised when the bounded acquisition window expires."""


class InvalidLockError(LockError):
    """Raised when existing lock metadata cannot be trusted."""


class LockOwnershipError(LockError):
    """Raised when a caller tries to release a lock it no longer owns."""


@dataclass(frozen=True, slots=True)
class LockMetadata:
    project: str
    task: str
    created_at: str
    pid: int
    owner_token: str

    @classmethod
    def from_mapping(cls, value: Any) -> Self:
        if not isinstance(value, dict):
            raise ValueError("lock metadata must be an object")
        expected = {"project", "task", "created_at", "pid", "owner_token"}
        if set(value) != expected:
            raise ValueError("lock metadata fields are invalid")
        project = value["project"]
        task = value["task"]
        created_at = value["created_at"]
        pid = value["pid"]
        owner_token = value["owner_token"]
        if not all(isinstance(item, str) for item in (project, task, created_at, owner_token)):
            raise ValueError("lock metadata string fields are invalid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ValueError("lock metadata pid is invalid")
        if not _LOCK_ID_PATTERN.fullmatch(project) or not _LOCK_ID_PATTERN.fullmatch(task):
            raise ValueError("lock metadata identifiers are invalid")
        if not owner_token or len(owner_token) > 64:
            raise ValueError("lock metadata owner token is invalid")
        _parse_timestamp(created_at)
        return cls(
            project=project,
            task=task,
            created_at=created_at,
            pid=pid,
            owner_token=owner_token,
        )


@dataclass(frozen=True, slots=True)
class LockInspection:
    path: Path
    exists: bool
    metadata: LockMetadata | None
    stale: bool
    recoverable: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _LockSnapshot:
    metadata: LockMetadata
    signature: tuple[int, int, int, int]


class ProjectFileLock:
    """One exclusive lock file per project.

    A stale lock is automatically recoverable only when its timestamp exceeds
    ``stale_after`` *and* its PID is confirmed absent. Malformed or changed lock
    files are never deleted automatically.
    """

    def __init__(
        self,
        lock_root: Path,
        project_id: str,
        task_id: str,
        *,
        wait_timeout: float = 0.0,
        poll_interval: float = 0.1,
        stale_after: timedelta = timedelta(hours=6),
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        process_alive: Callable[[int], bool] | None = None,
    ) -> None:
        if not _LOCK_ID_PATTERN.fullmatch(project_id):
            raise ValueError("project_id is unsafe for a lock file")
        if not _LOCK_ID_PATTERN.fullmatch(task_id):
            raise ValueError("task_id is unsafe for lock metadata")
        if wait_timeout < 0:
            raise ValueError("wait_timeout must be non-negative")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if stale_after.total_seconds() < 0:
            raise ValueError("stale_after must be non-negative")

        self._lock_root = lock_root.resolve(strict=False)
        self._path = self._lock_root / f"{project_id}.lock"
        self._project_id = project_id
        self._task_id = task_id
        self._wait_timeout = wait_timeout
        self._poll_interval = poll_interval
        self._stale_after = stale_after
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic
        self._sleep = sleep
        self._process_alive = process_alive or _process_is_alive
        self._metadata: LockMetadata | None = None
        self._recovered_metadata: LockMetadata | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def metadata(self) -> LockMetadata | None:
        return self._metadata

    @property
    def recovered_metadata(self) -> LockMetadata | None:
        """Metadata of a stale owner reclaimed during the last acquisition."""

        return self._recovered_metadata

    def acquire(self) -> LockMetadata:
        if self._metadata is not None:
            raise LockOwnershipError("lock instance is already acquired")

        self._lock_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            os.chmod(self._lock_root, 0o700)
        canonical_root = self._lock_root.resolve(strict=True)
        if self._path.parent.resolve(strict=True) != canonical_root:
            raise InvalidLockError("lock path escaped the configured lock root")

        deadline = self._monotonic() + self._wait_timeout
        self._recovered_metadata = None
        while True:
            metadata = LockMetadata(
                project=self._project_id,
                task=self._task_id,
                created_at=_format_timestamp(self._utc_now()),
                pid=os.getpid(),
                owner_token=uuid.uuid4().hex,
            )
            try:
                self._create_exclusive(metadata)
            except FileExistsError as error:
                inspection = self.inspect()
                if inspection.recoverable and inspection.metadata is not None:
                    try:
                        snapshot = self._read_snapshot()
                    except (OSError, ValueError, json.JSONDecodeError):
                        snapshot = None
                    if (
                        snapshot is not None
                        and snapshot.metadata == inspection.metadata
                        and self._remove_unchanged(snapshot)
                    ):
                        self._recovered_metadata = snapshot.metadata
                        continue
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    owner = inspection.metadata.task if inspection.metadata else "unknown"
                    raise LockTimeoutError(
                        f"project {self._project_id!r} is locked by task {owner!r}"
                    ) from error
                self._sleep(min(self._poll_interval, remaining))
                continue
            self._metadata = metadata
            return metadata

    def release(self) -> None:
        owned = self._metadata
        if owned is None:
            return
        try:
            snapshot = self._read_snapshot()
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise LockOwnershipError("lock file is invalid and was not removed") from error
        if snapshot is None or snapshot.metadata.owner_token != owned.owner_token:
            raise LockOwnershipError("lock file is missing, invalid, or owned by another task")
        if not self._remove_unchanged(snapshot):
            raise LockOwnershipError("lock file changed before release")
        self._metadata = None

    def inspect(self) -> LockInspection:
        if not self._path.exists() and not self._path.is_symlink():
            return LockInspection(
                path=self._path,
                exists=False,
                metadata=None,
                stale=False,
                recoverable=False,
            )
        try:
            snapshot = self._read_snapshot()
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return LockInspection(
                path=self._path,
                exists=True,
                metadata=None,
                stale=False,
                recoverable=False,
                error=str(error),
            )
        if snapshot is None:
            return LockInspection(
                path=self._path,
                exists=False,
                metadata=None,
                stale=False,
                recoverable=False,
            )
        stale = self._is_stale(snapshot.metadata)
        return LockInspection(
            path=self._path,
            exists=True,
            metadata=snapshot.metadata,
            stale=stale,
            recoverable=stale,
        )

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()

    def _create_exclusive(self, metadata: LockMetadata) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self._path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(asdict(metadata), stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            self._path.unlink(missing_ok=True)
            raise

    def _read_snapshot(self) -> _LockSnapshot | None:
        try:
            file_stat = self._path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("lock path is not a regular file")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self._path, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            opened_stat = os.fstat(stream.fileno())
            if _stat_signature(opened_stat) != _stat_signature(file_stat):
                raise ValueError("lock file changed while it was opened")
            value = json.load(stream)
        return _LockSnapshot(
            metadata=LockMetadata.from_mapping(value),
            signature=_stat_signature(opened_stat),
        )

    def _remove_unchanged(self, snapshot: _LockSnapshot) -> bool:
        try:
            current = self._path.lstat()
        except FileNotFoundError:
            return False
        if _stat_signature(current) != snapshot.signature:
            return False
        try:
            self._path.unlink()
        except FileNotFoundError:
            return False
        return True

    def _is_stale(self, metadata: LockMetadata) -> bool:
        age = self._utc_now() - _parse_timestamp(metadata.created_at)
        return age >= self._stale_after and not self._process_alive(metadata.pid)

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("lock clock must return a timezone-aware datetime")
        return value.astimezone(UTC)


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("lock created_at must include a timezone")
    return parsed.astimezone(UTC)


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
