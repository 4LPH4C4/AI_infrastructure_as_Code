#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=lib/mac-service.sh
source "${SCRIPT_DIR}/lib/mac-service.sh"

require_macos_service
verify_installed_service
if ! service_is_loaded; then
  printf 'Service is not loaded: %s\n' "$(service_target)"
  exit 0
fi
/bin/launchctl bootout "gui/$(id -u)" "$(service_plist_path)"
printf 'Stopped and unloaded %s\n' "$(service_target)"
