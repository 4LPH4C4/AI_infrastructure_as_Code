# Mac mini first boot

This checklist installs and operates the Phase 1 native runtime. Commands that
affect machine policy should be reviewed before execution. No production Mac
mini validation has been performed from the development host.

## 1. macOS baseline

- [ ] `[MAC-VERIFY]` Install current macOS security updates and reboot.
- [ ] `[MAC-VERIFY]` Choose a stable hostname and confirm local DNS/LAN behavior.
- [ ] `[MAC-VERIFY]` Enable FileVault and record the recovery key securely.
- [ ] `[MAC-VERIFY]` Configure sleep, restart-after-power-loss, and unattended
  operation according to the owner's physical-security requirements.
- [ ] Create a dedicated, non-shared local account for the hub where practical.
- [ ] Keep inbound services disabled unless a later phase explicitly needs them.

Do not copy passwords, API tokens, OAuth secrets, private keys, or recovery keys
into the repository or shell history.

## 2. Developer tools and repository

1. Install Xcode Command Line Tools:

   ```bash
   xcode-select --install
   ```

2. `[MAC-VERIFY]` Install Homebrew from its official instructions at
   <https://brew.sh>. Review the installer before running it. The repository does
   not download and pipe an installer into a shell.

3. Clone the repository using the intended GitHub identity:

   ```bash
   git clone https://github.com/4LPH4C4/AI_infrastructure_as_Code.git
   cd AI_infrastructure_as_Code
   ```

4. Review the bootstrap inputs, then run them:

   ```bash
   less Brewfile
   less bootstrap/bootstrap-macos.sh
   ./bootstrap/bootstrap-macos.sh
   ```

The bootstrap applies the Homebrew bundle, synchronizes the locked Python
environment, and creates the runtime workspace. It is designed to be idempotent.
It does not start a service or install `launchd` configuration.

## 3. Authentication and machine configuration

- [ ] Configure Git author name and email for the dedicated account.
- [ ] `[MAC-VERIFY]` Authenticate GitHub with `gh auth login` and verify only the
  minimum required scopes.
- [ ] `[MAC-VERIFY]` Configure GitHub SSH if SSH remotes will be used.
- [ ] Copy `.env.example` to `.env` when required and populate it locally:

  ```bash
  cp .env.example .env
  chmod 600 .env
  ```

- [ ] Store recoverable secrets in a password manager or macOS Keychain. Never
  commit `.env`.
- [ ] `[MAC-VERIFY]` Install Codex using the reviewed official instructions at
  <https://developers.openai.com/codex/cli>. The official macOS/Linux quickstart
  currently shows a standalone installer; this repository deliberately does not
  pipe a remote installer into a shell automatically.
- [ ] `[MAC-VERIFY]` Run `codex`, sign in interactively, and verify the dedicated
  service account can execute a disposable fixture task.
- [ ] `[MAC-VERIFY]` Decide whether Docker is required before installing it; it is
  not required by the Phase 1 native runtime baseline.

Create the five active registries from the reviewed examples, then customize
only non-secret metadata:

```bash
for name in settings agents teams projects permissions; do
  cp -n "config/${name}.example.yaml" "config/${name}.yaml"
done
```

Set every project's `base_branch` to the reviewed remote default branch. Enable
exactly one Developer for the test product team. Before any service write, run:

```bash
uv run --locked --no-dev ai-hub check-config
uv run --locked --no-dev ai-hub migrate
```

Keep Slack token values only in `.env`. Set `AI_HUB_SLACK_ENABLED=true`, the bot
and app token variables, and `AI_HUB_SLACK_ALLOWED_USER_IDS` only after the Slack
app and least-privilege allowlist are ready.

## 4. Phase 1 service installation and verification

Validate configuration and initialize storage before installing the service:

```bash
uv run --locked --no-dev ai-hub check-config
uv run --locked --no-dev ai-hub migrate
```

Verify the workspace remains local runtime state:

```bash
find workspace -maxdepth 2 -type d -print
git status --short
```

Expected directories are `projects`, `tasks`, `memory`, `indexes`, `locks`,
`artifacts`, and `logs`.

Install the exact per-user launchd definition, then load and start it explicitly:

```bash
./launchd/install.sh
./scripts/start.sh
./scripts/status.sh
./scripts/doctor.sh
```

The doctor command reports `PASS`, `WARN`, `FAIL`, and `MAC-VERIFY` separately.
It checks secret presence when required but never prints secret values.

The generated plist contains absolute executable, repository, and log paths but
no secrets. It controls only `gui/<uid>/com.macmini-ai-hub.service`. Remove it
with `./launchd/uninstall.sh`; the removal script rejects an unexpected label or
path.

- [ ] `[MAC-VERIFY]` Send a Slack fixture request and confirm quick acknowledgement.
- [ ] `[MAC-VERIFY]` Confirm the fixture uses a registered project, task branch,
  exclusive lock, and Codex runtime without changing any other repository.
- [ ] `[MAC-VERIFY]` Confirm Codex can edit the fixture and run its safe checks
  while command network/web search remain disabled and untrusted operations fail
  closed when no approval channel is available.
- [ ] `[MAC-VERIFY]` Stop and start the service and inspect redacted log output.
- [ ] `[MAC-VERIFY]` Reboot and confirm recovery and localhost-only readiness.

## 5. Operator runbooks

### Backup and restore

Stop the service before a cold backup. Back up committed configuration with Git,
copy `.env` only through an encrypted secret-recovery channel, and use SQLite's
online backup command for a running database when a cold stop is not possible.
Retain `workspace/tasks/ai-hub.sqlite3`, required artifacts, and any logs needed
for an incident. Project repositories can normally be reconstructed from their
registered origins and pushed task branches.

To restore, stop the service, restore the database to the configured exact path,
set ownership to the dedicated account and mode `600`, run doctor, then start.
Never restore stale lock files. `[MAC-VERIFY]` Perform a disposable backup and
restore drill before relying on it.

### Stuck project lock

1. Stop the service and confirm no AI Hub or Codex task process remains.
2. Inspect only `project`, `task`, `created_at`, and `pid` in the exact
   `workspace/locks/<project>.lock` file.
3. Confirm the age exceeds policy and the PID is absent. Malformed locks are
   never removed automatically.
4. Move that one verified file to a private quarantine directory, restart, and
   retain it for incident review. Never wildcard-delete the lock directory.

### Runtime failure or Slack disconnect

Run `./scripts/status.sh` and `./scripts/doctor.sh`. Inspect the bounded service
logs under `workspace/logs` without pasting token-bearing input. A runtime
failure remains recorded on its task; do not rerun by deleting database rows.
For Slack, verify allowlisted users, token *presence*, network access, and Socket
Mode reconnect state without printing token values. Restart once after fixing
configuration; repeated failure requires log and event investigation.

### Update and rollback

Stop the service, require a clean infrastructure checkout, fetch reviewed
changes, and update with `git pull --ff-only`. Run `uv sync --locked --no-dev`,
the full test suite, `./launchd/install.sh`, doctor, and start. Back up SQLite
before any migration. Prefer a reviewed Git revert for rollback; never use
`reset --hard`, force-push, or `clean`. Restore a pre-migration database backup
only with the matching reviewed code version.

## Troubleshooting

- Missing Command Line Tools: run `xcode-select --install`, finish the GUI
  installer, and rerun bootstrap.
- `brew` not found: follow the post-install PATH instructions printed by the
  official Homebrew installer, open a new shell, and rerun bootstrap.
- Missing workspace directory: run `./bootstrap/init-workspace.sh`.
- Service not installed: run `./launchd/install.sh` as the dedicated user; do
  not use `sudo` or copy it into `/Library/LaunchDaemons`.
- Doctor failure: fix each `FAIL`; `WARN` and `MAC-VERIFY` require review.
