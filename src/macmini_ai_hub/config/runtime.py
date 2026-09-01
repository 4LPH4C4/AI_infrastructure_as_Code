"""Machine-local Phase 1 settings with fail-closed path and network defaults."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, SecretStr, StringConstraints, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from macmini_ai_hub.config.models import Environment, LogLevel

ExecutableName = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500),
]


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    repository_root: Path
    config_directory: Path
    workspace_directory: Path
    projects_directory: Path
    database_path: Path
    logs_directory: Path
    locks_directory: Path


class OperationalSettings(BaseSettings):
    """Settings loaded from environment/``.env`` without exposing secret values."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AI_HUB_",
        extra="ignore",
        case_sensitive=False,
        validate_default=True,
        populate_by_name=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    repository_root: Path = Path(".")
    config_dir: Path = Path("config")
    workspace_dir: Path = Path("workspace")
    database_path: Path = Path("workspace/tasks/ai-hub.sqlite3")
    use_example_config: bool = False
    host: str = "127.0.0.1"
    port: Annotated[int, Field(strict=True, ge=1, le=65_535)] = 8765
    log_level: LogLevel = LogLevel.INFO
    max_concurrent_tasks: Annotated[int, Field(strict=True, ge=1, le=16)] = 2
    poll_interval_seconds: Annotated[float, Field(strict=True, gt=0, le=60)] = 1.0
    shutdown_timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=300)] = 30
    codex_executable: ExecutableName = "codex"
    codex_timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=86_400)] = 3600
    runtime_output_limit_bytes: Annotated[int, Field(strict=True, ge=1024, le=10_000_000)] = (
        1_000_000
    )
    slack_enabled: bool = False
    slack_bot_token: SecretStr | None = Field(default=None, validation_alias="SLACK_BOT_TOKEN")
    slack_app_token: SecretStr | None = Field(default=None, validation_alias="SLACK_APP_TOKEN")
    slack_signing_secret: SecretStr | None = Field(
        default=None,
        validation_alias="SLACK_SIGNING_SECRET",
    )
    slack_allowed_user_ids: str = ""

    @field_validator("host")
    @classmethod
    def validate_local_host(cls, value: str) -> str:
        if value not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Phase 1 HTTP service must bind to loopback")
        return value

    @field_validator("codex_executable")
    @classmethod
    def validate_executable(cls, value: str) -> str:
        if any(character in value for character in ("\x00", "\n", "\r")):
            raise ValueError("codex_executable contains control characters")
        return value

    @model_validator(mode="after")
    def validate_slack(self) -> Self:
        if self.slack_enabled:
            missing = [
                name
                for name, secret in (
                    ("SLACK_BOT_TOKEN", self.slack_bot_token),
                    ("SLACK_APP_TOKEN", self.slack_app_token),
                )
                if secret is None or not secret.get_secret_value()
            ]
            if missing:
                raise ValueError("Slack is enabled but required token variables are missing")
            if not self.allowed_slack_users:
                raise ValueError("Slack is enabled but AI_HUB_SLACK_ALLOWED_USER_IDS is empty")
        return self

    @property
    def allowed_slack_users(self) -> frozenset[str]:
        return frozenset(
            user_id.strip()
            for user_id in self.slack_allowed_user_ids.split(",")
            if user_id.strip()
        )

    def resolve_paths(self) -> RuntimePaths:
        root = self.repository_root.resolve()

        def resolve_from_root(path: Path) -> Path:
            return path.resolve() if path.is_absolute() else (root / path).resolve()

        config_directory = resolve_from_root(self.config_dir)
        workspace_directory = resolve_from_root(self.workspace_dir)
        database_path = resolve_from_root(self.database_path)
        try:
            database_path.relative_to(workspace_directory)
        except ValueError as error:
            raise ValueError("database_path must stay inside workspace_dir") from error
        return RuntimePaths(
            repository_root=root,
            config_directory=config_directory,
            workspace_directory=workspace_directory,
            projects_directory=workspace_directory / "projects",
            database_path=database_path,
            logs_directory=workspace_directory / "logs",
            locks_directory=workspace_directory / "locks",
        )
