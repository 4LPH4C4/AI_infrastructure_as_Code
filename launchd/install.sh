#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
LABEL="com.macmini-ai-hub.service"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf '%s\n' "ERROR: launchd installation is supported only on macOS." >&2
  printf '%s\n' "[MAC-VERIFY] Install the service on the production Mac mini." >&2
  exit 2
fi
if [[ -z "${HOME:-}" || ! -d "${HOME}" ]]; then
  printf '%s\n' "ERROR: a valid HOME directory is required." >&2
  exit 2
fi

TARGET_DIRECTORY="${HOME}/Library/LaunchAgents"
TARGET_PATH="${TARGET_DIRECTORY}/${LABEL}.plist"
EXPECTED_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"
SERVICE_TARGET="${DOMAIN}/${LABEL}"

if [[ "${TARGET_PATH}" != "${EXPECTED_PATH}" ]]; then
  printf '%s\n' "ERROR: refusing unexpected launchd target: ${TARGET_PATH}" >&2
  exit 2
fi

mkdir -p -- "${TARGET_DIRECTORY}" "${REPO_ROOT}/workspace/logs"
chmod 700 -- "${TARGET_DIRECTORY}" "${REPO_ROOT}/workspace/logs"
TEMP_PATH="$(mktemp "${TARGET_PATH}.tmp.XXXXXX")"
cleanup() {
  rm -f -- "${TEMP_PATH}"
}
trap cleanup EXIT

"${SCRIPT_DIR}/render-plist.sh" >"${TEMP_PATH}"
chmod 600 -- "${TEMP_PATH}"
/usr/bin/plutil -lint -- "${TEMP_PATH}" >/dev/null
RENDERED_LABEL="$(/usr/libexec/PlistBuddy -c 'Print :Label' "${TEMP_PATH}")"
if [[ "${RENDERED_LABEL}" != "${LABEL}" ]]; then
  printf '%s\n' "ERROR: rendered plist label does not match the exact service target." >&2
  exit 2
fi

if [[ -e "${TARGET_PATH}" ]]; then
  EXISTING_LABEL="$(/usr/libexec/PlistBuddy -c 'Print :Label' "${TARGET_PATH}" 2>/dev/null || true)"
  if [[ "${EXISTING_LABEL}" != "${LABEL}" ]]; then
    printf '%s\n' "ERROR: refusing to replace a plist with an unexpected label." >&2
    exit 2
  fi
fi

if /bin/launchctl print "${SERVICE_TARGET}" >/dev/null 2>&1; then
  /bin/launchctl bootout "${DOMAIN}" "${TARGET_PATH}"
fi
/bin/mv -f -- "${TEMP_PATH}" "${TARGET_PATH}"
trap - EXIT

printf '%s\n' "Installed inactive service: ${SERVICE_TARGET}"
printf '%s\n' "Start it explicitly with ${REPO_ROOT}/scripts/start.sh"
printf '%s\n' "[MAC-VERIFY] Validate launchd logs, failure restart, login, and reboot recovery."
