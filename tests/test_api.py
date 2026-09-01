from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from macmini_ai_hub.api import create_app


@dataclass
class FakeProbe:
    name: str
    result: bool = True
    error: Exception | None = None
    delay_seconds: float = 0
    calls: int = 0

    async def check(self) -> bool:
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return self.result


def test_health_is_liveness_only_and_never_calls_dependencies() -> None:
    storage = FakeProbe(name="storage", result=False)
    client = TestClient(create_app(readiness_probes=(storage,)))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert storage.calls == 0


def test_ready_reports_each_required_component_without_details() -> None:
    storage = FakeProbe(name="storage")
    runtime = FakeProbe(name="runtime", result=False)
    client = TestClient(create_app(readiness_probes=(storage, runtime)))

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "components": {"storage": "ok", "runtime": "unavailable"},
    }
    assert response.headers["cache-control"] == "no-store"


def test_ready_is_ok_only_when_all_dependencies_are_ready() -> None:
    client = TestClient(
        create_app(
            readiness_probes=(
                FakeProbe(name="storage"),
                FakeProbe(name="runtime"),
                FakeProbe(name="workspace"),
            )
        )
    )

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_hides_exception_and_timeout_details() -> None:
    failed = FakeProbe(name="storage", error=RuntimeError("password=never-print"))
    slow = FakeProbe(name="runtime", delay_seconds=0.05)
    client = TestClient(
        create_app(
            readiness_probes=(failed, slow),
            readiness_timeout_seconds=0.001,
        )
    )

    response = client.get("/ready")
    body = response.text.lower()

    assert response.status_code == 503
    assert response.json()["components"] == {
        "storage": "unavailable",
        "runtime": "unavailable",
    }
    assert "password" not in body
    assert "never-print" not in body
    assert "timeout" not in body


def test_app_factory_rejects_duplicate_probe_names_and_invalid_timeout() -> None:
    with pytest.raises(ValueError, match="unique"):
        create_app(
            readiness_probes=(FakeProbe(name="storage"), FakeProbe(name="storage"))
        )
    with pytest.raises(ValueError, match="positive"):
        create_app(readiness_timeout_seconds=0)


def test_operational_app_disables_interactive_schema_endpoints() -> None:
    client = TestClient(create_app())

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
