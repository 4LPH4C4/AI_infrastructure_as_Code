#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
TEMPLATE_PATH="${SCRIPT_DIR}/com.macmini-ai-hub.service.plist.template"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf '%s\n' "ERROR: launchd plist generation is supported only on macOS." >&2
  printf '%s\n' "[MAC-VERIFY] Render and validate the plist on the production Mac mini." >&2
  exit 2
fi
if [[ ! -e "${REPO_ROOT}/.git" || ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
  printf '%s\n' "ERROR: repository root validation failed: ${REPO_ROOT}" >&2
  exit 2
fi
if [[ ! -f "${TEMPLATE_PATH}" ]]; then
  printf '%s\n' "ERROR: launchd template is missing: ${TEMPLATE_PATH}" >&2
  exit 2
fi

UV_EXECUTABLE="$(command -v uv || true)"
if [[ -z "${UV_EXECUTABLE}" || "${UV_EXECUTABLE}" != /* || ! -x "${UV_EXECUTABLE}" ]]; then
  printf '%s\n' "ERROR: uv must resolve to an absolute executable path." >&2
  exit 2
fi
UV_EXECUTABLE="$(cd -- "$(dirname -- "${UV_EXECUTABLE}")" && pwd -P)/$(basename -- "${UV_EXECUTABLE}")"
CODEX_EXECUTABLE="$(command -v codex || true)"
if [[ -z "${CODEX_EXECUTABLE}" || "${CODEX_EXECUTABLE}" != /* || ! -x "${CODEX_EXECUTABLE}" ]]; then
  printf '%s\n' "ERROR: codex must resolve to an absolute executable path." >&2
  exit 2
fi
CODEX_EXECUTABLE="$(cd -- "$(dirname -- "${CODEX_EXECUTABLE}")" && pwd -P)/$(basename -- "${CODEX_EXECUTABLE}")"
SERVICE_PATH="$(dirname -- "${CODEX_EXECUTABLE}"):$(dirname -- "${UV_EXECUTABLE}"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

STDOUT_LOG="${REPO_ROOT}/workspace/logs/ai-hub.stdout.log"
STDERR_LOG="${REPO_ROOT}/workspace/logs/ai-hub.stderr.log"

validate_xml_path() {
  local value="$1"
  local field_name="$2"
  if [[ "${value}" == *$'\n'* || "${value}" == *$'\r'* || "${value}" == *'&'* ||
        "${value}" == *'<'* || "${value}" == *'>'* || "${value}" == *'|'* ||
        "${value}" == *'\\'* ]]; then
    printf 'ERROR: %s contains characters unsafe for plist substitution.\n' "${field_name}" >&2
    exit 2
  fi
}

validate_xml_path "${UV_EXECUTABLE}" "uv executable path"
validate_xml_path "${CODEX_EXECUTABLE}" "Codex executable path"
validate_xml_path "${SERVICE_PATH}" "service PATH"
validate_xml_path "${REPO_ROOT}" "repository root"
validate_xml_path "${STDOUT_LOG}" "stdout log path"
validate_xml_path "${STDERR_LOG}" "stderr log path"

sed \
  -e "s|__UV_EXECUTABLE__|${UV_EXECUTABLE}|g" \
  -e "s|__SERVICE_PATH__|${SERVICE_PATH}|g" \
  -e "s|__REPOSITORY_ROOT__|${REPO_ROOT}|g" \
  -e "s|__STDOUT_LOG__|${STDOUT_LOG}|g" \
  -e "s|__STDERR_LOG__|${STDERR_LOG}|g" \
  "${TEMPLATE_PATH}"
