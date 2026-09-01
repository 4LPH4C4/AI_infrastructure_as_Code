#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/mac-service.sh
source "${SCRIPT_DIR}/lib/mac-service.sh"

require_macos_service
verify_installed_service
if ! service_is_loaded; then
  /bin/launchctl bootstrap "gui/$(id -u)" "$(service_plist_path)"
fi
/bin/launchctl kickstart "$(service_target)"
printf 'Started %s\n' "$(service_target)"
printf '%s\n' "[MAC-VERIFY] Confirm readiness and log output on the production Mac mini."
