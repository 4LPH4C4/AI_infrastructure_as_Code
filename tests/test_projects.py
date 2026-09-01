from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from macmini_ai_hub.config import ProjectDefinition, ProjectRegistry
from macmini_ai_hub.projects import (
    BranchCollisionError,
    DirtyTreePolicy,
    DirtyWorkingTreeError,
    GitCommandError,
    ProjectWorkspaceManager,
    RepositoryOriginError,
    UnsafeWorkspaceError,
)


def run_git(cwd: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    return result.stdout.strip()


def create_source_repository(path: Path) -> Path:
    path.mkdir(parents=True)
    run_git(path, "init")
    run_git(path, "config", "user.name", "AI Hub Test")
    run_git(path, "config", "user.email", "ai-hub-test@example.invalid")
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    run_git(path, "add", "README.md")
    run_git(path, "commit", "-m", "fixture")
    return path


def make_manager(tmp_path: Path) -> tuple[ProjectWorkspaceManager, Path]:
    source = create_source_repository(tmp_path / "source")
    repository_root = tmp_path / "hub"
    repository_root.mkdir()
    workspace_root = repository_root / "workspace" / "projects"
    registry = ProjectRegistry(
        schema_version=1,
        projects={
            "example": ProjectDefinition(
                display_name="Example",
                repository=source.as_uri(),
                workspace="workspace/projects/example",
                team="example-team",
            )
        },
    )
    return ProjectWorkspaceManager(repository_root, workspace_root, registry), source


def test_clone_then_select_registered_repository(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)

    cloned = manager.clone_or_select("example")
    selected = manager.clone_or_select("example")

    assert cloned.path == selected.path
    assert cloned.path == (tmp_path / "hub" / "workspace" / "projects" / "example")
    assert not cloned.dirty
    assert (cloned.path / ".git").is_dir()


def test_dirty_tree_is_rejected_unless_explicitly_allowed(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)
    workspace = manager.clone_or_select("example")
    (workspace.path / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(DirtyWorkingTreeError, match="dirty"):
        manager.clone_or_select("example")

    allowed = manager.clone_or_select("example", dirty_policy=DirtyTreePolicy.ALLOW)
    assert allowed.dirty
    assert manager.changed_files(allowed.path) == ("untracked.txt",)


def test_wrong_origin_is_rejected(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)
    workspace = manager.clone_or_select("example")
    other = create_source_repository(tmp_path / "other")
    run_git(workspace.path, "remote", "set-url", "origin", other.as_uri())

    with pytest.raises(RepositoryOriginError, match="origin"):
        manager.clone_or_select("example")


def test_task_branch_is_safe_and_collision_is_rejected(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)

    created = manager.create_task_branch("example", "TASK-1042", "Retry incorrect answers")

    assert created.branch == "agent/TASK-1042-retry-incorrect-answers"
    assert manager.current_branch(created.workspace) == created.branch
    with pytest.raises(BranchCollisionError, match="already exists"):
        manager.create_task_branch("example", "TASK-1042", "Retry incorrect answers")


def test_consecutive_task_branches_start_from_remote_default(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)
    first = manager.create_task_branch("example", "TASK-1", "first change")
    (first.workspace / "first.txt").write_text("first\n", encoding="utf-8")
    run_git(first.workspace, "add", "first.txt")
    run_git(first.workspace, "commit", "-m", "first task")
    first_commit = run_git(first.workspace, "rev-parse", "HEAD")

    second = manager.create_task_branch("example", "TASK-2", "second change")

    assert run_git(second.workspace, "rev-parse", "HEAD") == run_git(
        second.workspace, "rev-parse", "refs/remotes/origin/HEAD"
    )
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", first_commit, "HEAD"],
        cwd=second.workspace,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    assert ancestry.returncode == 1
    assert not (second.workspace / "first.txt").exists()


def test_configured_missing_base_branch_fails_closed(tmp_path: Path) -> None:
    _, source = make_manager(tmp_path)
    registry = ProjectRegistry(
        schema_version=1,
        projects={
            "example": ProjectDefinition(
                display_name="Example",
                repository=source.as_uri(),
                workspace="workspace/projects/example",
                team="example-team",
                base_branch="missing",
            )
        },
    )
    strict_manager = ProjectWorkspaceManager(
        tmp_path / "hub",
        tmp_path / "hub" / "workspace" / "projects",
        registry,
    )

    with pytest.raises(RepositoryOriginError, match="base branch"):
        strict_manager.create_task_branch("example", "TASK-3", "missing base")


def test_missing_repository_is_reported_without_partial_success(tmp_path: Path) -> None:
    repository_root = tmp_path / "hub"
    repository_root.mkdir()
    registry = ProjectRegistry(
        schema_version=1,
        projects={
            "missing": ProjectDefinition(
                display_name="Missing",
                repository=(tmp_path / "does-not-exist.git").as_uri(),
                workspace="workspace/projects/missing",
                team="missing-team",
            )
        },
    )
    manager = ProjectWorkspaceManager(
        repository_root, repository_root / "workspace" / "projects", registry
    )

    with pytest.raises(GitCommandError, match="clone"):
        manager.clone_or_select("missing")


def test_registry_path_escape_is_rejected_before_git_runs(tmp_path: Path) -> None:
    source = create_source_repository(tmp_path / "source")
    repository_root = tmp_path / "hub"
    repository_root.mkdir()
    registry = ProjectRegistry(
        schema_version=1,
        projects={
            "escape": ProjectDefinition(
                display_name="Escape",
                repository=source.as_uri(),
                workspace="workspace/projects-escape/example",
                team="escape-team",
            )
        },
    )
    manager = ProjectWorkspaceManager(
        repository_root, repository_root / "workspace" / "projects", registry
    )

    with pytest.raises(UnsafeWorkspaceError, match="escapes"):
        manager.clone_or_select("escape")


def test_symlink_escape_is_rejected_before_git_runs(tmp_path: Path) -> None:
    source = create_source_repository(tmp_path / "source")
    repository_root = tmp_path / "hub"
    workspace_root = repository_root / "workspace" / "projects"
    workspace_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (workspace_root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")
    registry = ProjectRegistry(
        schema_version=1,
        projects={
            "escape": ProjectDefinition(
                display_name="Escape",
                repository=source.as_uri(),
                workspace="workspace/projects/link/example",
                team="escape-team",
            )
        },
    )
    manager = ProjectWorkspaceManager(repository_root, workspace_root, registry)

    with pytest.raises(UnsafeWorkspaceError, match="escapes"):
        manager.clone_or_select("escape")


def test_invalid_task_id_is_rejected(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)

    with pytest.raises(ValueError, match="unsafe"):
        manager.create_task_branch("example", "../escape", "unsafe")
