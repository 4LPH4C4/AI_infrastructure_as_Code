# Roadmap

Progress is phase-gated. A later phase remains locked until the current phase passes its exit criteria, the completion report is reviewed, and the user explicitly authorizes the next phase. `docs/PHASE_STATUS.yaml` is the machine-readable authority; `docs/PHASES.md` contains the execution gates and exact Phase 1 backlog.

## Phase 0 — Foundation and Architecture

**Status:** Complete on 2026-09-01; target-Mac checks remain `[MAC-VERIFY]`. Phase 1 is locked pending explicit user approval.

**Goal:** create a coherent, testable foundation without functioning agent automation.

**Deliverables:** architecture and security policy; root agent/contributor guidance; strict configuration models and example registries; team/project/agent relationships; task states and legal transitions; versioned observable event envelope; runtime protocol with disabled adapter; Python 3.12/uv/pytest/ruff/mypy baseline; safe bootstrap, doctor, launchd placeholders, ignored workspace structure; ADRs and first-boot documentation.

**Dependencies:** repository access and a non-secret development environment. Physical Mac access is not required; hardware-only results stay `[MAC-VERIFY]`.

**Exit criteria:** tests, lint, and type checks pass; configuration cross-references, lifecycle rules, and events are tested; repository tree and dependency direction are coherent; no secrets/runtime data are tracked; Phase 1 functionality is absent; docs/status are current; all `[MAC-VERIFY]` and unresolved assumptions are reported.

**Not included:** live Slack/Codex, task workers or persistence, full orchestration, multi-agent workflows, automatic Git edits, database/Redis/n8n, operational launchd services, Pixel UI, deployment.

## Phase 1 — Core AI Hub MVP

**Status:** In progress; explicitly authorized on 2026-09-01.

**Goal:** deliver the smallest end-to-end, single-Developer flow:

```text
Slack Socket Mode -> Gateway -> basic Orchestrator -> Codex runtime
                  -> isolated project branch -> durable result -> Slack
```

**Deliverables:** Slack Socket Mode adapter and non-blocking acknowledgements; gateway task creation; SQLite task/run/event persistence and migrations; basic one-agent orchestrator; Developer agent; real Codex runtime adapter; project clone/select and branch safety; per-project locks and bounded concurrency; structured logs/events; task status/cancellation; localhost health/readiness; launchd service; expanded doctor and recovery tests.

**Dependencies:** Phase 0 PASS and explicit approval; target project test fixture; Slack and Codex credentials supplied only on the machine; physical Mac validation for production acceptance.

**Exit criteria:** the approved Slack MVP creates a durable task, locks the selected project, invokes Codex on an isolated task branch, records result/events, releases the lock, and returns status/result; failure/timeout/restart paths are tested without real external services; live smoke test and reboot recovery pass on the Mac mini; security and secret checks pass.

**Not included:** Developer→Reviewer→QA chains, multiple agents per task, dynamic team creation, Pixel Office, Redis/PostgreSQL/n8n, automatic push/merge/deploy, or public service exposure.

## Phase 2 — Product Teams and Multi-Agent Workflows

**Goal:** make configurable shared and product organizations operational.

**Deliverables:** team-aware routing; shared/product agent registries in execution; multiple agents per product; Developer→Reviewer→QA; delegation, task handoff, artifact provenance, permissions enforcement, richer history, and parallel-safe scheduling.

**Dependencies:** Phase 1 production acceptance and explicit approval; stable persistence/event/runtime contracts; documented permission and concurrency policy.

**Exit criteria:** representative product tasks route to the declared product team, use shared services where configured, enforce permissions and locks, survive failures, preserve artifact/event history, and complete review/QA gates with deterministic integration tests.

**Not included:** game UI, automated team generation, broad external automation, unsupported distributed/multi-machine scheduling.

## Phase 3 — Pixel Agent Office

**Goal:** add a truthful, optional, low-load visual observability layer.

**Deliverables:** TypeScript/Phaser browser client; SSE or WebSocket event projection; HQ overview, configuration-driven team rooms, agent detail, and task flow; real state-to-animation mapping; offline/error/idle accuracy.

**Dependencies:** Phase 2 event history and projections are stable; explicit approval; privacy/redaction review.

**Exit criteria:** UI reconstructs and follows actual system state, handles reconnect/replay, exposes no secrets or hidden reasoning, imposes no core-runtime dependency, and goes quiet when nothing is running.

**Not included:** authoritative task control, fabricated activity, chain-of-thought display, 3D/heavy always-on rendering.

## Phase 4 — Automation and Advanced Integrations

**Goal:** add only integrations whose user value justifies their security and operational cost.

**Deliverables:** selected scheduling/n8n workflows, GitHub/notification/webhook/research/data integrations, backups and restore drills, remote access if safely justified, richer dashboard/history, and task cost/performance analytics.

**Dependencies:** Phase 3 production acceptance, stable APIs/events, threat model and credential plan for every integration, and explicit approval.

**Exit criteria:** each enabled integration has bounded permissions, offline tests, documented failure/recovery behavior, secret rotation, monitoring, and a removal path; backup restoration is verified on representative state.

**Not included:** integrations without a concrete need, public databases/debug endpoints, enterprise IAM, Kubernetes/service mesh, distributed consensus, or microservice sprawl.

## Long-term acceptance target

```text
fresh Mac mini -> clone -> bootstrap -> configure auth/secrets
-> start -> doctor -> Slack task -> Codex modifies test project
-> required review/QA -> result -> reboot -> automatic recovery
```

Every phase must move toward this flow without claiming unapproved or unverified capability.
