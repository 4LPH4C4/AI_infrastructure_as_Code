"""Ports used by the source-neutral gateway application service."""

from __future__ import annotations

from typing import Protocol

from pydantic import JsonValue

from macmini_ai_hub.config.models import Identifier
from macmini_ai_hub.domain.tasks import TaskId
from macmini_ai_hub.gateway.models import (
    CancelTaskCommand,
    CreateTaskCommand,
    GatewayCommand,
    GatewayResponse,
    OpaqueId,
    TaskView,
)


class GatewayPortError(RuntimeError):
    """Expected adapter failure that is safe to classify, but not to echo."""


class TaskNotFoundError(GatewayPortError):
    pass


class TaskConflictError(GatewayPortError):
    pass


class DependencyUnavailableError(GatewayPortError):
    pass


class ActorAuthorizer(Protocol):
    async def is_authorized(
        self,
        *,
        actor_id: OpaqueId,
        command: GatewayCommand,
        project: Identifier | None,
    ) -> bool: ...


class TaskCommandPort(Protocol):
    async def create_task(self, command: CreateTaskCommand) -> TaskView: ...

    async def cancel_task(self, command: CancelTaskCommand) -> TaskView: ...


class TaskQueryPort(Protocol):
    async def get_task(self, task_id: TaskId) -> TaskView | None: ...

    async def list_tasks(self, *, limit: int) -> tuple[TaskView, ...]: ...


class TaskEnqueuePort(Protocol):
    async def enqueue_task(self, task_id: TaskId) -> TaskView: ...


class RequestDeduplicator(Protocol):
    """Atomic reservation plus completed-response replay for source events."""

    async def get(self, key: str) -> GatewayResponse | None: ...

    async def reserve(self, key: str) -> bool: ...

    async def remember(self, key: str, response: GatewayResponse) -> None: ...

    async def release(self, key: str) -> None: ...


class StoredGatewayRequest(Protocol):
    @property
    def response(self) -> dict[str, JsonValue] | None: ...


class GatewayRequestStore(Protocol):
    """Synchronous durable subset implemented by the Phase 1 SQLite store."""

    def get_gateway_request(self, idempotency_key: str) -> StoredGatewayRequest | None: ...

    def reserve_gateway_request(self, idempotency_key: str) -> bool: ...

    def remember_gateway_response(
        self,
        idempotency_key: str,
        response: dict[str, JsonValue],
    ) -> object: ...

    def release_gateway_request(self, idempotency_key: str) -> bool: ...

    def reconcile_incomplete_gateway_requests(self) -> tuple[str, ...]: ...


class TaskIdFactory(Protocol):
    def new(self, idempotency_key: str) -> TaskId: ...
