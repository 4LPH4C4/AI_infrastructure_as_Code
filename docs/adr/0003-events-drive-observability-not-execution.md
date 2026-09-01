# ADR-0003: Events drive observability, not execution authority

- Status: Accepted
- Date: 2026-09-01

## Context

Task history, structured logging, Slack progress, dashboards, and the future Pixel Agent Office need a common, truthful representation of activity. Letting each consumer inspect runtime internals would create coupling, inconsistent state, privacy leakage, and pressure to expose model reasoning.

## Decision

1. A durable task record is the current-state source of truth. Immutable, versioned domain events provide history and downstream projection input.
2. Material lifecycle/routing/assignment/review/QA/artifact outcomes emit an event envelope with event ID/type, UTC timestamp, correlation/causation, and relevant task/project/team/agent references.
3. State transition and matching event append should be transactional once persistence exists.
4. Consumers use `event_id` for idempotency and tolerate reconnect/replay.
5. Events and logs contain observable facts only. They never contain hidden chain-of-thought, unredacted secrets, or fabricated activity.
6. Slack status, operational logs, analytics, and Pixel Office are downstream projections. Their failure cannot control or redefine successful execution.
7. Pixel Office is read-oriented. It may visualize configured rooms, real task/agent/team state, delegation, artifacts, idle/offline/failure, but it is not the runtime or an authoritative command path.

## Consequences

- All status surfaces can agree on the same vocabulary.
- Event replay can rebuild projections and explain failures without reading agent internals.
- The UI accurately becomes quiet when the backend is idle.
- Event schema evolution, redaction, retention, and ordering scope require explicit policy.
- Delivery failures are tracked separately from task results.

## Rejected alternatives

- Poll agent objects directly: ephemeral, tightly coupled, and restart-unsafe.
- Make Pixel UI control the runtime: turns optional visualization into a critical dependency.
- Display model chain-of-thought: not an observable operational requirement and creates privacy/security risk.
- Fabricate animation when no event exists: makes observability misleading.
