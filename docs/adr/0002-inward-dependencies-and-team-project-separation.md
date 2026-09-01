# ADR-0002: Inward dependencies and team/project separation

- Status: Accepted
- Date: 2026-09-01

## Context

Slack is the first planned interface and Codex the first planned coding runtime, but neither should define the core platform. Products need independent repositories and configurable agent organizations. Treating a Slack command, agent class, team, and repository as one object would make future interfaces/runtimes and shared services expensive to add.

## Decision

1. Enforce this control flow and dependency direction:

   ```text
   interface adapter -> Agent Gateway -> Orchestrator -> domain/runtime ports
   external adapters (Codex, SQLite, Slack, filesystem) -> domain/runtime ports
   ```

2. Interfaces translate protocol and authenticate; they never invoke Codex or change workspace state directly.
3. The gateway normalizes/validates and creates durable task identity. The orchestrator selects the smallest sufficient workflow and uses runtime, persistence, event, and lock ports.
4. Raw Codex behavior is isolated to one runtime adapter.
5. Model separately:
   - shared platform teams for reusable services;
   - product teams for product accountability;
   - agents as configured team members with runtime/permission profiles;
   - projects as source/workspace records linked to a responsible product team;
   - tasks as durable work records linking source, project, team, agents, and state.
6. Validate the entire configuration bundle, including team/agent/project/permission cross-references. Product names and future visual rooms remain data, not Python control flow.

## Consequences

- Slack, CLI, HTTP, and future interfaces can share gateway behavior.
- Codex can later be replaced or complemented without rewriting orchestration.
- Shared agents can support multiple product teams without pretending to own their repositories.
- The AI Hub root is never the implicit project working directory; every execution resolves an isolated registered workspace.
- More explicit DTOs and composition are required, but unit and fake-runtime integration testing stay offline and deterministic.

## Rejected alternatives

- Slack-to-Codex direct invocation: couples protocol, execution, and error handling and blocks non-Slack interfaces.
- One class per hard-coded product/team: prevents configuration-driven growth.
- Treat team and project as the same entity: breaks shared services, ownership changes, and repository isolation.
- Microservices per layer: adds operations cost with no single-host benefit.
