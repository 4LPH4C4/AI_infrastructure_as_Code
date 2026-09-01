from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from macmini_ai_hub.runtime import (
    DisabledRuntime,
    RuntimeAdapter,
    RuntimeExecutionDisabled,
    RuntimeRequest,
)


def runtime_request(tmp_path: Path) -> RuntimeRequest:
    return RuntimeRequest(
        task_id="TASK-1042",
        agent="example-developer",
        project="example-project",
        workspace=tmp_path.resolve(),
        prompt="Do not execute this Phase 0 contract.",
    )


def test_disabled_runtime_satisfies_protocol_without_executing(tmp_path: Path) -> None:
    runtime = DisabledRuntime()

    assert isinstance(runtime, RuntimeAdapter)
    with pytest.raises(RuntimeExecutionDisabled, match="disabled in Phase 0"):
        asyncio.run(runtime.execute(runtime_request(tmp_path)))


def test_disabled_runtime_cancellation_is_also_fail_closed() -> None:
    with pytest.raises(RuntimeExecutionDisabled, match="nothing to cancel"):
        asyncio.run(DisabledRuntime().cancel("TASK-1042"))


def test_runtime_request_requires_absolute_workspace(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="absolute path"):
        RuntimeRequest(
            task_id="TASK-1042",
            agent="example-developer",
            project="example-project",
            workspace=Path("workspace/projects/example-project"),
            prompt="This is still not executed.",
        )


def test_runtime_request_rejects_string_timeout(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="valid integer"):
        RuntimeRequest(
            task_id="TASK-1042",
            agent="example-developer",
            project="example-project",
            workspace=tmp_path.resolve(),
            prompt="This is still not executed.",
            timeout_seconds="3600",
        )
