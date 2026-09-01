# Phase Gates and Execution Plan

## Gate policy

The repository advances sequentially:

```text
Phase 0 -> review + explicit approval -> Phase 1
        -> review + explicit approval -> Phase 2
        -> review + explicit approval -> Phase 3
        -> review + explicit approval -> Phase 4
```

The current authorization is in `PHASE_STATUS.yaml`. Only the current phase may be implemented. “Planned,” an interface stub, or an item listed below does not authorize implementation. At every boundary:

1. run tests, lint, and type checks;
2. inspect the full diff, status, and repository tree;
3. perform a secret/security sanity check;
4. verify phase scope and architecture direction;
5. update README, roadmap, phase status, instructions, and relevant ADRs;
6. report unresolved assumptions and `[MAC-VERIFY]` items;
7. publish the phase completion report;
8. stop for explicit user approval.

An authorization should be unambiguous, for example: `Proceed with Phase 1.`

## Phase 0 — Foundation and Architecture (complete)

Phase 0 creates documentation, domain/config/event/runtime contracts, safe local tooling, tests, and macOS skeletons. It does not create a useful fake Slack, Codex, orchestrator, worker, database, or Pixel implementation.

Exit checklist:

- [x] architecture and inward dependency direction documented;
- [x] settings, permissions, agent, team, and project schemas validated together;
- [x] shared team/product team/agent/project/task differences modeled;
- [x] task statuses and legal transitions implemented and tested;
- [x] versioned event envelope/types implemented and tested;
- [x] runtime abstraction cannot execute a real runtime;
- [x] Python baseline, offline tests, lint, and typing pass;
- [x] bootstrap/doctor/workspace skeleton is safe and honest;
- [x] secrets and runtime data are ignored and absent from history/diff;
- [x] Phase 0 non-goals remain absent;
- [x] documentation, ADRs, and phase status agree;
- [x] `[MAC-VERIFY]` and unresolved assumptions recorded.

### Phase 0 `[MAC-VERIFY]`

These items are not blockers without the target hardware, but must not be reported as tested:

- Apple Silicon architecture and supported macOS version;
- Xcode Command Line Tools detection/install flow;
- Homebrew discovery (including `/opt/homebrew`) and Brewfile result;
- bootstrap idempotence and workspace ownership/permissions;
- GitHub SSH and/or `gh` authentication;
- Codex CLI installation and authentication;
- Docker Desktop behavior if a later approved dependency needs it;
- power, sleep, FileVault, firewall, and unattended-server settings;
- launchd load/unload, log paths, restart behavior, and reboot recovery;
- Slack Socket Mode connectivity after Phase 1 implementation;
- full fresh-machine and reboot acceptance flows.

## Exact Phase 1 backlog — implemented offline, awaiting target-Mac verification

P1-01 through P1-14 are implemented and pass the offline gates as of 2026-09-01: 277 tests pass with 86% statement coverage, and Ruff, mypy, Bash syntax, and the locked dependency audit pass. Live Slack, authenticated Codex fixture execution, launchd lifecycle, and reboot recovery remain `[MAC-VERIFY]`. This does not authorize Phase 2.

### P1-01 — Composition root and production configuration

- Wire the existing strict registries into one startup configuration.
- Add machine-local paths/settings without credentials in version control.
- Fail startup on invalid cross-references or unsafe workspace paths.
- **Acceptance:** valid examples load; missing/unknown/duplicate/unsafe input fails with redacted, actionable errors.

### P1-02 — SQLite durable store and migrations

- Implement storage ports for tasks, runs, events, and artifact metadata.
- Add versioned SQLite migrations and transactional task-transition/event append.
- Define interrupted-run reconciliation and backup-safe database location.
- **Acceptance:** restart preserves history/current state; concurrent writes are bounded; migration, rollback/failure, and corruption/unavailable paths have tests.

### P1-03 — Structured events, logs, and projections

- Persist the Phase 0 event envelope and expose task-status projections.
- Add correlation/causation, redaction, idempotent event consumers, and bounded log retention policy.
- **Acceptance:** each lifecycle change emits one valid durable event; secrets never appear in logs/events; replay reconstructs the expected projection.

### P1-04 — Agent Gateway

- Implement source-neutral request normalization, validation, authentication/authorization handoff, task IDs, source tracking, durable creation, and enqueue handoff.
- Define safe errors and immediate acknowledgement DTOs.
- **Acceptance:** valid requests create one durable queued task; malformed/unauthorized/duplicate requests do not invoke orchestration and return safe deterministic results.

### P1-05 — Slack Socket Mode adapter

- Add Slack Bolt Socket Mode without a public inbound webhook.
- Support help, create/developer task, list/status/detail, and cancellation intents using natural, minimal syntax.
- Acknowledge quickly; process long work off the Slack handler; deliver later progress/result from projections.
- **Acceptance:** mocked adapter tests cover auth, deduplication, ack latency boundary, reconnect, malformed input, rate/error handling, and redaction; `[MAC-VERIFY]` live connection passes.

### P1-06 — Basic single-Developer orchestrator

- Resolve project/product team and one enabled Developer agent.
- Drive only `queued -> planning -> running -> completed/failed/blocked/cancelled` as applicable.
- Enforce configurable total concurrency and classify bounded retries/failures.
- **Acceptance:** integration tests use a fake runtime and prove success, runtime failure, timeout, cancellation, missing project, and restart reconciliation. No reviewer/QA/multi-agent chain exists.

### P1-07 — Project workspace manager and conservative Git workflow

- Clone or select the registered repository under `workspace/projects/<project>`.
- Validate canonical path, origin/expected repository, working-tree policy, and task branch `agent/<task-id>-<slug>`.
- Capture changed-file and branch metadata; keep auto-push/merge disabled.
- **Acceptance:** fixture repositories cover clone/select, dirty tree, missing repo, wrong origin, branch collision, conflict, and path escape. No force-push/reset/clean is used.

### P1-08 — Project locking and cleanup

- Add robust per-project exclusive locks plus configurable total concurrency (initial default: two tasks).
- Store lock owner/task/timestamps, detect stale locks safely, and release in success/failure/cancellation paths.
- **Acceptance:** two modifying tasks cannot overlap on one project; separate projects may run within the limit; crash/stale-lock recovery is deterministic and audited.

### P1-09 — Real Codex runtime adapter

- Implement the Phase 0 runtime protocol in one adapter using explicit arguments and resolved project working directory.
- Capture timing, exit status, bounded/redacted output, changed files, cancellation, and timeout.
- Apply agent permission and dangerous-operation policy before execution.
- **Acceptance:** adapter contract tests use a fake executable; `[MAC-VERIFY]` authenticated Codex smoke test changes only the approved fixture branch; raw Codex calls appear nowhere else.

### P1-10 — Task result and Slack lifecycle delivery

- Consolidate implemented changes, tests, branch, runtime outcome, and safe errors.
- Deliver queued/running/blocked/completed/failed/cancelled status without making notification delivery authoritative.
- **Acceptance:** a failed Slack delivery is retriable/observable and does not change a successful task to failed; duplicate deliveries are idempotent.

### P1-11 — Local health and readiness

- Add minimal `GET /health` and `GET /ready` endpoints bound to localhost by default.
- Report liveness separately from storage/runtime/workspace readiness and never return secrets.
- **Acceptance:** dependency failure changes readiness, not liveness; tests verify localhost configuration and response redaction.

### P1-12 — launchd service and lifecycle commands

- Add inactive-by-default, generated/configurable launchd definitions for the native hub process.
- Implement install/start/stop/restart/status/remove with exact target checks and useful logs.
- **Acceptance:** static/shell tests pass; `[MAC-VERIFY]` load, unload, restart-on-failure, login/boot behavior, and reboot recovery pass on the Mac mini.

### P1-13 — Doctor and operator runbooks

- Extend doctor to check Homebrew, Git/`gh`, Python/uv, Node if required, Codex, required variable presence, workspace permissions, SQLite, Slack configuration, process, and readiness without printing values.
- Document backup/restore, stuck lock, failed runtime, Slack disconnect, update, and rollback procedures.
- **Acceptance:** doctor distinguishes pass/warn/fail/not-implemented/MAC-VERIFY, has deterministic tests where possible, and returns a meaningful nonzero exit on required failures.

### P1-14 — End-to-end MVP verification and phase close

- Add an offline integration path: Gateway -> Orchestrator -> fake Runtime -> SQLite -> result projection.
- Perform the approved live fixture task: create `README_TEST.md` containing `AI Hub test` in a test project branch.
- Run test/lint/type/security checks, fresh-machine bootstrap, reboot recovery, documentation/status update, and Phase 1 completion report.
- **Acceptance:** the full offline suite passes; `[MAC-VERIFY]` Slack request creates a durable task, obtains/releases the lock, invokes Codex, records events/result, modifies only the fixture branch, reports to Slack, and recovers after reboot.

### Phase 1 global constraints

- one Mac mini; no desktop workers or distributed system;
- one Developer execution path; no shared Reviewer/QA chain yet;
- no Pixel UI, n8n, Redis, PostgreSQL, dynamic team creation, or broad automation;
- no public inbound endpoint, automatic merge, force-push, or production deployment;
- primary tests require neither real Slack nor real Codex;
- all live/hardware acceptance remains `[MAC-VERIFY]` until actually observed.

## Phase 2 — Product Teams and Multi-Agent Workflows

After a separate approval, operationalize shared/product teams, team-aware routing, Developer→Reviewer→QA, delegation, permissions enforcement, artifact handoffs, and parallel-safe histories. Do not implement it as part of a Phase 1 “enhancement.”

## Phase 3 — Pixel Agent Office

After a separate approval, build a read-oriented Phaser/TypeScript view over real events. It must not control agents, fake state, or expose hidden reasoning.

## Phase 4 — Automation and Advanced Integrations

After a separate approval, evaluate n8n, schedulers, GitHub workflows, remote access, backups, external data/notification providers, and analytics one integration at a time.

## Required completion report

Every phase ends with:

```text
# Phase N Completion Report

## 1. Status
PASS / PARTIAL
## 2. Implemented
## 3. Repository Structure
## 4. Architecture Decisions
## 5. Tests
## 6. Security Review
## 7. MAC-VERIFY Items
## 8. Known Limitations
## 9. Next Phase Proposed Backlog
## 10. User Action Required
Approve the next phase before implementation begins.
```
