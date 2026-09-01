"""Source-neutral Agent Gateway application service."""

from __future__ import annotations

import logging
from collections import Counter
from uuid import NAMESPACE_URL, uuid5

from macmini_ai_hub.domain.tasks import TaskId
from macmini_ai_hub.gateway.models import (
    CancelTaskCommand,
    CreateTaskCommand,
    GatewayCode,
    GatewayCommand,
    GatewayRequest,
    GatewayResponse,
    TaskView,
)
from macmini_ai_hub.gateway.ports import (
    ActorAuthorizer,
    DependencyUnavailableError,
    RequestDeduplicator,
    TaskCommandPort,
    TaskConflictError,
    TaskEnqueuePort,
    TaskIdFactory,
    TaskNotFoundError,
    TaskQueryPort,
)
from macmini_ai_hub.gateway.security import contains_sensitive_material

_HELP = (
    "Commands: help | dev <project> <instruction> | status | tasks | "
    "task <TASK-ID> | stop <TASK-ID>"
)
_LOGGER = logging.getLogger(__name__)


class UuidTaskIdFactory:
    def new(self, idempotency_key: str) -> TaskId:
        value = uuid5(NAMESPACE_URL, f"macmini-ai-hub:gateway:{idempotency_key}")
        return f"TASK-{value.hex.upper()}"


class AgentGateway:
    def __init__(
        self,
        *,
        authorizer: ActorAuthorizer,
        commands: TaskCommandPort,
        queries: TaskQueryPort,
        enqueuer: TaskEnqueuePort,
        deduplicator: RequestDeduplicator,
        task_ids: TaskIdFactory | None = None,
    ) -> None:
        self._authorizer = authorizer
        self._commands = commands
        self._queries = queries
        self._enqueuer = enqueuer
        self._deduplicator = deduplicator
        self._task_ids = task_ids or UuidTaskIdFactory()

    async def handle(self, request: GatewayRequest) -> GatewayResponse:
        try:
            authorized = await self._authorizer.is_authorized(
                actor_id=request.actor_id,
                command=request.command,
                project=request.project,
            )
        except Exception:
            return GatewayResponse(
                success=False,
                code=GatewayCode.UNAVAILABLE,
                message="Authorization is temporarily unavailable.",
            )
        if not authorized:
            return GatewayResponse(
                success=False,
                code=GatewayCode.UNAUTHORIZED,
                message="This actor is not authorized to use the AI Hub.",
            )
        if request.instruction is not None and contains_sensitive_material(request.instruction):
            return GatewayResponse(
                success=False,
                code=GatewayCode.INVALID_REQUEST,
                message="Task instructions must not contain credential material.",
            )

        try:
            cached = await self._deduplicator.get(request.idempotency_key)
        except Exception:
            return GatewayResponse(
                success=False,
                code=GatewayCode.UNAVAILABLE,
                message="Request deduplication is temporarily unavailable.",
            )
        if cached is not None:
            return cached.model_copy(update={"replayed": True})
        try:
            reserved = await self._deduplicator.reserve(request.idempotency_key)
        except Exception:
            return GatewayResponse(
                success=False,
                code=GatewayCode.UNAVAILABLE,
                message="Request deduplication is temporarily unavailable.",
            )
        if not reserved:
            return GatewayResponse(
                success=True,
                code=GatewayCode.DUPLICATE,
                message="This request is already being processed.",
                replayed=True,
            )

        try:
            response = await self._dispatch(request)
        except TaskNotFoundError:
            response = GatewayResponse(
                success=False,
                code=GatewayCode.NOT_FOUND,
                message="The requested task was not found.",
            )
        except TaskConflictError:
            response = GatewayResponse(
                success=False,
                code=GatewayCode.CONFLICT,
                message="The task cannot be changed from its current state.",
            )
        except DependencyUnavailableError:
            response = GatewayResponse(
                success=False,
                code=GatewayCode.UNAVAILABLE,
                message="A required AI Hub component is temporarily unavailable.",
            )
        except Exception:  # An interface must never receive adapter exception details.
            response = GatewayResponse(
                success=False,
                code=GatewayCode.INTERNAL_ERROR,
                message="The AI Hub could not process this request safely.",
            )
        except BaseException:
            try:
                await self._deduplicator.release(request.idempotency_key)
            except Exception:
                _LOGGER.exception("failed to release interrupted gateway reservation")
            raise

        if response.code in {GatewayCode.UNAVAILABLE, GatewayCode.INTERNAL_ERROR}:
            try:
                await self._deduplicator.release(request.idempotency_key)
            except Exception:
                _LOGGER.exception("failed to release transient gateway reservation")
            return response

        try:
            await self._deduplicator.remember(request.idempotency_key, response)
        except Exception:
            return GatewayResponse(
                success=False,
                code=GatewayCode.UNAVAILABLE,
                message=(
                    "The request was processed, but its response receipt could not be stored. "
                    "Check task status before retrying."
                ),
                task=response.task,
                tasks=response.tasks,
            )
        return response

    async def _dispatch(self, request: GatewayRequest) -> GatewayResponse:
        if request.command is GatewayCommand.HELP:
            return GatewayResponse(success=True, code=GatewayCode.OK, message=_HELP)
        if request.command is GatewayCommand.DEV:
            return await self._create_task(request)
        if request.command is GatewayCommand.TASK:
            return await self._task_detail(request)
        if request.command is GatewayCommand.TASKS:
            return await self._task_list()
        if request.command is GatewayCommand.STATUS:
            return await self._status()
        if request.command is GatewayCommand.STOP:
            return await self._cancel(request)
        raise AssertionError(f"unhandled gateway command: {request.command!r}")

    async def _create_task(self, request: GatewayRequest) -> GatewayResponse:
        if request.project is None or request.instruction is None:
            raise ValueError("validated dev request is missing required fields")
        command = CreateTaskCommand(
            task_id=self._task_ids.new(request.idempotency_key),
            source=request.source,
            source_event_id=request.source_event_id,
            actor_id=request.actor_id,
            reply_target=request.reply_target,
            project=request.project,
            instruction=request.instruction,
        )
        task = await self._commands.create_task(command)
        try:
            task = await self._enqueuer.enqueue_task(task.task_id)
        except Exception:
            return GatewayResponse(
                success=False,
                code=GatewayCode.UNAVAILABLE,
                message=(
                    f"Task {task.task_id} was saved but could not be queued. "
                    "Check its status before retrying."
                ),
                task=task,
            )
        return GatewayResponse(
            success=True,
            code=GatewayCode.ACCEPTED,
            message=(
                f"Task created. ID: {task.task_id}; project: {task.project}; "
                f"team: {task.team}; status: {task.status.value}."
            ),
            task=task,
        )

    async def _task_detail(self, request: GatewayRequest) -> GatewayResponse:
        if request.task_id is None:
            raise ValueError("validated task request is missing task_id")
        task = await self._queries.get_task(request.task_id)
        if task is None:
            raise TaskNotFoundError(request.task_id)
        return GatewayResponse(
            success=True,
            code=GatewayCode.OK,
            message=_format_task(task),
            task=task,
        )

    async def _task_list(self) -> GatewayResponse:
        tasks = await self._queries.list_tasks(limit=20)
        message = (
            "No tasks found." if not tasks else "\n".join(_format_task(task) for task in tasks)
        )
        return GatewayResponse(
            success=True,
            code=GatewayCode.OK,
            message=message,
            tasks=tasks,
        )

    async def _status(self) -> GatewayResponse:
        tasks = await self._queries.list_tasks(limit=100)
        counts = Counter(task.status.value for task in tasks)
        if not counts:
            message = "AI Hub is available. No tasks are recorded."
        else:
            summary = ", ".join(f"{status}={counts[status]}" for status in sorted(counts))
            message = f"AI Hub is available. Task status: {summary}."
        return GatewayResponse(
            success=True,
            code=GatewayCode.OK,
            message=message,
            tasks=tasks,
        )

    async def _cancel(self, request: GatewayRequest) -> GatewayResponse:
        if request.task_id is None:
            raise ValueError("validated stop request is missing task_id")
        task = await self._commands.cancel_task(
            CancelTaskCommand(
                task_id=request.task_id,
                source=request.source,
                source_event_id=request.source_event_id,
                actor_id=request.actor_id,
            )
        )
        return GatewayResponse(
            success=True,
            code=GatewayCode.OK,
            message=f"Cancellation recorded for {task.task_id}; status: {task.status.value}.",
            task=task,
        )


def _format_task(task: TaskView) -> str:
    return f"{task.task_id}: project={task.project}; team={task.team}; status={task.status.value}"
