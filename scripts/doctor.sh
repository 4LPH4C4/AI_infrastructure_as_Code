#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
WORKSPACE_ROOT="${REPO_ROOT}/workspace"

pass_count=0
warn_count=0
fail_count=0

pass() {
  pass_count=$((pass_count + 1))
  printf '[PASS] %s\n' "$1"
}

warn() {
  warn_count=$((warn_count + 1))
  printf '[WARN] %s\n' "$1"
}

fail() {
  fail_count=$((fail_count + 1))
  printf '[FAIL] %s\n' "$1"
}

not_implemented() {
  printf '[NOT IMPLEMENTED] %s\n' "$1"
}

mac_verify() {
  printf '[MAC-VERIFY] %s\n' "$1"
}

check_required_command() {
  local command_name="$1"
  if command -v "${command_name}" >/dev/null 2>&1; then
    pass "${command_name} is available"
  else
    fail "${command_name} is missing (run bootstrap/bootstrap-macos.sh on macOS)"
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

printf '%s\n' "AI Hub Phase 0 doctor"
printf '%s\n' "Repository: ${REPO_ROOT}"
printf '%s\n' "Diagnostic output reports presence and status only; it never prints secret values."
printf '%s\n' "[IMPLEMENTED] Phase 0 repository, toolchain, workspace, and configuration-presence checks"

if [[ -e "${REPO_ROOT}/.git" ]]; then
  pass "repository metadata is present"
else
  fail "repository metadata is missing"
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  pass "host operating system is macOS"
  if [[ "$(uname -m)" == "arm64" ]]; then
    pass "host architecture is Apple Silicon (arm64)"
  else
    warn "host architecture is not Apple Silicon; review the intended production target"
  fi
  if /usr/bin/xcode-select -p >/dev/null 2>&1; then
    pass "Xcode Command Line Tools are selected"
  else
    fail "Xcode Command Line Tools are not selected"
  fi
else
  warn "current host is not macOS; production checks require the Mac mini"
fi

for required_command in brew git gh uv node shellcheck; do
  check_required_command "${required_command}"
done

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  pass "locked Python development environment is synchronized"
else
  fail ".venv/bin/python is missing (run bootstrap/bootstrap-macos.sh on macOS)"
fi

# These tools are expected by later phases but are not installed by the Phase 0
# baseline. Presence is useful information; absence is not a Phase 0 failure.
check_optional_command codex "runtime integration begins in Phase 1"
check_optional_command docker "container use remains an explicit future decision"

workspace_directories=(
  projects
  tasks
  memory
  indexes
  locks
  artifacts
  logs
)

for directory in "${workspace_directories[@]}"; do
  workspace_path="${WORKSPACE_ROOT}/${directory}"
  if [[ -d "${workspace_path}" && -w "${workspace_path}" ]]; then
    pass "workspace/${directory} exists and is writable"
  elif [[ -d "${workspace_path}" ]]; then
    fail "workspace/${directory} exists but is not writable"
  else
    fail "workspace/${directory} is missing (run bootstrap/init-workspace.sh)"
  fi
done

if [[ -f "${REPO_ROOT}/.env" ]]; then
  pass ".env exists (contents intentionally not inspected or displayed)"
else
  warn ".env is absent; create it from .env.example when machine-specific configuration is needed"
fi

if command -v gh >/dev/null 2>&1; then
  if gh auth status >/dev/null 2>&1; then
    pass "GitHub CLI reports an authenticated session"
  else
    warn "GitHub CLI is not authenticated; run 'gh auth login' on the Mac mini"
  fi
fi

not_implemented "Agent Gateway health check (Phase 1)"
not_implemented "Orchestrator health check (Phase 1)"
not_implemented "Codex runtime authentication check (Phase 1)"
not_implemented "Slack configuration and connection check (Phase 1)"
not_implemented "launchd service and reboot recovery check (Phase 1)"

mac_verify "Homebrew prefix and shell PATH on Apple Silicon"
mac_verify "workspace ownership, permissions, and disk capacity"
mac_verify "GitHub SSH/CLI authentication for the production account"
mac_verify "Codex installation and authentication before Phase 1"
mac_verify "Docker requirement and runtime if a later phase adopts it"
mac_verify "Slack Socket Mode connection after Phase 1 implementation"
mac_verify "launchd loading and automatic recovery after reboot in Phase 1"
mac_verify "power, sleep, FileVault, and reboot behavior"

printf '\nSummary: %d pass, %d warning, %d failure.\n' "${pass_count}" "${warn_count}" "${fail_count}"
printf '%s\n' "Phase 1 services are intentionally not implemented and are not counted as passing checks."

if (( fail_count > 0 )); then
  exit 1
fi
