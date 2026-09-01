#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/mac-service.sh
source "${SCRIPT_DIR}/lib/mac-service.sh"

require_macos_service
verify_installed_service
if ! service_is_loaded; then
  printf 'Service is installed but not loaded: %s\n' "$(service_target)"
  exit 1
fi
PID="$(service_pid)"
if [[ -n "${PID}" ]]; then
  printf 'launchd: running (pid %s)\n' "${PID}"
else
  printf '%s\n' "launchd: loaded, not running"
fi

cd -- "${SERVICE_REPO_ROOT}"
uv run --locked --no-dev ai-hub status
