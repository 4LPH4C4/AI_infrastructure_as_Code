# launchd user service

Phase 1 runs the hub as the current user's exact launchd target:

```text
gui/<uid>/com.macmini-ai-hub.service
```

The committed plist is a tokenized, secret-free template. `render-plist.sh`
resolves the repository and `uv` executable to absolute paths and rejects paths
that cannot be substituted safely. The generated PATH includes the resolved
Codex and `uv` executable directories, including a standalone user install. It
never reads `.env` or embeds credentials.

Install the service definition without loading or starting it:

```bash
./launchd/install.sh
```

Then use the lifecycle wrappers:

```bash
./scripts/start.sh
./scripts/status.sh
./scripts/restart.sh
./scripts/stop.sh
```

Remove only the exact plist whose embedded label matches the expected service:

```bash
./launchd/uninstall.sh
```

The user LaunchAgent runs `uv run --locked --no-dev ai-hub serve` from the
repository root. Logs are written to `workspace/logs/ai-hub.stdout.log` and
`workspace/logs/ai-hub.stderr.log`. A non-successful exit is restarted with
launchd throttling; an intentional clean stop remains stopped.

`[MAC-VERIFY]` Run install, start, stop, crash recovery, login, reboot recovery,
log permissions, and uninstall acceptance checks on the production Mac mini.
