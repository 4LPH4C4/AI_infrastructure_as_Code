# Mac Mini AI Hub

Mac Mini AI Hub is an infrastructure-as-code and agent-platform-as-code project for a single, always-on Apple Silicon Mac mini. It is intended to host reusable AI agents, product-specific teams, project workspaces, scheduled automations, and human interfaces without turning a personal server into a distributed platform.

> **Current phase: Phase 1 — implementation complete, production validation pending**
>
> The offline suite passes. Live Slack, authenticated Codex, launchd, and reboot checks remain `[MAC-VERIFY]` on the target Mac mini. Phase 2 and later are locked.

The engineering priority is:

```text
Reproducibility > Reliability > Security > Maintainability
> Extensibility > Operational simplicity > Fancy features
```

## What exists

- strict settings and cross-validated agent/team/project/permission registries;
- source-neutral Agent Gateway with authorization and durable request deduplication;
- Slack Bolt Socket Mode commands with background handling and idempotent delivery;
- SQLite migrations and durable task, event, run, artifact, route, and receipt state;
- a single-Developer orchestrator with bounded concurrency, cancellation, and restart recovery;
- an explicit-argument Codex CLI adapter with workspace-write sandboxing, untrusted-command approval policy, network-off execution, timeout, cancellation, and bounded redacted output;
- registered project clone/select, remote-base task branches, and per-project file locks;
- structured events, replay projections, rotating redacted JSON logs, and localhost health/readiness;
- generated per-user launchd service operations, doctor checks, and recovery runbooks;
- deterministic offline integration from Gateway through a fake runtime to persisted completion.

See [the phase plan](docs/PHASES.md), [machine-readable status](docs/PHASE_STATUS.yaml), and [Phase 1 completion report](docs/PHASE_1_COMPLETION_REPORT.md).

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

Phase 1 executes exactly one enabled Developer for the selected product project. Reviewer, QA, delegation, and other multi-agent chains remain Phase 2 work.

## Repository map

```text
config/                 safe examples plus ignored machine-local registries
src/macmini_ai_hub/     domain, gateway, orchestrator, adapters, and composition
tests/                  offline contract, failure, recovery, and integration tests
bootstrap/              idempotent macOS setup
scripts/                doctor and exact lifecycle operations
launchd/                generated per-user service template and installer
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

They are validated together, including agent/team, team/project, permission-profile, and workspace relationships. Create ignored active registries before starting the service:

```bash
for name in settings agents teams projects permissions; do
  cp -n "config/${name}.example.yaml" "config/${name}.yaml"
done
```

Customize the project repository/workspace/`base_branch` and enable exactly one product-team Developer using the `codex` runtime and a project-workspace permission profile. The public examples are validation fixtures and are not a runnable private-project configuration. Never add tokens, passwords, repository credentials, or private keys to YAML.

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

Primary tests require no Slack, Codex service call, network access, or physical Mac mini. Fake executables and adapters exercise timeout, cancellation, persistence, locks, and end-to-end lifecycle behavior offline.

The current Phase 1 closeout result is 277 passing tests with 86% statement coverage, plus clean Ruff, mypy, Bash syntax, and locked-dependency vulnerability checks.

## Mac mini installation

The intended fresh-machine flow is:

```bash
git clone https://github.com/4LPH4C4/AI_infrastructure_as_Code.git
cd AI_infrastructure_as_Code
cp .env.example .env
./bootstrap/bootstrap-macos.sh
./launchd/install.sh
./scripts/start.sh
./scripts/doctor.sh
```

Before installation, create and review the active registries and configure `.env`. Bootstrap installs the locked baseline and initializes private workspace directories but does not start the service. Follow [the first-boot checklist](docs/MAC_MINI_FIRST_BOOT.md); hardware and live-service items marked `[MAC-VERIFY]` have not been claimed as tested.

## Operations and troubleshooting

Run:

```bash
./scripts/doctor.sh
./scripts/start.sh
./scripts/status.sh
./scripts/restart.sh
./scripts/stop.sh
```

Doctor reports presence and status without printing values. `GET /health` means the process is alive; `GET /ready` checks storage, workspace, and the configured runtime and is bound to `127.0.0.1` by default. Backup, stale-lock, Slack disconnect, update, and rollback procedures are in the first-boot guide.

## Security and Git

- Do not expose database, admin, debug, health, or visualization services to the public Internet by default.
- Do not commit `.env`, credentials, keys, logs, task data, artifacts, or managed project workspaces.
- Autonomous project agents default to `auto_push: false` and `auto_merge: false`; force-push and destructive Git operations are prohibited.
- Codex runs with user config ignored, command network and web search disabled, and untrusted commands requiring approval. In the non-interactive service, unavailable approval fails closed.
- Human-authorized repository maintenance may commit and push reviewed changes to `origin` using normal, non-force Git operations.
- Treat commands such as `rm -rf`, `git clean -fd`, `git reset --hard`, database deletion, secret changes, and production deployment as dangerous operations requiring exact-scope review and human approval.

Read [SECURITY.md](SECURITY.md) before enabling any external integration and [CONTRIBUTING.md](CONTRIBUTING.md) before changing the repository.

## Phase gate

Phase 1 implementation is complete but production acceptance still requires the listed `[MAC-VERIFY]` checks. No contributor or agent may implement Phase 2 until the Phase 1 report is reviewed and the user explicitly authorizes it. Multi-agent Reviewer/QA flows, Pixel Office, public endpoints, automatic push/merge, and deployment remain prohibited.
