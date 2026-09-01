# Contributing

## Before changing anything

1. Read `AGENTS.md`, `ARCHITECTURE.md`, and `docs/PHASE_STATUS.yaml`.
2. Confirm the requested work belongs to the authorized phase.
3. Inspect `git status` and preserve unrelated changes.
4. Identify which contract, test, configuration example, and documentation the change affects.

Do not implement a locked phase because it appears in the roadmap. Phase 1 requires explicit user approval.

## Development setup

Use Python 3.12+ and `uv`:

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy
```

Equivalent Make targets may be used. Tests must remain deterministic and offline unless a test is explicitly marked as a manual `[MAC-VERIFY]` smoke check.

## Change design

- Keep domain/config contracts independent of Slack, Codex, databases, and web frameworks.
- Add external behavior behind an existing or clearly justified port/adapter.
- Keep modules small, typed, explicit, and dependency-injected at boundaries.
- Prefer configuration over hard-coded teams, agents, products, paths, or UI rooms.
- Reject unknown/duplicate configuration and validate all references together.
- Update lifecycle/event tests whenever a state or event contract changes.
- Do not add frameworks, services, containers, or daemons without an architecture decision and current-phase need.
- Mark physical Mac claims `[MAC-VERIFY]` until observed.

Architecture-changing contributions should add or supersede a concise ADR when they alter deployment topology, dependency direction, persistence, interface connection, event semantics, organization boundaries, security posture, or phase gates.

## Testing expectations

At minimum, Phase 0 changes should cover relevant cases from:

- valid and invalid configuration parsing;
- duplicate/unknown field rejection;
- agent/team/project/permission cross-references;
- legal and illegal task transitions;
- event envelope/type/timestamp validation;
- runtime disabled behavior and DTO validation;
- shell/static bootstrap behavior where portable.

Primary automated tests never require live Slack, Codex, GitHub, Internet access, or the physical Mac mini. Do not replace a missing test with a fabricated passing doctor result.

## Git workflow

- Use a focused branch when appropriate; future project tasks use `agent/<task-id>-<slug>`.
- Make small, reviewable commits with imperative messages.
- Do not rewrite or discard another contributor's changes.
- Do not commit generated workspace data, local configuration, `.env`, credentials, logs, databases, task artifacts, private keys, or authentication caches.
- Inspect `git diff --check`, the complete diff, and staged filenames before committing.
- Normal push is allowed when the user has authorized repository version control and checks pass. Never force-push or auto-merge.

Recommended pre-commit review:

```bash
git status --short
git diff --check
uv run pytest
uv run ruff check .
uv run mypy
```

## Security and operations

Follow `SECURITY.md`. Treat recursive deletion, destructive Git, database deletion, secret changes, public exposure, and deployment as approval-gated dangerous operations. Confirm exact canonical targets and prefer reversible steps.

Shell scripts should be readable, modular, fail fast with `set -euo pipefail`, avoid secret output, and be idempotent where practical. Detect Apple Silicon/Homebrew paths instead of assuming them. Lifecycle placeholders must return an honest not-implemented status until the service exists.

## Documentation

Update documentation in the same change when behavior, configuration, paths, commands, phase scope, `[MAC-VERIFY]` items, or architecture decisions change. Keep these files consistent:

- `README.md`: user-facing current capability and setup;
- `ARCHITECTURE.md`: boundaries and contracts;
- `ROADMAP.md` and `docs/PHASES.md`: goals/gates/backlog;
- `docs/PHASE_STATUS.yaml`: current authorization/status;
- `AGENTS.md`: persistent agent rules;
- `docs/adr/`: durable decisions.

## Review checklist

- [ ] Work is inside the authorized phase.
- [ ] Dependency direction is preserved.
- [ ] Tests cover success and failure paths and pass offline.
- [ ] Lint/type checks pass.
- [ ] No secret, credential, private repository, or generated runtime data is tracked.
- [ ] Dangerous operations/public exposure were not introduced implicitly.
- [ ] Configuration and docs are current.
- [ ] Unverified Mac behavior is marked `[MAC-VERIFY]`.
- [ ] Diff is focused and contains no unrelated user changes.

## Phase completion

A phase is complete only after all automated checks, full repository/diff review, security sanity check, status/documentation updates, `[MAC-VERIFY]` inventory, known-limitations report, and explicit stop at the next gate. Use the report format in `docs/PHASES.md`.
