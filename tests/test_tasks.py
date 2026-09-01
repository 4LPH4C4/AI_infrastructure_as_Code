from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from macmini_ai_hub.domain.tasks import (
    LEGAL_TASK_TRANSITIONS,
    InvalidTaskTransition,
    Task,
    TaskStatus,
    can_transition,
    transition_task,
)


def make_task() -> Task:
    return Task(
        task_id="TASK-1042",
        source="test",
        project="example-project",
        team="example-product",
        request="Validate the lifecycle.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_transition_table_is_total_and_terminal_states_are_final() -> None:
    assert set(LEGAL_TASK_TRANSITIONS) == set(TaskStatus)
    for status in TaskStatus:
        assert status not in LEGAL_TASK_TRANSITIONS[status]
    for terminal in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        assert terminal.is_terminal
        assert LEGAL_TASK_TRANSITIONS[terminal] == frozenset()


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current, targets in LEGAL_TASK_TRANSITIONS.items()
        for target in targets
    ],
)
def test_every_declared_transition_is_legal(current: TaskStatus, target: TaskStatus) -> None:
    assert can_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current in TaskStatus
        for target in TaskStatus
        if target not in LEGAL_TASK_TRANSITIONS[current]
    ],
)
def test_every_undeclared_transition_is_illegal(current: TaskStatus, target: TaskStatus) -> None:
    assert not can_transition(current, target)


def test_transition_task_sets_started_and_completed_timestamps() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    completed_at = created_at + timedelta(seconds=2)
    task = make_task()

    queued = transition_task(task, TaskStatus.QUEUED, at=created_at)
    running = transition_task(queued, TaskStatus.RUNNING, at=started_at)
    completed = transition_task(running, TaskStatus.COMPLETED, at=completed_at)

    assert task.status is TaskStatus.PENDING
    assert completed.started_at == started_at
    assert completed.completed_at == completed_at
    assert completed.status is TaskStatus.COMPLETED


def test_illegal_transition_raises_structured_error() -> None:
    with pytest.raises(InvalidTaskTransition) as error:
        transition_task(make_task(), TaskStatus.COMPLETED)

    assert error.value.current is TaskStatus.PENDING
    assert error.value.target is TaskStatus.COMPLETED


def test_transition_time_cannot_move_backwards() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    running = transition_task(
        transition_task(make_task(), TaskStatus.QUEUED, at=created_at),
        TaskStatus.RUNNING,
        at=created_at + timedelta(seconds=2),
    )

    with pytest.raises(ValueError, match="must not precede task start"):
        transition_task(running, TaskStatus.REVIEW, at=created_at + timedelta(seconds=1))


def test_task_rejects_naive_timestamps_and_duplicate_agents() -> None:
    data = make_task().model_dump()
    data["created_at"] = datetime(2026, 1, 1)
    data["assigned_agents"] = ("orchestrator", "orchestrator")

    with pytest.raises(ValidationError):
        Task.model_validate(data)
