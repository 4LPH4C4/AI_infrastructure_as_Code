from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from macmini_ai_hub.application import build_application
from macmini_ai_hub.config import OperationalSettings
from macmini_ai_hub.integrations import SlackSocketModeService

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def repository_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "hub"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    return root


def settings(root: Path, **updates: object) -> OperationalSettings:
    values: dict[str, object] = {
        "repository_root": root,
        "config_dir": REPOSITORY_ROOT / "config",
        "workspace_dir": Path("workspace"),
        "database_path": Path("workspace/tasks/state.sqlite3"),
        "use_example_config": True,
        "codex_executable": sys.executable,
        "slack_enabled": False,
    }
    values.update(updates)
    return OperationalSettings.model_validate(values)


def test_composition_builds_and_reports_all_local_dependencies_ready(tmp_path: Path) -> None:
    root = repository_fixture(tmp_path)
    application = build_application(settings(root))
    try:
        assert application.store.schema_version == 4
        with TestClient(application.http_app) as client:
            response = client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "components": {"storage": "ok", "workspace": "ok", "runtime": "ok"},
        }
    finally:
        application.close()


def test_initialize_releases_only_interrupted_delivery_reservations(tmp_path: Path) -> None:
    application = build_application(settings(repository_fixture(tmp_path)))
    try:
        assert application.store.reserve_delivery("delivery-1")
        asyncio.run(application.initialize())
        assert application.store.reserve_delivery("delivery-1")
    finally:
        application.close()


def test_workspace_setting_mismatch_fails_before_runtime_state_is_created(tmp_path: Path) -> None:
    root = repository_fixture(tmp_path)
    mismatched = settings(
        root,
        workspace_dir=Path("other-workspace"),
        database_path=Path("other-workspace/tasks/state.sqlite3"),
    )

    try:
        build_application(mismatched)
    except ValueError as error:
        assert "workspace_dir" in str(error)
    else:
        raise AssertionError("unsafe workspace mismatch was accepted")

    assert not (root / "other-workspace").exists()


def test_serve_cancels_socket_mode_start_after_bounded_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ImmediateServer:
        def __init__(self, config: object) -> None:
            del config
            self.should_exit = False

        async def serve(self) -> None:
            return

    class BlockingSlack:
        def __init__(self) -> None:
            self.stopped = False
            self.cancelled = False

        async def start(self) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

        async def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr(
        "macmini_ai_hub.application.composition.uvicorn.Server",
        ImmediateServer,
    )
    application = build_application(
        settings(repository_fixture(tmp_path), shutdown_timeout_seconds=1)
    )
    fake_slack = BlockingSlack()
    application.slack = cast(SlackSocketModeService, fake_slack)
    try:
        asyncio.run(asyncio.wait_for(application.serve(), timeout=1))
        assert fake_slack.stopped
        assert fake_slack.cancelled
    finally:
        application.close()
