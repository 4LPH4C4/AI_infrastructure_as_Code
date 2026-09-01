"""Deterministic Phase 1 Developer selection from validated registries."""

from __future__ import annotations

from dataclasses import dataclass

from macmini_ai_hub.config.models import (
    AgentDefinition,
    Capability,
    ConfigBundle,
    RuntimeKind,
    TeamType,
    WorkingDirectoryPolicy,
)
from macmini_ai_hub.domain.tasks import Task


class DeveloperSelectionError(LookupError):
    """Raised when a task cannot resolve exactly one eligible Developer."""


@dataclass(frozen=True, slots=True)
class DeveloperSelection:
    agent_id: str
    definition: AgentDefinition


def select_developer(bundle: ConfigBundle, task: Task) -> DeveloperSelection:
    """Resolve the one enabled, write-capable product Developer allowed in Phase 1."""

    team = bundle.teams.teams.get(task.team)
    project = bundle.projects.projects.get(task.project)
    if team is None or team.type is not TeamType.PRODUCT:
        raise DeveloperSelectionError(f"task team {task.team!r} is not a product team")
    if project is None or project.team != task.team or team.project != task.project:
        raise DeveloperSelectionError("task project and product team are not reciprocal")

    required_capabilities = {
        Capability.READ,
        Capability.WRITE,
        Capability.EXECUTE,
        Capability.GIT,
    }
    prohibited_capabilities = {
        Capability.NETWORK,
        Capability.DEPLOY,
        Capability.ADMIN,
    }
    candidates: list[DeveloperSelection] = []
    for agent_id in sorted(team.agents):
        agent = bundle.agents.agents[agent_id]
        capabilities = set(bundle.permissions.permissions[agent.permission_profile])
        if (
            agent.enabled
            and agent.role == "developer"
            and agent.runtime is RuntimeKind.CODEX
            and agent.working_directory_policy is WorkingDirectoryPolicy.PROJECT_WORKSPACE
            and required_capabilities <= capabilities
            and capabilities.isdisjoint(prohibited_capabilities)
        ):
            candidates.append(DeveloperSelection(agent_id=agent_id, definition=agent))

    if not candidates:
        raise DeveloperSelectionError(
            f"team {task.team!r} has no enabled Codex Developer with required capabilities"
        )
    if len(candidates) > 1:
        identifiers = ", ".join(candidate.agent_id for candidate in candidates)
        raise DeveloperSelectionError(
            f"Phase 1 requires exactly one eligible Developer, found: {identifiers}"
        )
    return candidates[0]
