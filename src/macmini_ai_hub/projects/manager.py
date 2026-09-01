"""Safe Git workspace selection for registered Phase 1 projects."""

from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from macmini_ai_hub.config.models import ProjectDefinition, ProjectRegistry

_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_FORBIDDEN_GIT_COMMANDS = frozenset({"clean", "merge", "push", "reset"})
_FORBIDDEN_GIT_ARGUMENTS = frozenset({"--force", "--force-with-lease", "--hard", "-f"})


class ProjectWorkspaceError(RuntimeError):
    """Base error for project workspace operations."""


class ProjectNotFoundError(ProjectWorkspaceError):
    """Raised when a project ID is absent from the registry."""


class UnsafeWorkspaceError(ProjectWorkspaceError):
    """Raised when a registered path escapes the configured project root."""


class RepositoryOriginError(ProjectWorkspaceError):
    """Raised when a checkout's origin does not match its registry entry."""


class DirtyWorkingTreeError(ProjectWorkspaceError):
    """Raised when an operation requires a clean working tree."""


class BranchCollisionError(ProjectWorkspaceError):
    """Raised when a task branch already exists."""


class GitCommandError(ProjectWorkspaceError):
    """Raised when an allowlisted Git command fails."""

    def __init__(self, operation: str, returncode: int, stderr: str) -> None:
        detail = stderr.strip() or "Git returned no diagnostic output"
        super().__init__(f"Git {operation} failed with exit code {returncode}: {detail}")
        self.operation = operation
        self.returncode = returncode


class DirtyTreePolicy(StrEnum):
    """Whether an existing checkout may contain uncommitted changes."""

    REJECT = "reject"
    ALLOW = "allow"


@dataclass(frozen=True, slots=True)
class ProjectWorkspace:
    project_id: str
    path: Path
    repository: str
    branch: str
    dirty: bool


@dataclass(frozen=True, slots=True)
class TaskBranch:
    project_id: str
    workspace: Path
    branch: str


class ProjectWorkspaceManager:
    """Clone and select only workspaces declared by ``ProjectRegistry``.

    All subprocesses use explicit argument vectors, a fixed working directory,
    disabled terminal prompting, and no shell. Destructive Git commands and force
    flags are rejected as a defense-in-depth invariant.
    """

    def __init__(
        self,
        repository_root: Path,
        workspace_root: Path,
        registry: ProjectRegistry,
        *,
        git_executable: str = "git",
        command_timeout_seconds: float = 120.0,
    ) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")
        self._repository_root = repository_root.resolve(strict=True)
        self._workspace_root = workspace_root.resolve(strict=False)
        self._registry = registry
        self._git_executable = git_executable
        self._command_timeout_seconds = command_timeout_seconds

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    def clone_or_select(
        self,
        project_id: str,
        *,
        dirty_policy: DirtyTreePolicy = DirtyTreePolicy.REJECT,
    ) -> ProjectWorkspace:
        project = self._project(project_id)
        target = self._project_path(project_id, project)
        self._workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)

        if target.exists() or target.is_symlink():
            if not target.is_dir():
                raise UnsafeWorkspaceError(f"project workspace is not a directory: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._run_git(
                ("clone", "--origin", "origin", "--", project.repository, str(target)),
                cwd=target.parent,
            )

        canonical_target = self._assert_contained(target)
        top_level = self._run_git(("rev-parse", "--show-toplevel"), cwd=canonical_target)
        reported_top_level = Path(top_level.stdout.strip()).resolve(strict=True)
        if reported_top_level != canonical_target:
            raise UnsafeWorkspaceError(
                f"registered workspace is not the repository root: {canonical_target}"
            )

        actual_origin = self._run_git(("remote", "get-url", "origin"), cwd=canonical_target)
        actual_origin_value = actual_origin.stdout.strip()
        if actual_origin_value != project.repository:
            raise RepositoryOriginError(
                f"project {project_id!r} origin does not match the registered repository"
            )

        status = self._working_tree_status(canonical_target)
        if status and dirty_policy is DirtyTreePolicy.REJECT:
            raise DirtyWorkingTreeError(f"project {project_id!r} working tree is dirty")

        return ProjectWorkspace(
            project_id=project_id,
            path=canonical_target,
            repository=project.repository,
            branch=self.current_branch(canonical_target),
            dirty=bool(status),
        )

    def create_task_branch(
        self,
        project_id: str,
        task_id: str,
        description: str,
    ) -> TaskBranch:
        workspace = self.clone_or_select(project_id, dirty_policy=DirtyTreePolicy.REJECT)
        branch = task_branch_name(task_id, description)

        validation = self._run_git(
            ("check-ref-format", "--branch", branch),
            cwd=workspace.path,
            check=False,
        )
        if validation.returncode != 0:
            raise ValueError(f"generated task branch is not a valid Git branch: {branch}")

        collision = self._run_git(
            ("show-ref", "--verify", "--quiet", f"refs/heads/{branch}"),
            cwd=workspace.path,
            check=False,
        )
        if collision.returncode == 0:
            raise BranchCollisionError(f"task branch already exists: {branch}")
        if collision.returncode not in {0, 1}:
            raise GitCommandError("show-ref", collision.returncode, collision.stderr)

        base_ref = self._task_base_ref(workspace.path, self._project(project_id))
        self._run_git(("switch", "--create", branch, base_ref), cwd=workspace.path)
        return TaskBranch(project_id=project_id, workspace=workspace.path, branch=branch)

    def current_branch(self, workspace: Path) -> str:
        canonical_workspace = self._assert_contained(workspace)
        result = self._run_git(
            ("symbolic-ref", "--quiet", "--short", "HEAD"), cwd=canonical_workspace
        )
        return result.stdout.strip()

    def changed_files(self, workspace: Path) -> tuple[str, ...]:
        canonical_workspace = self._assert_contained(workspace)
        status = self._working_tree_status(canonical_workspace)
        paths: set[str] = set()
        for line in status.splitlines():
            if len(line) < 4:
                continue
            path = line[3:]
            if " -> " in path:
                path = path.rsplit(" -> ", maxsplit=1)[1]
            paths.add(path)
        return tuple(sorted(paths))

    def _project(self, project_id: str) -> ProjectDefinition:
        try:
            return self._registry.projects[project_id]
        except KeyError as error:
            raise ProjectNotFoundError(f"unknown project: {project_id}") from error

    def _project_path(self, project_id: str, project: ProjectDefinition) -> Path:
        target = self._repository_root.joinpath(*project.workspace.split("/"))
        try:
            return self._assert_contained(target)
        except UnsafeWorkspaceError as error:
            raise UnsafeWorkspaceError(
                f"project {project_id!r} workspace escapes the configured projects directory"
            ) from error

    def _assert_contained(self, path: Path) -> Path:
        canonical = path.resolve(strict=False)
        if canonical == self._workspace_root or not canonical.is_relative_to(self._workspace_root):
            raise UnsafeWorkspaceError(
                f"workspace path must be below {self._workspace_root}: {canonical}"
            )
        return canonical

    def _working_tree_status(self, workspace: Path) -> str:
        return self._run_git(
            ("status", "--porcelain=v1", "--untracked-files=all"), cwd=workspace
        ).stdout

    def _task_base_ref(self, workspace: Path, project: ProjectDefinition) -> str:
        """Resolve a registered or cloned remote default branch without network access."""

        if project.base_branch is not None:
            remote_ref = f"refs/remotes/origin/{project.base_branch}"
        else:
            resolved = self._run_git(
                ("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"),
                cwd=workspace,
            ).stdout.strip()
            if not resolved.startswith("refs/remotes/origin/"):
                raise RepositoryOriginError("origin/HEAD does not name an origin branch")
            remote_ref = resolved

        verification = self._run_git(
            ("show-ref", "--verify", "--quiet", remote_ref),
            cwd=workspace,
            check=False,
        )
        if verification.returncode != 0:
            if verification.returncode == 1:
                raise RepositoryOriginError(
                    f"configured task base branch does not exist: {remote_ref}"
                )
            raise GitCommandError("show-ref", verification.returncode, verification.stderr)
        return remote_ref

    def _run_git(
        self,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if not arguments:
            raise ValueError("Git arguments must not be empty")
        if arguments[0] in _FORBIDDEN_GIT_COMMANDS:
            raise ValueError(f"forbidden Git command: {arguments[0]}")
        forbidden_arguments = _FORBIDDEN_GIT_ARGUMENTS.intersection(arguments)
        if forbidden_arguments:
            raise ValueError(f"forbidden Git argument: {sorted(forbidden_arguments)[0]}")

        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        try:
            result = subprocess.run(
                [self._git_executable, *arguments],
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._command_timeout_seconds,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GitCommandError(arguments[0], -1, str(error)) from error
        if check and result.returncode != 0:
            raise GitCommandError(arguments[0], result.returncode, result.stderr)
        return result


def task_branch_name(task_id: str, description: str) -> str:
    """Build a bounded, ref-safe ``agent/<task-id>-<slug>`` branch name."""

    if not _TASK_ID_PATTERN.fullmatch(task_id):
        raise ValueError("task_id contains characters that are unsafe in a Git branch")
    normalized = unicodedata.normalize("NFKD", description).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "task"
    available = max(1, 120 - len("agent/") - len(task_id) - 1)
    slug = slug[:available].rstrip("-") or "task"
    return f"agent/{task_id}-{slug}"
