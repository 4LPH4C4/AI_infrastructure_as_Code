"""Core domain contracts independent of interfaces and runtimes."""

from macmini_ai_hub.domain.events import EventEnvelope, EventLevel, EventType
from macmini_ai_hub.domain.tasks import (
    LEGAL_TASK_TRANSITIONS,
    InvalidTaskTransition,
    Task,
    TaskStatus,
    allowed_transitions,
    can_transition,
    transition_task,
)

__all__ = [
    "LEGAL_TASK_TRANSITIONS",
    "EventEnvelope",
    "EventLevel",
    "EventType",
    "InvalidTaskTransition",
    "Task",
    "TaskStatus",
    "allowed_transitions",
    "can_transition",
    "transition_task",
]
