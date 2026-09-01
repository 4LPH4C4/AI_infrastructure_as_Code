#!/usr/bin/env bash
set -euo pipefail

SERVICE_LABEL="com.macmini-ai-hub.service"
SERVICE_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SERVICE_REPO_ROOT="$(cd -- "${SERVICE_SCRIPT_DIR}/../.." && pwd -P)"

require_macos_service() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    printf '%s\n' "ERROR: launchd service control is supported only on macOS." >&2
    printf '%s\n' "[MAC-VERIFY] Run this command on the production Mac mini." >&2
    exit 2
  fi
  if [[ -z "${HOME:-}" || ! -d "${HOME}" ]]; then
    printf '%s\n' "ERROR: a valid HOME directory is required." >&2
    exit 2
  fi
}

service_plist_path() {
  printf '%s\n' "${HOME}/Library/LaunchAgents/${SERVICE_LABEL}.plist"
}

service_target() {
  printf 'gui/%s/%s\n' "$(id -u)" "${SERVICE_LABEL}"
}

verify_installed_service() {
  local plist_path
  local expected_path
  local installed_label
  plist_path="$(service_plist_path)"
  expected_path="${HOME}/Library/LaunchAgents/${SERVICE_LABEL}.plist"
  if [[ "${plist_path}" != "${expected_path}" || ! -f "${plist_path}" ]]; then
    printf '%s\n' "ERROR: service is not installed at the exact expected path: ${expected_path}" >&2
    printf '%s\n' "Run ${SERVICE_REPO_ROOT}/launchd/install.sh first." >&2
    exit 2
  fi
  installed_label="$(/usr/libexec/PlistBuddy -c 'Print :Label' "${plist_path}" 2>/dev/null || true)"
  if [[ "${installed_label}" != "${SERVICE_LABEL}" ]]; then
    printf '%s\n' "ERROR: installed plist label does not match ${SERVICE_LABEL}." >&2
    exit 2
  fi
}

service_is_loaded() {
  /bin/launchctl print "$(service_target)" >/dev/null 2>&1
}

service_pid() {
  /bin/launchctl print "$(service_target)" 2>/dev/null |
    /usr/bin/awk '/^[[:space:]]*pid = [0-9]+$/ { print $3; exit }'
}
