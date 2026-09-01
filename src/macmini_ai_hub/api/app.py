"""Minimal local health and readiness HTTP application."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol

from fastapi import FastAPI, Response, status
from pydantic import BaseModel, ConfigDict

from macmini_ai_hub.config.models import Identifier


class ReadinessProbe(Protocol):
    @property
    def name(self) -> Identifier: ...

    async def check(self) -> bool: ...


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str = "ok"


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    components: dict[Identifier, str]


def create_app(
    *,
    readiness_probes: Sequence[ReadinessProbe] = (),
    readiness_timeout_seconds: float = 2.0,
) -> FastAPI:
    """Create an app only; host/port and localhost binding belong to composition."""

    if readiness_timeout_seconds <= 0:
        raise ValueError("readiness_timeout_seconds must be positive")
    names = [probe.name for probe in readiness_probes]
    if len(names) != len(set(names)):
        raise ValueError("readiness probe names must be unique")

    app = FastAPI(
        title="Mac Mini AI Hub Operations",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health", response_model=HealthResponse)
    async def health(response: Response) -> HealthResponse:
        response.headers["Cache-Control"] = "no-store"
        return HealthResponse()

    @app.get("/ready", response_model=ReadinessResponse)
    async def ready(response: Response) -> ReadinessResponse:
        checks = await asyncio.gather(
            *(
                _check_probe(probe, timeout_seconds=readiness_timeout_seconds)
                for probe in readiness_probes
            )
        )
        components = dict(zip(names, checks, strict=True))
        is_ready = all(value == "ok" for value in components.values())
        response.status_code = (
            status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        response.headers["Cache-Control"] = "no-store"
        return ReadinessResponse(
            status="ok" if is_ready else "unavailable",
            components=components,
        )

    return app


async def _check_probe(probe: ReadinessProbe, *, timeout_seconds: float) -> str:
    try:
        is_ready = await asyncio.wait_for(probe.check(), timeout=timeout_seconds)
    except Exception:
        return "unavailable"
    return "ok" if is_ready else "unavailable"
