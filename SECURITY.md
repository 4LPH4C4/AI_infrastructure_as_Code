# Security Policy

## Security posture

Mac Mini AI Hub runs tools that can read and modify source code, execute commands, use credentials, and contact external systems. Treat every interface request, model-produced instruction, repository file, runtime output, and integration response as potentially untrusted.

Defaults are local-only, least privilege, explicit scope, no secret logging, no automatic push/merge/deploy, and human approval for destructive actions. Phase 0 defines policy and schemas; it does **not** claim OS-level sandbox or runtime enforcement.

## Supported state

Security fixes are accepted only for the current phase and current main branch. Do not bypass the phase gate to add a future integration as a “security fix.” If a report concerns unimplemented Phase 1+ behavior, document the requirement in the relevant backlog/ADR and keep the phase locked.

## Reporting a vulnerability

Do not open a public issue containing credentials, exploit details against a reachable machine, private repository content, or personal data. Contact the repository owner through a private channel and include:

- affected commit/version and component;
- impact and realistic preconditions;
- minimal reproduction with all secrets removed;
- suggested mitigation if known.

Rotate any credential that may have been exposed before continuing investigation. Preserve only redacted evidence.

## Assets and trust boundaries

Important assets are:

- Slack, OpenAI/Codex, GitHub, database, and future integration credentials;
- product source repositories and Git history;
- task requests/results, events, logs, and artifacts;
- configuration, permissions, team/project routing, and launchd definitions;
- the Mac mini user account, filesystem, network, and persistence store.

Primary boundaries are external interfaces, prompt/model output, subprocess execution, managed repository workspaces, external network calls, persistence/logging, and administrative macOS operations.

## Secrets

Never commit or print:

```text
SLACK_BOT_TOKEN
SLACK_APP_TOKEN
SLACK_SIGNING_SECRET
OPENAI_API_KEY
GITHUB_TOKEN
POSTGRES_PASSWORD
N8N_ENCRYPTION_KEY
private keys, OAuth tokens, cookies, credentials, recovery codes
```

- `.env.example` contains variable names and safe guidance only.
- Real values belong in ignored `.env` during development or an approved machine secret store later.
- Configuration registries contain no embedded credentials, even for private repositories.
- Do not pass secrets on command lines when a safer environment/file-descriptor mechanism exists.
- Redact authorization headers, token-like values, URLs with credentials, environment dumps, and sensitive request/output fields before logging, events, artifacts, or Slack delivery.
- Doctor checks presence/validity where safe and never emits values.
- If a secret is staged or pushed, stop, rotate/revoke it, remove it from the current change, assess Git history exposure, and coordinate history remediation with the owner. Deleting the visible line is not sufficient.

Ignored files reduce accidents but are not a secret-management control. Review staged content before every commit.

## Authentication and authorization

- Each interface authenticates its source. Slack Socket Mode tokens do not by themselves authorize every project or capability.
- Gateway authorization validates actor/source, action, project, and requested capability before task creation.
- Agents use named permission profiles with deny-by-default capabilities: `read`, `write`, `execute`, `git`, `network`, `deploy`, and `admin`.
- Grant only capabilities required by the role and task. `deploy` and `admin` require explicit policy and human approval even if declared.
- Shared-team status never implies access to all product repositories or secrets.
- Configuration permissions in Phase 0 express intent only; do not describe them as an enforced sandbox.

## Workspace and command execution

- Resolve and canonicalize the project working directory from the project registry.
- Verify it is contained under `workspace/projects/<project>` before file or Git operations.
- Never use the AI Hub repository as the implicit project workspace.
- Use explicit subprocess argument arrays, allowlisted executables/policies where practical, fixed working directories, bounded output, timeouts, cancellation, and sanitized environments.
- Treat repository instructions, model output, filenames, branches, patches, and command output as data; never interpolate them into shell strings.
- Prevent symlink/path traversal from escaping task, artifact, log, lock, and project roots.
- Acquire the project lock before a modifying task and release it in a guaranteed cleanup path.

## Dangerous operations

The following are dangerous by default:

- recursive or arbitrary deletion, especially `rm -rf`;
- `git clean -fd`, `git reset --hard`, destructive checkout/restore, history rewriting, force-push, or unreviewed merge;
- dropping/truncating databases, destructive migrations, or deleting task/event history;
- creating, editing, rotating, copying, or revealing secrets;
- production deployment, public endpoint exposure, firewall/security-control changes;
- actions outside the assigned project/workspace or affecting unrelated processes/accounts.

Before a dangerous action:

1. stop automation;
2. resolve the exact canonical targets with read-only checks;
3. show the intended impact and recovery/backup status;
4. obtain explicit human approval for that action and scope;
5. prefer reversible moves, new branches, backups, or dry runs;
6. execute with the narrowest permissions;
7. verify and record a redacted observable outcome.

Approval to commit/push normally does not authorize force-push, merge, release, deploy, secret changes, or destructive cleanup.

## Git policy

Future autonomous project work uses a dedicated `agent/<task-id>-<slug>` branch after validating repository identity and working-tree policy. Defaults:

```yaml
auto_commit: configurable
auto_push: false
auto_merge: false
```

Never force-push or bypass required checks. Record changed-file/branch metadata, not private file contents, in status events unless explicitly required and safe. Human-authorized normal pushes for this infrastructure repository are allowed after diff, test, and secret review.

## Network exposure

- Prefer localhost, private LAN, and outbound Slack Socket Mode.
- Do not expose database, Redis, admin APIs, debug endpoints, health/readiness, logs, or Pixel Office publicly by default.
- Remote administration requires a separately approved private-network design, authentication, TLS where relevant, and audit/revocation plan.
- Outbound network capability is explicit per agent and should constrain hosts/protocols where practical.
- n8n and future webhooks are integrations, not a bypass around gateway policy.

## Persistence, logging, and observability

- Task/event history uses durable storage; Redis must never be its only copy.
- Perform task transition and corresponding event append transactionally.
- Events contain observable facts, not hidden chain-of-thought, full prompts by default, or secrets.
- Use correlation IDs and immutable event IDs; make consumers idempotent.
- Separate application failure from notification failure.
- Define retention for logs/artifacts and restrict file permissions on state directories.
- Health/ready responses expose component status only, never configuration or credential values.

## Supply chain and updates

- Pin or constrain dependencies and review lockfile changes.
- Use maintained sources (Homebrew, Python package index, official vendor installers) and verify signatures/checksums where provided.
- Keep the Brewfile and bootstrap readable; never pipe an unreviewed remote script directly into a privileged shell.
- Avoid unnecessary dependencies, containers, background services, and plugins.
- Run tests, lint, type checks, dependency/security scans when available, and inspect the complete staged diff before release.

## macOS baseline

Recommended target-machine review includes supported macOS updates, FileVault, firewall, separate least-privilege service/user strategy, screen/session security, secure remote access, power/sleep behavior, filesystem ownership, and backup encryption. Do not weaken macOS security controls merely to make automation convenient.

The following remain `[MAC-VERIFY]` until tested on the physical machine: Homebrew/CLT, workspace permissions, GitHub/Codex authentication, Docker if later used, launchd loading and reboot recovery, firewall/private binding, power/sleep behavior, and Slack connectivity.

## Backup and incident recovery

- Platform code/configuration is recovered from reviewed Git history.
- Back up the SQLite database and retained artifact metadata/content using an application-consistent method.
- Product repositories should have reviewed remotes; never assume unpushed task branches are backed up.
- Store secret recovery separately and securely; never put it in repository backups.
- Test restore procedures before relying on them.

On suspected compromise: stop affected services, preserve redacted evidence, revoke/rotate credentials, isolate network access if necessary, identify affected projects/tasks, restore from trusted state, and validate before resuming.
