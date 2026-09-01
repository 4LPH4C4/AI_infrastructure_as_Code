from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

import pytest

from macmini_ai_hub.domain.tasks import TaskStatus
from macmini_ai_hub.gateway import GatewayCode, GatewayCommand, GatewayRequest, GatewayResponse
from macmini_ai_hub.integrations.slack import (
    DeliveryOutcome,
    RetryingSlackDelivery,
    SlackCommandError,
    SlackDeliveryFailed,
    SlackDeliveryRequest,
    SlackRoute,
    SlackSocketModeService,
    SlackTaskNotifier,
    TaskLifecycleUpdate,
    decode_slack_route_target,
    encode_slack_route_target,
    format_task_update,
    parse_slack_command,
)


@dataclass
class CapturingDelivery:
    requests: list[SlackDeliveryRequest] = field(default_factory=list)

    async def deliver(self, request: SlackDeliveryRequest) -> DeliveryOutcome:
        self.requests.append(request)
        return DeliveryOutcome.SENT


@dataclass
class CapturingSender:
    failures_remaining: int = 0
    calls: list[tuple[str, str, str | None, str]] = field(default_factory=list)

    async def send(
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None,
        client_message_id: str,
    ) -> None:
        self.calls.append((channel, text, thread_ts, client_message_id))
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("Slack failed with token=xoxb-never-expose")


@dataclass
class FakeSlackResponse:
    status_code: int
    headers: dict[str, object] = field(default_factory=dict)


class FakeSlackHttpError(RuntimeError):
    def __init__(self, status_code: int, *, headers: dict[str, object] | None = None) -> None:
        super().__init__("unsafe upstream Slack diagnostic")
        self.response = FakeSlackResponse(status_code, headers or {})


@dataclass
class ScriptedSender:
    errors: list[Exception]
    calls: int = 0

    async def send(
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None,
        client_message_id: str,
    ) -> None:
        del channel, text, thread_ts, client_message_id
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)


@dataclass
class CapturingGateway:
    requests: list[GatewayRequest] = field(default_factory=list)

    async def handle(self, request: GatewayRequest) -> GatewayResponse:
        self.requests.append(request)
        return GatewayResponse(
            success=True,
            code=GatewayCode.ACCEPTED,
            message="Task accepted.",
        )


class BlockingGateway:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def handle(self, request: GatewayRequest) -> GatewayResponse:
        del request
        self.started.set()
        await self.release.wait()
        return GatewayResponse(success=True, code=GatewayCode.OK, message="Finished safely.")


@pytest.mark.parametrize(
    ("text", "expected", "project", "task_id"),
    [
        ("<@UBOT> help", GatewayCommand.HELP, None, None),
        (
            "<@UBOT> dev example-project Create README_TEST.md",
            GatewayCommand.DEV,
            "example-project",
            None,
        ),
        ("status", GatewayCommand.STATUS, None, None),
        ("tasks", GatewayCommand.TASKS, None, None),
        ("task task-1042", GatewayCommand.TASK, None, "TASK-1042"),
        ("stop TASK-1042", GatewayCommand.STOP, None, "TASK-1042"),
    ],
)
def test_minimal_slack_commands_parse_to_source_neutral_requests(
    text: str,
    expected: GatewayCommand,
    project: str | None,
    task_id: str | None,
) -> None:
    request = parse_slack_command(
        text,
        source_event_id="Ev-1",
        actor_id="U123",
        reply_target="C123",
    )

    assert request.command is expected
    assert request.project == project
    assert request.task_id == task_id
    assert request.source == "slack"


def test_empty_mention_defaults_to_help_and_preserves_instruction() -> None:
    help_request = parse_slack_command(
        "<@USPECIFIC>",
        source_event_id="Ev-1",
        actor_id="U123",
        reply_target="C123",
        bot_user_id="USPECIFIC",
    )
    dev_request = parse_slack_command(
        "dev example-project 여러 단어가 있는 요청",
        source_event_id="Ev-2",
        actor_id="U123",
        reply_target="C123",
    )

    assert help_request.command is GatewayCommand.HELP
    assert dev_request.instruction == "여러 단어가 있는 요청"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("unknown", "Unknown command"),
        ("dev example-project", "Usage: dev"),
        ("task not-a-task", "Usage: task"),
        ("help unexpected", "does not accept arguments"),
    ],
)
def test_invalid_slack_commands_return_safe_parser_errors(text: str, message: str) -> None:
    with pytest.raises(SlackCommandError, match=message):
        parse_slack_command(
            text,
            source_event_id="Ev-1",
            actor_id="U123",
            reply_target="C123",
        )


def test_retrying_delivery_redacts_retries_and_is_idempotent() -> None:
    async def scenario() -> None:
        sender = CapturingSender(failures_remaining=2)
        delays: list[float] = []

        async def record_sleep(delay: float) -> None:
            delays.append(delay)

        delivery = RetryingSlackDelivery(
            sender,
            max_attempts=3,
            base_delay_seconds=0.5,
            sleep=record_sleep,
        )
        request = SlackDeliveryRequest(
            delivery_id="delivery-1",
            route=SlackRoute(channel="C123", thread_ts="171.1"),
            text="Done. Authorization: Bearer abcdefghijk secret=top-secret",
        )
        assert await delivery.deliver(request) is DeliveryOutcome.SENT
        assert await delivery.deliver(request) is DeliveryOutcome.DUPLICATE
        assert len(sender.calls) == 3
        assert delays == [0.5, 1.0]
        assert all("top-secret" not in call[1] for call in sender.calls)
        assert all("abcdefghijk" not in call[1] for call in sender.calls)
        assert len({call[3] for call in sender.calls}) == 1

    asyncio.run(scenario())


def test_delivery_exhaustion_releases_receipt_for_later_retry() -> None:
    async def scenario() -> None:
        sender = CapturingSender(failures_remaining=1)
        delivery = RetryingSlackDelivery(
            sender,
            max_attempts=1,
            base_delay_seconds=0,
        )
        request = SlackDeliveryRequest(
            delivery_id="delivery-recoverable",
            route=SlackRoute(channel="C123"),
            text="Safe status",
        )
        with pytest.raises(SlackDeliveryFailed, match="delivery failed"):
            await delivery.deliver(request)
        assert await delivery.deliver(request) is DeliveryOutcome.SENT

    asyncio.run(scenario())


def test_rate_limit_retry_after_is_honored_with_a_hard_delay_cap() -> None:
    async def scenario() -> None:
        sender = ScriptedSender(errors=[FakeSlackHttpError(429, headers={"Retry-After": "120"})])
        delays: list[float] = []

        async def record_sleep(delay: float) -> None:
            delays.append(delay)

        delivery = RetryingSlackDelivery(
            sender,
            max_attempts=2,
            base_delay_seconds=0.5,
            max_retry_delay_seconds=5,
            sleep=record_sleep,
        )
        outcome = await delivery.deliver(
            SlackDeliveryRequest(
                delivery_id="delivery-rate-limit",
                route=SlackRoute(channel="C123"),
                text="Safe status",
            )
        )

        assert outcome is DeliveryOutcome.SENT
        assert sender.calls == 2
        assert delays == [5]

    asyncio.run(scenario())


def test_non_retryable_slack_4xx_fails_immediately_and_safely() -> None:
    async def scenario() -> None:
        sender = ScriptedSender(errors=[FakeSlackHttpError(400)])
        delays: list[float] = []

        async def record_sleep(delay: float) -> None:
            delays.append(delay)

        delivery = RetryingSlackDelivery(
            sender,
            max_attempts=3,
            base_delay_seconds=0.5,
            sleep=record_sleep,
        )
        with pytest.raises(SlackDeliveryFailed, match="delivery failed") as captured:
            await delivery.deliver(
                SlackDeliveryRequest(
                    delivery_id="delivery-bad-request",
                    route=SlackRoute(channel="C123"),
                    text="Safe status",
                )
            )

        assert sender.calls == 1
        assert delays == []
        assert "upstream" not in str(captured.value)

    asyncio.run(scenario())


def test_task_notifier_formats_observable_result_and_deduplicates() -> None:
    async def scenario() -> None:
        sender = CapturingSender()
        notifier = SlackTaskNotifier(
            RetryingSlackDelivery(sender, max_attempts=1, base_delay_seconds=0)
        )
        update = TaskLifecycleUpdate(
            notification_id="event-42",
            task_id="TASK-1042",
            status=TaskStatus.COMPLETED,
            project="example-project",
            team="example-product",
            summary=("Created README_TEST.md",),
            changed_files=("README_TEST.md",),
            tests=("pytest passed",),
            runtime_outcome="codex: succeeded",
            branch="agent/TASK-1042-readme",
            error="token=must-not-leak",
        )
        first = await notifier.notify(route=SlackRoute(channel="C123"), update=update)
        duplicate = await notifier.notify(route=SlackRoute(channel="C123"), update=update)

        assert first is DeliveryOutcome.SENT
        assert duplicate is DeliveryOutcome.DUPLICATE
        assert len(sender.calls) == 1
        assert "TASK-1042 completed" in sender.calls[0][1]
        assert "Changed files:\n- README_TEST.md" in sender.calls[0][1]
        assert "Runtime: codex: succeeded" in sender.calls[0][1]
        assert "must-not-leak" not in sender.calls[0][1]
        assert "hidden" not in format_task_update(update).lower()

    asyncio.run(scenario())


def test_slack_route_target_round_trips_thread_and_supports_legacy_channels() -> None:
    route = SlackRoute(channel="C123", thread_ts="171.42")

    assert decode_slack_route_target(encode_slack_route_target(route)) == route
    assert decode_slack_route_target("channel:C456") == SlackRoute(channel="C456")
    assert decode_slack_route_target("C789") == SlackRoute(channel="C789")
    with pytest.raises(ValueError, match="unsupported"):
        encode_slack_route_target(SlackRoute(channel="ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"))


def test_socket_mode_listener_schedules_gateway_without_waiting_for_it() -> None:
    async def scenario() -> None:
        gateway = BlockingGateway()
        delivery = CapturingDelivery()
        service = SlackSocketModeService(
            gateway=gateway,
            bot_token="xoxb-test-value",
            app_token="xapp-test-value",
            delivery=delivery,
        )

        task = service.accept_event(
            body={"event_id": "Ev-1"},
            event={
                "user": "U123",
                "channel": "C123",
                "ts": "171.1",
                "text": "<@UBOT> status",
            },
        )
        assert task is not None
        await asyncio.wait_for(gateway.started.wait(), timeout=0.1)
        assert not task.done()
        assert service.background_task_count == 1

        gateway.release.set()
        await service.drain()
        assert delivery.requests[0].delivery_id == "slack-event:Ev-1:gateway-response"
        assert delivery.requests[0].route.thread_ts == "171.1"

    asyncio.run(scenario())


def test_socket_mode_service_forwards_request_metadata_and_safe_parser_error() -> None:
    async def scenario() -> None:
        gateway = CapturingGateway()
        delivery = CapturingDelivery()
        service = SlackSocketModeService(
            gateway=gateway,
            bot_token="xoxb-test-value",
            app_token="xapp-test-value",
            delivery=delivery,
            bot_user_id="UBOT",
        )
        service.accept_event(
            body={"event_id": "Ev-42"},
            event={
                "user": "U42",
                "channel": "C42",
                "ts": "171.42",
                "text": "<@UBOT> dev example-project do work",
            },
        )
        await service.drain()
        assert gateway.requests[0].source_event_id == "Ev-42"
        assert gateway.requests[0].actor_id == "U42"
        assert gateway.requests[0].reply_target is not None
        assert decode_slack_route_target(gateway.requests[0].reply_target) == SlackRoute(
            channel="C42",
            thread_ts="171.42",
        )

        service.accept_event(
            body={"event_id": "Ev-43"},
            event={
                "user": "U42",
                "channel": "C42",
                "ts": "171.43",
                "text": "<@UBOT> invalid password=hunter2",
            },
        )
        await service.drain()
        assert delivery.requests[-1].text.startswith("Unknown command")
        assert "hunter2" not in delivery.requests[-1].text

    asyncio.run(scenario())


def test_bot_messages_are_ignored_and_construction_does_not_import_slack_bolt() -> None:
    loaded_before = "slack_bolt.async_app" in sys.modules
    service = SlackSocketModeService(
        gateway=CapturingGateway(),
        bot_token="xoxb-test-value",
        app_token="xapp-test-value",
        delivery=CapturingDelivery(),
    )
    assert ("slack_bolt.async_app" in sys.modules) is loaded_before
    assert (
        service.accept_event(
            body={"event_id": "Ev-bot"},
            event={"bot_id": "B123", "channel": "C123", "text": "status"},
        )
        is None
    )


def test_background_event_errors_are_reported_without_crashing_listener() -> None:
    async def scenario() -> None:
        errors: list[BaseException] = []
        service = SlackSocketModeService(
            gateway=CapturingGateway(),
            bot_token="xoxb-test-value",
            app_token="xapp-test-value",
            delivery=CapturingDelivery(),
            on_background_error=errors.append,
        )
        task = service.accept_event(body={}, event={"user": "U123", "text": "status"})
        assert task is not None
        await service.drain()
        await asyncio.sleep(0)
        assert len(errors) == 1
        assert isinstance(errors[0], SlackCommandError)

    asyncio.run(scenario())
