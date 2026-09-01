"""Production composition root for the Phase 1 single-Mac service."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from macmini_ai_hub.api import create_app
from macmini_ai_hub.application.adapters import (
    DurableTaskEnqueuer,
    GatewayTaskAdapter,
    ProjectExecutionAdapter,
    RuntimeReadinessProbe,
    StorageReadinessProbe,
    WorkspaceReadinessProbe,
)
from macmini_ai_hub.application.notifications import StoredRouteResultNotifier
from macmini_ai_hub.config import (
    ConfigBundle,
    OperationalSettings,
    RuntimePaths,
    load_config_bundle,
)
from macmini_ai_hub.gateway import (
    AgentGateway,
    AllowlistAuthorizer,
    DurableRequestDeduplicator,
)
from macmini_ai_hub.integrations import (
    DeliveryOutcome,
    SlackDeliveryPort,
    SlackDeliveryRequest,
    SlackSocketModeService,
    SlackTaskNotifier,
)
from macmini_ai_hub.observability import configure_rotating_json_logging
from macmini_ai_hub.orchestrator import SingleDeveloperOrchestrator
from macmini_ai_hub.projects import ProjectWorkspaceManager
from macmini_ai_hub.runtime import CodexRuntime, runtime_config_from_settings
from macmini_ai_hub.storage import (
    AsyncSQLiteDeliveryReceipts,
    AsyncSQLiteOrchestrationStore,
    SQLiteStore,
)

_LOGGER = logging.getLogger(__name__)


class DeferredSlackDelivery:
    """Break the gateway/orchestrator/Slack construction cycle explicitly."""

    def __init__(self) -> None:
        self._target: SlackDeliveryPort | None = None

    def bind(self, target: SlackDeliveryPort) -> None:
        if self._target is not None:
            raise RuntimeError("Slack delivery is already bound")
        self._target = target

    async def deliver(self, request: SlackDeliveryRequest) -> DeliveryOutcome:
        if self._target is None:
            raise RuntimeError("Slack delivery is not available")
        return await self._target.deliver(request)


@dataclass(slots=True)
class HubApplication:
    settings: OperationalSettings
    paths: RuntimePaths
    bundle: ConfigBundle
    store: SQLiteStore
    orchestration_store: AsyncSQLiteOrchestrationStore
    receipts: AsyncSQLiteDeliveryReceipts
    deduplicator: DurableRequestDeduplicator
    orchestrator: SingleDeveloperOrchestrator
    gateway: AgentGateway
    http_app: FastAPI
    slack: SlackSocketModeService | None
    notifier: StoredRouteResultNotifier | None

    async def initialize(self) -> None:
        """Reconcile crash residue before any interface can accept work."""

        await self.orchestration_store.reconcile_interrupted()
        await self.receipts.reconcile_interrupted()
        await self.deduplicator.reconcile_interrupted()
        if self.notifier is not None:
            await self.notifier.reconcile_pending()

    async def serve(self) -> None:
        await self.initialize()
        stop = asyncio.Event()
        server = uvicorn.Server(
            uvicorn.Config(
                self.http_app,
                host=self.settings.host,
                port=self.settings.port,
                log_config=None,
                access_log=False,
            )
        )
        server_task = asyncio.create_task(server.serve(), name="http-server")
        orchestrator_task = asyncio.create_task(
            self.orchestrator.run_forever(stop),
            name="orchestrator",
        )
        tasks: set[asyncio.Task[None]] = {server_task, orchestrator_task}
        slack_task: asyncio.Task[None] | None = None
        if self.slack is not None:
            slack_task = asyncio.create_task(self.slack.start(), name="slack-socket-mode")
            tasks.add(slack_task)

        error: BaseException | None = None
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.cancelled():
                    continue
                task_error = task.exception()
                if task_error is not None:
                    error = task_error
                    break
            if error is None and server_task not in done:
                error = RuntimeError("a required background service stopped unexpectedly")
        finally:
            stop.set()
            server.should_exit = True

            async def finish_services() -> None:
                if self.slack is not None:
                    await self.slack.stop()
                if slack_task is not None and not slack_task.done():
                    slack_task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

            try:
                await asyncio.wait_for(
                    finish_services(),
                    timeout=self.settings.shutdown_timeout_seconds,
                )
            except TimeoutError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        if error is not None:
            raise error

    def close(self) -> None:
        self.store.close()


def build_application(settings: OperationalSettings | None = None) -> HubApplication:
    """Validate configuration and construct every Phase 1 adapter once."""

    resolved_settings = settings or OperationalSettings(repository_root=Path.cwd())
    paths, bundle = validate_startup_configuration(resolved_settings)
    _prepare_runtime_directories(paths)
    configure_rotating_json_logging(paths.logs_directory, level=resolved_settings.log_level.value)

    store = SQLiteStore(paths.database_path)
    try:
        orchestration_store = AsyncSQLiteOrchestrationStore(store)
        receipts = AsyncSQLiteDeliveryReceipts(store)
        manager = ProjectWorkspaceManager(
            paths.repository_root,
            paths.projects_directory,
            bundle.projects,
        )
        projects = ProjectExecutionAdapter(
            manager=manager,
            lock_root=paths.locks_directory,
        )
        runtime = CodexRuntime(
            runtime_config_from_settings(
                executable=resolved_settings.codex_executable,
                output_limit_bytes=resolved_settings.runtime_output_limit_bytes,
            )
        )

        deferred_delivery: DeferredSlackDelivery | None = None
        notifier: StoredRouteResultNotifier | None = None
        if resolved_settings.slack_enabled:
            deferred_delivery = DeferredSlackDelivery()
            notifier = StoredRouteResultNotifier(
                store=store,
                slack=SlackTaskNotifier(deferred_delivery),
            )

        orchestrator = SingleDeveloperOrchestrator(
            bundle=bundle,
            store=orchestration_store,
            projects=projects,
            runtime=runtime,
            notifier=notifier,
            max_concurrent_tasks=resolved_settings.max_concurrent_tasks,
            poll_interval_seconds=resolved_settings.poll_interval_seconds,
            runtime_timeout_seconds=resolved_settings.codex_timeout_seconds,
        )
        tasks = GatewayTaskAdapter(store=store, bundle=bundle, canceller=orchestrator)
        deduplicator = DurableRequestDeduplicator(store)
        gateway = AgentGateway(
            authorizer=AllowlistAuthorizer(resolved_settings.allowed_slack_users),
            commands=tasks,
            queries=tasks,
            enqueuer=DurableTaskEnqueuer(store=store, wakeup=orchestrator),
            deduplicator=deduplicator,
        )

        slack: SlackSocketModeService | None = None
        if resolved_settings.slack_enabled:
            if (
                resolved_settings.slack_bot_token is None
                or resolved_settings.slack_app_token is None
                or deferred_delivery is None
            ):
                raise RuntimeError("validated Slack settings are incomplete")
            slack = SlackSocketModeService(
                gateway=gateway,
                bot_token=resolved_settings.slack_bot_token.get_secret_value(),
                app_token=resolved_settings.slack_app_token.get_secret_value(),
                receipts=receipts,
                on_background_error=_log_background_error,
            )
            slack.build()
            deferred_delivery.bind(slack.delivery)

        http_app = create_app(
            readiness_probes=(
                StorageReadinessProbe(store),
                WorkspaceReadinessProbe(paths.workspace_directory),
                RuntimeReadinessProbe(resolved_settings.codex_executable),
            )
        )
        return HubApplication(
            settings=resolved_settings,
            paths=paths,
            bundle=bundle,
            store=store,
            orchestration_store=orchestration_store,
            receipts=receipts,
            deduplicator=deduplicator,
            orchestrator=orchestrator,
            gateway=gateway,
            http_app=http_app,
            slack=slack,
            notifier=notifier,
        )
    except BaseException:
        store.close()
        raise


def validate_startup_configuration(
    settings: OperationalSettings,
) -> tuple[RuntimePaths, ConfigBundle]:
    """Validate repository, registry, and workspace contracts without writing state."""

    paths = settings.resolve_paths()
    _validate_repository_root(paths.repository_root)
    bundle = load_config_bundle(
        paths.config_directory,
        use_examples=settings.use_example_config,
    )
    _validate_workspace_contract(paths, bundle)
    return paths, bundle


def _validate_repository_root(root: Path) -> None:
    if not root.is_dir() or not (root / ".git").exists() or not (root / "pyproject.toml").is_file():
        raise ValueError("repository_root must identify a complete AI Hub Git checkout")


def _validate_workspace_contract(paths: RuntimePaths, bundle: ConfigBundle) -> None:
    declared = (paths.repository_root / bundle.settings.settings.workspace_root).resolve()
    if declared != paths.workspace_directory:
        raise ValueError("operational workspace_dir must match settings.workspace_root")
    for project_id, project in bundle.projects.projects.items():
        target = paths.repository_root.joinpath(*project.workspace.split("/")).resolve()
        if target == paths.projects_directory or not target.is_relative_to(
            paths.projects_directory
        ):
            raise ValueError(f"project {project_id!r} workspace is outside workspace/projects")


def _prepare_runtime_directories(paths: RuntimePaths) -> None:
    for directory in (
        paths.workspace_directory,
        paths.projects_directory,
        paths.database_path.parent,
        paths.logs_directory,
        paths.locks_directory,
        paths.workspace_directory / "memory",
        paths.workspace_directory / "indexes",
        paths.workspace_directory / "artifacts",
    ):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)


def _log_background_error(error: BaseException) -> None:
    _LOGGER.error(
        "Slack background processing failed",
        extra={"error_type": type(error).__name__},
    )
