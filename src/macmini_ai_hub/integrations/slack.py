"""Slack Socket Mode adapter and idempotent outbound delivery.

Importing this module does not import Slack Bolt and never starts a connection.
`SlackSocketModeService.build` and `start` are the explicit integration boundary.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Protocol, cast
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from macmini_ai_hub.config.models import Identifier
from macmini_ai_hub.domain.tasks import TaskId, TaskStatus
from macmini_ai_hub.gateway.models import (
    GatewayCode,
    GatewayCommand,
    GatewayRequest,
    GatewayResponse,
    OpaqueId,
)
from macmini_ai_hub.gateway.security import redact_sensitive_text

if TYPE_CHECKING:
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
    from slack_bolt.async_app import AsyncApp

SafeLine = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=500,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]

_LEADING_MENTION = re.compile(r"^<@[A-Z0-9]+>\s*", re.IGNORECASE)
_TASK_ID_PATTERN = re.compile(r"^TASK-[A-Z0-9][A-Z0-9-]*$")
_SLACK_ROUTE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_SLACK_ROUTE_TARGET_PREFIX = "slack-v1:"
_NO_THREAD = "_"
_MAX_STORED_ROUTE_LENGTH = 200


class SlackCommandError(ValueError):
    """Safe-to-display command validation failure."""


class SlackDeliveryFailed(RuntimeError):
    pass


class DeliveryOutcome(StrEnum):
    SENT = "sent"
    DUPLICATE = "duplicate"
    IN_PROGRESS = "in_progress"


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SlackRoute(StrictFrozenModel):
    channel: OpaqueId
    thread_ts: OpaqueId | None = None


class SlackDeliveryRequest(StrictFrozenModel):
    delivery_id: OpaqueId
    route: SlackRoute
    text: Annotated[
        str,
        StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=20_000),
    ]

    @property
    def client_message_id(self) -> str:
        return str(uuid5(NAMESPACE_URL, f"macmini-ai-hub:{self.delivery_id}"))


class TaskLifecycleUpdate(StrictFrozenModel):
    """Observable task update suitable for Slack; no prompt or hidden reasoning."""

    notification_id: OpaqueId
    task_id: TaskId
    status: TaskStatus
    project: Identifier
    team: Identifier
    summary: tuple[SafeLine, ...] = Field(default=(), max_length=20)
    changed_files: tuple[SafeLine, ...] = Field(default=(), max_length=20)
    tests: tuple[SafeLine, ...] = Field(default=(), max_length=20)
    runtime_outcome: SafeLine | None = None
    branch: SafeLine | None = None
    error: SafeLine | None = None


def encode_slack_route_target(route: SlackRoute) -> str:
    """Encode one validated Slack reply route into the opaque storage field."""

    components = (
        (route.channel, route.thread_ts) if route.thread_ts is not None else (route.channel,)
    )
    if any(
        _SLACK_ROUTE_COMPONENT.fullmatch(component) is None
        or redact_sensitive_text(component) != component
        for component in components
    ):
        raise ValueError("Slack route contains an unsupported or secret-shaped component")
    target = f"{_SLACK_ROUTE_TARGET_PREFIX}{route.channel}:{route.thread_ts or _NO_THREAD}"
    if len(target) > _MAX_STORED_ROUTE_LENGTH:
        raise ValueError("Slack route exceeds the durable target limit")
    return target


def decode_slack_route_target(target: str) -> SlackRoute:
    """Decode current and legacy Slack route targets without guessing structure."""

    if target.startswith(_SLACK_ROUTE_TARGET_PREFIX):
        encoded = target.removeprefix(_SLACK_ROUTE_TARGET_PREFIX)
        channel, separator, thread = encoded.partition(":")
        if (
            not separator
            or _SLACK_ROUTE_COMPONENT.fullmatch(channel) is None
            or (thread != _NO_THREAD and _SLACK_ROUTE_COMPONENT.fullmatch(thread) is None)
        ):
            raise ValueError("stored Slack route target is invalid")
        return SlackRoute(channel=channel, thread_ts=None if thread == _NO_THREAD else thread)
    if target.startswith("channel:"):
        return SlackRoute(channel=target.removeprefix("channel:"))
    return SlackRoute(channel=target)


class GatewayHandler(Protocol):
    async def handle(self, request: GatewayRequest) -> GatewayResponse: ...


class SlackMessageSender(Protocol):
    async def send(
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None,
        client_message_id: str,
    ) -> None: ...


class SlackWebApiClient(Protocol):
    async def chat_postMessage(
        self,
        *,
        channel: str,
        text: str,
        client_msg_id: str,
        thread_ts: str | None = None,
    ) -> object: ...


class SlackDeliveryPort(Protocol):
    async def deliver(self, request: SlackDeliveryRequest) -> DeliveryOutcome: ...


class DeliveryReceiptStore(Protocol):
    async def is_delivered(self, delivery_id: str) -> bool: ...

    async def reserve(self, delivery_id: str) -> bool: ...

    async def mark_delivered(self, delivery_id: str) -> None: ...

    async def release(self, delivery_id: str) -> None: ...


class InMemoryDeliveryReceiptStore:
    """Process-local fallback; a durable adapter is required for reboot replay."""

    def __init__(self) -> None:
        self._delivered: set[str] = set()
        self._in_flight: set[str] = set()
        self._lock = asyncio.Lock()

    async def is_delivered(self, delivery_id: str) -> bool:
        async with self._lock:
            return delivery_id in self._delivered

    async def reserve(self, delivery_id: str) -> bool:
        async with self._lock:
            if delivery_id in self._delivered or delivery_id in self._in_flight:
                return False
            self._in_flight.add(delivery_id)
            return True

    async def mark_delivered(self, delivery_id: str) -> None:
        async with self._lock:
            self._in_flight.discard(delivery_id)
            self._delivered.add(delivery_id)

    async def release(self, delivery_id: str) -> None:
        async with self._lock:
            self._in_flight.discard(delivery_id)


class RetryingSlackDelivery:
    """Redacted, bounded-retry delivery with stable Slack client message IDs."""

    def __init__(
        self,
        sender: SlackMessageSender,
        *,
        receipts: DeliveryReceiptStore | None = None,
        max_attempts: int = 3,
        base_delay_seconds: float = 0.25,
        max_retry_delay_seconds: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must not be negative")
        if max_retry_delay_seconds < 0:
            raise ValueError("max_retry_delay_seconds must not be negative")
        self._sender = sender
        self._receipts = receipts or InMemoryDeliveryReceiptStore()
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._max_retry_delay_seconds = max_retry_delay_seconds
        self._sleep = sleep

    async def deliver(self, request: SlackDeliveryRequest) -> DeliveryOutcome:
        if await self._receipts.is_delivered(request.delivery_id):
            return DeliveryOutcome.DUPLICATE
        if not await self._receipts.reserve(request.delivery_id):
            return DeliveryOutcome.IN_PROGRESS

        safe_text = redact_sensitive_text(request.text)
        try:
            for attempt in range(1, self._max_attempts + 1):
                try:
                    await self._sender.send(
                        channel=request.route.channel,
                        text=safe_text,
                        thread_ts=request.route.thread_ts,
                        client_message_id=request.client_message_id,
                    )
                except Exception as error:
                    status_code = _slack_http_status(error)
                    if status_code is not None and 400 <= status_code < 500 and status_code != 429:
                        raise SlackDeliveryFailed("Slack message delivery failed") from None
                    if attempt == self._max_attempts:
                        raise SlackDeliveryFailed("Slack message delivery failed") from None
                    retry_after = _slack_retry_after_seconds(error) if status_code == 429 else None
                    delay = (
                        retry_after
                        if retry_after is not None
                        else self._base_delay_seconds * (2 ** (attempt - 1))
                    )
                    await self._sleep(min(delay, self._max_retry_delay_seconds))
                else:
                    await self._receipts.mark_delivered(request.delivery_id)
                    return DeliveryOutcome.SENT
        except BaseException:
            await self._receipts.release(request.delivery_id)
            raise
        raise AssertionError("delivery loop ended unexpectedly")


def _slack_http_status(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int) and not isinstance(status_code, bool):
        return status_code
    return None


def _slack_retry_after_seconds(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return None
    raw_value: object | None = None
    for name, value in headers.items():
        if isinstance(name, str) and name.lower() == "retry-after":
            raw_value = value
            break
    if isinstance(raw_value, (tuple, list)) and raw_value:
        raw_value = raw_value[0]
    if not isinstance(raw_value, (str, int, float)) or isinstance(raw_value, bool):
        return None
    try:
        seconds = float(raw_value)
    except ValueError:
        return None
    return seconds if seconds >= 0 and math.isfinite(seconds) else None


class SlackWebClientSender:
    """Narrow wrapper over Slack's async WebClient, constructed only after build."""

    def __init__(self, client: SlackWebApiClient) -> None:
        self._client = client

    async def send(
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None,
        client_message_id: str,
    ) -> None:
        await self._client.chat_postMessage(
            channel=channel,
            text=text,
            client_msg_id=client_message_id,
            thread_ts=thread_ts,
        )


class SlackTaskNotifier:
    """Formats lifecycle/result projections and sends them idempotently."""

    def __init__(self, delivery: SlackDeliveryPort) -> None:
        self._delivery = delivery

    async def notify(
        self,
        *,
        route: SlackRoute,
        update: TaskLifecycleUpdate,
    ) -> DeliveryOutcome:
        return await self._delivery.deliver(
            SlackDeliveryRequest(
                delivery_id=f"task-update:{update.notification_id}",
                route=route,
                text=format_task_update(update),
            )
        )


def format_task_update(update: TaskLifecycleUpdate) -> str:
    lines = [
        f"{update.task_id} {update.status.value}",
        f"Project: {update.project}",
        f"Team: {update.team}",
    ]
    if update.summary:
        lines.append("Summary:")
        lines.extend(f"- {item}" for item in update.summary)
    if update.changed_files:
        lines.append("Changed files:")
        lines.extend(f"- {item}" for item in update.changed_files)
    if update.tests:
        lines.append("Tests:")
        lines.extend(f"- {item}" for item in update.tests)
    if update.runtime_outcome is not None:
        lines.append(f"Runtime: {update.runtime_outcome}")
    if update.branch is not None:
        lines.append(f"Branch: {update.branch}")
    if update.error is not None:
        lines.append(f"Error: {update.error}")
    return redact_sensitive_text("\n".join(lines))


def parse_slack_command(
    text: str,
    *,
    source_event_id: str,
    actor_id: str,
    reply_target: str,
    bot_user_id: str | None = None,
) -> GatewayRequest:
    cleaned = text.strip()
    if bot_user_id is None:
        cleaned = _LEADING_MENTION.sub("", cleaned, count=1)
    else:
        cleaned = re.sub(
            rf"^<@{re.escape(bot_user_id)}>\s*",
            "",
            cleaned,
            count=1,
            flags=re.IGNORECASE,
        )
    if not cleaned:
        cleaned = GatewayCommand.HELP.value

    command_name, *remainder = cleaned.split(maxsplit=1)
    try:
        command = GatewayCommand(command_name.lower())
    except ValueError as exc:
        raise SlackCommandError(
            "Unknown command. Use: help, dev, status, task, tasks, or stop."
        ) from exc

    fields: dict[str, object] = {
        "source": "slack",
        "source_event_id": source_event_id,
        "actor_id": actor_id,
        "reply_target": reply_target,
        "command": command,
    }
    arguments = remainder[0].strip() if remainder else ""
    if command is GatewayCommand.DEV:
        dev_parts = arguments.split(maxsplit=1)
        if len(dev_parts) != 2:
            raise SlackCommandError("Usage: dev <project> <instruction>")
        fields["project"], fields["instruction"] = dev_parts
    elif command in {GatewayCommand.TASK, GatewayCommand.STOP}:
        normalized_task_id = arguments.upper()
        if not _TASK_ID_PATTERN.fullmatch(normalized_task_id):
            raise SlackCommandError(f"Usage: {command.value} <TASK-ID>")
        fields["task_id"] = normalized_task_id
    elif arguments:
        raise SlackCommandError(f"{command.value} does not accept arguments")

    try:
        return GatewayRequest.model_validate(fields)
    except ValidationError as exc:
        raise SlackCommandError("The command contains invalid identifiers or text.") from exc


class SlackSocketModeService:
    """Explicitly started Slack Bolt service with non-blocking event listeners."""

    def __init__(
        self,
        *,
        gateway: GatewayHandler,
        bot_token: str,
        app_token: str,
        delivery: SlackDeliveryPort | None = None,
        receipts: DeliveryReceiptStore | None = None,
        bot_user_id: str | None = None,
        on_background_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        if not bot_token.strip() or not app_token.strip():
            raise ValueError("Slack bot and app tokens are required")
        self._gateway = gateway
        self._bot_token = bot_token
        self._app_token = app_token
        self._delivery = delivery
        self._receipts = receipts
        self._bot_user_id = bot_user_id
        self._on_background_error = on_background_error or (lambda error: None)
        self._background: set[asyncio.Task[None]] = set()
        self._app: AsyncApp | None = None
        self._handler: AsyncSocketModeHandler | None = None

    @property
    def background_task_count(self) -> int:
        return len(self._background)

    @property
    def delivery(self) -> SlackDeliveryPort:
        """Return the configured delivery port after ``build`` has completed."""

        if self._delivery is None:
            raise RuntimeError("Slack service has not been built")
        return self._delivery

    def build(self) -> AsyncSocketModeHandler:
        """Import and configure Slack Bolt without connecting to Slack."""

        if self._handler is not None:
            return self._handler

        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
        from slack_bolt.async_app import AsyncApp

        app = AsyncApp(token=self._bot_token)
        if self._delivery is None:
            web_client = cast(SlackWebApiClient, app.client)
            self._delivery = RetryingSlackDelivery(
                SlackWebClientSender(web_client),
                receipts=self._receipts,
            )

        @app.event("app_mention")
        async def handle_app_mention(
            body: dict[str, object],
            event: dict[str, object],
        ) -> None:
            self.accept_event(body=body, event=event)

        self._app = app
        self._handler = AsyncSocketModeHandler(app, self._app_token)
        return self._handler

    async def start(self) -> None:
        """Connect and run until the Slack handler is closed."""

        start = cast(Callable[[], Awaitable[None]], self.build().start_async)
        await start()

    async def stop(self) -> None:
        if self._handler is not None:
            close = cast(Callable[[], Awaitable[None]], self._handler.close_async)
            await close()
        tasks = tuple(self._background)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def accept_event(
        self,
        *,
        body: Mapping[str, object],
        event: Mapping[str, object],
    ) -> asyncio.Task[None] | None:
        """Schedule processing and return immediately to the Bolt listener."""

        if event.get("bot_id") is not None or event.get("subtype") == "bot_message":
            return None
        task = asyncio.create_task(self._process_event(body=body, event=event))
        self._background.add(task)
        task.add_done_callback(self._finish_background_task)
        return task

    async def drain(self) -> None:
        """Wait for currently scheduled work; useful for graceful shutdown/tests."""

        while self._background:
            await asyncio.gather(*tuple(self._background), return_exceptions=True)

    def _finish_background_task(self, task: asyncio.Task[None]) -> None:
        self._background.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._on_background_error(error)

    async def _process_event(
        self,
        *,
        body: Mapping[str, object],
        event: Mapping[str, object],
    ) -> None:
        channel = _first_string(event, "channel")
        actor_id = _first_string(event, "user")
        source_event_id = _first_string(body, "event_id") or _first_string(
            event, "client_msg_id", "event_ts", "ts"
        )
        text = _first_string(event, "text")
        if channel is None or source_event_id is None:
            raise SlackCommandError("Slack event is missing delivery metadata.")

        thread_ts = _first_string(event, "thread_ts", "ts")
        route = SlackRoute(channel=channel, thread_ts=thread_ts)
        if actor_id is None or text is None:
            response = GatewayResponse(
                success=False,
                code=GatewayCode.INVALID_REQUEST,
                message="Slack event is missing actor or command text.",
            )
        else:
            try:
                request = parse_slack_command(
                    text,
                    source_event_id=source_event_id,
                    actor_id=actor_id,
                    reply_target=encode_slack_route_target(route),
                    bot_user_id=self._bot_user_id,
                )
            except SlackCommandError as exc:
                response = GatewayResponse(
                    success=False,
                    code=GatewayCode.INVALID_REQUEST,
                    message=redact_sensitive_text(str(exc)),
                )
            else:
                response = await self._gateway.handle(request)

        delivery = self._delivery
        if delivery is None:
            raise RuntimeError("Slack service must be built or given a delivery adapter")
        await delivery.deliver(
            SlackDeliveryRequest(
                delivery_id=f"slack-event:{source_event_id}:gateway-response",
                route=route,
                text=response.message,
            )
        )


def _first_string(values: Mapping[str, object], *names: str) -> str | None:
    for name in names:
        value = values.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
