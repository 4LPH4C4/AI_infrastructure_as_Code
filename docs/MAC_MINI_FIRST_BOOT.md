# Mac mini first boot

This checklist separates the Phase 0 repository bootstrap from future runtime
work. Commands that affect machine policy should be reviewed before execution.
No production Mac mini validation has been performed from the development host.

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
development environment, and creates the runtime workspace. It is designed to
be idempotent. It does not start a service or install `launchd` configuration.

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
- [ ] `[MAC-VERIFY]` Install and authenticate Codex before Phase 1 work begins.
- [ ] `[MAC-VERIFY]` Decide whether Docker is required before installing it; it is
  not part of the Phase 0 Homebrew baseline.

Slack credentials and Socket Mode are Phase 1 work. Do not configure a live Slack
integration from this Phase 0 guide.

## 4. Phase 0 verification

Run the diagnostic framework:

```bash
./scripts/doctor.sh
```

The doctor command reports `PASS`, `WARN`, `FAIL`, `NOT IMPLEMENTED`, and
`MAC-VERIFY` separately. It checks only whether `.env` exists and never prints
its contents or secret values.

Verify the workspace remains local runtime state:

```bash
find workspace -maxdepth 2 -type d -print
git status --short
```

Expected directories are `projects`, `tasks`, `memory`, `indexes`, `locks`,
`artifacts`, and `logs`.

## 5. Phase 1 placeholders — do not execute yet

The following acceptance steps are intentionally locked until Phase 1 is
approved and implemented:

- [ ] Start the Agent Gateway, orchestrator, and Codex runtime adapter.
- [ ] Configure Slack Socket Mode and send a test task.
- [ ] Install and load a reviewed `launchd` service definition.
- [ ] `[MAC-VERIFY]` Reboot and confirm automatic recovery.
- [ ] `[MAC-VERIFY]` Confirm log rotation and failure recovery.
- [ ] Run an end-to-end test task in a disposable project repository.

`scripts/start.sh`, `stop.sh`, `restart.sh`, and `status.sh` deliberately exit
with code 3 in Phase 0. They do not report fake service success.

## Troubleshooting

- Missing Command Line Tools: run `xcode-select --install`, finish the GUI
  installer, and rerun bootstrap.
- `brew` not found: follow the post-install PATH instructions printed by the
  official Homebrew installer, open a new shell, and rerun bootstrap.
- Missing workspace directory: run `./bootstrap/init-workspace.sh`.
- Doctor failure: fix each `FAIL`; `WARN` and `MAC-VERIFY` require review, while
  `NOT IMPLEMENTED` is an honest phase boundary rather than a healthy service.
