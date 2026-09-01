from __future__ import annotations

import sys
from pathlib import Path

import pytest

from macmini_ai_hub.cli import main

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def repository_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "hub"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    return root


def configure_environment(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    setter = monkeypatch.setenv
    setter("AI_HUB_CONFIG_DIR", str(REPOSITORY_ROOT / "config"))
    setter("AI_HUB_USE_EXAMPLE_CONFIG", "true")
    setter("AI_HUB_WORKSPACE_DIR", "workspace")
    setter("AI_HUB_DATABASE_PATH", "workspace/tasks/state.sqlite3")
    setter("AI_HUB_CODEX_EXECUTABLE", sys.executable)
    setter("AI_HUB_SLACK_ENABLED", "false")


def test_check_config_and_migrate_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = repository_fixture(tmp_path)
    configure_environment(monkeypatch, root)

    assert main(["--repository-root", str(root), "check-config"]) == 0
    assert not (root / "workspace").exists()
    assert main(["--repository-root", str(root), "migrate"]) == 0
    assert (root / "workspace" / "tasks" / "state.sqlite3").is_file()


def test_cli_failure_never_echoes_secret_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = repository_fixture(tmp_path)
    configure_environment(monkeypatch, root)
    setter = monkeypatch.setenv
    setter("AI_HUB_SLACK_ENABLED", "true")
    setter("SLACK_BOT_TOKEN", "xoxb-DO-NOT-PRINT-THIS")
    setter("SLACK_APP_TOKEN", "xapp-DO-NOT-PRINT-THIS")
    setter("AI_HUB_SLACK_ALLOWED_USER_IDS", "")

    assert main(["--repository-root", str(root), "check-config"]) == 1
    captured = capsys.readouterr()
    assert "DO-NOT-PRINT-THIS" not in captured.out + captured.err
    assert "values were redacted" in captured.err
