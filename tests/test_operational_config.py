from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from macmini_ai_hub.config import OperationalSettings


@pytest.fixture(autouse=True)
def isolate_operational_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("AI_HUB_") or name in {
            "SLACK_BOT_TOKEN",
            "SLACK_APP_TOKEN",
            "SLACK_SIGNING_SECRET",
        }:
            monkeypatch.delenv(name, raising=False)


def test_operational_paths_resolve_inside_repository(tmp_path: Path) -> None:
    settings = OperationalSettings(repository_root=tmp_path, use_example_config=True)

    paths = settings.resolve_paths()

    assert paths.projects_directory == tmp_path / "workspace" / "projects"
    assert paths.database_path == tmp_path / "workspace" / "tasks" / "ai-hub.sqlite3"


def test_database_must_stay_in_workspace(tmp_path: Path) -> None:
    settings = OperationalSettings(repository_root=tmp_path, database_path=Path("outside.sqlite3"))

    with pytest.raises(ValueError, match="inside workspace"):
        settings.resolve_paths()


def test_phase_one_rejects_non_loopback_binding() -> None:
    with pytest.raises(ValidationError, match="loopback"):
        OperationalSettings(host="0.0.0.0")


def test_slack_requires_tokens_and_actor_allowlist() -> None:
    with pytest.raises(ValidationError, match="token variables"):
        OperationalSettings(slack_enabled=True)

    with pytest.raises(ValidationError, match="ALLOWED_USER_IDS"):
        OperationalSettings(
            slack_enabled=True,
            slack_bot_token="xoxb-placeholder",
            slack_app_token="xapp-placeholder",
        )


def test_secret_values_are_redacted_from_model_repr() -> None:
    settings = OperationalSettings(
        slack_enabled=True,
        slack_bot_token="xoxb-placeholder",
        slack_app_token="xapp-placeholder",
        slack_allowed_user_ids="U123,U456",
    )

    rendered = repr(settings)
    assert "xoxb-placeholder" not in rendered
    assert settings.allowed_slack_users == frozenset({"U123", "U456"})
