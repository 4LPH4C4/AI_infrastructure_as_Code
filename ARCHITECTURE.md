# Architecture

## 1. Scope and constraints

Mac Mini AI Hub is a modular monolith designed to run natively on one Apple Silicon Mac mini. The Mac mini is the only production runtime. Development computers are temporary authoring environments, not worker nodes, failover nodes, or members of a cluster.

Phase 1 implements the single-Developer slice of this modular monolith: Slack Socket Mode, the source-neutral gateway, SQLite-backed orchestration, isolated Git workspaces, one Codex adapter, observable events, and local operations. Phase 2+ capabilities remain gated in `docs/PHASES.md`.

Key constraints:

- one machine and operational simplicity before distribution;
- product repositories isolated from the AI Hub repository;
- durable, explicit task state as the system of record;
- all material actions represented by observable events;
- secrets and dangerous capabilities denied by default;
- no future-phase implementation without an approval gate.

## 2. System context

```text
                   Human and automation interfaces
        Slack | CLI | HTTP API | Web UI | Scheduler | Webhook
                              |
                              v
                        Agent Gateway
                              |
                              v
                         Orchestrator
                              |
                 +------------+------------+
                 |                         |
        Shared Platform Teams         Product Teams
                 |                         |
                 +------------+------------+
                              |
                              v
                         Runtime Port
                              |
               +--------------+--------------+
               |              |              |
          Codex adapter     API adapter   Local-tool adapter
                              |
                              v
                 workspace/projects/<project>

Material state changes --> Event store --> projections/notifications/logs
                                             |              |
                                             v              v
                                       Slack status    Pixel Office
```

Long-running execution is never performed on an interface event-handling path. Interfaces acknowledge a durable task after gateway acceptance, then consume later task/event projections for results.

## 3. Dependency direction

Dependencies point toward stable domain policy and ports. External technology never becomes a domain dependency.

```text
Interface adapters ──> Gateway application service ──> Orchestrator service
       │                                                   │
       │                                                   v
       └──────────────────────────────────────────> Domain + ports
                                                           ^
Codex / SQLite / filesystem / Slack / HTTP adapters ───────┘

Domain events ──> event publisher port ──> storage/log/Slack/Pixel adapters
```

Rules:

1. Domain objects import no Slack, FastAPI, Codex, subprocess, SQLAlchemy, or visualization code.
2. Gateway depends on normalization/authentication/task-creation ports, not a concrete runtime.
3. Orchestrator selects policy and invokes runtime, storage, lock, and event ports through dependency injection.
4. Runtime adapters receive an explicit execution request containing project and working-directory context. Raw Codex calls appear only in the Codex adapter.
5. Persistence adapters translate domain records; storage-specific identifiers do not leak into domain entities.
6. Observability consumers are downstream and read-oriented. Core execution never depends on Slack delivery or Pixel availability.
7. Configuration wires implementations at the composition root; it does not hide runtime globals.

The initial implementation stays a modular monolith. These boundaries support substitution and testing without requiring microservices.

## 4. Layer responsibilities

### 4.1 Interface layer

Adapters translate external protocols into an interface-neutral request and translate result projections back to the source. Phase 1 implements Slack Socket Mode; CLI task submission, HTTP task APIs, webhooks, web/mobile UIs, and scheduled jobs can later use the same gateway.

An interface may:

- verify source-specific authenticity;
- collect request/source metadata;
- submit to the Agent Gateway;
- immediately acknowledge accepted task identity;
- render status and completion notifications.

It may not choose a Codex command, access a project workspace, change task state directly, or wait synchronously for long-running execution.

### 4.2 Agent Gateway

The gateway is the normalized system entry point. It owns:

- authentication/authorization handoff;
- request normalization and command validation;
- stable task ID and source/correlation metadata;
- project/team hint validation;
- task creation and initial event emission;
- enqueue/orchestrator handoff;
- source-neutral acknowledgement and result-delivery contracts.

Malformed or unauthorized input fails before runtime dispatch and produces safe, observable failure information.

### 4.3 Orchestrator

The orchestrator interprets task intent, resolves project and team, selects the smallest sufficient workflow, manages dependencies, state, locks, retries, review/QA gates, failure handling, and result consolidation.

Phase 1 is restricted to one Developer flow. Multi-agent routing, shared reviewer/QA handoffs, delegation, and parallel-safe execution belong to Phase 2. n8n is never the orchestrator.

### 4.4 Runtime layer

The runtime protocol separates an agent from its execution engine:

```text
Agent role -> Runtime protocol -> Codex/API/local implementation
```

An execution request identifies task, agent, project, resolved working directory, instruction, timeout/policy, and correlation context. The DTO captures start/end, status, exit code where applicable, bounded/redacted stdout/stderr, and changed-file metadata. Phase 1 persists only safe run metadata rather than raw output. Runtime data must not expose secrets or hidden reasoning.

Phase 1 supplies one Codex CLI adapter with explicit arguments, stdin prompts, ignored user configuration, a `workspace-write` sandbox, command network/web search disabled, `untrusted` approval policy, sanitized environment, timeouts, cancellation, bounded redacted output, and no shell-string interpolation. The disabled adapter remains available for fail-closed tests/configuration.

## 5. Organization and ownership model

These concepts are related but not interchangeable:

| Concept | Meaning | Owns/links |
|---|---|---|
| Shared platform team | Cross-product reusable capability | shared agents; no required product repository |
| Product team | Organizational boundary accountable for a product | product agents and one declared project relationship |
| Agent | Configured role able to receive assignments | exactly one team, runtime name, permission profile |
| Project | Source/work boundary | repository locator, isolated workspace, responsible product team |
| Task | Durable unit of requested work | source, project, team, agents, lifecycle, timestamps |
| Run | One runtime attempt for an agent assignment | task, agent, runtime result; Phase 1 persistence |
| Artifact | Observable output or handoff reference | task/run and safe location/metadata |

A team is not a repository. A project is not an agent group. This separation permits shared agents to support many products, changes in team composition without moving source, and future team creation from configuration.

Registries are data driven. A product team references its project, a project references its responsible team, an agent references its team and permission profile, and the complete configuration bundle validates cross-references before startup. Examples such as Study Hub are illustrative only and must not be hard-coded into control flow.

Future visual metadata such as `room_id`, `room_type`, and display name belongs to team configuration. It does not grant runtime authority.

## 6. Project and workspace isolation

```text
AI Hub repository/
└── workspace/                    generated and ignored
    ├── projects/<project>/       independent Git repositories
    ├── tasks/<task-id>/          task-local scratch/state
    ├── memory/                   future retained context
    ├── indexes/                  derived indexes
    ├── locks/                    project/task lock records
    ├── artifacts/                task outputs
    └── logs/                     operational logs
```

Every execution resolves its working directory from the project registry and validates the canonical path under `workspace/projects`. No agent may default to the AI Hub root. Each task branch starts explicitly from the registered `origin/<base_branch>` or validated `origin/HEAD`, so one task branch never becomes the next task's base. A per-project exclusive lock is the Phase 1 starting point; configurable global concurrency begins conservatively at two tasks, while only one modifying task may use a project at a time.

Project Git policy is conservative:

```text
inspect -> clean-tree policy -> agent/<task-id>-<slug> branch
        -> modify -> test -> summarize
```

Auto-commit is configurable. Auto-push and auto-merge default to false. Force-push and destructive history/worktree operations are prohibited.

## 7. Task model: the operational SSOT

A task is the authoritative lifecycle record. The Phase 0 immutable snapshot covers identity, request, source, project, team, assigned agents, status, and lifecycle timestamps. Phase 1 persistence extends the operational record so it carries:

- `task_id`, request, source, and source reference;
- project, team, resolved working directory, assigned agents;
- current status and blocking/failure summary;
- creation, start, update, and completion timestamps;
- correlation information and produced artifact/result references.

Statuses:

| State | Meaning |
|---|---|
| `pending` | accepted as a draft/domain object but not yet queued |
| `queued` | durable and awaiting orchestration/execution capacity |
| `planning` | route and execution plan are being determined |
| `running` | an assigned runtime is doing work |
| `review` | output awaits or is undergoing review |
| `qa` | output awaits or is undergoing validation |
| `blocked` | progress requires a resolvable dependency or human input |
| `completed` | requested work and required gates succeeded |
| `failed` | processing ended unsuccessfully with recorded reason |
| `cancelled` | processing was intentionally stopped |

Legal transitions are explicit; callers may not assign arbitrary state:

| From | Allowed destinations |
|---|---|
| `pending` | `queued`, `cancelled` |
| `queued` | `planning`, `running`, `failed`, `cancelled` |
| `planning` | `running`, `blocked`, `failed`, `cancelled` |
| `running` | `review`, `qa`, `blocked`, `completed`, `failed`, `cancelled` |
| `review` | `running`, `qa`, `blocked`, `completed`, `failed`, `cancelled` |
| `qa` | `running`, `review`, `blocked`, `completed`, `failed`, `cancelled` |
| `blocked` | `queued`, `planning`, `running`, `review`, `qa`, `failed`, `cancelled` |
| `completed` | none |
| `failed` | none; retry creates a new run or task according to future policy |
| `cancelled` | none |

Every accepted transition updates timestamps and atomically records the matching SQLite event. Process restart reconstructs current state from durable records and reconciles interrupted running work rather than trusting in-memory agent objects.

## 8. Event architecture

Events are immutable observable facts and form the integration seam for task history, structured logs, status updates, dashboards, and the future Pixel Office. The task record remains the current-state SSOT; events are its durable history and projection feed.

Conceptual envelope:

```json
{
  "schema_version": 1,
  "event_id": "c774c2b1-58b5-4c8b-90c9-3a1eaa0943e2",
  "event_type": "agent.status_changed",
  "timestamp": "2026-09-01T12:00:00Z",
  "task_id": "TASK-1042",
  "project": "study-hub",
  "team": "study-hub",
  "agent": "study-backend",
  "correlation_id": "8e4070ae-a9b8-45fb-9127-b6527034d46e",
  "causation_id": "239fe412-5c1a-492d-ad88-ac17d403a84a",
  "payload": {}
}
```

Core event families include:

- task: `task.created`, `task.queued`, `task.started`, `task.blocked`, `task.completed`, `task.failed`, `task.cancelled`;
- team: `team.activated`, `team.idle`;
- agent: `agent.assigned`, `agent.started`, `agent.status_changed`, `agent.completed`, `agent.failed`;
- review: `review.requested`, `review.started`, `review.completed`;
- QA: `qa.requested`, `qa.started`, `qa.completed`;
- artifact: `artifact.created`, `artifact.transferred`;
- routing: `project.task.routed`.

Identifiers/timestamps are generated by trusted application services, timestamps are UTC, event types are validated, and payloads reject secrets and hidden reasoning. Delivery should tolerate duplicate notification/projection handling by using `event_id`; ordering assumptions are scoped to one task/correlation stream.

## 9. Observability and Pixel Agent Office

Structured operational records use fields such as timestamp, level, event ID/type, task, project, team, agent, and a redacted message. Health and readiness are separate: health means the process is alive; readiness means required storage/runtime dependencies can accept work. Diagnostics never include secret values.

The Phase 3 Pixel Agent Office is optional and downstream:

```text
event store/projection -> SSE or WebSocket -> TypeScript/Phaser UI
```

It visualizes real task, agent, team, project, runtime, review, QA, and artifact events. Idle looks idle; failure looks failed. It never invents activity, attempts to reveal chain-of-thought, writes authoritative state, or becomes a runtime dependency. HQ, team-room, agent-detail, and task-flow views are projections over the same contracts used by other observability consumers.

## 10. Persistence

Durable state includes tasks, runs, events, registry snapshots/references, and artifact metadata. Runtime files and Git workspaces are not a substitute for a state store.

Phase 1 starts with SQLite because a single Mac benefits from transactional durability, low operations cost, backup simplicity, and no extra daemon. Repositories depend on storage ports and versioned migrations so PostgreSQL can replace SQLite if measured concurrency or operational requirements justify it. Redis may later support ephemeral coordination but must never be the sole task/event history.

State transitions and corresponding event appends should share one transaction. Artifact content may live on the filesystem while the database stores identity, ownership, checksum/type, and location. Backup design separates:

- Git-tracked platform configuration and source;
- database and retained artifacts/logs;
- independent product repositories/remotes;
- secrets, which require a separate secure recovery mechanism.

## 11. Security architecture

Trust boundaries are interface input, agent-generated instructions/output, local command execution, managed Git repositories, external APIs, and persisted/logged data.

Controls:

- authenticate at the interface and authorize again against task/project capabilities;
- strict schemas, unknown-field rejection, safe YAML, and cross-registry validation;
- deny-by-default permission profiles (`read`, `write`, `execute`, `git`, `network`, `deploy`, `admin`);
- canonical workspace-path validation and project-scoped locks;
- argument-vector subprocess execution, bounded output, timeouts, and cancellation;
- redaction before persistence/logging/delivery;
- localhost/private-LAN binding and no unnecessary public inbound ports;
- explicit human approval for destructive Git/filesystem/database, secret, deploy, or exposure actions;
- permission profiles express policy intent; the Codex `workspace-write` sandbox and canonical workspace checks add enforcement, but configuration alone is never treated as proof of OS isolation.

Slack Socket Mode is preferred in Phase 1 to avoid a public webhook into a home network. Credentials stay in untracked machine configuration or an approved secret store. See `SECURITY.md` for operating policy.

## 12. macOS operations

Native processes are preferred for the gateway, orchestrator, and Codex runtime because they need direct filesystem and CLI access. Containers are reserved for services that gain clear isolation/packaging value; do not containerize everything or add Kubernetes. n8n, PostgreSQL, Redis, and Docker services require later justification.

The bootstrap sequence checks Xcode Command Line Tools and Homebrew, installs the reviewed Brewfile, and initializes workspace directories. It detects paths instead of assuming x86 or `/opt/homebrew`. Lifecycle scripts operate only on the exact generated per-user service target.

Phase 1 includes inactive-by-default launchd generation plus install/start/stop/restart/status/remove commands. Hardware-dependent results remain `[MAC-VERIFY]` until executed on the target Mac mini, especially power/sleep behavior, Homebrew/CLT, workspace permissions, GitHub/Codex authentication, launchd loading, reboot recovery, and Slack connectivity.

## 13. Failure and recovery principles

Expected failures include invalid configuration, malformed/unauthorized tasks, missing repositories, dirty/conflicting Git state, lock contention, runtime error/timeout, cancellation, storage unavailability, Slack disconnection, and service restart.

- Never silently swallow a failure.
- Record a safe failure summary and observable event.
- Release locks in a guaranteed cleanup path while retaining audit context.
- Retry only classified transient failures with bounded attempts/backoff.
- Never retry a destructive or ambiguous side effect blindly.
- Resume after restart from durable state; mark or reconcile interrupted runs explicitly.
- Notification failure must not rewrite successful execution as failed; it is a separate delivery condition.

## 14. Deferred technology

The following choices remain gated directions, not current implementations:

- Phase 2: product/shared multi-agent workflows, reviewer/QA, permissions enforcement, handoffs and artifacts;
- Phase 3: TypeScript + Phaser with SSE/WebSocket read projections;
- Phase 4: justified scheduling, n8n, GitHub workflows, integrations, analytics, and backups.

The exact gate and backlog are maintained in `docs/PHASES.md`.
