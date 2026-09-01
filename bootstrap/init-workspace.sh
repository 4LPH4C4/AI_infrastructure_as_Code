#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
WORKSPACE_ROOT="${REPO_ROOT}/workspace"

if [[ ! -e "${REPO_ROOT}/.git" ]]; then
  printf '%s\n' "ERROR: repository root could not be verified: ${REPO_ROOT}" >&2
  exit 2
fi

# Runtime state is private to the account running the hub.
umask 077

workspace_directories=(
  projects
  tasks
  memory
  indexes
  locks
  artifacts
  logs
)

mkdir -p -- "${WORKSPACE_ROOT}"
chmod 700 -- "${WORKSPACE_ROOT}"

for directory in "${workspace_directories[@]}"; do
  workspace_path="${WORKSPACE_ROOT}/${directory}"
  mkdir -p -- "${workspace_path}"
  chmod 700 -- "${workspace_path}"
done

printf '%s\n' "Workspace directories are ready under ${WORKSPACE_ROOT}."
printf '%s\n' "[MAC-VERIFY] Confirm ownership, permissions, and available disk space on the production Mac mini."
