from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from macmini_ai_hub.config import ConfigBundle, load_config_bundle
from macmini_ai_hub.domain.events import EventEnvelope
from macmini_ai_hub.domain.tasks import Task, TaskStatus, transition_task
from macmini_ai_hub.orchestrator import SingleDeveloperOrchestrator
from macmini_ai_hub.orchestrator.ports import PreparedWorkspace, RunOutcome
from macmini_ai_hub.runtime import RuntimeRequest, RuntimeResult, RuntimeStatus


class FakeStore:
    def __init__(self, task: Task) -> None:
        self.task = task
        self.run_outcome: RunOutcome | None = None
        self.run_error_code: str | None = None
        self.created_runs: list[str] = []
        self.started_runs: list[str] = []

    async def get_task(self, task_id: str) -> Task:
        assert task_id == self.task.task_id
        return self.task

    async def list_queued_tasks(self, *, limit: int) -> tuple[Task, ...]:
        del limit
        return (self.task,) if self.task.status is TaskStatus.QUEUED else ()

    async def transition_task(
        self, task_id: str, target: TaskStatus, event: EventEnvelope
    ) -> Task:
        assert event.payload["status"] == target.value
        self.task = transition_task(self.task, target, at=event.timestamp)
        return self.task

    async def assign_task(
        self, task_id: str, agent_id: str, event: EventEnvelope
    ) -> Task:
        del task_id, event
        self.task = Task.model_validate(
            {**self.task.model_dump(), "assigned_agents": (agent_id,)}
        )
        return self.task

    async def cancel_task(self, task_id: str, event: EventEnvelope) -> Task:
        return await self.transition_task(task_id, TaskStatus.CANCELLED, event)

    async def create_run(self, *, task_id: str, agent_id: str, runtime: str) -> str:
        del task_id, agent_id, runtime
        run_id = "RUN-3001"
        self.created_runs.append(run_id)
        return run_id

    async def start_run(self, run_id: str) -> None:
        assert run_id == "RUN-3001"
        self.started_runs.append(run_id)

    async def finish_run(
        self,
        run_id: str,
        outcome: RunOutcome,
        *,
        exit_code: int | None,
        error_code: str | None,
    ) -> None:
        del run_id, exit_code
        self.run_outcome = outcome
        self.run_error_code = error_code

    async def reconcile_interrupted(self) -> None:
        return None


class FakeProjects:
    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def open_task_workspace(
        self, *, project_id: str, task_id: str, description: str
    ) -> AsyncIterator[PreparedWorkspace]:
        del project_id, task_id, description
        yield PreparedWorkspace(path=self.path, branch="agent/TASK-3001-test")


class FakeRuntime:
    def __init__(self, status: RuntimeStatus) -> None:
        self.status = status
        self.cancelled: list[str] = []

    @property
    def name(self) -> str:
        return "fake"

    async def execute(self, request: RuntimeRequest) -> RuntimeResult:
        del request
        now = datetime.now(UTC)
        return RuntimeResult(
            status=self.status,
            started_at=now,
            completed_at=now,
            exit_code=0 if self.status is RuntimeStatus.SUCCEEDED else 1,
            changed_files=("README_TEST.md",),
        )

    async def cancel(self, task_id: str) -> None:
        self.cancelled.append(task_id)


class RaisingRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__(RuntimeStatus.FAILED)

    async def execute(self, request: RuntimeRequest) -> RuntimeResult:
        del request
        raise RuntimeError("runtime adapter crashed")


class FakeNotifier:
    def __init__(self) -> None:
        self.statuses: list[TaskStatus] = []

    async def notify_task(self, task: Task) -> None:
        self.statuses.append(task.status)


def bundle() -> ConfigBundle:
    root = Path(__file__).resolve().parents[1]
    value = load_config_bundle(root / "config").model_dump(mode="json")
    value["agents"]["agents"]["example-developer"]["enabled"] = True
    return ConfigBundle.model_validate(value)


def queued_task() -> Task:
    pending = Task(
        task_id="TASK-3001",
        source="test",
        project="example-project",
        team="example-product",
        request="Create README_TEST.md.",
    )
    return transition_task(pending, TaskStatus.QUEUED, at=pending.created_at)


def test_single_developer_success_path(tmp_path: Path) -> None:
    store = FakeStore(queued_task())
    notifier = FakeNotifier()
    orchestrator = SingleDeveloperOrchestrator(
        bundle=bundle(),
        store=store,
        projects=FakeProjects(tmp_path),
        runtime=FakeRuntime(RuntimeStatus.SUCCEEDED),
        notifier=notifier,
    )

    result = asyncio.run(orchestrator.process_task("TASK-3001"))

    assert result.status is TaskStatus.COMPLETED
    assert store.task.assigned_agents == ("example-developer",)
    assert store.run_outcome is RunOutcome.SUCCEEDED
    assert notifier.statuses == [TaskStatus.RUNNING, TaskStatus.COMPLETED]


def test_runtime_failure_records_failed_task(tmp_path: Path) -> None:
    store = FakeStore(queued_task())
    orchestrator = SingleDeveloperOrchestrator(
        bundle=bundle(),
        store=store,
        projects=FakeProjects(tmp_path),
        runtime=FakeRuntime(RuntimeStatus.FAILED),
    )

    result = asyncio.run(orchestrator.run_once())

    assert result[0].status is TaskStatus.FAILED
    assert store.run_outcome is RunOutcome.FAILED


def test_runtime_timeout_is_classified_and_persisted(tmp_path: Path) -> None:
    store = FakeStore(queued_task())
    orchestrator = SingleDeveloperOrchestrator(
        bundle=bundle(),
        store=store,
        projects=FakeProjects(tmp_path),
        runtime=FakeRuntime(RuntimeStatus.TIMED_OUT),
    )

    result = asyncio.run(orchestrator.run_once())

    assert result[0].status is TaskStatus.FAILED
    assert store.run_outcome is RunOutcome.TIMED_OUT


def test_runtime_exception_closes_started_run_and_fails_task(tmp_path: Path) -> None:
    store = FakeStore(queued_task())
    orchestrator = SingleDeveloperOrchestrator(
        bundle=bundle(),
        store=store,
        projects=FakeProjects(tmp_path),
        runtime=RaisingRuntime(),
    )

    result = asyncio.run(orchestrator.process_task("TASK-3001"))

    assert result.status is TaskStatus.FAILED
    assert result.error_code == "runtime-exception"
    assert store.task.status is TaskStatus.FAILED
    assert store.created_runs == ["RUN-3001"]
    assert store.started_runs == ["RUN-3001"]
    assert store.run_outcome is RunOutcome.FAILED
    assert store.run_error_code == "runtime-exception"


def test_running_task_cancellation_reaches_runtime_and_terminal_state(tmp_path: Path) -> None:
    store = FakeStore(queued_task())
    store.task = transition_task(store.task, TaskStatus.RUNNING, at=store.task.created_at)
    runtime = FakeRuntime(RuntimeStatus.SUCCEEDED)
    orchestrator = SingleDeveloperOrchestrator(
        bundle=bundle(),
        store=store,
        projects=FakeProjects(tmp_path),
        runtime=runtime,
    )

    cancelled = asyncio.run(orchestrator.cancel_task(store.task.task_id))

    assert cancelled.status is TaskStatus.CANCELLED
    assert runtime.cancelled == [store.task.task_id]
