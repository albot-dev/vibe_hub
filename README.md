# Agent Hub

Agent Hub is a GitHub-style backend built for autonomous software agents.
Humans provide high-level objectives; agents decompose, implement, validate, review, and merge work with policy controls.

## Production-Ready Baseline Included

- FastAPI API with typed schemas and SQLAlchemy models
- Git-backed execution engine (clone, branch, commit, merge)
- Pluggable provider layer (`rule_based`, optional `openai`)
- Automation policy controls (`auto_triage`, `auto_assign`, `auto_review`, `auto_merge`, approval/test gates)
- Per-request observability (`X-Request-ID`, latency logging)
- API-key protection for mutating endpoints
- Optional JWT auth with role enforcement (`admin`, `maintainer`, `viewer`)
- Async autopilot job queue with background worker
- GitHub sync endpoint for opening remote PRs + commit statuses
- Prometheus-compatible `/metrics` endpoint
- CI workflow (`.github/workflows/ci.yml`) with unit tests, smoke tests, and shell syntax checks
- Container build files (`Dockerfile`, `.dockerignore`) using pinned base image digest and lockfile-frozen dependency sync

## Core Architecture

- API: `app/main.py`
- DB setup/session: `app/db.py`
- Domain models: `app/models.py`
- Orchestration loop: `app/orchestration.py`
- Git workspace manager: `app/git_ops.py`
- Provider abstraction: `app/providers.py`
- Job queue + worker: `app/job_queue.py`, `app/job_worker.py`
- Runtime config: `app/config.py`
- Security/auth dependencies: `app/security.py`, `app/auth.py`, `app/permissions.py`
- Repo path validation: `app/repo_security.py`

## Environment Setup

Install prerequisites before running this project:

- `git`
- `python` 3.11+
- `uv`
- `cosign` (required for production signed-image verification)

Install `uv` (official installer):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

If `curl` is unavailable:

```bash
wget -qO- https://astral.sh/uv/install.sh | sh
```

Alternative install methods:

```bash
brew install uv
pipx install uv
```

If you see `zsh: command not found: uv`, your `PATH` likely does not include `~/.local/bin`.
Add it and reload your shell:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Verify:

```bash
uv --version
python3 --version
```

Install `cosign` using the official instructions:
`https://docs.sigstore.dev/cosign/system_config/installation/`

Common setup errors:

- `zsh: command not found: uv`:
  - install `uv` and ensure `~/.local/bin` is in `PATH` (see commands above)
- `error: Failed to spawn: alembic`:
  - install/sync dev dependencies:
    ```bash
    uv sync --extra dev
    ```
  - then rerun:
    ```bash
    make db-upgrade
    # or
    make smoke
    ```

## Quickstart (Local)

```bash
uv sync --extra dev
uv run uvicorn app.main:app --reload
```

Open API docs at `http://127.0.0.1:8000/docs`.

## Optional LLM Provider (OpenAI)

```bash
uv sync --extra dev --extra llm
export AGENT_HUB_PROVIDER=openai
export OPENAI_API_KEY=your_key_here
```

## Security Configuration

To require API keys for write operations (`POST`, `PATCH` endpoints):

```bash
export AGENT_HUB_REQUIRE_API_KEY=1
export AGENT_HUB_API_KEYS=key_one,key_two
```

Use either header:

- `X-API-Key: key_one`
- `Authorization: Bearer key_one`

To enforce bearer-role checks on all write endpoints:

```bash
export AGENT_HUB_AUTH_REQUIRE_ROLES=1
export AGENT_HUB_JWT_SECRET=replace-with-strong-32-plus-char-secret
```

Issue a JWT (requires API key mode enabled):

```bash
curl -sX POST http://127.0.0.1:8000/auth/token \
  -H 'content-type: application/json' \
  -H 'X-API-Key: key_one' \
  -d '{"subject":"ci-bot","role":"maintainer"}'
```

## Runtime Configuration

- `AGENT_HUB_APP_ENV`: environment label (`development`, `staging`, `production`)
- `AGENT_HUB_LOG_LEVEL`: logging level (default: `INFO`)
- `AGENT_HUB_DATABASE_URL`: SQLAlchemy DB URL (default: `sqlite:///./agent_hub.db`)
- `AGENT_HUB_COSIGN_CERTIFICATE_IDENTITY_REGEX`: trusted regex for keyless image signing certificate identity
- `AGENT_HUB_COSIGN_CERTIFICATE_OIDC_ISSUER`: trusted OIDC issuer for keyless image signing certificates
- `AGENT_HUB_REQUIRE_API_KEY`: require API keys on mutating endpoints (`0` default)
- `AGENT_HUB_API_KEYS`: comma-separated API keys
- `AGENT_HUB_AUTH_REQUIRE_ROLES`: require bearer JWT role checks on mutating endpoints (`0` default)
- `AGENT_HUB_AUTH_REQUIRE_READS`: require bearer JWT on read endpoints (`0` default)
- `AGENT_HUB_JWT_SECRET`: HS256 secret for JWT verification/issuance
- `AGENT_HUB_JWT_TTL_SECONDS`: token lifetime in seconds (default: `3600`)
- `AGENT_HUB_WORKSPACES`: directory for git execution workspaces (default: `.agent_workspaces`)
- `AGENT_HUB_ALLOW_LOCAL_REPO_PATHS`: allow local repo paths (`1` default, must be `0` in production)
- `AGENT_HUB_ALLOWED_LOCAL_REPO_ROOT`: optional root path restriction for local repos
- `AGENT_HUB_GIT_COMMAND_TIMEOUT_SEC`: git command timeout (default: `60`)
- `AGENT_HUB_GIT_COMMAND_RETRIES`: retries for transient git failures (default: `1`)
- `AGENT_HUB_JOB_WORKER_ENABLED`: enable background job worker (`1` default)
- `AGENT_HUB_JOB_WORKER_POLL_INTERVAL_SEC`: worker poll interval seconds (default: `1.0`)
- `AGENT_HUB_JOB_STALE_TIMEOUT_SEC`: stale `running` job timeout in seconds before recovery (default: `900`)
- `AGENT_HUB_PROVIDER`: provider key (`rule_based`, `openai`)
- `AGENT_HUB_PROVIDER_FALLBACK`: fallback to `rule_based` if provider init fails (`1` default)
- `AGENT_HUB_OPENAI_MODEL`: model for `openai` provider (default: `gpt-4.1-mini`)
- `AGENT_HUB_OPENAI_TIMEOUT_SEC`: OpenAI timeout seconds (default: `45`)
- `AGENT_HUB_TEST_CMD`: optional validation command run in workspace
- `AGENT_HUB_AUTO_PUSH`: push branch/default branch after merge (`0` default)
- `AGENT_HUB_RATE_LIMIT_ENABLED`: enable in-memory rate limiting for write endpoints (`0` default)
- `AGENT_HUB_RATE_LIMIT_REQUESTS_PER_MINUTE`: write request limit per minute per client IP (default: `120`)
- `AGENT_HUB_RATE_LIMIT_TRUST_PROXY_HEADERS`: trust `X-Forwarded-For`/`X-Real-IP` for rate-limit keys (`0` default)
- `AGENT_HUB_TRUSTED_PROXY_IPS`: comma-separated proxy source IPs allowed to supply trusted forwarding headers
- `AGENT_HUB_GITHUB_WEBHOOK_SECRET`: GitHub webhook signing secret (validates `X-Hub-Signature-256`, required in production)
- `AGENT_HUB_METRICS_REQUIRE_TOKEN`: require bearer token on `/metrics` (`0` default)
- `AGENT_HUB_METRICS_BEARER_TOKEN`: bearer token used to access `/metrics`
- `AGENT_HUB_GITHUB_WEBHOOK_AUTO_ENQUEUE`: auto-enqueue autopilot job for `issues:opened` webhooks (`0` default)

When `AGENT_HUB_APP_ENV=production`, startup fails fast if critical safety controls are missing (API keys, write/read role auth, JWT secret, webhook secret, metrics auth token, non-sqlite DB, local-path repo access disabled, proxy allowlist when trusted headers are enabled, and placeholder `replace-with` secrets).

## GitHub Webhooks

`POST /webhooks/github` consumes raw GitHub webhook payloads and supports:

- `issues` with action `opened`: creates a project objective from issue title/body
- `issue_comment` with action `created`: enqueues a job when comment contains `/agent run`

Repository mapping is resolved via owner/repo matching (including `https://github.com/...`, `git@github.com:...`, and API URL forms).  
When `AGENT_HUB_GITHUB_WEBHOOK_SECRET` is configured, requests must include a valid `X-Hub-Signature-256` HMAC SHA-256 signature.  
In production mode (`AGENT_HUB_APP_ENV=production`), webhook secret configuration is mandatory.
Webhook requests also require `X-GitHub-Delivery`; deliveries are persisted and deduplicated by this id.  
Duplicate delivery ids return `{"action":"ignored","reason":"Duplicate delivery"}` and do not trigger side effects.

## API Flow

1. Create project: `POST /projects`
2. Bootstrap agents: `POST /projects/{project_id}/bootstrap`
3. Optional manual lifecycle management: `GET /projects/{project_id}/agents`, `POST /projects/{project_id}/agents`, `PATCH /projects/{project_id}/agents/{agent_id}`
4. Create objective: `POST /projects/{project_id}/objectives`
5. Tune policy: `PATCH /projects/{project_id}/policy`
6. Run synchronously: `POST /projects/{project_id}/autopilot/run`
7. Or queue async execution: `POST /projects/{project_id}/jobs/autopilot`
8. Cancel or retry async jobs: `POST /projects/{project_id}/jobs/{job_id}/cancel`, `POST /projects/{project_id}/jobs/{job_id}/retry`
9. Inspect: `/dashboard`, `/events`, `/work-items`, `/runs`, `/pull-requests`, `/projects/{id}/jobs`, `/metrics`
10. Sync local PR metadata to GitHub: `POST /projects/{id}/pull-requests/{pr_id}/github/sync`
11. Receive inbound GitHub webhooks: `POST /webhooks/github`

### Example

```bash
curl -sX POST http://127.0.0.1:8000/projects \
  -H 'content-type: application/json' \
  -d '{"name":"acme-api","repo_url":"https://github.com/acme/api","default_branch":"main"}'

curl -sX POST http://127.0.0.1:8000/projects/1/bootstrap

curl -sX POST http://127.0.0.1:8000/projects/1/objectives \
  -H 'content-type: application/json' \
  -d '{"objective":"Reduce flaky tests; improve auth edge-case coverage","max_work_items":2,"created_by":"system"}'

curl -sX PATCH http://127.0.0.1:8000/projects/1/policy \
  -H 'content-type: application/json' \
  -d '{"auto_merge":true,"min_review_approvals":1}'

curl -sX POST http://127.0.0.1:8000/projects/1/autopilot/run \
  -H 'content-type: application/json' \
  -d '{"max_items":2}'

curl -sX POST http://127.0.0.1:8000/projects/1/jobs/autopilot \
  -H 'content-type: application/json' \
  -d '{"max_items":2,"requested_by":"scheduler"}'

curl -sX POST http://127.0.0.1:8000/projects/1/jobs/1/retry
```

## Health and Metrics

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`
  - Includes `agent_hub_autopilot_jobs_stale_recovered_total`
  - Includes `agent_hub_autopilot_job_worker_loop_errors_total`
  - Includes `agent_hub_rate_limit_rejections_total`

## Development Commands

```bash
make install
make test
make smoke
make check-large-files
bash -n scripts/*.sh
make run
make docker-build
make db-upgrade
make prod-config
make prod-preflight
make verify-image-signature
make prod-pull
make prod-deploy
make prod-up
make prod-logs
make prod-down
make prod-backup
make prod-restore
```

## Smoke Test

Run `make smoke` to execute an end-to-end API smoke flow with temporary infrastructure:

- creates a temporary git repository and SQLite database
- applies migrations
- starts the API in secure mode (API key + JWT role enforcement)
- validates project/bootstrap/objective/autopilot/job-retry flows
- validates GitHub webhook signature handling + delivery-id deduplication

## Repository Hygiene

Run `make check-large-files` to fail fast if any tracked file exceeds 95 MB (GitHub push-safe guardrail).

## Production Compose Deployment

1. Create a production env file and set strong secrets.
```bash
cp .env.example .env
```
`.env` is ignored by git by default in this repository.
2. Edit `.env` values before first deploy:
- `POSTGRES_IMAGE` (pin to immutable digest)
- `PROMETHEUS_IMAGE` (pin to immutable digest)
- `POSTGRES_PASSWORD`
- `AGENT_HUB_DATABASE_URL` (keep in sync with `POSTGRES_*`; URL-encode password)
- `AGENT_HUB_IMAGE` (pin to immutable digest from `.github/workflows/image.yml`, example: `ghcr.io/<owner>/<repo>@sha256:<digest>`)
- `AGENT_HUB_COSIGN_CERTIFICATE_IDENTITY_REGEX` (match trusted workflow identity for your repo, e.g. `...@refs/(heads/main|tags/v.*)$`)
- `AGENT_HUB_COSIGN_CERTIFICATE_OIDC_ISSUER` (typically `https://token.actions.githubusercontent.com`)
- `AGENT_HUB_API_KEYS`
- `AGENT_HUB_AUTH_REQUIRE_READS`
- `AGENT_HUB_JWT_SECRET`
- `AGENT_HUB_BIND_HOST` (`127.0.0.1` recommended behind reverse proxy)
- `AGENT_HUB_GITHUB_WEBHOOK_SECRET` (required in production)
- `AGENT_HUB_METRICS_REQUIRE_TOKEN` (`1` in production)
- `AGENT_HUB_METRICS_BEARER_TOKEN` (required in production; used by Prometheus scrape auth)
- `AGENT_HUB_RATE_LIMIT_TRUST_PROXY_HEADERS` / `AGENT_HUB_TRUSTED_PROXY_IPS` (set only when running behind trusted proxies)
3. Run production preflight checks (env policy + compose config render).
```bash
make prod-preflight
```
4. Verify signature trust policy, then pull/start via the production deploy chain.
```bash
make verify-image-signature
make prod-backup
CONFIRM_DB_BACKUP=1 make prod-deploy
```
`make prod-deploy` runs production env preflight (including compose config render) and signature verification before pull, then applies migrations and starts services.
`make prod-db-upgrade` performs an explicit Postgres readiness wait before running Alembic and requires `CONFIRM_DB_BACKUP=1`.
When `AGENT_HUB_APP_ENV=production`, schema auto-create is disabled at startup; Alembic migrations are required.
5. Verify service health and logs.
```bash
make prod-ps
make prod-logs
```
Production compose hardening includes read-only root filesystem for the app service, dropped Linux capabilities, and `no-new-privileges`.

Image publishing workflow:
- `.github/workflows/image.yml`
- Runs on `main`, `v*` tags, and manual dispatch
- Publishes to GHCR and prints deploy-ready digest reference in the workflow summary

Signed-image deploy flow:
1. Pin `AGENT_HUB_IMAGE` to a release digest in `.env`.
2. Install `cosign` on the deploy host.
3. Set `AGENT_HUB_COSIGN_CERTIFICATE_IDENTITY_REGEX` and `AGENT_HUB_COSIGN_CERTIFICATE_OIDC_ISSUER`.
4. Run `make prod-preflight`.
5. Run `make verify-image-signature`.
6. Run `make prod-backup` then `CONFIRM_DB_BACKUP=1 make prod-deploy` (preflight and verification run again before image pull/up).

## Monitoring and Alerts

- Prometheus is included in `docker-compose.prod.yml`.
- Scrape target: `app:8000/metrics`.
- Self scrape: `prometheus:9090/metrics`.
- The app `/metrics` endpoint uses bearer token auth in production; Prometheus reads token from `.env` via `AGENT_HUB_METRICS_BEARER_TOKEN`.
- Prometheus config: `deploy/prometheus/prometheus.yml`
- Alert rules: `deploy/prometheus/alerts.yml`
- UI endpoint (bound locally): `http://127.0.0.1:${PROMETHEUS_PORT:-9090}`

## Operations Runbook

- Full operational procedures are in `docs/OPERATIONS.md`.
- Includes first deploy, update process, migration flow, backup/restore, and incident checklist.
- Backup command:
```bash
make prod-backup
```
- Default backup output path: `$HOME/.agent_hub/backups`.
- Restore command (explicit confirmation required):
```bash
CONFIRM_DB_RESTORE=restore-postgres BACKUP_INPUT_PATH=/path/to/backup.sql make prod-restore
```
- Optional restore reset for non-empty databases:
```bash
CONFIRM_DB_RESTORE=restore-postgres RESET_BEFORE_RESTORE=1 BACKUP_INPUT_PATH=/path/to/backup.sql make prod-restore
```

## Container Run

```bash
docker build -t agent-hub:latest .
docker run --rm -p 8000:8000 agent-hub:latest
```

## Remaining Work Before Large-Scale Production

- Expand migration coverage with forward-only data migrations
- Background job queue + worker autoscaling
- Multi-tenant authn/authz (JWT/OIDC + RBAC)
- GitHub/GitLab native PR/check integration
- Distributed tracing and centralized log shipping
- Stateful policy/audit management UI
