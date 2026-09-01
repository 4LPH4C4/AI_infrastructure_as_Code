"""Bounded, cancellable Codex CLI adapter for the approved Phase 1 runtime."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from macmini_ai_hub.domain.tasks import TaskId
from macmini_ai_hub.runtime.base import (
    RuntimeRequest,
    RuntimeResult,
    RuntimeStatus,
)

CommandPart = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=2_000),
]

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?\S+"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)\S+"),
    re.compile(r"\b(?:sk|xox[baprs]|xapp)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
)
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----.*?-----END \1-----",
    re.DOTALL,
)
_TRUNCATED_MARKER = "\n[output truncated by AI Hub]"


def redact_runtime_output(value: str) -> str:
    """Apply a conservative fallback redactor before output leaves the adapter."""

    redacted = _PEM_PRIVATE_KEY.sub("[REDACTED]", value)
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]" if pattern.groups else "[REDACTED]", redacted)
    return redacted


class CodexRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    executable: CommandPart = "codex"
    arguments: tuple[CommandPart, ...] = (
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
    git_executable: CommandPart = "git"
    output_limit_bytes: Annotated[int, Field(strict=True, ge=1_024, le=10_000_000)] = 1_000_000
    termination_grace_seconds: Annotated[float, Field(strict=True, gt=0, le=30)] = 5.0
    environment_names: tuple[str, ...] = (
        "PATH",
        "HOME",
        "USERPROFILE",
        "TMPDIR",
        "TMP",
        "TEMP",
        "CODEX_HOME",
        "LANG",
        "LC_ALL",
        "TERM",
        "SSL_CERT_FILE",
    )

    @field_validator("executable", "git_executable")
    @classmethod
    def validate_command_part(cls, value: str) -> str:
        if any(character in value for character in ("\x00", "\r", "\n")):
            raise ValueError("command contains control characters")
        return value

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for argument in value:
            if "\x00" in argument:
                raise ValueError("argument contains a NUL character")
        return value

    @field_validator("environment_names")
    @classmethod
    def validate_environment_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("environment_names must not contain duplicates")
        return value


class RuntimeLaunchError(RuntimeError):
    """Raised when the configured runtime executable cannot be launched."""


class RuntimeTaskNotRunning(LookupError):
    """Raised when cancellation targets no active process."""


class CodexRuntime:
    """Execute Codex with explicit argv/stdin and bounded, redacted output."""

    def __init__(
        self,
        config: CodexRuntimeConfig | None = None,
        *,
        environment: Mapping[str, str] | None = None,
        redactor: Callable[[str], str] = redact_runtime_output,
    ) -> None:
        self._config = config or CodexRuntimeConfig()
        source_environment = environment if environment is not None else os.environ
        self._environment = {
            name: source_environment[name]
            for name in self._config.environment_names
            if name in source_environment
        }
        self._redactor = redactor
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._cancelled: set[str] = set()
        self._process_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "codex"

    async def execute(self, request: RuntimeRequest) -> RuntimeResult:
        started_at = datetime.now(UTC)
        try:
            process = await asyncio.create_subprocess_exec(
                self._config.executable,
                *self._config.arguments,
                cwd=request.workspace,
                env=self._environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as error:
            raise RuntimeLaunchError("configured Codex executable could not be launched") from error

        async with self._process_lock:
            if request.task_id in self._processes:
                await self._terminate(process)
                raise RuntimeLaunchError(f"task {request.task_id} already has a running process")
            self._processes[request.task_id] = process

        stdout_task = asyncio.create_task(self._read_bounded(process.stdout))
        stderr_task = asyncio.create_task(self._read_bounded(process.stderr))
        status = RuntimeStatus.FAILED
        try:
            if process.stdin is None:
                raise RuntimeLaunchError("runtime stdin pipe was not created")
            try:
                process.stdin.write(request.prompt.encode("utf-8"))
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=request.timeout_seconds)
            except TimeoutError:
                status = RuntimeStatus.TIMED_OUT
                await self._terminate(process)
            else:
                async with self._process_lock:
                    was_cancelled = request.task_id in self._cancelled
                if was_cancelled:
                    status = RuntimeStatus.CANCELLED
                elif process.returncode == 0:
                    status = RuntimeStatus.SUCCEEDED
        except BaseException:
            await self._terminate(process)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        finally:
            async with self._process_lock:
                self._processes.pop(request.task_id, None)
                self._cancelled.discard(request.task_id)

        stdout_bytes, stdout_truncated = await stdout_task
        stderr_bytes, stderr_truncated = await stderr_task
        stdout = self._decode_output(stdout_bytes, stdout_truncated)
        stderr = self._decode_output(stderr_bytes, stderr_truncated)
        changed_files = await self._collect_changed_files(request.workspace)
        return RuntimeResult(
            status=status,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            changed_files=changed_files,
        )

    async def cancel(self, task_id: TaskId) -> None:
        async with self._process_lock:
            process = self._processes.get(task_id)
            if process is None:
                raise RuntimeTaskNotRunning(f"task {task_id} has no running runtime process")
            self._cancelled.add(task_id)
        await self._terminate(process)

    async def _read_bounded(
        self,
        stream: asyncio.StreamReader | None,
    ) -> tuple[bytes, bool]:
        if stream is None:
            return b"", False
        output = bytearray()
        truncated = False
        while chunk := await stream.read(65_536):
            remaining = self._config.output_limit_bytes - len(output)
            if remaining > 0:
                output.extend(chunk[:remaining])
            if len(chunk) > remaining:
                truncated = True
        return bytes(output), truncated

    def _decode_output(self, value: bytes, truncated: bool) -> str:
        decoded = value.decode("utf-8", errors="replace")
        if truncated:
            decoded += _TRUNCATED_MARKER
        return self._redactor(decoded)

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            await process.wait()
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=self._config.termination_grace_seconds)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def _collect_changed_files(self, workspace: Path) -> tuple[str, ...]:
        try:
            process = await asyncio.create_subprocess_exec(
                self._config.git_executable,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                cwd=workspace,
                env=self._environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError):
            return ()
        output, _ = await process.communicate()
        if process.returncode != 0:
            return ()
        paths: set[str] = set()
        for raw_record in output.split(b"\x00"):
            if not raw_record:
                continue
            record = raw_record.decode("utf-8", errors="replace")
            candidate = record[3:] if len(record) >= 3 and record[2] == " " else record
            path = Path(candidate)
            if path.is_absolute() or ".." in path.parts or not candidate:
                continue
            paths.add(path.as_posix())
        return tuple(sorted(paths))


def runtime_config_from_settings(
    *,
    executable: str,
    output_limit_bytes: int,
) -> CodexRuntimeConfig:
    """Small composition helper that keeps settings out of the runtime contract."""

    return CodexRuntimeConfig(
        executable=executable,
        output_limit_bytes=output_limit_bytes,
    )
