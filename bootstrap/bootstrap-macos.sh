#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
BREWFILE="${REPO_ROOT}/Brewfile"

if [[ ! -f "${BREWFILE}" || ! -e "${REPO_ROOT}/.git" ]]; then
  printf '%s\n' "ERROR: run this script from a complete Git clone of the AI Hub repository." >&2
  exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf '%s\n' "ERROR: bootstrap-macos.sh supports macOS only." >&2
  printf '%s\n' "[MAC-VERIFY] Run the bootstrap on the production Mac mini." >&2
  exit 2
fi

printf '%s\n' "Phase 1 macOS bootstrap"

if ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
  printf '%s\n' "ERROR: Xcode Command Line Tools are required." >&2
  printf '%s\n' "Run 'xcode-select --install', complete the installer, then rerun this script." >&2
  printf '%s\n' "[MAC-VERIFY] Xcode Command Line Tools installation." >&2
  exit 2
fi

if ! command -v brew >/dev/null 2>&1; then
  printf '%s\n' "ERROR: Homebrew is required but was not found." >&2
  printf '%s\n' "Install it from https://brew.sh, review the installer, then rerun this script." >&2
  printf '%s\n' "This repository intentionally does not execute a remote installer automatically." >&2
  printf '%s\n' "[MAC-VERIFY] Homebrew installation and shell PATH on the production Mac mini." >&2
  exit 2
fi

printf '%s\n' "Installing the version-controlled Homebrew baseline..."
brew bundle --file "${BREWFILE}"

printf '%s\n' "Synchronizing the locked Phase 1 Python environment..."
cd -- "${REPO_ROOT}"
uv sync --locked --dev

"${SCRIPT_DIR}/init-workspace.sh"

printf '%s\n' "Phase 1 bootstrap completed."
printf '%s\n' "Next: configure .env and active registries, then run 'uv run --locked --no-dev ai-hub check-config'."
printf '%s\n' "Migrate storage and install launchd explicitly only after configuration passes."
printf '%s\n' "[MAC-VERIFY] Validate all installed tools and bootstrap output on the production Mac mini."
