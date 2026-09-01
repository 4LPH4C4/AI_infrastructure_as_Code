"""Portable, secret-safe Phase 1 readiness checks used by ``doctor.sh``."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from macmini_ai_hub.config import OperationalSettings, load_config_bundle
from macmini_ai_hub.locks import LockMetadata


@dataclass(frozen=True, slots=True)
class Diagnostic:
    level: str
    message: str


def collect_diagnostics(repository_root: Path) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    env_file = repository_root / ".env"
    try:
        settings = OperationalSettings(
            repository_root=repository_root,
            _env_file=env_file if env_file.is_file() else None,
        )
        paths = settings.resolve_paths()
    except Exception:  # Configuration errors are intentionally redacted.
        return [Diagnostic("FAIL", "operational configuration is invalid (values redacted)")]

    diagnostics.append(Diagnostic("PASS", "operational configuration is valid"))
    try:
        load_config_bundle(
            paths.config_directory,
            use_examples=settings.use_example_config,
        )
    except Exception:
        suffix = "*.example.yaml" if settings.use_example_config else "*.yaml"
        diagnostics.append(
            Diagnostic("FAIL", f"registry configuration {suffix} is missing or invalid")
        )
    else:
        diagnostics.append(Diagnostic("PASS", "registry configuration is valid"))

    for name, path in (
        ("workspace", paths.workspace_directory),
        ("projects", paths.projects_directory),
        ("logs", paths.logs_directory),
        ("locks", paths.locks_directory),
        ("tasks", paths.database_path.parent),
    ):
        if path.is_dir() and _directory_is_writable(path):
            diagnostics.append(Diagnostic("PASS", f"{name} directory exists and is writable"))
        elif path.is_dir():
            diagnostics.append(Diagnostic("FAIL", f"{name} directory is not writable"))
        else:
            diagnostics.append(Diagnostic("FAIL", f"{name} directory is missing"))

    diagnostics.extend(_database_diagnostics(paths.database_path))
    diagnostics.extend(_lock_diagnostics(paths.locks_directory))

    if settings.slack_enabled:
        diagnostics.append(
            Diagnostic("PASS", "Slack is enabled with required token presence and actor allowlist")
        )
    else:
        diagnostics.append(Diagnostic("WARN", "Slack is disabled by configuration"))

    diagnostics.extend(_http_diagnostics(settings.host, settings.port))
    return diagnostics


def _directory_is_writable(path: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(prefix=".doctor-", dir=path):
            pass
    except OSError:
        return False
    return True


def _database_diagnostics(database_path: Path) -> list[Diagnostic]:
    if not database_path.exists():
        return [Diagnostic("WARN", "SQLite database is not initialized")]
    if not database_path.is_file():
        return [Diagnostic("FAIL", "SQLite database path is not a regular file")]
    try:
        connection = sqlite3.connect(
            f"file:{urllib.parse.quote(database_path.as_posix(), safe='/:')}?mode=ro",
            uri=True,
            timeout=1.0,
        )
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return [Diagnostic("FAIL", "SQLite database cannot be opened or checked")]
    if result != ("ok",):
        return [Diagnostic("FAIL", "SQLite quick_check did not return ok")]
    return [Diagnostic("PASS", "SQLite database quick_check passed")]


def _lock_diagnostics(lock_directory: Path) -> list[Diagnostic]:
    if not lock_directory.is_dir():
        return []
    valid = 0
    malformed = 0
    for lock_path in lock_directory.glob("*.lock"):
        try:
            value = json.loads(lock_path.read_text(encoding="utf-8"))
            LockMetadata.from_mapping(value)
        except (OSError, ValueError, json.JSONDecodeError):
            malformed += 1
        else:
            valid += 1
    if malformed:
        return [
            Diagnostic(
                "FAIL",
                f"lock directory contains {malformed} malformed lock(s); no lock was removed",
            )
        ]
    if valid:
        return [Diagnostic("WARN", f"lock directory contains {valid} active lock(s)")]
    return [Diagnostic("PASS", "lock directory contains no active locks")]


def _http_diagnostics(host: str, port: int) -> list[Diagnostic]:
    return [
        _http_endpoint_diagnostic(host, port, "/health", "health"),
        _http_endpoint_diagnostic(host, port, "/ready", "readiness"),
    ]


def _http_endpoint_diagnostic(host: str, port: int, path: str, name: str) -> Diagnostic:
    authority = f"[{host}]" if ":" in host else host
    request = urllib.request.Request(
        f"http://{authority}:{port}{path}",
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=1.0) as response:
            status = response.status
            response.read(4096)
    except urllib.error.HTTPError as error:
        return Diagnostic("FAIL", f"local {name} endpoint returned HTTP {error.code}")
    except (OSError, urllib.error.URLError):
        return Diagnostic("WARN", f"local {name} endpoint is not reachable")
    if status == 200:
        return Diagnostic("PASS", f"local {name} endpoint responded successfully")
    return Diagnostic("FAIL", f"local {name} endpoint returned HTTP {status}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    arguments = parser.parse_args()
    diagnostics = collect_diagnostics(arguments.repository_root.resolve(strict=True))
    for diagnostic in diagnostics:
        print(f"[{diagnostic.level}] {diagnostic.message}")
    return 1 if any(item.level == "FAIL" for item in diagnostics) else 0


if __name__ == "__main__":
    sys.exit(main())
