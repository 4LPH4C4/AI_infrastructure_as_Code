# Mac Mini AI Hub

Mac Mini AI Hub is an infrastructure-as-code and agent-platform-as-code project for a single, always-on Apple Silicon Mac mini. It is intended to host reusable AI agents, product-specific teams, project workspaces, scheduled automations, and human interfaces without turning a personal server into a distributed platform.

> **Current phase: Phase 1 — Core AI Hub MVP (in progress)**
>
> Phase 2 and later are locked. Phase 1 is limited to the approved single-Developer Slack-to-Codex flow; multi-agent workflows and Pixel Agent Office remain out of scope.

The engineering priority is:

```text
Reproducibility > Reliability > Security > Maintainability
> Extensibility > Operational simplicity > Fancy features
```

## What exists in Phase 0

- documented boundaries and dependency rules;
- strict, validated example settings and agent/team/project/permission registries;
- task lifecycle and observable event contracts;
- a disabled runtime implementation that cannot invoke Codex accidentally;
- a Python 3.12 development baseline and deterministic tests;
- safe macOS bootstrap and doctor skeletons;
- ignored runtime workspace conventions;
- security, contribution, phase-gate, and architecture decision records.

Phase 0 establishes contracts only. See [the phase plan](docs/PHASES.md) and [machine-readable status](docs/PHASE_STATUS.yaml).

## Target architecture

```text
Slack / CLI / Web / API / Scheduler       (interfaces)
                    |
                    v
              Agent Gateway               (normalize, validate, identify)
                    |
                    v
               Orchestrator               (plan, route, coordinate)
                    |
          +---------+---------+
          |                   |
 Shared Platform Teams   Product Teams     (organization/policy)
          |                   |
          +---------+---------+
                    v
              Agent Runtime               (execution abstraction)
                    |
          +---------+---------+
          |         |         |
        Codex      APIs   Local tools       (adapters; future)
                    |
                    v
        workspace/projects/<project>       (isolated repositories)

All state changes -> events -> logs/status/Slack/Pixel consumers
```

An interface never calls Codex directly. Platform policy and domain contracts do not depend on Slack, Codex, storage engines, or the future Pixel UI. Full rules are in [ARCHITECTURE.md](ARCHITECTURE.md).

## Shared teams, product teams, and projects

- A **shared platform team** offers reusable capabilities such as orchestration, review, QA, research, or infrastructure.
- A **product team** is the configurable group accountable for one product's work.
- An **agent** is a role-bearing, permission-bound member of a team.
- A **project** is source code and its isolated workspace; it is not a team.
- A **task** is the durable unit of requested work and references its source, project, team, agents, status, and timestamps.

Phase 0 can represent these relationships but does not execute a team workflow.

## Repository map

```text
config/                 safe example registries; never credentials
src/macmini_ai_hub/     Phase 0 domain, config, and runtime contracts
tests/                  foundational contract and validation tests
bootstrap/              safe macOS bootstrap skeleton
scripts/                doctor and lifecycle command skeletons
launchd/                inactive future service examples
workspace/              ignored runtime projects, tasks, locks, artifacts, logs
docs/                   phase plan, first-boot guide, and ADRs
```

The AI Hub repository controls the platform. Independently managed product repositories belong under `workspace/projects/` and remain separate Git repositories.

## Configuration

Safe templates live in `config/*.example.yaml`:

- `settings.example.yaml`
- `agents.example.yaml`
- `teams.example.yaml`
- `projects.example.yaml`
- `permissions.example.yaml`

They are validated together, including agent/team, team/project, and permission-profile references. Copy templates to machine-local configuration only when the implementation directs it. Never add tokens, passwords, private repository credentials, or private keys to YAML.

Machine secrets belong in an untracked `.env` or a future approved macOS secret store. Start from `.env.example` and verify it remains untracked before adding values.

## Development

Prerequisites are Python 3.12+ and `uv`.

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy
```

Use the Make targets when available:

```bash
make test
make lint
make typecheck
make check
```

Tests must not require Slack, Codex, network access, or a physical Mac mini. A Phase 0 runtime is deliberately disabled.

## Mac mini installation

The intended fresh-machine flow is eventually:

```bash
git clone https://github.com/4LPH4C4/AI_infrastructure_as_Code.git
cd AI_infrastructure_as_Code
cp .env.example .env
./bootstrap/bootstrap-macos.sh
./scripts/start.sh
```

In Phase 0, bootstrap can install declared Homebrew packages and initialize workspace directories after checking prerequisites. Lifecycle commands intentionally report **not implemented** until Phase 1. Follow [the first-boot checklist](docs/MAC_MINI_FIRST_BOOT.md); every item requiring physical hardware is marked `[MAC-VERIFY]` and has not been claimed as tested.

## Operations and troubleshooting

Run:

```bash
./scripts/doctor.sh
```

Doctor distinguishes `PASS`, `WARN`, `FAIL`, `NOT IMPLEMENTED`, and `[MAC-VERIFY]`; it must never print secret values. In Phase 0, service status and runtime checks being unimplemented is expected. Check [the roadmap](ROADMAP.md) before treating future commands as defects.

Long-term acceptance requires reboot recovery, Slack Socket Mode, real task execution, and one-command diagnosis. Those are Phase 1 gates, not current capabilities.

## Security and Git

- Do not expose database, admin, debug, health, or visualization services to the public Internet by default.
- Do not commit `.env`, credentials, keys, logs, task data, artifacts, or managed project workspaces.
- Autonomous project agents default to `auto_push: false` and `auto_merge: false`; force-push and destructive Git operations are prohibited.
- Human-authorized repository maintenance may commit and push reviewed changes to `origin` using normal, non-force Git operations.
- Treat commands such as `rm -rf`, `git clean -fd`, `git reset --hard`, database deletion, secret changes, and production deployment as dangerous operations requiring exact-scope review and human approval.

Read [SECURITY.md](SECURITY.md) before enabling any external integration and [CONTRIBUTING.md](CONTRIBUTING.md) before changing the repository.

## Phase gate

No contributor or agent may implement Phase 1 without explicit user approval. The exact Phase 1 backlog is frozen in [docs/PHASES.md](docs/PHASES.md); approval should be an unambiguous instruction such as `Proceed with Phase 1.`
