"""Conservative, registry-driven project workspace management."""

from macmini_ai_hub.projects.manager import (
    BranchCollisionError,
    DirtyTreePolicy,
    DirtyWorkingTreeError,
    GitCommandError,
    ProjectNotFoundError,
    ProjectWorkspace,
    ProjectWorkspaceError,
    ProjectWorkspaceManager,
    RepositoryOriginError,
    TaskBranch,
    UnsafeWorkspaceError,
)

__all__ = [
    "BranchCollisionError",
    "DirtyTreePolicy",
    "DirtyWorkingTreeError",
    "GitCommandError",
    "ProjectNotFoundError",
    "ProjectWorkspace",
    "ProjectWorkspaceError",
    "ProjectWorkspaceManager",
    "RepositoryOriginError",
    "TaskBranch",
    "UnsafeWorkspaceError",
]
