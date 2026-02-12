#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_ENV_FILE="${PROJECT_ROOT}/.env"
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [env_file]

Validate production .env safety checks used by deploy targets.

Options via env:
  ENV_FILE    Env file to load (default: ${DEFAULT_ENV_FILE})
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
  echo "hint: cp .env.example .env and set production-safe values." >&2
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
      add_error "line ${line_no}: expected KEY=VALUE entry"
      continue
    fi

    local var_name="${line%%=*}"
    local var_value="${line#*=}"

    var_name="${var_name%"${var_name##*[![:space:]]}"}"
    var_name="${var_name#"${var_name%%[![:space:]]*}"}"
    var_value="${var_value#"${var_value%%[![:space:]]*}"}"
    var_value="${var_value%"${var_value##*[![:space:]]}"}"

    if [[ ! "${var_name}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      add_error "line ${line_no}: invalid env var name: ${var_name}"
      continue
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

declare -a ERRORS=()

add_error() {
  ERRORS+=("$1")
}

require_non_empty() {
  local var_name="$1"
  local var_value="${!var_name:-}"
  if [[ -z "${var_value}" ]]; then
    add_error "required env var is empty or unset: ${var_name}"
  fi
}

require_exact_value() {
  local var_name="$1"
  local expected="$2"
  local actual="${!var_name:-}"
  if [[ "${actual}" != "${expected}" ]]; then
    add_error "${var_name} must be ${expected} (got: ${actual:-<unset>})"
  fi
}

require_no_placeholder() {
  local var_name="$1"
  local var_value="${!var_name:-}"
  if [[ "${var_value}" == *replace-with* ]]; then
    add_error "${var_name} must not use placeholder values containing 'replace-with'"
  fi
}

require_digest_pinned_image() {
  local var_name="$1"
  local var_value="${!var_name:-}"
  if [[ ! "${var_value}" =~ ^[^[:space:]]+@sha256:[A-Fa-f0-9]{64}$ ]]; then
    add_error "${var_name} must be digest pinned (expected <image>@sha256:<64-hex-digest>)"
  fi
}

validate_jwt_secret_length() {
  local secret="${AGENT_HUB_JWT_SECRET:-}"
  if (( ${#secret} < 32 )); then
    add_error "AGENT_HUB_JWT_SECRET must be at least 32 characters long"
  fi
}

validate_metrics_token_length() {
  local token="${AGENT_HUB_METRICS_BEARER_TOKEN:-}"
  if (( ${#token} < 24 )); then
    add_error "AGENT_HUB_METRICS_BEARER_TOKEN must be at least 24 characters long"
  fi
}

validate_proxy_header_trust_configuration() {
  local trust_headers="${AGENT_HUB_RATE_LIMIT_TRUST_PROXY_HEADERS:-0}"
  local trusted_proxy_ips="${AGENT_HUB_TRUSTED_PROXY_IPS:-}"

  if [[ "${trust_headers}" == "1" && -z "${trusted_proxy_ips}" ]]; then
    add_error "AGENT_HUB_TRUSTED_PROXY_IPS must be non-empty when AGENT_HUB_RATE_LIMIT_TRUST_PROXY_HEADERS=1"
  fi
}

validate_database_url() {
  local url="${AGENT_HUB_DATABASE_URL:-}"
  if [[ "${url}" != postgresql+psycopg://* ]]; then
    add_error "AGENT_HUB_DATABASE_URL must start with postgresql+psycopg://"
  fi

  local parse_status=0
  local -a parts=()
  mapfile -t parts < <(
    python3 - "${url}" <<'PY'
from urllib.parse import unquote, urlsplit
import sys

value = sys.argv[1]
parsed = urlsplit(value)

if not parsed.scheme or not parsed.netloc:
    raise ValueError("missing scheme or netloc")

username = "" if parsed.username is None else unquote(parsed.username)
database = parsed.path[1:] if parsed.path.startswith("/") else parsed.path
database = unquote(database) if database else ""
host = parsed.hostname or ""

print(parsed.scheme)
print(host)
print(username)
print(database)
PY
  ) || parse_status=$?

  if (( parse_status != 0 )); then
    add_error "AGENT_HUB_DATABASE_URL is not parseable as a SQLAlchemy postgresql URL"
    return
  fi

  local db_scheme="${parts[0]:-}"
  local db_host="${parts[1]:-}"
  local db_user="${parts[2]:-}"
  local db_name="${parts[3]:-}"

  if [[ "${db_scheme}" != "postgresql+psycopg" ]]; then
    add_error "AGENT_HUB_DATABASE_URL scheme must be postgresql+psycopg"
  fi

  if [[ "${db_host}" != "postgres" ]]; then
    add_error "AGENT_HUB_DATABASE_URL host must be postgres for production compose deploys"
  fi

  if [[ -n "${db_user}" && -n "${POSTGRES_USER:-}" && "${db_user}" != "${POSTGRES_USER}" ]]; then
    add_error "AGENT_HUB_DATABASE_URL username (${db_user}) must match POSTGRES_USER (${POSTGRES_USER})"
  fi

  if [[ -n "${db_name}" && -n "${POSTGRES_DB:-}" && "${db_name}" != "${POSTGRES_DB}" ]]; then
    add_error "AGENT_HUB_DATABASE_URL database (${db_name}) must match POSTGRES_DB (${POSTGRES_DB})"
  fi
}

load_env_file "${ENV_FILE}"

required_vars=(
  POSTGRES_IMAGE
  PROMETHEUS_IMAGE
  POSTGRES_DB
  POSTGRES_USER
  POSTGRES_PASSWORD
  AGENT_HUB_IMAGE
  AGENT_HUB_COSIGN_CERTIFICATE_IDENTITY_REGEX
  AGENT_HUB_COSIGN_CERTIFICATE_OIDC_ISSUER
  AGENT_HUB_APP_ENV
  AGENT_HUB_DATABASE_URL
  AGENT_HUB_REQUIRE_API_KEY
  AGENT_HUB_API_KEYS
  AGENT_HUB_AUTH_REQUIRE_ROLES
  AGENT_HUB_AUTH_REQUIRE_READS
  AGENT_HUB_JWT_SECRET
  AGENT_HUB_ALLOW_LOCAL_REPO_PATHS
  AGENT_HUB_GITHUB_WEBHOOK_SECRET
  AGENT_HUB_METRICS_REQUIRE_TOKEN
  AGENT_HUB_METRICS_BEARER_TOKEN
  AGENT_HUB_RATE_LIMIT_TRUST_PROXY_HEADERS
)

for var_name in "${required_vars[@]}"; do
  require_non_empty "${var_name}"
  require_no_placeholder "${var_name}"
done

require_digest_pinned_image "AGENT_HUB_IMAGE"
require_digest_pinned_image "POSTGRES_IMAGE"
require_digest_pinned_image "PROMETHEUS_IMAGE"

require_exact_value "AGENT_HUB_REQUIRE_API_KEY" "1"
require_exact_value "AGENT_HUB_AUTH_REQUIRE_ROLES" "1"
require_exact_value "AGENT_HUB_AUTH_REQUIRE_READS" "1"
require_exact_value "AGENT_HUB_ALLOW_LOCAL_REPO_PATHS" "0"
require_exact_value "AGENT_HUB_APP_ENV" "production"
require_exact_value "AGENT_HUB_METRICS_REQUIRE_TOKEN" "1"

validate_jwt_secret_length
validate_metrics_token_length
validate_proxy_header_trust_configuration
validate_database_url

if (( ${#ERRORS[@]} > 0 )); then
  echo "error: production env validation failed for ${ENV_FILE}" >&2
  for message in "${ERRORS[@]}"; do
    echo "- ${message}" >&2
  done
  exit 1
fi

echo "production env validation passed for ${ENV_FILE}"
