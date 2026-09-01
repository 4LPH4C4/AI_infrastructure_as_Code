from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVICE_LABEL = "com.macmini-ai-hub.service"


def test_launchd_template_is_valid_secret_free_plist() -> None:
    template_path = REPOSITORY_ROOT / "launchd" / f"{SERVICE_LABEL}.plist.template"
    raw = template_path.read_bytes()
    document = plistlib.loads(raw)

    assert document["Label"] == SERVICE_LABEL
    assert document["RunAtLoad"] is False
    assert document["ProgramArguments"][-2:] == ["ai-hub", "serve"]
    assert document["ProgramArguments"][0] == "__UV_EXECUTABLE__"
    assert document["WorkingDirectory"] == "__REPOSITORY_ROOT__"
    assert document["EnvironmentVariables"]["PATH"] == "__SERVICE_PATH__"
    rendered = raw.decode("utf-8").lower()
    assert "token" not in rendered
    assert "secret" not in rendered
    assert "password" not in rendered


def test_all_operator_shell_scripts_enable_strict_mode() -> None:
    script_paths = [
        *sorted((REPOSITORY_ROOT / "bootstrap").glob("*.sh")),
        *sorted((REPOSITORY_ROOT / "scripts").glob("*.sh")),
        *sorted((REPOSITORY_ROOT / "scripts" / "lib").glob("*.sh")),
        *sorted((REPOSITORY_ROOT / "launchd").glob("*.sh")),
    ]

    assert script_paths
    for script_path in script_paths:
        lines = script_path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "#!/usr/bin/env bash", script_path
        assert lines[1] == "set -euo pipefail", script_path


def test_launchd_scripts_validate_the_exact_user_service_target() -> None:
    install_script = (REPOSITORY_ROOT / "launchd" / "install.sh").read_text(
        encoding="utf-8"
    )
    start_script = (REPOSITORY_ROOT / "scripts" / "start.sh").read_text(encoding="utf-8")
    combined = "\n".join(
        (
            install_script,
            (REPOSITORY_ROOT / "launchd" / "uninstall.sh").read_text(encoding="utf-8"),
            (REPOSITORY_ROOT / "scripts" / "lib" / "mac-service.sh").read_text(
                encoding="utf-8"
            ),
        )
    )

    assert SERVICE_LABEL in combined
    assert "Library/LaunchAgents" in combined
    assert "/Library/LaunchDaemons" not in combined
    assert "PlistBuddy" in combined
    assert "rm -rf" not in combined
    assert "launchctl bootstrap" not in install_script
    assert "launchctl bootstrap" in start_script


def test_portable_doctor_redacts_secret_values() -> None:
    secret_marker = "DO-NOT-PRINT-THIS-SECRET"
    environment = os.environ.copy()
    environment.update(
        {
            "AI_HUB_USE_EXAMPLE_CONFIG": "true",
            "AI_HUB_SLACK_ENABLED": "false",
            "SLACK_BOT_TOKEN": secret_marker,
            "SLACK_APP_TOKEN": secret_marker,
            "PYTHONPATH": str(REPOSITORY_ROOT / "src"),
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "scripts" / "doctor_portable.py"),
            "--repository-root",
            str(REPOSITORY_ROOT),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        shell=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert secret_marker not in output
    assert "registry configuration is valid" in output
    assert "SQLite database is not initialized" in output
