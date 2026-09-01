"""Application adapter for durable, route-aware task notifications."""

from __future__ import annotations

import asyncio
import logging
import re

from pydantic import JsonValue

from macmini_ai_hub.domain.tasks import Task, TaskStatus
from macmini_ai_hub.gateway.security import redact_sensitive_text
from macmini_ai_hub.integrations.slack import (
    SlackTaskNotifier,
    TaskLifecycleUpdate,
    decode_slack_route_target,
)
from macmini_ai_hub.storage import RunRecord, SQLiteStore, StoredEvent

_SLACK_SOURCE = "slack"
_REPLAYABLE_STATUSES = frozenset(
    {
        TaskStatus.RUNNING,
        TaskStatus.BLOCKED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
)
_LOGGER = logging.getLogger(__name__)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")
_MAX_RESULT_ITEMS = 20


class StoredRouteResultNotifier:
    """Deliver observable task state to its stored Slack route, if any."""

    def __init__(self, *, store: SQLiteStore, slack: SlackTaskNotifier) -> None:
        self._store = store
        self._slack = slack

    async def notify_task(self, task: Task) -> None:
        route = await asyncio.to_thread(self._store.get_task_route, task.task_id)
        if route is None or route.source != _SLACK_SOURCE:
            return

        events, runs = await asyncio.gather(
            asyncio.to_thread(
                self._store.list_events,
                task_id=task.task_id,
                limit=10_000,
            ),
            asyncio.to_thread(self._store.list_runs, task.task_id),
        )
        update = _task_update(task, events=events, runs=runs)

        await self._slack.notify(
            route=decode_slack_route_target(route.target),
            update=update,
        )

    async def reconcile_pending(self) -> tuple[str, ...]:
        """Replay routed lifecycle updates that lack a durable delivery receipt."""

        routes = await asyncio.to_thread(self._store.list_task_routes)
        failed: list[str] = []
        for route in routes:
            if route.source != _SLACK_SOURCE:
                continue
            try:
                task = await asyncio.to_thread(self._store.get_task, route.task_id)
                if task.status not in _REPLAYABLE_STATUSES:
                    continue
                delivery_id = f"task-update:{task.task_id}:{task.status.value}"
                delivered = await asyncio.to_thread(
                    self._store.is_delivery_delivered,
                    delivery_id,
                )
                if not delivered:
                    await self.notify_task(task)
            except Exception:
                failed.append(route.task_id)
                _LOGGER.exception(
                    "task notification replay failed",
                    extra={"task_id": route.task_id},
                )
        return tuple(failed)


def _task_update(
    task: Task,
    *,
    events: tuple[StoredEvent, ...],
    runs: tuple[RunRecord, ...],
) -> TaskLifecycleUpdate:
    payload = _matching_lifecycle_payload(task, events)
    branch = _safe_optional_line(payload.get("branch"))
    changed_files = _safe_lines(payload.get("changed_files"))
    latest_run = runs[-1] if runs else None
    runtime_outcome = (
        _safe_optional_line(f"{latest_run.runtime}: {latest_run.status.value}")
        if latest_run is not None
        else None
    )
    error_value = payload.get("reason")
    if error_value is None and latest_run is not None:
        error_value = latest_run.error_code
    error = (
        _safe_optional_line(error_value)
        if task.status in {TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        else None
    )
    return TaskLifecycleUpdate(
        notification_id=f"{task.task_id}:{task.status.value}",
        task_id=task.task_id,
        status=task.status,
        project=task.project,
        team=task.team,
        changed_files=changed_files,
        runtime_outcome=runtime_outcome,
        branch=branch,
        error=error,
    )


def _matching_lifecycle_payload(
    task: Task,
    events: tuple[StoredEvent, ...],
) -> dict[str, JsonValue]:
    for stored in reversed(events):
        event = stored.envelope
        if event.task_id == task.task_id and event.payload.get("status") == task.status.value:
            return event.payload
    return {}


def _safe_lines(value: JsonValue | None) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    lines: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        line = _safe_optional_line(item)
        if line is not None:
            lines.append(line)
        if len(lines) == _MAX_RESULT_ITEMS:
            break
    return tuple(lines)


def _safe_optional_line(value: JsonValue | None) -> str | None:
    if not isinstance(value, str):
        return None
    single_line = _CONTROL_CHARACTERS.sub(" ", value).strip()
    if not single_line:
        return None
    return redact_sensitive_text(single_line, max_length=500)
