"""Public Agent Gateway contracts."""

from macmini_ai_hub.gateway.dedup import (
    DurableRequestDeduplicator,
    InMemoryRequestDeduplicator,
)
from macmini_ai_hub.gateway.models import (
    CancelTaskCommand,
    CreateTaskCommand,
    GatewayCode,
    GatewayCommand,
    GatewayRequest,
    GatewayResponse,
    TaskView,
)
from macmini_ai_hub.gateway.ports import (
    ActorAuthorizer,
    DependencyUnavailableError,
    GatewayRequestStore,
    RequestDeduplicator,
    TaskCommandPort,
    TaskConflictError,
    TaskEnqueuePort,
    TaskIdFactory,
    TaskNotFoundError,
    TaskQueryPort,
)
from macmini_ai_hub.gateway.security import (
    AllowlistAuthorizer,
    contains_sensitive_material,
    redact_sensitive_text,
)
from macmini_ai_hub.gateway.service import AgentGateway, UuidTaskIdFactory

__all__ = [
    "ActorAuthorizer",
    "AgentGateway",
    "AllowlistAuthorizer",
    "CancelTaskCommand",
    "CreateTaskCommand",
    "DependencyUnavailableError",
    "DurableRequestDeduplicator",
    "GatewayCode",
    "GatewayCommand",
    "GatewayRequest",
    "GatewayRequestStore",
    "GatewayResponse",
    "InMemoryRequestDeduplicator",
    "RequestDeduplicator",
    "TaskCommandPort",
    "TaskConflictError",
    "TaskEnqueuePort",
    "TaskIdFactory",
    "TaskNotFoundError",
    "TaskQueryPort",
    "TaskView",
    "UuidTaskIdFactory",
    "contains_sensitive_material",
    "redact_sensitive_text",
]
