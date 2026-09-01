# launchd placeholder

Production service management is intentionally deferred to Phase 1. Phase 0 does
not install, load, start, or claim to validate a `launchd` service.

The adjacent plist is a disabled design marker, not an installable service. It
runs `/usr/bin/false`, contains no real runtime command, and must not be copied to
`~/Library/LaunchAgents` or `/Library/LaunchDaemons`.

Phase 1 must replace it with a reviewed definition that establishes:

- the correct per-user or system service boundary;
- an absolute program path and working directory;
- explicit, non-secret environment handling;
- stdout/stderr log paths under the runtime workspace;
- restart throttling and graceful shutdown behavior;
- least-privilege file ownership and permissions.

`[MAC-VERIFY]` Loading, unloading, log rotation, failure recovery, and automatic
recovery after reboot must be tested on the production Mac mini in Phase 1.
