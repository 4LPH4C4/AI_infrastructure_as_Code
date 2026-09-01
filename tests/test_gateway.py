from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from pydantic import JsonValue, ValidationError

from macmini_ai_hub.domain.tasks import TaskStatus
from macmini_ai_hub.gateway import (
    AgentGateway,
    AllowlistAuthorizer,
    CancelTaskCommand,
    CreateTaskCommand,
    DurableRequestDeduplicator,
    GatewayCode,
    GatewayCommand,
    GatewayRequest,
    GatewayResponse,
    InMemoryRequestDeduplicator,
    TaskConflictError,
    TaskView,
    redact_sensitive_text,
)


@dataclass
class FakeStoredRequest:
    response: dict[str, JsonValue] | None


@dataclass
class FakeGatewayRequestStore:
    records: dict[str, FakeStoredRequest] = field(default_factory=dict)

    def get_gateway_request(self, idempotency_key: str) -> FakeStoredRequest | None:
        return self.records.get(idempotency_key)

    def reserve_gateway_request(self, idempotency_key: str) -> bool:
        if idempotency_key in self.records:
            return False
        self.records[idempotency_key] = FakeStoredRequest(response=None)
        return True

    def remember_gateway_response(
        self,
        idempotency_key: str,
        response: dict[str, JsonValue],
    ) -> object:
        self.records[idempotency_key] = FakeStoredRequest(response=response)
        return self.records[idempotency_key]

    def release_gateway_request(self, idempotency_key: str) -> bool:
        return self.records.pop(idempotency_key, None) is not None

    def reconcile_incomplete_gateway_requests(self) -> tuple[str, ...]:
        incomplete = tuple(key for key, record in self.records.items() if record.response is None)
        for key in incomplete:
            self.records.pop(key)
        return incomplete


class FixedTaskIds:
    def __init__(self, value: str = "TASK-FIXED-1") -> None:
        self.value = value

    def new(self, idempotency_key: str) -> str:
        del idempotency_key
        return self.value


@dataclass
class FakeTaskAdapter:
    created: list[CreateTaskCommand] = field(default_factory=list)
    cancelled: list[CancelTaskCommand] = field(default_factory=list)
    enqueued: list[str] = field(default_factory=list)
    tasks: dict[str, TaskView] = field(default_factory=dict)
    create_started: asyncio.Event | None = None
    allow_create: asyncio.Event | None = None
    enqueue_error: Exception | None = None
    cancel_error: Exception | None = None

    async def create_task(self, command: CreateTaskCommand) -> TaskView:
        self.created.append(command)
        if self.create_started is not None:
            self.create_started.set()
        if self.allow_create is not None:
            await self.allow_create.wait()
        task = TaskView(
            task_id=command.task_id,
            project=command.project,
            team="example-product",
            status=TaskStatus.PENDING,
        )
        self.tasks[task.task_id] = task
        return task

    async def cancel_task(self, command: CancelTaskCommand) -> TaskView:
        self.cancelled.append(command)
        if self.cancel_error is not None:
            raise self.cancel_error
        task = self.tasks.get(command.task_id)
        if task is None:
            raise TaskConflictError("unsafe adapter detail token=secret")
        cancelled = task.model_copy(update={"status": TaskStatus.CANCELLED})
        self.tasks[task.task_id] = cancelled
        return cancelled

    async def get_task(self, task_id: str) -> TaskView | None:
        return self.tasks.get(task_id)

    async def list_tasks(self, *, limit: int) -> tuple[TaskView, ...]:
        return tuple(self.tasks.values())[:limit]

    async def enqueue_task(self, task_id: str) -> TaskView:
        self.enqueued.append(task_id)
        if self.enqueue_error is not None:
            raise self.enqueue_error
        queued = self.tasks[task_id].model_copy(update={"status": TaskStatus.QUEUED})
        self.tasks[task_id] = queued
        return queued


def gateway_request(
    command: GatewayCommand,
    *,
    event_id: str = "Ev-1",
    actor_id: str = "U-ALLOWED",
    project: str | None = None,
    task_id: str | None = None,
    instruction: str | None = None,
) -> GatewayRequest:
    return GatewayRequest(
        source="slack",
        source_event_id=event_id,
        actor_id=actor_id,
        reply_target="C-1",
        command=command,
        project=project,
        task_id=task_id,
        instruction=instruction,
    )


def make_gateway(adapter: FakeTaskAdapter) -> AgentGateway:
    return AgentGateway(
        authorizer=AllowlistAuthorizer({"U-ALLOWED"}),
        commands=adapter,
        queries=adapter,
        enqueuer=adapter,
        deduplicator=InMemoryRequestDeduplicator(),
        task_ids=FixedTaskIds(),
    )


def test_request_contract_requires_only_arguments_for_selected_command() -> None:
    with pytest.raises(ValidationError, match="dev requires"):
        gateway_request(GatewayCommand.DEV, project="example-project")
    with pytest.raises(ValidationError, match="does not accept task arguments"):
        gateway_request(GatewayCommand.HELP, project="example-project")
    with pytest.raises(ValidationError, match="requires task_id"):
        gateway_request(GatewayCommand.STOP)


def test_authorization_is_fail_closed_before_task_creation() -> None:
    adapter = FakeTaskAdapter()
    response = asyncio.run(
        make_gateway(adapter).handle(
            gateway_request(
                GatewayCommand.DEV,
                actor_id="U-DENIED",
                project="example-project",
                instruction="Create a safe file.",
            )
        )
    )

    assert response.code is GatewayCode.UNAUTHORIZED
    assert not response.success
    assert adapter.created == []
    assert adapter.enqueued == []


@pytest.mark.parametrize(
    "instruction",
    [
        "Use token=not-a-real-credential",
        "Call with Bearer not-a-real-credential",
        "xoxb-not-a-real-slack-token",
        "sk-not-a-real-openai-token-1234",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ_1234567890",
        "-----BEGIN PRIVATE KEY-----\nnot-real-material\n-----END PRIVATE KEY-----",
    ],
)
def test_credential_material_is_rejected_before_task_persistence(instruction: str) -> None:
    adapter = FakeTaskAdapter()
    response = asyncio.run(
        make_gateway(adapter).handle(
            gateway_request(
                GatewayCommand.DEV,
                project="example-project",
                instruction=instruction,
            )
        )
    )

    assert response.code is GatewayCode.INVALID_REQUEST
    assert adapter.created == []
    assert adapter.enqueued == []


def test_plain_token_vocabulary_is_not_misclassified_as_a_credential() -> None:
    adapter = FakeTaskAdapter()
    response = asyncio.run(
        make_gateway(adapter).handle(
            gateway_request(
                GatewayCommand.DEV,
                project="example-project",
                instruction="Update the token parser documentation.",
            )
        )
    )

    assert response.code is GatewayCode.ACCEPTED
    assert len(adapter.created) == 1


def test_dev_creates_then_enqueues_source_neutral_task() -> None:
    adapter = FakeTaskAdapter()
    response = asyncio.run(
        make_gateway(adapter).handle(
            gateway_request(
                GatewayCommand.DEV,
                project="example-project",
                instruction="Create README_TEST.md.",
            )
        )
    )

    assert response.code is GatewayCode.ACCEPTED
    assert response.task is not None
    assert response.task.status is TaskStatus.QUEUED
    assert adapter.enqueued == ["TASK-FIXED-1"]
    assert adapter.created[0].source == "slack"
    assert adapter.created[0].actor_id == "U-ALLOWED"
    assert "Create README_TEST" not in response.message


def test_completed_duplicate_replays_response_without_creating_again() -> None:
    async def scenario() -> tuple[GatewayCode, bool, int, int]:
        adapter = FakeTaskAdapter()
        gateway = make_gateway(adapter)
        request = gateway_request(
            GatewayCommand.DEV,
            project="example-project",
            instruction="Create one file.",
        )
        first = await gateway.handle(request)
        duplicate = await gateway.handle(request)
        assert duplicate == first.model_copy(update={"replayed": True})
        return duplicate.code, duplicate.replayed, len(adapter.created), len(adapter.enqueued)

    code, replayed, creates, enqueues = asyncio.run(scenario())
    assert code is GatewayCode.ACCEPTED
    assert replayed
    assert (creates, enqueues) == (1, 1)


def test_concurrent_duplicate_is_acknowledged_without_waiting() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        adapter = FakeTaskAdapter(create_started=started, allow_create=release)
        gateway = make_gateway(adapter)
        request = gateway_request(
            GatewayCommand.DEV,
            project="example-project",
            instruction="Create one file.",
        )
        original = asyncio.create_task(gateway.handle(request))
        await started.wait()
        duplicate = await asyncio.wait_for(gateway.handle(request), timeout=0.1)
        assert duplicate.code is GatewayCode.DUPLICATE
        assert duplicate.replayed
        release.set()
        await original
        assert len(adapter.created) == 1

    asyncio.run(scenario())


def test_enqueue_failure_is_transient_and_can_be_retried() -> None:
    async def scenario() -> tuple[GatewayCode, GatewayCode, int]:
        adapter = FakeTaskAdapter(enqueue_error=RuntimeError("queue password=secret"))
        gateway = make_gateway(adapter)
        request = gateway_request(
            GatewayCommand.DEV,
            project="example-project",
            instruction="Create one file.",
        )
        first = await gateway.handle(request)
        duplicate = await gateway.handle(request)
        assert "secret" not in first.message
        return first.code, duplicate.code, len(adapter.created)

    first_code, duplicate_code, creates = asyncio.run(scenario())
    assert first_code is GatewayCode.UNAVAILABLE
    assert duplicate_code is GatewayCode.UNAVAILABLE
    assert creates == 2


def test_help_task_list_status_and_stop_use_safe_projections() -> None:
    async def scenario() -> None:
        adapter = FakeTaskAdapter()
        task = TaskView(
            task_id="TASK-1042",
            project="example-project",
            team="example-product",
            status=TaskStatus.RUNNING,
            assigned_agents=("example-developer",),
        )
        adapter.tasks[task.task_id] = task
        gateway = make_gateway(adapter)

        help_response = await gateway.handle(gateway_request(GatewayCommand.HELP, event_id="E1"))
        detail = await gateway.handle(
            gateway_request(GatewayCommand.TASK, event_id="E2", task_id=task.task_id)
        )
        tasks = await gateway.handle(gateway_request(GatewayCommand.TASKS, event_id="E3"))
        status = await gateway.handle(gateway_request(GatewayCommand.STATUS, event_id="E4"))
        stopped = await gateway.handle(
            gateway_request(GatewayCommand.STOP, event_id="E5", task_id=task.task_id)
        )

        assert "dev <project>" in help_response.message
        assert detail.task == task
        assert tasks.tasks == (task,)
        assert "running=1" in status.message
        assert stopped.task is not None
        assert stopped.task.status is TaskStatus.CANCELLED

    asyncio.run(scenario())


def test_unknown_adapter_exception_is_not_exposed() -> None:
    adapter = FakeTaskAdapter(cancel_error=RuntimeError("Authorization: Bearer super-secret"))
    response = asyncio.run(
        make_gateway(adapter).handle(gateway_request(GatewayCommand.STOP, task_id="TASK-1042"))
    )

    assert response.code is GatewayCode.INTERNAL_ERROR
    assert "secret" not in response.message.lower()
    assert "bearer" not in response.message.lower()


def test_interface_redaction_covers_github_tokens_and_pem_private_keys() -> None:
    value = (
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 "
        "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ_1234567890\n"
        "-----BEGIN RSA PRIVATE KEY-----\nprivate-material\n-----END RSA PRIVATE KEY-----"
    )

    redacted = redact_sensitive_text(value)

    assert "ghp_" not in redacted
    assert "github_pat_" not in redacted
    assert "private-material" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_in_memory_deduplicator_is_bounded_and_validates_configuration() -> None:
    async def scenario() -> None:
        deduplicator = InMemoryRequestDeduplicator(max_entries=1)
        response = GatewayResponse(success=True, code=GatewayCode.OK, message="ok")
        assert await deduplicator.reserve("one")
        await deduplicator.remember("one", response)
        assert await deduplicator.reserve("two")
        await deduplicator.remember("two", response)
        assert await deduplicator.get("one") is None
        assert await deduplicator.get("two") == response

    asyncio.run(scenario())
    with pytest.raises(ValueError, match="positive"):
        InMemoryRequestDeduplicator(max_entries=0)


def test_durable_deduplicator_reserves_and_replays_validated_response() -> None:
    async def scenario() -> None:
        store = FakeGatewayRequestStore()
        deduplicator = DurableRequestDeduplicator(store)
        response = GatewayResponse(success=True, code=GatewayCode.OK, message="safe")

        assert await deduplicator.reserve("slack:Ev-1")
        assert not await deduplicator.reserve("slack:Ev-1")
        assert await deduplicator.get("slack:Ev-1") is None
        await deduplicator.remember("slack:Ev-1", response)
        assert await deduplicator.get("slack:Ev-1") == response

        await deduplicator.release("slack:Ev-2")

    asyncio.run(scenario())
