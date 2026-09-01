# Repository Instructions for Agents

## Mission and priorities

This repository defines a reproducible, secure, always-on AI Agent Platform for one Apple Silicon Mac mini. It manages agents, product teams, isolated project repositories, tasks, events, and future interfaces. It is not a generic chatbot, distributed cluster, or desktop-worker system.

Apply this priority order to every decision:

```text
Reproducibility > Reliability > Security > Maintainability
> Extensibility > Operational simplicity > Fancy features
```

## Hard phase gate

The authorized phase is read from `docs/PHASE_STATUS.yaml`.

**Never implement a future phase without explicit phase authorization from the user.** A roadmap entry, TODO, interface, test fixture, or suggestive request is not authorization. Finish the current phase, run its gates, report, and stop.

At Phase 0:

- allowed: architecture/config/domain contracts, disabled adapters, deterministic foundational tests, safe bootstrap and documentation;
- prohibited: live Slack or Slack authentication, real Codex invocation, full orchestration, multi-agent execution, queue workers, automatic Git editing, database/Redis/n8n infrastructure, Pixel UI, production dashboards, or automatic deployment.

## Dependency and directory rules

The dependency direction is inward:

```text
interfaces -> gateway -> orchestrator -> domain/runtime ports
                                       ^
adapters (Slack, Codex, SQLite, HTTP) ---+

events -> read-only observability consumers
```

- `src/macmini_ai_hub/domain/`: dependency-light entities, states, events, and policies. It must not import adapters or frameworks.
- `src/macmini_ai_hub/config/`: strict configuration loading and cross-registry validation. Never load secrets into version-controlled models.
- `src/macmini_ai_hub/runtime/`: execution protocol and DTOs. Raw Codex subprocess calls belong only in a future adapter.
- `config/`: public example registries only.
- `workspace/`: generated runtime state. Do not commit contents except intentional placeholders.
- `workspace/projects/<project>/`: separate product repositories. Never assume the AI Hub repository is a task working directory.
- `bootstrap/`, `scripts/`, `launchd/`: macOS operations. Preserve idempotence, fail-fast behavior, diagnostics, and `[MAC-VERIFY]` truthfulness.
- `docs/adr/`: accepted architecture decisions. Update or supersede an ADR when changing a decision.

Interfaces must never invoke Codex or other execution engines directly. The Agent Gateway normalizes and validates requests. The Orchestrator uses ports and policy to create the smallest sufficient workflow. Runtime and persistence implementations are replaceable adapters.

## Organization and domain language

- **Shared platform team:** reusable cross-product services (orchestrator, reviewer, QA, research, infra).
- **Product team:** configurable ownership boundary for one product.
- **Agent:** configured role, runtime, permission profile, and team membership.
- **Project:** source repository plus workspace metadata; distinct from the responsible team.
- **Task:** durable work request and single source of truth for lifecycle state.
- **Event:** immutable observable fact about a state change or action.

Registry relationships must remain explicit and validated. Do not hard-code named example products into Python behavior. Team and future Pixel-room creation must remain configuration-driven.

## Task and event rules

Use only the documented task states and transitions in `ARCHITECTURE.md`. Terminal states are `completed`, `failed`, and `cancelled`; never silently resurrect one. Record failure, blocking, retry, review, and QA changes as events when those capabilities exist.

Events use a versioned envelope containing identity, UTC timestamp, type, correlation/causation, and relevant task/project/team/agent references. Payloads contain observable facts only.

Never store, log, infer, or expose hidden chain-of-thought. The future Pixel Agent Office is a read-oriented projection of task, agent, team, project, and runtime events. It must not control the runtime or invent activity.

## Code and test rules

- Target Python 3.12+ with type hints and small cohesive modules.
- Prefer explicit protocols, dependency injection at boundaries, structured exceptions, and deterministic behavior.
- Avoid global mutable state, giant service classes, deep inheritance, premature frameworks, microservices, and distributed infrastructure.
- Parse YAML safely, reject duplicate keys and unknown fields, and validate registry references as one bundle.
- Do not swallow exceptions. Preserve diagnosable failure context without secrets.
- Unit tests must run offline without Slack, Codex, or a physical Mac.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run mypy` (or `make check`) before declaring a phase or change complete.
- Inspect the full diff and repository tree; check that no secret or generated workspace data is staged.

## Git policy

- Inspect `git status` before work. Preserve unrelated user changes.
- Use focused branches such as `agent/TASK-1042-short-name` for future project tasks.
- Do not amend, rewrite, or discard changes you did not create.
- Default autonomous settings are `auto_commit: configurable`, `auto_push: false`, and `auto_merge: false`.
- A human may explicitly authorize a normal commit/push for repository version control. That permission never implies force-push, merge, release, or deployment.
- Never force-push. Never bypass required checks. Never auto-merge.
- Prohibit `git reset --hard`, `git clean -fd`, and destructive checkout/restore unless the exact target and loss are understood and the human explicitly approves.
- Do not operate on nested project repositories without the task's explicit project/workspace binding.

## Security and dangerous operations

Capabilities are deny-by-default and scoped to the assigned project, workspace, and task. A configured permission is policy intent, not proof of sandbox enforcement.

Never commit, echo, log, or include in task/event payloads:

- API/OAuth tokens or passwords;
- `.env` values, private keys, credentials, or authentication caches;
- Slack request bodies that contain sensitive material;
- unredacted command output likely to contain secrets.

Dangerous operations include recursive deletion, arbitrary-directory deletion, destructive Git, force-push, database drops, secret changes, production deployment, public network exposure, and disabling security controls. Before any such action: stop; resolve the exact target; explain impact and recovery; obtain explicit human approval; prefer a reversible alternative; verify the result.

Bind future services to localhost/private LAN unless a reviewed requirement says otherwise. Slack Socket Mode is the Phase 1 default direction so the home network needs no public inbound webhook.

## macOS and environment rules

- Production is one Apple Silicon Mac mini. Do not add desktop workers, fallback nodes, clustering, or x86-only assumptions.
- Detect Homebrew and tool paths; do not blindly hard-code `/opt/homebrew`.
- Shell scripts use `set -euo pipefail` where appropriate, are modular and idempotent, and do not fabricate successful checks.
- Mark untested physical-machine behavior exactly as `[MAC-VERIFY]` in code output and documentation.
- Phase 0 `[MAC-VERIFY]` includes Apple Silicon/Homebrew/CLT behavior, package installation, workspace permissions, GitHub and Codex authentication, Docker, power/sleep configuration, launchd load/reboot recovery, and later Slack connectivity.
- Never change machine secrets automatically. `.env.example` contains names and documentation, never values.

## Workspace and persistence

Runtime paths are `workspace/projects`, `tasks`, `memory`, `indexes`, `locks`, `artifacts`, and `logs`. Keep generated contents ignored. Validate that a resolved path stays inside its intended workspace before writing, locking, moving, or deleting.

SQLite is the Phase 1 default for durable task/run/event history because this is one machine. Redis must never be the only history store. Design storage behind ports so migration remains possible. Source code is recovered from Git; state, artifacts, and secrets require separate backup policies.

## Completion process

At the end of every phase:

1. run tests, lint, and type checks;
2. inspect `git diff`, `git status`, and repository structure;
3. perform a secret and security sanity check;
4. verify every change is inside the authorized phase;
5. update README, roadmap, phase status, ADRs, and these instructions as needed;
6. list unresolved assumptions and all `[MAC-VERIFY]` items;
7. produce the required completion report;
8. stop and request approval for the next phase.
