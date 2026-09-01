from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from macmini_ai_hub.application import DurableTaskEnqueuer, GatewayTaskAdapter
from macmini_ai_hub.config import ConfigBundle, load_config_bundle
from macmini_ai_hub.domain.tasks import TaskStatus
from macmini_ai_hub.gateway import (
    AgentGateway,
    AllowlistAuthorizer,
    DurableRequestDeduplicator,
    GatewayCode,
    GatewayCommand,
    GatewayRequest,
)
from macmini_ai_hub.observability import replay_task
from macmini_ai_hub.orchestrator import SingleDeveloperOrchestrator
from macmini_ai_hub.orchestrator.ports import PreparedWorkspace
from macmini_ai_hub.runtime import RuntimeRequest, RuntimeResult, RuntimeStatus
from macmini_ai_hub.storage import AsyncSQLiteOrchestrationStore, SQLiteStore


class FixedTaskIds:
    def new(self, idempotency_key: str) -> str:
        del idempotency_key
        return "TASK-9001"


class FakeProjects:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    @asynccontextmanager
    async def open_task_workspace(
        self,
        *,
        project_id: str,
        task_id: str,
        description: str,
    ) -> AsyncIterator[PreparedWorkspace]:
        del project_id, task_id, description
        yield PreparedWorkspace(self.workspace, "agent/TASK-9001-ai-hub-test")


class FileWritingRuntime:
    @property
    def name(self) -> str:
        return "fake"

    async def execute(self, request: RuntimeRequest) -> RuntimeResult:
        (request.workspace / "README_TEST.md").write_text("AI Hub test\n", encoding="utf-8")
        now = datetime.now(UTC)
        return RuntimeResult(
            status=RuntimeStatus.SUCCEEDED,
            started_at=now,
            completed_at=now,
            exit_code=0,
            changed_files=("README_TEST.md",),
        )

    async def cancel(self, task_id: str) -> None:
        del task_id


def enabled_bundle() -> ConfigBundle:
    root = Path(__file__).resolve().parents[1]
    value = load_config_bundle(root / "config").model_dump(mode="json")
    value["agents"]["agents"]["example-developer"]["enabled"] = True
    return ConfigBundle.model_validate(value)


def test_gateway_to_orchestrator_to_sqlite_and_projection_survives_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    workspace = tmp_path / "project"
    workspace.mkdir()
    bundle = enabled_bundle()

    with SQLiteStore(database) as store:
        orchestration_store = AsyncSQLiteOrchestrationStore(
            store,
            run_id_factory=lambda: "RUN-9001",
        )
        orchestrator = SingleDeveloperOrchestrator(
            bundle=bundle,
            store=orchestration_store,
            projects=FakeProjects(workspace),
            runtime=FileWritingRuntime(),
        )
        tasks = GatewayTaskAdapter(store=store, bundle=bundle, canceller=orchestrator)
        gateway = AgentGateway(
            authorizer=AllowlistAuthorizer({"USER-1"}),
            commands=tasks,
            queries=tasks,
            enqueuer=DurableTaskEnqueuer(store=store, wakeup=orchestrator),
            deduplicator=DurableRequestDeduplicator(store),
            task_ids=FixedTaskIds(),
        )
        request = GatewayRequest(
            source="test",
            source_event_id="event-9001",
            actor_id="USER-1",
            command=GatewayCommand.DEV,
            project="example-project",
            instruction='Create README_TEST.md containing "AI Hub test".',
        )

        response = asyncio.run(gateway.handle(request))
        assert response.code is GatewayCode.ACCEPTED
        assert response.task is not None
        assert response.task.status is TaskStatus.QUEUED

        outcome = asyncio.run(orchestrator.run_once())
        assert outcome[0].status is TaskStatus.COMPLETED
        assert (workspace / "README_TEST.md").read_text(encoding="utf-8") == "AI Hub test\n"
        stored_events = store.list_events(task_id="TASK-9001")
        projection = replay_task(item.envelope for item in stored_events)
        assert projection.status is TaskStatus.COMPLETED
        assert store.list_runs("TASK-9001")[0].status.value == "succeeded"

    with SQLiteStore(database) as reopened:
        assert reopened.get_task("TASK-9001").status is TaskStatus.COMPLETED
        assert len(reopened.list_events(task_id="TASK-9001")) >= 6
        assert reopened.list_runs("TASK-9001")[0].run_id == "RUN-9001"
