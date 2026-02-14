#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_ENV_FILE="${PROJECT_ROOT}/.env"
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"
COSIGN_AUTO_INSTALL="${COSIGN_AUTO_INSTALL:-1}"
COSIGN_INSTALL_DIR="${COSIGN_INSTALL_DIR:-${PROJECT_ROOT}/.tools/bin}"
COSIGN_INSTALL_HELPER="${COSIGN_INSTALL_HELPER:-${PROJECT_ROOT}/scripts/install_cosign.sh}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [env_file]

Verify AGENT_HUB_IMAGE has a valid keyless cosign signature.

Options via env:
  ENV_FILE                                         Env file to load (default: ${DEFAULT_ENV_FILE})
  COSIGN_AUTO_INSTALL                              Auto-install local cosign when missing: 1/0 (default: ${COSIGN_AUTO_INSTALL})
  COSIGN_INSTALL_DIR                               Local install directory (default: ${COSIGN_INSTALL_DIR})
  COSIGN_INSTALL_HELPER                            Install helper script (default: ${COSIGN_INSTALL_HELPER})
  AGENT_HUB_IMAGE                                  Fully qualified image ref (must be digest pinned)
  AGENT_HUB_COSIGN_CERTIFICATE_IDENTITY_REGEX      Trusted certificate identity regex
  AGENT_HUB_COSIGN_CERTIFICATE_OIDC_ISSUER         Trusted OIDC issuer
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 1
fi

if [[ $# -eq 1 ]]; then
  ENV_FILE="$1"
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "error: env file not found: ${ENV_FILE}" >&2
  echo "hint: cp .env.example .env and set AGENT_HUB_IMAGE + cosign trust settings." >&2
  exit 1
fi

load_env_file() {
  local file_path="$1"
  local line=""
  local line_no=0

  while IFS= read -r line || [[ -n "${line}" ]]; do
    ((line_no += 1))
    line="${line#"${line%%[![:space:]]*}"}"

    if [[ -z "${line}" || "${line}" == \#* ]]; then
      continue
    fi

    if [[ "${line}" == export[[:space:]]* ]]; then
      line="${line#export}"
      line="${line#"${line%%[![:space:]]*}"}"
    fi

    if [[ "${line}" != *=* ]]; then
      echo "error: invalid env entry on line ${line_no}: expected KEY=VALUE format" >&2
      exit 1
    fi

    local var_name="${line%%=*}"
    local var_value="${line#*=}"

    var_name="${var_name%"${var_name##*[![:space:]]}"}"
    var_name="${var_name#"${var_name%%[![:space:]]*}"}"
    var_value="${var_value#"${var_value%%[![:space:]]*}"}"
    var_value="${var_value%"${var_value##*[![:space:]]}"}"

    if [[ ! "${var_name}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "error: invalid env var name on line ${line_no}: ${var_name}" >&2
      exit 1
    fi

    if [[ "${var_value}" =~ ^\"(.*)\"$ ]]; then
      var_value="${BASH_REMATCH[1]}"
    elif [[ "${var_value}" =~ ^\'(.*)\'$ ]]; then
      var_value="${BASH_REMATCH[1]}"
    fi

    printf -v "${var_name}" "%s" "${var_value}"
    export "${var_name}"
  done < "${file_path}"
}

require_non_empty() {
  local var_name="$1"
  local var_value="${!var_name:-}"
  if [[ -z "${var_value}" ]]; then
    echo "error: required env var is empty or unset: ${var_name}" >&2
    exit 1
  fi
}

ensure_cosign() {
  if command -v cosign >/dev/null 2>&1; then
    return
  fi

  if [[ "${COSIGN_AUTO_INSTALL}" != "1" ]]; then
    cat >&2 <<'MSG'
error: cosign is not installed or not in PATH.
Set COSIGN_AUTO_INSTALL=1 to bootstrap a local copy, or install cosign manually:
  https://docs.sigstore.dev/cosign/system_config/installation/
MSG
    exit 1
  fi

  if [[ ! -f "${COSIGN_INSTALL_HELPER}" ]]; then
    echo "error: cosign install helper not found: ${COSIGN_INSTALL_HELPER}" >&2
    exit 1
  fi

  echo "cosign not found in PATH; installing to ${COSIGN_INSTALL_DIR}" >&2
  COSIGN_INSTALL_DIR="${COSIGN_INSTALL_DIR}" bash "${COSIGN_INSTALL_HELPER}" >&2
  export PATH="${COSIGN_INSTALL_DIR}:${PATH}"

  if ! command -v cosign >/dev/null 2>&1; then
    echo "error: cosign install finished but cosign is still not in PATH" >&2
    exit 1
  fi
}

ensure_cosign
load_env_file "${ENV_FILE}"

require_non_empty "AGENT_HUB_IMAGE"
require_non_empty "AGENT_HUB_COSIGN_CERTIFICATE_IDENTITY_REGEX"
require_non_empty "AGENT_HUB_COSIGN_CERTIFICATE_OIDC_ISSUER"

if [[ "${AGENT_HUB_IMAGE}" != *@sha256:* ]]; then
  echo "error: AGENT_HUB_IMAGE must be pinned to a digest (expected *@sha256:<digest>)" >&2
  exit 1
fi

echo "verifying keyless cosign signature for ${AGENT_HUB_IMAGE}"
if ! cosign verify \
  --certificate-identity-regexp "${AGENT_HUB_COSIGN_CERTIFICATE_IDENTITY_REGEX}" \
  --certificate-oidc-issuer "${AGENT_HUB_COSIGN_CERTIFICATE_OIDC_ISSUER}" \
  "${AGENT_HUB_IMAGE}"; then
  echo "error: cosign signature verification failed for ${AGENT_HUB_IMAGE}" >&2
  exit 1
fi

echo "signature verification passed for ${AGENT_HUB_IMAGE}"
