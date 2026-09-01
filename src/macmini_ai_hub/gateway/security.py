"""Small fail-closed gateway security helpers."""

from __future__ import annotations

import re

from macmini_ai_hub.config.models import Identifier
from macmini_ai_hub.gateway.models import GatewayCommand, OpaqueId

_NAMED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|authorization|client[_-]?secret|password|private[_-]?key|"
    r"refresh[_-]?token|secret|signing[_-]?secret|token)\b(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SLACK_TOKEN = re.compile(r"\bxox[a-z]-[A-Za-z0-9-]{8,}\b", re.IGNORECASE)
_OPENAI_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_GITHUB_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----.*?-----END \1-----",
    re.DOTALL,
)


def redact_sensitive_text(value: str, *, max_length: int = 4_000) -> str:
    """Redact common credential shapes before interface delivery."""

    redacted = _PEM_PRIVATE_KEY.sub("[REDACTED]", value)
    redacted = _BEARER_SECRET.sub("Bearer [REDACTED]", redacted)
    redacted = _SLACK_TOKEN.sub("[REDACTED]", redacted)
    redacted = _OPENAI_TOKEN.sub("[REDACTED]", redacted)
    redacted = _GITHUB_TOKEN.sub("[REDACTED]", redacted)
    redacted = _NAMED_SECRET.sub(r"\1\2[REDACTED]", redacted)
    if len(redacted) > max_length:
        redacted = redacted[: max_length - 14].rstrip() + "… [truncated]"
    return redacted


def contains_sensitive_material(value: str) -> bool:
    """Detect credential-shaped content without treating length as sensitivity."""

    return redact_sensitive_text(value, max_length=max(len(value), 14)) != value


class AllowlistAuthorizer:
    """Exact actor allowlist; an empty allowlist authorizes nobody."""

    def __init__(self, allowed_actor_ids: set[str] | frozenset[str]) -> None:
        self._allowed_actor_ids = frozenset(allowed_actor_ids)

    async def is_authorized(
        self,
        *,
        actor_id: OpaqueId,
        command: GatewayCommand,
        project: Identifier | None,
    ) -> bool:
        del command, project
        return actor_id in self._allowed_actor_ids
