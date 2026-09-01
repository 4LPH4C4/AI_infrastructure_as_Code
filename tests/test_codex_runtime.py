from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from macmini_ai_hub.runtime import (
    CodexRuntime,
    CodexRuntimeConfig,
    RuntimeRequest,
    RuntimeStatus,
    RuntimeTaskNotRunning,
    redact_runtime_output,
)


def write_fake_runtime(tmp_path: Path, source: str) -> Path:
    script = tmp_path / "fake_runtime.py"
    script.write_text(source, encoding="utf-8")
    return script


def request(tmp_path: Path, *, task_id: str = "TASK-2001", timeout: int = 5) -> RuntimeRequest:
    return RuntimeRequest(
        task_id=task_id,
        agent="example-developer",
        project="example-project",
        workspace=tmp_path.resolve(),
        prompt="literal ; echo unsafe\napi_key=super-secret-value",
        timeout_seconds=timeout,
    )


def runtime(script: Path, *, output_limit: int = 100_000) -> CodexRuntime:
    return CodexRuntime(
        CodexRuntimeConfig(
            executable=sys.executable,
            arguments=(str(script),),
            output_limit_bytes=output_limit,
        )
    )


def test_default_codex_command_enforces_workspace_write_sandbox() -> None:
    config = CodexRuntimeConfig()

    assert config.arguments == (
        "--ask-for-approval",
        "untrusted",
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--json",
        "--sandbox",
        "workspace-write",
        "--config",
        "sandbox_workspace_write.network_access=false",
        "--config",
        'web_search="disabled"',
        "--config",
        "allow_login_shell=false",
        "-",
    )
    assert "--dangerously-bypass-approvals-and-sandbox" not in config.arguments
    assert "untrusted" in config.arguments
    assert "sandbox_workspace_write.network_access=false" in config.arguments


def test_runtime_uses_stdin_without_shell_and_redacts_output(tmp_path: Path) -> None:
    script = write_fake_runtime(
        tmp_path,
        "import sys\nvalue = sys.stdin.read()\nprint(value, end='')\n",
    )

    result = asyncio.run(runtime(script).execute(request(tmp_path)))

    assert result.status is RuntimeStatus.SUCCEEDED
    assert "literal ; echo unsafe" in result.stdout
    assert "super-secret-value" not in result.stdout
    assert "[REDACTED]" in result.stdout


def test_runtime_redacts_github_tokens_and_pem_private_keys() -> None:
    value = (
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 "
        "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ_1234567890\n"
        "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----"
    )

    redacted = redact_runtime_output(value)

    assert "ghp_" not in redacted
    assert "github_pat_" not in redacted
    assert "private-material" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_runtime_bounds_output(tmp_path: Path) -> None:
    script = write_fake_runtime(tmp_path, "print('x' * 5000)\n")

    result = asyncio.run(runtime(script, output_limit=1024).execute(request(tmp_path)))

    assert result.status is RuntimeStatus.SUCCEEDED
    assert len(result.stdout) < 1200
    assert "output truncated" in result.stdout


def test_runtime_timeout_terminates_process(tmp_path: Path) -> None:
    script = write_fake_runtime(tmp_path, "import time\ntime.sleep(30)\n")

    result = asyncio.run(runtime(script).execute(request(tmp_path, timeout=1)))

    assert result.status is RuntimeStatus.TIMED_OUT
    assert result.exit_code is not None


def test_runtime_can_be_cancelled_by_task_id(tmp_path: Path) -> None:
    script = write_fake_runtime(tmp_path, "import time\ntime.sleep(30)\n")

    async def scenario() -> RuntimeStatus:
        adapter = runtime(script)
        execution = asyncio.create_task(adapter.execute(request(tmp_path)))
        await asyncio.sleep(0.2)
        await adapter.cancel("TASK-2001")
        return (await execution).status

    assert asyncio.run(scenario()) is RuntimeStatus.CANCELLED


def test_cancelling_unknown_task_fails_explicitly(tmp_path: Path) -> None:
    script = write_fake_runtime(tmp_path, "print('unused')\n")

    with pytest.raises(RuntimeTaskNotRunning):
        asyncio.run(runtime(script).cancel("TASK-9999"))


def test_runtime_that_exits_before_reading_stdin_is_recorded_as_failed(tmp_path: Path) -> None:
    script = write_fake_runtime(tmp_path, "raise SystemExit(2)\n")
    early_exit_request = request(tmp_path).model_copy(update={"prompt": "x" * 100_000})

    result = asyncio.run(runtime(script).execute(early_exit_request))

    assert result.status is RuntimeStatus.FAILED
    assert result.exit_code == 2
