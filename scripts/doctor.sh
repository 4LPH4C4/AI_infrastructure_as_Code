#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"

pass_count=0
warn_count=0
fail_count=0

pass() { pass_count=$((pass_count + 1)); printf '[PASS] %s\n' "$1"; }
warn() { warn_count=$((warn_count + 1)); printf '[WARN] %s\n' "$1"; }
fail() { fail_count=$((fail_count + 1)); printf '[FAIL] %s\n' "$1"; }
mac_verify() { printf '[MAC-VERIFY] %s\n' "$1"; }

check_required_command() {
  local command_name="$1"
  if command -v "${command_name}" >/dev/null 2>&1; then
    pass "${command_name} is available"
  else
    fail "${command_name} is missing"
  fi
}

check_optional_command() {
  local command_name="$1"
  local reason="$2"
  if command -v "${command_name}" >/dev/null 2>&1; then
    pass "${command_name} is available (${reason})"
  else
    warn "${command_name} is not available (${reason})"
  fi
}

printf '%s\n' "AI Hub Phase 1 doctor"
printf '%s\n' "Repository: ${REPO_ROOT}"
printf '%s\n' "Diagnostic output reports presence and status only; it never prints secret values."

if [[ -e "${REPO_ROOT}/.git" && -f "${REPO_ROOT}/pyproject.toml" ]]; then
  pass "repository root is valid"
else
  fail "repository root is invalid"
fi

for required_command in git gh uv codex; do
  check_required_command "${required_command}"
done
check_optional_command node "reserved for later UI tooling"
check_optional_command shellcheck "operator script linting"
check_optional_command docker "not required by the native Phase 1 runtime"

if [[ -x "${REPO_ROOT}/.venv/bin/python" || -x "${REPO_ROOT}/.venv/Scripts/python.exe" ]]; then
  pass "locked Python environment is synchronized"
else
  fail "locked Python environment is missing; run bootstrap/bootstrap-macos.sh"
fi

if [[ -f "${REPO_ROOT}/.env" ]]; then
  pass ".env exists (values not displayed)"
else
  fail ".env is missing; create it from .env.example"
fi

if command -v gh >/dev/null 2>&1; then
  if gh auth status >/dev/null 2>&1; then
    pass "GitHub CLI reports an authenticated session"
  else
    warn "GitHub CLI is not authenticated"
  fi
fi

if command -v uv >/dev/null 2>&1; then
  set +e
  PORTABLE_OUTPUT="$(cd -- "${REPO_ROOT}" && uv run --locked --no-dev python \
    "${SCRIPT_DIR}/doctor_portable.py" --repository-root "${REPO_ROOT}" 2>&1)"
  PORTABLE_EXIT=$?
  set -e
  printf '%s\n' "${PORTABLE_OUTPUT}"
  if (( PORTABLE_EXIT != 0 )); then
    fail_count=$((fail_count + 1))
  fi
else
  fail "portable configuration, database, lock, and health checks could not run"
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  pass "host operating system is macOS"
  if /usr/bin/xcode-select -p >/dev/null 2>&1; then
    pass "Xcode Command Line Tools are selected"
  else
    fail "Xcode Command Line Tools are not selected"
  fi
  SERVICE_PLIST="${HOME}/Library/LaunchAgents/com.macmini-ai-hub.service.plist"
  if [[ -f "${SERVICE_PLIST}" ]]; then
    INSTALLED_LABEL="$(/usr/libexec/PlistBuddy -c 'Print :Label' "${SERVICE_PLIST}" 2>/dev/null || true)"
    if [[ "${INSTALLED_LABEL}" == "com.macmini-ai-hub.service" ]]; then
      pass "launchd service plist is installed with the expected label"
      SERVICE_TARGET="gui/$(id -u)/com.macmini-ai-hub.service"
      if /bin/launchctl print "${SERVICE_TARGET}" >/dev/null 2>&1; then
        SERVICE_PID="$(/bin/launchctl print "${SERVICE_TARGET}" 2>/dev/null |
          /usr/bin/awk '/^[[:space:]]*pid = [0-9]+$/ { print $3; exit }')"
        if [[ -n "${SERVICE_PID}" ]]; then
          pass "launchd service process is running"
        else
          fail "launchd service is loaded but not running"
        fi
      else
        fail "launchd service is installed but not loaded"
      fi
    else
      fail "launchd plist label does not match the expected service"
    fi
  else
    fail "launchd service is not installed"
  fi
else
  warn "current host is not macOS; launchd and hardware checks were skipped"
fi

mac_verify "Codex authentication with a disposable fixture task"
mac_verify "Slack Socket Mode connectivity and reconnect behavior"
mac_verify "launchd start, stop, crash restart, login, and reboot recovery"
mac_verify "Homebrew prefix, power, sleep, FileVault, firewall, and disk capacity"

printf '\nSummary: %d local pass, %d local warning, %d local failure.\n' \
  "${pass_count}" "${warn_count}" "${fail_count}"
if (( fail_count > 0 )); then
  exit 1
fi
