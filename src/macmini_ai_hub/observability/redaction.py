"""Deterministic recursive redaction for logs and read projections."""

from __future__ import annotations

import re

from pydantic import JsonValue

REDACTED = "[REDACTED]"

_SECRET_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "authorization_header",
        "client_secret",
        "cookie",
        "credentials",
        "github_token",
        "openai_api_key",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "signing_secret",
        "slack_app_token",
        "slack_bot_token",
        "token",
    }
)
_SECRET_SUFFIXES = ("_password", "_secret", "_token", "_api_key", "_private_key")
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----.*?-----END \1-----",
    re.DOTALL,
)
_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_PEM_PRIVATE_KEY, REDACTED),
    (re.compile(r"\b(?:xox[baprs]-|xapp-)[A-Za-z0-9-]+\b"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), REDACTED),
    (
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
        REDACTED,
    ),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), f"Bearer {REDACTED}"),
    (
        re.compile(
            r"(?i)\b(((?:[a-z0-9]+[_-])*api[_-]?key|password|client[_-]?secret|"
            r"access[_-]?token|refresh[_-]?token|authorization)\s*[:=]\s*)([^\s,;]+)"
        ),
        rf"\1{REDACTED}",
    ),
    (re.compile(r"(?i)(https?://)([^:/@\s]+):([^@\s]+)@"), rf"\1{REDACTED}@"),
)


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SECRET_KEYS or normalized.endswith(_SECRET_SUFFIXES)


def redact_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _TEXT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_secrets(value: JsonValue) -> JsonValue:
    """Return a JSON-compatible deep copy with secret keys and values removed."""

    if isinstance(value, dict):
        return {
            key: REDACTED if _is_secret_key(key) else redact_secrets(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(child) for child in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
