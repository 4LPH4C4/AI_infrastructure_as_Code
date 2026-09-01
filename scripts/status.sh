#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"

printf '%s\n' "NOT IMPLEMENTED: AI Hub runtime status belongs to Phase 1." >&2
printf '%s\n' "There is no Phase 0 service whose status can be reported. Repository: ${REPO_ROOT}" >&2
exit 3
