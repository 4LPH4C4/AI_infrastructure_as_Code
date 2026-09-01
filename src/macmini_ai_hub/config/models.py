"""Pydantic models for safe, version-controlled AI Hub configuration."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

Identifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=63,
        pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
    ),
]
DisplayName = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120),
]
ModelName = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120),
]
GitBranchName = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$",
    ),
]


class StrictModel(BaseModel):
    """Common validation posture for all configuration objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Environment(StrEnum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class RuntimeKind(StrEnum):
    """Runtime names that configuration can represent in Phase 0.

    ``codex`` is metadata only. Phase 0 intentionally provides no Codex adapter.
    """

    DISABLED = "disabled"
    CODEX = "codex"


class TeamType(StrEnum):
    PLATFORM = "platform"
    PRODUCT = "product"


class WorkingDirectoryPolicy(StrEnum):
    PROJECT_WORKSPACE = "project-workspace"
    READ_ONLY = "read-only"


class Capability(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    GIT = "git"
    NETWORK = "network"
    DEPLOY = "deploy"
    ADMIN = "admin"


def _validate_unique(
    items: tuple[str | StrEnum, ...], field_name: str
) -> tuple[str | StrEnum, ...]:
    if len(items) != len(set(items)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return items


def _validate_relative_path(value: str, field_name: str) -> str:
    if "\\" in value:
        raise ValueError(f"{field_name} must use POSIX separators")
    path = PurePosixPath(value)
    has_drive_prefix = bool(path.parts and path.parts[0].endswith(":") and len(path.parts[0]) == 2)
    if path.is_absolute() or has_drive_prefix or value in {"", "."} or ".." in path.parts:
        raise ValueError(f"{field_name} must be a non-empty safe relative path")
    return path.as_posix()


class GitSafetyPolicy(StrictModel):
    """Conservative defaults for later agent Git workflows."""

    auto_commit: StrictBool = False
    auto_push: StrictBool = False
    auto_merge: StrictBool = False
    allow_force_push: Literal[False] = False

    @model_validator(mode="after")
    def validate_dependencies(self) -> Self:
        if self.auto_push and not self.auto_commit:
            raise ValueError("auto_push requires auto_commit")
        if self.auto_merge and not self.auto_push:
            raise ValueError("auto_merge requires auto_push")
        return self


class Settings(StrictModel):
    instance_name: DisplayName = "Mac Mini AI Hub"
    environment: Environment = Environment.LOCAL
    timezone: DisplayName = "Asia/Seoul"
    workspace_root: str = "workspace"
    log_level: LogLevel = LogLevel.INFO
    max_concurrent_tasks: Annotated[StrictInt, Field(ge=1, le=16)] = 2
    default_runtime: RuntimeKind = RuntimeKind.DISABLED
    git: GitSafetyPolicy = Field(default_factory=GitSafetyPolicy)

    @field_validator("workspace_root")
    @classmethod
    def validate_workspace_root(cls, value: str) -> str:
        return _validate_relative_path(value, "workspace_root")


class SettingsConfig(StrictModel):
    schema_version: Literal[1] = 1
    settings: Settings


class AgentDefinition(StrictModel):
    role: Identifier
    team: Identifier
    runtime: RuntimeKind
    enabled: StrictBool = True
    permission_profile: Identifier
    working_directory_policy: WorkingDirectoryPolicy = WorkingDirectoryPolicy.PROJECT_WORKSPACE
    model: ModelName | None = None
    skills: tuple[Identifier, ...] = ()
    tools: tuple[Identifier, ...] = ()
    max_concurrency: Annotated[StrictInt, Field(ge=1, le=8)] = 1

    @field_validator("skills", "tools")
    @classmethod
    def validate_unique_names(cls, value: tuple[str, ...], info: object) -> tuple[str, ...]:
        field_name = getattr(info, "field_name", "items")
        return tuple(_validate_unique(value, field_name))


class AgentRegistry(StrictModel):
    schema_version: Literal[1] = 1
    agents: dict[Identifier, AgentDefinition]


class TeamDefinition(StrictModel):
    type: TeamType
    display_name: DisplayName
    room: Identifier
    agents: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    project: Identifier | None = None

    @field_validator("agents")
    @classmethod
    def validate_unique_agents(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validate_unique(value, "agents"))

    @model_validator(mode="after")
    def validate_team_kind(self) -> Self:
        if self.type is TeamType.PLATFORM and self.project is not None:
            raise ValueError("platform teams must not reference a project")
        if self.type is TeamType.PRODUCT and self.project is None:
            raise ValueError("product teams must reference a project")
        return self


class TeamRegistry(StrictModel):
    schema_version: Literal[1] = 1
    teams: dict[Identifier, TeamDefinition]


class ProjectDefinition(StrictModel):
    display_name: DisplayName
    repository: Annotated[
        str,
        StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500),
    ]
    workspace: str
    team: Identifier
    base_branch: GitBranchName | None = None

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if any(character in value for character in ("\n", "\r", "\x00")):
            raise ValueError("repository contains control characters")

        if "://" in value:
            parsed = urlsplit(value)
            if parsed.scheme not in {"https", "ssh", "git", "file"}:
                raise ValueError("repository uses an unsupported URL scheme")
            if parsed.query or parsed.fragment or parsed.password:
                raise ValueError("repository URLs must not contain credentials, query, or fragment")
            if parsed.scheme == "https" and parsed.username:
                raise ValueError("HTTPS repository URLs must not contain credentials")

        lowered = value.lower()
        secret_markers = ("token=", "password=", "api_key=", "apikey=")
        if any(marker in lowered for marker in secret_markers):
            raise ValueError("repository must not contain credential material")
        return value

    @field_validator("workspace")
    @classmethod
    def validate_workspace(cls, value: str) -> str:
        return _validate_relative_path(value, "workspace")

    @field_validator("base_branch")
    @classmethod
    def validate_base_branch(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split("/")
        if (
            ".." in value
            or "@{" in value
            or "//" in value
            or value.endswith(("/", ".", ".lock"))
            or any(part.startswith(".") or part.endswith(".") for part in parts)
        ):
            raise ValueError("base_branch is not a safe Git branch name")
        return value


class ProjectRegistry(StrictModel):
    schema_version: Literal[1] = 1
    projects: dict[Identifier, ProjectDefinition]


class PermissionRegistry(StrictModel):
    schema_version: Literal[1] = 1
    permissions: dict[Identifier, Annotated[tuple[Capability, ...], Field(min_length=1)]]

    @field_validator("permissions")
    @classmethod
    def validate_permission_profiles(
        cls, value: dict[str, tuple[Capability, ...]]
    ) -> dict[str, tuple[Capability, ...]]:
        for profile_name, capabilities in value.items():
            _validate_unique(capabilities, f"permissions.{profile_name}")
        return value


class ConfigBundle(StrictModel):
    """All registries after schema and cross-registry validation."""

    settings: SettingsConfig
    agents: AgentRegistry
    teams: TeamRegistry
    projects: ProjectRegistry
    permissions: PermissionRegistry

    @model_validator(mode="after")
    def validate_relationships(self) -> Self:
        errors: list[str] = []
        agents = self.agents.agents
        teams = self.teams.teams
        projects = self.projects.projects
        permission_profiles = self.permissions.permissions

        for agent_id, agent in agents.items():
            team = teams.get(agent.team)
            if team is None:
                errors.append(f"agent {agent_id!r} references unknown team {agent.team!r}")
            elif agent_id not in team.agents:
                errors.append(f"agent {agent_id!r} is not listed by team {agent.team!r}")
            if agent.permission_profile not in permission_profiles:
                errors.append(
                    f"agent {agent_id!r} references unknown permission profile "
                    f"{agent.permission_profile!r}"
                )

        for team_id, team in teams.items():
            for agent_id in team.agents:
                team_agent = agents.get(agent_id)
                if team_agent is None:
                    errors.append(f"team {team_id!r} references unknown agent {agent_id!r}")
                elif team_agent.team != team_id:
                    errors.append(
                        f"team {team_id!r} lists agent {agent_id!r}, "
                        f"which belongs to {team_agent.team!r}"
                    )

            if team.type is TeamType.PRODUCT and team.project is not None:
                project = projects.get(team.project)
                if project is None:
                    errors.append(
                        f"product team {team_id!r} references unknown project {team.project!r}"
                    )
                elif project.team != team_id:
                    errors.append(
                        f"product team {team_id!r} and project {team.project!r} are not reciprocal"
                    )

        expected_project_prefix = PurePosixPath(self.settings.settings.workspace_root) / "projects"
        project_workspaces: dict[PurePosixPath, str] = {}
        for project_id, project in projects.items():
            team = teams.get(project.team)
            if team is None:
                errors.append(f"project {project_id!r} references unknown team {project.team!r}")
            elif team.type is not TeamType.PRODUCT:
                errors.append(f"project {project_id!r} must be owned by a product team")
            elif team.project != project_id:
                errors.append(
                    f"project {project_id!r} and product team {project.team!r} are not reciprocal"
                )

            workspace = PurePosixPath(project.workspace)
            if workspace == expected_project_prefix or not workspace.is_relative_to(
                expected_project_prefix
            ):
                errors.append(
                    f"project {project_id!r} workspace must be under "
                    f"{expected_project_prefix.as_posix()!r}"
                )
            if existing_project_id := project_workspaces.get(workspace):
                errors.append(
                    f"projects {existing_project_id!r} and {project_id!r} share workspace "
                    f"{workspace.as_posix()!r}"
                )
            project_workspaces[workspace] = project_id

        rooms: dict[str, str] = {}
        for team_id, team in teams.items():
            if existing_team_id := rooms.get(team.room):
                errors.append(
                    f"teams {existing_team_id!r} and {team_id!r} share room {team.room!r}"
                )
            rooms[team.room] = team_id

        if errors:
            raise ValueError("invalid configuration relationships: " + "; ".join(errors))
        return self
