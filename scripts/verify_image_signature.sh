#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_ENV_FILE="${PROJECT_ROOT}/.env"
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [env_file]

Verify AGENT_HUB_IMAGE has a valid keyless cosign signature.

Options via env:
  ENV_FILE                                         Env file to load (default: ${DEFAULT_ENV_FILE})
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

if ! command -v cosign >/dev/null 2>&1; then
  cat >&2 <<'MSG'
error: cosign is not installed or not in PATH.
install cosign first, then rerun verification:
  https://docs.sigstore.dev/cosign/system_config/installation/
MSG
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "error: env file not found: ${ENV_FILE}" >&2
  echo "hint: cp .env.example .env and set AGENT_HUB_IMAGE + cosign trust settings." >&2
  exit 1
fi

load_env_file() {
  local file_path="$1"
  set -a
  # shellcheck disable=SC1090
  source "${file_path}"
  set +a
}

require_non_empty() {
  local var_name="$1"
  local var_value="${!var_name:-}"
  if [[ -z "${var_value}" ]]; then
    echo "error: required env var is empty or unset: ${var_name}" >&2
    exit 1
  fi
}

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
