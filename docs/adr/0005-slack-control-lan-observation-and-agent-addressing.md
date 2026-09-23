# ADR-0005: Slack control, LAN observation, and direct agent addressing

- Status: Accepted architectural direction; implementation remains phase-gated
- Date: 2026-09-16
- Extends: ADR-0002 and ADR-0003

## Context

The owner intends to leave the Mac mini running with little monitor interaction,
direct work through Slack, and inspect progress from phones, tablets, and PCs on
the same private network. The owner also wants to address individual specialists
and ask a coordinating agent to account for unsatisfactory results.

## Decision

1. Slack is the primary instruction and conversation interface. The Mac mini is
   the sole execution host. Its monitor is mainly for setup and recovery.
2. A responsive, authenticated private-LAN web interface will provide read-only
   task, agent, team, project, and artifact projections in Phase 3. A practical
   dashboard precedes optional Pixel presentation. Neither UI is authoritative.
   Current Phase 1 loopback binding remains unchanged. Public exposure is not required.
3. Phase 2 will support an explicit target agent as well as automatic routing.
   A direct address selects a requested specialist; it does not bypass the
   Gateway, authorization, durable records, project isolation, locks, or workflow gates.
4. Separate observational queries, specialist consultation, and change requests.
   Existing status queries use stored facts. Consultation is read-only and may
   invoke the requested specialist with bounded project context. Changes create
   or amend authorized work through orchestration; a casual question must not
   silently mutate a repository. Consultation persistence contracts are deferred
   to Phase 2 rather than adding task states now.
5. Agent replies identify the responsible agent, project, relevant task and
   evidence. Slack thread context must bind explicitly to a project and target;
   ambiguous references require clarification before execution. Consultation
   does not silently redirect or interrupt a running assignment.
6. The platform orchestrator remains a deterministic application service. A
   user-facing coordinating or team-lead agent is a role that consults recorded
   facts and proposes plans; it cannot independently rewrite authoritative state.
   A separate team-lead role is optional and requires explicit registry design.
7. Escalation to the coordinator references the original task, relevant agent
   output, failed acceptance criteria, and requested correction. The coordinator
   explains observable causes and arranges approved rework or reassignment.
   Terminal tasks are never resurrected; follow-up work retains provenance.
   Feedback changes neither prompts nor permissions automatically.
8. Native Slack mentions require actual Slack identities. Merely changing a
   reply's name/avatar does not create a mentionable agent. Two delivery options
   remain open for Phase 2:
   - one Hub bot plus an explicit agent selector (lower operational cost);
   - separately installed bot identities for selected stable specialists (native
     individual mentions), all routed into the same platform.
   The second option is the target user experience where literal individual
   mentions are needed; credential and installation costs must be reviewed.
   Do not create a bot for every catalog persona by default.
9. Bot output is not an implicit new instruction. Internal delegation uses
   orchestrator contracts, not bots triggering one another through channel text.
   Future multi-identity intake deduplicates by workspace/event and validates the
   intended recipient to avoid duplicate execution. Multiple targets must be
   deliberately routed or clarified, not independently started by each bot.

## Consequences and acceptance

- Phase 1 remains single-Developer with one Slack bot and local health endpoints.
  Direct agent consultation and a LAN web server are not implemented by this ADR.
- Phase 2 tests must cover exact target selection, disabled/unknown agents,
  cross-project access denial, read-only consultation, thread binding, bot-loop
  prevention, duplicate intake, busy-agent handling, and traceable escalation.
- Phase 3 must use the same Task/Event truth as Slack, support small touch screens,
  authenticate viewers, redact sensitive data, display stale/disconnected state,
  and avoid LAN access from implying blanket authorization.
- `[MAC-VERIFY]` The current user LaunchAgent is not proof of unattended recovery
  after boot. Login/FileVault, RunAtLoad policy, power loss, sleep, crash restart,
  and operator recovery must be verified without weakening machine security.
- Routine work should not require the monitor. Initial login, credentials,
  operating-system changes, and some recovery actions may still require an operator.

## Slack references

- [app_mention](https://docs.slack.dev/reference/events/app_mention): bot mentions
  and direct-message events are distinct; channel membership matters.
- [chat.postMessage](https://docs.slack.dev/reference/methods/chat.postMessage/):
  message presentation and thread replies do not create separate bot identities.

## Rejected alternatives

- Direct Slack-to-runtime invocation for specialists: bypasses platform policy.
- Treating a persona display name as a real Slack account: misleading addressing.
- A team lead as an unrestricted runtime authority: conflicts with durable policy.
- Using the web UI to independently mutate task state: creates two control paths.
- Automatically generating Slack accounts or exposing services now: outside the
  authorized phase and unnecessary for recording the operating requirements.
