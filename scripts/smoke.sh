#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TMP_DIR="$(mktemp -d)"
PORT="$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"

API_KEY="smoke-key"
JWT_SECRET="smoke-jwt-secret-abcdefghijklmnopqrstuvwxyz-123456"
WEBHOOK_SECRET="smoke-webhook-secret"
BASE_URL="http://127.0.0.1:${PORT}"
DB_PATH="${TMP_DIR}/smoke.db"
REMOTE_REPO="${TMP_DIR}/remote.git"
SEED_REPO="${TMP_DIR}/seed-repo"
WORKSPACES_DIR="${TMP_DIR}/workspaces"
SERVER_LOG="${TMP_DIR}/server.log"

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

assert_eq() {
  local expected="$1"
  local actual="$2"
  local label="$3"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "assertion failed: ${label}; expected='${expected}' actual='${actual}'" >&2
    exit 1
  fi
}

echo "[smoke] creating temp git repository"
git init --bare "${REMOTE_REPO}" >/dev/null
mkdir -p "${SEED_REPO}"
git -C "${SEED_REPO}" init -b main >/dev/null
git -C "${SEED_REPO}" config user.name "Smoke Bot"
git -C "${SEED_REPO}" config user.email "smoke@example.local"
cat > "${SEED_REPO}/README.md" <<'EOF'
# Smoke Repository
EOF
git -C "${SEED_REPO}" add README.md
git -C "${SEED_REPO}" commit -m "chore: seed repository" >/dev/null
git -C "${SEED_REPO}" remote add origin "${REMOTE_REPO}"
git -C "${SEED_REPO}" push -u origin main >/dev/null

echo "[smoke] applying migrations"
(
  cd "${PROJECT_ROOT}"
  AGENT_HUB_DATABASE_URL="sqlite:///${DB_PATH}" \
  uv run --extra dev alembic upgrade head >/dev/null
)

echo "[smoke] starting API on ${BASE_URL}"
(
  cd "${PROJECT_ROOT}"
  AGENT_HUB_DATABASE_URL="sqlite:///${DB_PATH}" \
  AGENT_HUB_REQUIRE_API_KEY=1 \
  AGENT_HUB_API_KEYS="${API_KEY}" \
  AGENT_HUB_AUTH_REQUIRE_ROLES=1 \
  AGENT_HUB_JWT_SECRET="${JWT_SECRET}" \
  AGENT_HUB_GITHUB_WEBHOOK_SECRET="${WEBHOOK_SECRET}" \
  AGENT_HUB_JOB_WORKER_ENABLED=0 \
  AGENT_HUB_ALLOW_LOCAL_REPO_PATHS=1 \
  AGENT_HUB_WORKSPACES="${WORKSPACES_DIR}" \
  uv run uvicorn app.main:app --host 127.0.0.1 --port "${PORT}" >"${SERVER_LOG}" 2>&1
) &
SERVER_PID=$!

for _ in {1..60}; do
  if curl -fsS "${BASE_URL}/health/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
curl -fsS "${BASE_URL}/health/ready" >/dev/null

echo "[smoke] issuing maintainer token"
TOKEN="$(
  curl -fsS -X POST "${BASE_URL}/auth/token" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{"subject":"smoke-user","role":"maintainer"}' \
    | json_get "access_token"
)"

AUTH_HEADERS=(-H "X-API-Key: ${API_KEY}" -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json")

echo "[smoke] creating local-repo project"
PROJECT_ID="$(
  curl -fsS -X POST "${BASE_URL}/projects" \
    "${AUTH_HEADERS[@]}" \
    -d "{\"name\":\"smoke-local-project\",\"repo_url\":\"${REMOTE_REPO}\",\"default_branch\":\"main\"}" \
    | json_get "id"
)"

echo "[smoke] bootstrapping agents and validating lifecycle endpoints"
curl -fsS -X POST "${BASE_URL}/projects/${PROJECT_ID}/bootstrap" "${AUTH_HEADERS[@]}" -d '{}' >/dev/null
AGENT_COUNT="$(
  curl -fsS "${BASE_URL}/projects/${PROJECT_ID}/agents" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))'
)"
assert_eq "4" "${AGENT_COUNT}" "bootstrap agent count"

NEW_AGENT_ID="$(
  curl -fsS -X POST "${BASE_URL}/projects/${PROJECT_ID}/agents" \
    "${AUTH_HEADERS[@]}" \
    -d '{"name":"Smoke Extra Coder","role":"coder","max_parallel_tasks":3,"capabilities":"extra throughput"}' \
    | json_get "id"
)"
UPDATED_STATUS="$(
  curl -fsS -X PATCH "${BASE_URL}/projects/${PROJECT_ID}/agents/${NEW_AGENT_ID}" \
    "${AUTH_HEADERS[@]}" \
    -d '{"status":"paused"}' \
    | json_get "status"
)"
assert_eq "paused" "${UPDATED_STATUS}" "agent update status"

echo "[smoke] creating objective and running autopilot once"
curl -fsS -X POST "${BASE_URL}/projects/${PROJECT_ID}/objectives" \
  "${AUTH_HEADERS[@]}" \
  -d '{"objective":"Improve smoke coverage; verify async job controls; validate webhook dedup","max_work_items":1,"created_by":"smoke"}' >/dev/null
RUN_PROCESSED="$(
  curl -fsS -X POST "${BASE_URL}/projects/${PROJECT_ID}/autopilot/run" \
    "${AUTH_HEADERS[@]}" \
    -d '{"max_items":1}' \
    | json_get "processed_items"
)"
assert_eq "1" "${RUN_PROCESSED}" "autopilot processed_items"

echo "[smoke] enqueue/cancel/retry job"
JOB_ID="$(
  curl -fsS -X POST "${BASE_URL}/projects/${PROJECT_ID}/jobs/autopilot" \
    "${AUTH_HEADERS[@]}" \
    -d '{"max_items":1,"requested_by":"smoke","max_attempts":2}' \
    | json_get "id"
)"

RETRY_CODE="$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE_URL}/projects/${PROJECT_ID}/jobs/${JOB_ID}/retry" "${AUTH_HEADERS[@]}")"
assert_eq "409" "${RETRY_CODE}" "retry on queued job"

CANCELED_STATUS="$(
  curl -fsS -X POST "${BASE_URL}/projects/${PROJECT_ID}/jobs/${JOB_ID}/cancel" \
    "${AUTH_HEADERS[@]}" \
    | json_get "status"
)"
assert_eq "canceled" "${CANCELED_STATUS}" "cancel job status"

RETRIED_STATUS="$(
  curl -fsS -X POST "${BASE_URL}/projects/${PROJECT_ID}/jobs/${JOB_ID}/retry" \
    "${AUTH_HEADERS[@]}" \
    | json_get "status"
)"
assert_eq "queued" "${RETRIED_STATUS}" "retry job status"

echo "[smoke] creating github-repo project for webhook mapping"
GH_PROJECT_ID="$(
  curl -fsS -X POST "${BASE_URL}/projects" \
    "${AUTH_HEADERS[@]}" \
    -d '{"name":"smoke-github-project","repo_url":"https://github.com/acme/smoke-repo.git","default_branch":"main"}' \
    | json_get "id"
)"
curl -fsS -X POST "${BASE_URL}/projects/${GH_PROJECT_ID}/bootstrap" "${AUTH_HEADERS[@]}" -d '{}' >/dev/null

WEBHOOK_BODY='{"action":"opened","repository":{"full_name":"acme/smoke-repo"},"issue":{"number":7,"title":"Webhook smoke objective"}}'
WEBHOOK_SIG="$(
  python3 - <<'PY'
import hashlib
import hmac

secret = "smoke-webhook-secret".encode("utf-8")
body = b'{"action":"opened","repository":{"full_name":"acme/smoke-repo"},"issue":{"number":7,"title":"Webhook smoke objective"}}'
print("sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest())
PY
)"

echo "[smoke] validating webhook processing and deduplication"
WEBHOOK_ACTION_1="$(
  curl -fsS -X POST "${BASE_URL}/webhooks/github" \
    -H "Content-Type: application/json" \
    -H "X-GitHub-Event: issues" \
    -H "X-GitHub-Delivery: smoke-delivery-1" \
    -H "X-Hub-Signature-256: ${WEBHOOK_SIG}" \
    -d "${WEBHOOK_BODY}" \
    | json_get "action"
)"
assert_eq "objective_created" "${WEBHOOK_ACTION_1}" "webhook first delivery action"

WEBHOOK_ACTION_2="$(
  curl -fsS -X POST "${BASE_URL}/webhooks/github" \
    -H "Content-Type: application/json" \
    -H "X-GitHub-Event: issues" \
    -H "X-GitHub-Delivery: smoke-delivery-1" \
    -H "X-Hub-Signature-256: ${WEBHOOK_SIG}" \
    -d "${WEBHOOK_BODY}" \
    | json_get "action"
)"
assert_eq "ignored" "${WEBHOOK_ACTION_2}" "webhook duplicate action"

METRICS="$(curl -fsS "${BASE_URL}/metrics")"
if ! grep -q "agent_hub_autopilot_jobs_stale_recovered_total" <<<"${METRICS}"; then
  echo "assertion failed: missing stale recovery metric" >&2
  exit 1
fi

echo "[smoke] success: end-to-end smoke flow passed"
