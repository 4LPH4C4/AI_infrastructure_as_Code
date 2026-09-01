"""Bounded in-memory request deduplication for one process."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from time import monotonic
from typing import cast

from pydantic import JsonValue

from macmini_ai_hub.gateway.models import GatewayResponse
from macmini_ai_hub.gateway.ports import GatewayRequestStore


class DurableRequestDeduplicator:
    """Async gateway adapter over a synchronous durable request store."""

    def __init__(self, store: GatewayRequestStore) -> None:
        self._store = store

    async def get(self, key: str) -> GatewayResponse | None:
        record = await asyncio.to_thread(self._store.get_gateway_request, key)
        if record is None or record.response is None:
            return None
        return GatewayResponse.model_validate(record.response)

    async def reserve(self, key: str) -> bool:
        return await asyncio.to_thread(self._store.reserve_gateway_request, key)

    async def remember(self, key: str, response: GatewayResponse) -> None:
        document = cast(dict[str, JsonValue], response.model_dump(mode="json"))
        await asyncio.to_thread(self._store.remember_gateway_response, key, document)

    async def release(self, key: str) -> None:
        await asyncio.to_thread(self._store.release_gateway_request, key)

    async def reconcile_interrupted(self) -> tuple[str, ...]:
        return await asyncio.to_thread(self._store.reconcile_incomplete_gateway_requests)


class InMemoryRequestDeduplicator:
    """Concurrency-safe fallback; production can provide a durable adapter."""

    def __init__(self, *, max_entries: int = 10_000, ttl_seconds: float = 86_400.0) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._completed: OrderedDict[str, tuple[float, GatewayResponse]] = OrderedDict()
        self._in_flight: set[str] = set()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> GatewayResponse | None:
        async with self._lock:
            self._prune()
            entry = self._completed.get(key)
            if entry is None:
                return None
            self._completed.move_to_end(key)
            return entry[1]

    async def reserve(self, key: str) -> bool:
        async with self._lock:
            self._prune()
            if key in self._in_flight or key in self._completed:
                return False
            self._in_flight.add(key)
            return True

    async def remember(self, key: str, response: GatewayResponse) -> None:
        async with self._lock:
            self._in_flight.discard(key)
            self._completed[key] = (monotonic(), response)
            self._completed.move_to_end(key)
            while len(self._completed) > self._max_entries:
                self._completed.popitem(last=False)

    async def release(self, key: str) -> None:
        async with self._lock:
            self._in_flight.discard(key)

    def _prune(self) -> None:
        cutoff = monotonic() - self._ttl_seconds
        while self._completed:
            first_key, (stored_at, _) = next(iter(self._completed.items()))
            if stored_at >= cutoff:
                break
            self._completed.pop(first_key)
