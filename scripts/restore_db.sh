#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
REQUIRED_CONFIRMATION="restore-postgres"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [input_path]

Restore a PostgreSQL SQL dump into the compose postgres service.

Options via env:
  COMPOSE_FILE        Compose file path (default: docker-compose.prod.yml)
  POSTGRES_SERVICE    Postgres service name (default: postgres)
  BACKUP_INPUT_PATH   Input SQL file path (used if positional arg is omitted)
  CONFIRM_DB_RESTORE  Must equal '${REQUIRED_CONFIRMATION}' to allow restore
  RESET_BEFORE_RESTORE Set to 1 to drop and recreate public schema before restore
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

INPUT_PATH="${1:-${BACKUP_INPUT_PATH:-}}"
if [[ -z "${INPUT_PATH}" ]]; then
  echo "error: input path required (arg or BACKUP_INPUT_PATH)" >&2
  usage >&2
  exit 1
fi

if [[ ! -r "${INPUT_PATH}" ]]; then
  echo "error: input file not found or unreadable: ${INPUT_PATH}" >&2
  exit 1
fi

if [[ "${CONFIRM_DB_RESTORE:-}" != "${REQUIRED_CONFIRMATION}" ]]; then
  cat >&2 <<MSG
error: refusing restore by default.
set CONFIRM_DB_RESTORE=${REQUIRED_CONFIRMATION} to proceed.
MSG
  exit 1
fi

if [[ "${RESET_BEFORE_RESTORE:-0}" == "1" ]]; then
  docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
    sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"'
fi

# Restore runs in a single transaction and fails on first SQL error.
docker compose -f "${COMPOSE_FILE}" exec -T "${POSTGRES_SERVICE}" \
  sh -lc 'psql -1 -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "${INPUT_PATH}"

echo "restore complete from: ${INPUT_PATH}"
