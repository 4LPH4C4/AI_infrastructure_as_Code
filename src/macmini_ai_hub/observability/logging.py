"""Bounded, secret-redacted JSON logging for the local service."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pydantic import JsonValue

from macmini_ai_hub.observability.redaction import redact_text


class RedactedJsonFormatter(logging.Formatter):
    """Render one bounded JSON object without leaking exception or message secrets."""

    def format(self, record: logging.LogRecord) -> str:
        document: dict[str, JsonValue] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage())[:4_000],
        }
        for name in ("task_id", "project", "team", "agent"):
            value = getattr(record, name, None)
            if isinstance(value, str) and value:
                document[name] = redact_text(value)[:200]
        if record.exc_info is not None:
            document["exception"] = redact_text(self.formatException(record.exc_info))[:8_000]
        return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def configure_rotating_json_logging(
    log_directory: Path,
    *,
    level: str,
    max_bytes: int = 10_000_000,
    backup_count: int = 5,
) -> Path:
    """Replace root handlers with one local rotating JSONL handler."""

    if max_bytes < 1 or backup_count < 1:
        raise ValueError("log rotation bounds must be positive")
    log_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = log_directory / "ai-hub.jsonl"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(RedactedJsonFormatter())
    root = logging.getLogger()
    for existing in tuple(root.handlers):
        root.removeHandler(existing)
        existing.close()
    root.setLevel(level)
    root.addHandler(handler)
    return log_path
