"""Operator CLI for the local Phase 1 service."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from macmini_ai_hub.application import (
    build_application,
    validate_startup_configuration,
)
from macmini_ai_hub.config import OperationalSettings
from macmini_ai_hub.storage import SQLiteStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-hub")
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
        help="AI Hub Git checkout (default: current directory)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-config", help="validate settings and registries without writing")
    commands.add_parser("migrate", help="initialize or migrate the durable local database")
    commands.add_parser("serve", help="run the orchestrator, local health API, and optional Slack")
    commands.add_parser("status", help="check local configuration, database, and readiness")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    repository_root = arguments.repository_root.resolve()
    try:
        settings = _settings(repository_root)
        if arguments.command == "check-config":
            paths, bundle = validate_startup_configuration(settings)
            print(
                "Configuration valid: "
                f"{len(bundle.projects.projects)} project(s), workspace={paths.workspace_directory}"
            )
            return 0
        if arguments.command == "migrate":
            application = build_application(settings)
            try:
                print(
                    "Database ready: "
                    f"schema={application.store.schema_version}, "
                    f"path={application.paths.database_path}"
                )
            finally:
                application.close()
            return 0
        if arguments.command == "status":
            return _status(settings)
        if arguments.command == "serve":
            application = build_application(settings)
            try:
                asyncio.run(application.serve())
            finally:
                application.close()
            return 0
        raise AssertionError(f"unhandled command: {arguments.command}")
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(
            f"ERROR: {type(error).__name__}; operation failed and values were redacted. "
            "Run make doctor for diagnostics.",
            file=sys.stderr,
        )
        return 1


def _settings(repository_root: Path) -> OperationalSettings:
    env_file = repository_root / ".env"
    return OperationalSettings(
        repository_root=repository_root,
        _env_file=env_file if env_file.is_file() else None,
    )


def _status(settings: OperationalSettings) -> int:
    paths, _ = validate_startup_configuration(settings)
    if not paths.database_path.is_file():
        print("AI Hub unavailable: SQLite database is not initialized.")
        return 1
    with SQLiteStore(paths.database_path) as store:
        schema_version = store.schema_version

    host = f"[{settings.host}]" if ":" in settings.host else settings.host
    request = urllib.request.Request(
        f"http://{host}:{settings.port}/ready",
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            document = json.loads(response.read(16_384))
            ready = response.status == 200 and document.get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        ready = False
    print(f"AI Hub: {'ready' if ready else 'unavailable'}; schema={schema_version}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
