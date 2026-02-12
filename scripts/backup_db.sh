#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [output_path]

Create a PostgreSQL SQL dump from docker compose.

Options via env:
  COMPOSE_FILE       Compose file path (default: docker-compose.prod.yml)
  POSTGRES_SERVICE   Postgres service name (default: postgres)
  BACKUP_OUTPUT_PATH Output file path (used if positional arg is omitted)
  BACKUP_OUTPUT_DIR  Output directory when no path is provided (default: $HOME/.agent_hub/backups)
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

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker is not installed or not in PATH" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "error: docker compose plugin is not available" >&2
  exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "error: compose file not found: ${COMPOSE_FILE}" >&2
  exit 1
fi

OUTPUT_PATH="${1:-${BACKUP_OUTPUT_PATH:-}}"
if [[ -z "${OUTPUT_PATH}" ]]; then
  OUTPUT_DIR="${BACKUP_OUTPUT_DIR:-$HOME/.agent_hub/backups}"
  mkdir -p "${OUTPUT_DIR}"
  OUTPUT_PATH="${OUTPUT_DIR%/}/postgres_$(date -u +%Y%m%dT%H%M%SZ).sql"
fi

OUTPUT_DIR="$(dirname "${OUTPUT_PATH}")"
mkdir -p "${OUTPUT_DIR}"

TMP_FILE="$(mktemp "${OUTPUT_DIR}/.backup_tmp.XXXXXX.sql")"
trap 'rm -f "${TMP_FILE}"' EXIT

# Credentials are read from the postgres container environment.
docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
  sh -lc 'pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > "${TMP_FILE}"

mv "${TMP_FILE}" "${OUTPUT_PATH}"
trap - EXIT
chmod 600 "${OUTPUT_PATH}" 2>/dev/null || true

echo "backup complete: ${OUTPUT_PATH}"
