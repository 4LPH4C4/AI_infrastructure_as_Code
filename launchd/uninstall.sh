#!/usr/bin/env bash
set -euo pipefail

LABEL="com.macmini-ai-hub.service"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf '%s\n' "ERROR: launchd removal is supported only on macOS." >&2
  printf '%s\n' "[MAC-VERIFY] Remove the service on the production Mac mini." >&2
  exit 2
fi
if [[ -z "${HOME:-}" || ! -d "${HOME}" ]]; then
  printf '%s\n' "ERROR: a valid HOME directory is required." >&2
  exit 2
fi

TARGET_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
EXPECTED_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"
SERVICE_TARGET="${DOMAIN}/${LABEL}"

if [[ "${TARGET_PATH}" != "${EXPECTED_PATH}" ]]; then
  printf '%s\n' "ERROR: refusing unexpected launchd target: ${TARGET_PATH}" >&2
  exit 2
fi
if [[ ! -e "${TARGET_PATH}" ]]; then
  printf '%s\n' "Service is not installed: ${SERVICE_TARGET}"
  exit 0
fi

EXISTING_LABEL="$(/usr/libexec/PlistBuddy -c 'Print :Label' "${TARGET_PATH}" 2>/dev/null || true)"
if [[ "${EXISTING_LABEL}" != "${LABEL}" ]]; then
  printf '%s\n' "ERROR: refusing to remove a plist with an unexpected label." >&2
  exit 2
fi

if /bin/launchctl print "${SERVICE_TARGET}" >/dev/null 2>&1; then
  /bin/launchctl bootout "${DOMAIN}" "${TARGET_PATH}"
fi
/bin/rm -- "${TARGET_PATH}"
printf '%s\n' "Removed service: ${SERVICE_TARGET}"
