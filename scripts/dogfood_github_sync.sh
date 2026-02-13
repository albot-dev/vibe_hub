#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TOKEN="${GITHUB_TOKEN:-${VIBE_HUB_GITHUB_TOKEN:-}}"
if [[ -z "${TOKEN}" ]]; then
  echo "error: set GITHUB_TOKEN or VIBE_HUB_GITHUB_TOKEN before running dogfood flow" >&2
  exit 1
fi

derive_default_repo() {
  local origin_url=""
  origin_url="$(git -C "${PROJECT_ROOT}" remote get-url origin 2>/dev/null || true)"
  if [[ "${origin_url}" =~ github.com[:/]([^/]+)/([^/.]+)(\.git)?$ ]]; then
    echo "${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    return 0
  fi
  return 1
}

DEFAULT_REPO="$(derive_default_repo || true)"
DOGFOOD_GITHUB_REPO="${DOGFOOD_GITHUB_REPO:-${DEFAULT_REPO}}"
if [[ -z "${DOGFOOD_GITHUB_REPO}" ]]; then
  echo "error: set DOGFOOD_GITHUB_REPO=<owner/repo>" >&2
  exit 1
fi

api_get_repo() {
  curl -fsS \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${DOGFOOD_GITHUB_REPO}"
}

if [[ "${DOGFOOD_CONFIRM:-0}" != "1" ]]; then
  echo "[dogfood] dry-run: validating token access for ${DOGFOOD_GITHUB_REPO}"
  api_get_repo >/dev/null
  echo "[dogfood] dry-run passed. Set DOGFOOD_CONFIRM=1 to run full PR sync flow."
  exit 0
fi

TMP_DIR="$(mktemp -d)"
PORT="$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"

API_KEY="dogfood-key"
JWT_SECRET="dogfood-jwt-secret-abcdefghijklmnopqrstuvwxyz-123456"
BASE_URL="http://127.0.0.1:${PORT}"
DB_PATH="${TMP_DIR}/dogfood.db"
WORKSPACES_DIR="${TMP_DIR}/workspaces"
SERVER_LOG="${TMP_DIR}/server.log"
REPO_URL_WITH_TOKEN="https://x-access-token:${TOKEN}@github.com/${DOGFOOD_GITHUB_REPO}.git"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

json_get() {
  local key="$1"
  python3 -c '
import json
import sys

key = sys.argv[1]
payload = json.load(sys.stdin)
value = payload
for part in key.split("."):
    if part.isdigit():
        value = value[int(part)]
    else:
        value = value[part]
print(value)
' "$key"
}

echo "[dogfood] applying migrations"
(
  cd "${PROJECT_ROOT}"
  AGENT_HUB_DATABASE_URL="sqlite:///${DB_PATH}" \
  uv run --extra dev alembic upgrade head >/dev/null
)

echo "[dogfood] starting API on ${BASE_URL}"
(
  cd "${PROJECT_ROOT}"
  GITHUB_TOKEN="${TOKEN}" \
  AGENT_HUB_DATABASE_URL="sqlite:///${DB_PATH}" \
  AGENT_HUB_REQUIRE_API_KEY=1 \
  AGENT_HUB_API_KEYS="${API_KEY}" \
  AGENT_HUB_AUTH_REQUIRE_ROLES=1 \
  AGENT_HUB_JWT_SECRET="${JWT_SECRET}" \
  AGENT_HUB_JOB_WORKER_ENABLED=0 \
  AGENT_HUB_ALLOW_LOCAL_REPO_PATHS=0 \
  AGENT_HUB_WORKSPACES="${WORKSPACES_DIR}" \
  AGENT_HUB_REQUIRE_TEST_CMD=0 \
  uv run uvicorn app.main:app --host 127.0.0.1 --port "${PORT}" >"${SERVER_LOG}" 2>&1
) &
SERVER_PID=$!

for _ in {1..80}; do
  if curl -fsS "${BASE_URL}/health/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
curl -fsS "${BASE_URL}/health/ready" >/dev/null

echo "[dogfood] issuing maintainer token"
AUTH_TOKEN="$(
  curl -fsS -X POST "${BASE_URL}/auth/token" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{"subject":"dogfood-user","role":"maintainer"}' \
    | json_get "access_token"
)"
AUTH_HEADERS=(-H "X-API-Key: ${API_KEY}" -H "Authorization: Bearer ${AUTH_TOKEN}" -H "Content-Type: application/json")

echo "[dogfood] creating project for ${DOGFOOD_GITHUB_REPO}"
PROJECT_PAYLOAD="$(
  DOGFOOD_GITHUB_REPO="${DOGFOOD_GITHUB_REPO}" REPO_URL_WITH_TOKEN="${REPO_URL_WITH_TOKEN}" python3 - <<'PY'
import json
import os

print(
    json.dumps(
        {
            "name": f"dogfood-{os.environ['DOGFOOD_GITHUB_REPO'].replace('/', '-')}",
            "repo_url": os.environ["REPO_URL_WITH_TOKEN"],
            "default_branch": os.environ.get("DOGFOOD_BASE_BRANCH", "main"),
        }
    )
)
PY
)"
PROJECT_ID="$(
  curl -fsS -X POST "${BASE_URL}/projects" \
    "${AUTH_HEADERS[@]}" \
    -d "${PROJECT_PAYLOAD}" \
    | json_get "id"
)"

curl -fsS -X POST "${BASE_URL}/projects/${PROJECT_ID}/bootstrap" "${AUTH_HEADERS[@]}" -d '{}' >/dev/null
curl -fsS -X PATCH "${BASE_URL}/projects/${PROJECT_ID}/policy" "${AUTH_HEADERS[@]}" -d '{"auto_merge":false}' >/dev/null

echo "[dogfood] creating objective + local autopilot PR"
curl -fsS -X POST "${BASE_URL}/projects/${PROJECT_ID}/objectives" \
  "${AUTH_HEADERS[@]}" \
  -d '{"objective":"Dogfood GitHub sync path with a real branch and PR metadata","max_work_items":1,"created_by":"dogfood"}' >/dev/null
curl -fsS -X POST "${BASE_URL}/projects/${PROJECT_ID}/autopilot/run" \
  "${AUTH_HEADERS[@]}" \
  -d '{"max_items":1}' >/dev/null

PR_ID="$(
  curl -fsS "${BASE_URL}/projects/${PROJECT_ID}/pull-requests" \
  | json_get "0.id"
)"
SOURCE_BRANCH="$(
  curl -fsS "${BASE_URL}/projects/${PROJECT_ID}/pull-requests" \
  | json_get "0.source_branch"
)"

WORKSPACE_PATH="${WORKSPACES_DIR}/project-${PROJECT_ID}"
echo "[dogfood] pushing source branch ${SOURCE_BRANCH}"
git -C "${WORKSPACE_PATH}" push origin "${SOURCE_BRANCH}" >/dev/null

echo "[dogfood] syncing local PR to GitHub"
SYNC_RESPONSE="$(
  curl -fsS -X POST "${BASE_URL}/projects/${PROJECT_ID}/pull-requests/${PR_ID}/github/sync" \
    "${AUTH_HEADERS[@]}" \
    -d '{"status_context":"agent-hub/dogfood","status_description":"Dogfood sync validation"}'
)"
GH_PR_NUMBER="$(printf '%s' "${SYNC_RESPONSE}" | json_get "github_pr_number")"
GH_PR_URL="$(printf '%s' "${SYNC_RESPONSE}" | json_get "github_pr_url")"
echo "[dogfood] created GitHub PR #${GH_PR_NUMBER}: ${GH_PR_URL}"

echo "[dogfood] validating created PR is reachable"
curl -fsS \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${DOGFOOD_GITHUB_REPO}/pulls/${GH_PR_NUMBER}" >/dev/null

if [[ "${DOGFOOD_CLEANUP:-1}" == "1" ]]; then
  echo "[dogfood] cleanup: closing PR and deleting remote branch"
  curl -fsS -X PATCH \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${DOGFOOD_GITHUB_REPO}/pulls/${GH_PR_NUMBER}" \
    -d '{"state":"closed"}' >/dev/null
  git -C "${WORKSPACE_PATH}" push origin --delete "${SOURCE_BRANCH}" >/dev/null 2>&1 || true
fi

echo "[dogfood] success: real GitHub sync flow completed"
