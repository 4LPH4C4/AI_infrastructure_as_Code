"""Storage records that complement the dependency-light domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from macmini_ai_hub.config.models import Identifier
from macmini_ai_hub.domain.events import EventEnvelope
from macmini_ai_hub.domain.tasks import Task, TaskId

RunId = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=5,
        max_length=68,
        pattern=r"^RUN-[A-Z0-9][A-Z0-9-]*$",
    ),
]
ArtifactId = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=5,
        max_length=68,
        pattern=r"^ART-[A-Z0-9][A-Z0-9-]*$",
    ),
]
ContentType = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=3,
        max_length=200,
        pattern=r"^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+$",
    ),
]
Sha256 = Annotated[
    str,
    StringConstraints(strict=True, to_lower=True, pattern=r"^[0-9a-f]{64}$"),
]
IdempotencyKey = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
OpaqueRouteValue = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]

_FORBIDDEN_RESPONSE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "cookie",
        "credentials",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "token",
    }
)
_FORBIDDEN_RESPONSE_SUFFIXES = (
    "_password",
    "_secret",
    "_token",
    "_api_key",
    "_private_key",
)


def _find_forbidden_key(value: JsonValue, path: str = "response") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("-", "_")
            if normalized in _FORBIDDEN_RESPONSE_KEYS or normalized.endswith(
                _FORBIDDEN_RESPONSE_SUFFIXES
            ):
                return f"{path}.{key}"
            if found := _find_forbidden_key(child, f"{path}.{key}"):
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if found := _find_forbidden_key(child, f"{path}[{index}]"):
                return found
    return None


def _reject_secret_shaped_value(value: str, field_name: str) -> str:
    lowered = value.lower()
    secret_prefixes = ("sk-", "xapp-", "xoxa-", "xoxb-", "xoxp-", "xoxr-", "xoxs-")
    secret_markers = ("api_key", "apikey", "password", "private_key", "secret=", "token=")
    if lowered.startswith(secret_prefixes) or any(marker in lowered for marker in secret_markers):
        raise ValueError(f"{field_name} must not contain a secret-shaped value")
    return value


class StorageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed-out"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"

    @property
    def is_terminal(self) -> bool:
        return self not in {self.QUEUED, self.RUNNING}


class RunRecord(StorageModel):
    run_id: RunId
    task_id: TaskId
    agent: Identifier
    runtime: Identifier
    status: RunStatus = RunStatus.QUEUED
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    exit_code: StrictInt | None = None
    error_code: Identifier | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at must not precede created_at")
        if self.status is self.status.QUEUED:
            if self.started_at is not None or self.completed_at is not None:
                raise ValueError("queued runs must not have execution timestamps")
        elif self.status is self.status.RUNNING:
            if self.started_at is None or self.completed_at is not None:
                raise ValueError("running runs require started_at and no completed_at")
        elif self.started_at is None or self.completed_at is None:
            raise ValueError("terminal runs require started_at and completed_at")
        if (
            self.completed_at is not None
            and self.started_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at must not precede started_at")
        if self.status is self.status.SUCCEEDED and self.error_code is not None:
            raise ValueError("successful runs must not have an error_code")
        return self


class ArtifactMetadata(StorageModel):
    artifact_id: ArtifactId
    task_id: TaskId
    run_id: RunId | None = None
    kind: Identifier
    path: str
    content_type: ContentType
    size_bytes: Annotated[StrictInt, Field(ge=0)]
    sha256: Sha256
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("artifact path must use POSIX separators")
        path = PurePosixPath(value)
        if path.is_absolute() or value in {"", "."} or ".." in path.parts:
            raise ValueError("artifact path must be a safe relative path")
        return path.as_posix()


class StoredEvent(StorageModel):
    sequence: Annotated[StrictInt, Field(ge=1)]
    envelope: EventEnvelope


class ReconciliationResult(StorageModel):
    interrupted_runs: tuple[RunRecord, ...] = ()
    blocked_tasks: tuple[Task, ...] = ()
    emitted_events: tuple[StoredEvent, ...] = ()


class GatewayRequestRecord(StorageModel):
    idempotency_key: IdempotencyKey
    response: dict[str, JsonValue] | None = None
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("response")
    @classmethod
    def reject_secret_response_fields(
        cls, value: dict[str, JsonValue] | None
    ) -> dict[str, JsonValue] | None:
        if value is not None and (forbidden := _find_forbidden_key(value)):
            raise ValueError(f"gateway response must not contain secret field {forbidden!r}")
        return value


class TaskRoute(StorageModel):
    task_id: TaskId
    source: OpaqueRouteValue
    target: OpaqueRouteValue

    @field_validator("source", "target")
    @classmethod
    def reject_secret_values(cls, value: str, info: object) -> str:
        return _reject_secret_shaped_value(value, str(getattr(info, "field_name", "route")))


class DeliveryState(StrEnum):
    RESERVED = "reserved"
    DELIVERED = "delivered"


class DeliveryReceipt(StorageModel):
    delivery_id: OpaqueRouteValue
    state: DeliveryState = DeliveryState.RESERVED
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    delivered_at: AwareDatetime | None = None

    @field_validator("delivery_id")
    @classmethod
    def reject_secret_delivery_id(cls, value: str) -> str:
        return _reject_secret_shaped_value(value, "delivery_id")

    @model_validator(mode="after")
    def validate_delivery_state(self) -> Self:
        if self.state is DeliveryState.RESERVED and self.delivered_at is not None:
            raise ValueError("reserved delivery must not have delivered_at")
        if self.state is DeliveryState.DELIVERED and self.delivered_at is None:
            raise ValueError("delivered receipt requires delivered_at")
        if self.delivered_at is not None and self.delivered_at < self.created_at:
            raise ValueError("delivered_at must not precede created_at")
        return self
