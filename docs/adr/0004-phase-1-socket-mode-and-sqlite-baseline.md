# ADR-0004: Phase 1 uses Slack Socket Mode and SQLite as the baseline

- Status: Accepted and implemented offline; target-Mac verification pending
- Date: 2026-09-01

## Context

The first end-to-end interface will be Slack on a personal Mac behind a home network. Operational task/run/event history must survive process and machine restarts. The system is one host with low initial concurrency, so public inbound HTTP, a database server, Redis, or a workflow platform would add avoidable failure and security surfaces.

## Decision

Phase 1 implements the following approved decisions:

1. Use Slack Bolt Socket Mode as the initial connection model. It initiates an outbound connection and does not require a public inbound webhook.
2. Keep Slack behind an interface adapter and Agent Gateway so another connection model can be introduced without changing execution policy.
3. Use SQLite as the first durable store for tasks, runs, events, and artifact metadata.
4. Put persistence behind repository/unit-of-work ports with versioned migrations so PostgreSQL remains a future option.
5. Keep Redis out of the initial durable path. If later used for ephemeral coordination, it is never the only task/event history.
6. Keep long-running work off Slack handlers; acknowledge durable task creation promptly and deliver results from projections.
7. Bind health/readiness locally by default and expose no database, debug, admin, or Pixel service publicly.

## Consequences

- Phase 1 has fewer daemons, credentials, ports, backups, and startup dependencies.
- Socket Mode availability depends on Slack and outbound connectivity but reduces home-network exposure.
- SQLite fits one-machine concurrency and offers transactional durability/backup simplicity; writes and project execution still require bounded concurrency.
- Storage migrations and clean ports are required from the first persistent schema.
- A measured need, migration plan, and new ADR are required before adopting PostgreSQL/Redis or a public webhook.

## Rejected alternatives

- Public Slack webhook for the MVP: requires inbound exposure/tunneling and more network hardening.
- PostgreSQL from Phase 1 start: operational cost is not justified by expected single-host load.
- Redis as state history: insufficient as the sole durable audit record.
- n8n as orchestrator: integration automation is not the core agent execution authority.
