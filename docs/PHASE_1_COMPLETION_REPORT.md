# Phase 1 Completion Report

## 1. Status

**PARTIAL — offline implementation and QA pass; production acceptance awaits target-Mac verification.**

Phase 1 is feature-complete for the approved single-Developer MVP. Phase 2 remains locked.

## 2. Implemented

- strict operational settings and one composition root;
- SQLite migrations and durable tasks, runs, events, artifacts, routes, request receipts, and delivery receipts;
- atomic gateway task creation/routing/queueing with deterministic retry identity;
- Slack Socket Mode command adapter, allowlist authorization, thread-aware replies, bounded retry, rate-limit handling, and restart replay;
- one-Developer orchestrator with bounded concurrency, cancellation, failure mapping, and interrupted-work reconciliation;
- registered repository selection, explicit remote-base task branches, dirty-tree rejection, and per-project locks;
- Codex CLI runtime with explicit arguments/stdin, sanitized environment, workspace sandbox, network/web-search denial, untrusted-command approval, timeout, cancellation, and bounded redacted output;
- result projection containing only durable branch, changed-file, runtime-outcome, and safe error metadata;
- rotating structured JSON logs plus localhost health/readiness;
- generated per-user launchd service controls, doctor checks, and operator recovery runbooks;
- offline Gateway → Orchestrator → fake Runtime → SQLite → projection integration.

## 3. Repository Structure

```text
config/                         public validated registry examples
src/macmini_ai_hub/api/        localhost health/readiness
src/macmini_ai_hub/gateway/    source-neutral requests and policy boundary
src/macmini_ai_hub/orchestrator/ single-Developer workflow and ports
src/macmini_ai_hub/runtime/    runtime contract and Codex adapter
src/macmini_ai_hub/storage/    SQLite records, migrations, and adapters
src/macmini_ai_hub/projects/   registered Git workspace manager
src/macmini_ai_hub/locks/      per-project exclusive file locks
src/macmini_ai_hub/integrations/ Slack Socket Mode adapter
src/macmini_ai_hub/observability/ projections, redaction, and logging
launchd/                       inactive install plus exact service controls
scripts/                       lifecycle and doctor commands
tests/                         offline unit, failure, restart, and MVP tests
```

Generated `workspace/` state remains ignored. Managed product repositories remain separate from the AI Hub repository.

## 4. Architecture Decisions

- Interfaces call the Agent Gateway, never Codex directly.
- Orchestration depends on runtime/storage/project ports; concrete adapters are wired only in composition.
- SQLite is authoritative for one-host operational history; notifications are non-authoritative projections.
- Request/task identity is deterministic across a crash window, and task plus route plus queued event are one transaction.
- Startup reconciles planning/running work, queued/running runs, incomplete request/delivery reservations, and undelivered routed lifecycle updates.
- Each task branch starts from the registered remote base, never from a previous task branch.
- Phase 1 rejects Developer profiles with network, deploy, or admin capabilities and requires project-workspace policy.

## 5. Tests

- `pytest`: **277 passed**;
- statement coverage: **86%** over 3,395 statements;
- Ruff: pass;
- mypy strict mode: pass;
- all repository Bash files: `bash -n` pass;
- locked dependency audit, including development groups: no known vulnerabilities;
- configuration, migration, storage atomicity, corruption/busy handling, restart recovery, locks, Git isolation, Slack rate/error/idempotency, redaction, runtime failure/timeout/cancellation, API readiness, lifecycle shutdown, and offline MVP paths are covered.

Automated tests run without live Slack, authenticated Codex calls, network access, or a physical Mac mini.

## 6. Security Review

- No credential values are present in version-controlled configuration.
- Task instructions containing credential-shaped material fail closed before persistence.
- GitHub/OpenAI/Slack tokens, bearer values, named secrets, credential URLs, and PEM private keys have redaction regressions.
- Runtime command construction uses no shell, ignores user Codex config, disables command network/web search, protects the workspace boundary, and does not enable bypass/yolo flags.
- Destructive Git, automatic push/merge/deploy, public binding, and secret-bearing diagnostics remain disabled.
- The dependency lock has no known vulnerability in the final audit.

## 7. MAC-VERIFY Items

- Apple Silicon, supported macOS, Command Line Tools, Homebrew prefix, and locked bootstrap idempotence;
- workspace ownership/modes and dedicated-account behavior;
- GitHub authentication and private project clone/origin/default-branch behavior;
- Codex installation/authentication plus the approved `README_TEST.md` fixture edit and safe test execution;
- Codex sandbox/approval behavior on macOS Seatbelt;
- live Slack Socket Mode authentication, acknowledgement, reconnect, 429 behavior, thread result, and redaction;
- launchd install/start/stop/crash restart/login behavior and reboot recovery;
- localhost-only readiness, firewall, FileVault, sleep/power-loss policy, logs, backup, and restore drill.

## 8. Known Limitations

- A per-user LaunchAgent requires the user GUI domain; pre-login boot behavior is not claimed.
- Codex approval behavior can only be accepted after the authenticated macOS fixture succeeds. Unavailable approval intentionally fails closed.
- Phase 1 does not auto-commit, push, merge, deploy, or clean project changes. A dirty task checkout blocks another task on that project until an operator reviews it.
- Slack lifecycle replay is durable and idempotent, but tests are reported only when structured test metadata exists; the service never invents a passing test result.
- One Developer executes per task. Reviewer, QA, delegation, and multi-agent workflow states remain non-operational Phase 2 contracts.
- SQLite and in-process scheduling target one Mac mini, not distributed workers.

## 9. Next Phase Proposed Backlog

After target-Mac acceptance and separate approval, Phase 2 may add team-aware multi-agent routing, Developer → Reviewer → QA gates, artifact handoffs, richer permission enforcement, parallel-safe histories, and failure-aware delegation. No Phase 2 execution path is included here.

## 10. User Action Required

Run and review the target-Mac `[MAC-VERIFY]` checklist. Approve Phase 2 explicitly only after Phase 1 production acceptance.
