# ADR-0001: Single-Mac, native-first, phase-gated delivery

- Status: Accepted
- Date: 2026-09-01

## Context

The production target is one always-on Apple Silicon Mac mini. The platform needs direct access to local Git workspaces and the Codex CLI, while reproducibility and operational simplicity outrank horizontal scale. Development may occur elsewhere, but other machines are not production workers.

The full product vision spans interfaces, execution, teams, visualization, and integrations. Building all layers at once would blur trust boundaries and make fresh-machine/reboot acceptance difficult to diagnose.

## Decision

1. Deploy the AI Hub as a modular monolith on a single Mac mini.
2. Prefer native macOS processes for gateway, orchestration, and runtime components that require local filesystem/CLI access.
3. Use containers only for a later service that has a demonstrated isolation or packaging benefit. Do not introduce Kubernetes, clustering, service mesh, or a custom scheduler.
4. Deliver sequentially through Phases 0–4. A phase ends with automated checks, security/scope review, documentation, completion report, and a hard stop. The next phase requires explicit user approval recorded in `docs/PHASE_STATUS.yaml`.
5. Mark physical-machine behavior `[MAC-VERIFY]` until observed on the target Mac.

## Consequences

- Installation, process supervision, filesystem permissions, backups, and diagnostics stay understandable for one operator.
- Direct runtime access is straightforward, but the Mac mini is a deliberate single-host availability boundary.
- Domain ports still permit adapter replacement; they do not promise distributed deployment.
- Later-phase contracts may be documented early, but live implementations cannot leak across phase gates.
- Containerized PostgreSQL, Redis, n8n, or similar services require a later explicit justification.

## Rejected alternatives

- Desktop worker/failover nodes or multi-machine synchronization: contradict the production model.
- Containerize every component: complicates local CLI/workspace access without Phase 0 value.
- Build the complete vision before review: increases security and integration risk and violates sequential acceptance.
