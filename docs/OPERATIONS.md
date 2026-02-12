# Operations Runbook

## Scope
This runbook covers production operations for deployments using `docker-compose.prod.yml`, with PostgreSQL running in the `postgres` service.

## Prerequisites
- Docker and Docker Compose plugin are installed on the host.
- `cosign` is installed on the host.
- Production environment variables are available to Compose (for example via `.env`).
- `.env` contains `AGENT_HUB_IMAGE` pinned to an immutable digest from `.github/workflows/image.yml` (for example `ghcr.io/<owner>/<repo>@sha256:<digest>`).
- `.env` contains `AGENT_HUB_COSIGN_CERTIFICATE_IDENTITY_REGEX` and `AGENT_HUB_COSIGN_CERTIFICATE_OIDC_ISSUER` for keyless cosign verification trust policy.
- `.env` contains `POSTGRES_IMAGE` and `PROMETHEUS_IMAGE` pinned to immutable digests.
- `.env` contains `AGENT_HUB_GITHUB_WEBHOOK_SECRET`, `AGENT_HUB_METRICS_BEARER_TOKEN`, and hardened production auth settings (`AGENT_HUB_REQUIRE_API_KEY=1`, `AGENT_HUB_AUTH_REQUIRE_ROLES=1`, `AGENT_HUB_AUTH_REQUIRE_READS=1`, `AGENT_HUB_ALLOW_LOCAL_REPO_PATHS=0`, `AGENT_HUB_METRICS_REQUIRE_TOKEN=1`).
- If `AGENT_HUB_RATE_LIMIT_TRUST_PROXY_HEADERS=1`, `.env` also contains `AGENT_HUB_TRUSTED_PROXY_IPS` with explicit proxy source IPs.
- You can run `docker compose -f docker-compose.prod.yml ps` successfully.

## First Deploy
1. Update `.env` with release image digests from CI/registry:
- `AGENT_HUB_IMAGE=ghcr.io/<owner>/<repo>@sha256:<digest>`
- `POSTGRES_IMAGE=<registry>/<image>@sha256:<digest>`
- `PROMETHEUS_IMAGE=<registry>/<image>@sha256:<digest>`
2. Run production preflight checks (env policy + compose config render).
```bash
make prod-preflight
```
3. Verify the app image keyless cosign signature.
```bash
bash scripts/verify_image_signature.sh
```
4. Take a database backup before migrations.
```bash
./scripts/backup_db.sh
```
5. Pull pinned service images.
```bash
docker compose -f docker-compose.prod.yml pull
```
6. Start database first.
```bash
docker compose -f docker-compose.prod.yml up -d postgres
```
7. Run database migrations before app rollout.
```bash
docker compose -f docker-compose.prod.yml run --rm app alembic upgrade head
```
The `make prod-db-upgrade` target performs an explicit Postgres readiness wait before running Alembic and requires `CONFIRM_DB_BACKUP=1`.
In production mode, application startup does not auto-create tables.
8. Start or update the full stack.
```bash
docker compose -f docker-compose.prod.yml up -d --no-build
```
9. Verify health and logs.
```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=200 app
```
10. Validate Prometheus scrape health.
```bash
docker compose -f docker-compose.prod.yml logs --tail=200 prometheus
```

Equivalent make commands:
```bash
make prod-preflight
make verify-image-signature
make prod-backup
CONFIRM_DB_BACKUP=1 make prod-deploy
```

## Rolling Update Basics
1. Update `.env` so `AGENT_HUB_IMAGE` points to the new release digest from CI.
2. Run production preflight checks (env policy + compose config render).
```bash
make prod-preflight
```
3. Verify the app image keyless cosign signature.
```bash
bash scripts/verify_image_signature.sh
```
4. Pull pinned service images.
```bash
docker compose -f docker-compose.prod.yml pull
```
5. Take a database backup before migrations.
```bash
./scripts/backup_db.sh
```
6. Apply migrations before replacing app containers when the release requires schema changes.
```bash
docker compose -f docker-compose.prod.yml run --rm app alembic upgrade head
```
7. Recreate app services with fresh images.
```bash
docker compose -f docker-compose.prod.yml up -d --no-deps --no-build app
```
8. Validate post-deploy health.
```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=200 app
```
9. Validate Prometheus scrape health.
```bash
docker compose -f docker-compose.prod.yml logs --tail=200 prometheus
```

Notes:
- With only one app replica, brief restart downtime is expected.
- For lower-risk updates, run at least two app replicas behind a load balancer and confirm readiness before draining old tasks.

## Migration Steps
1. Determine if the release includes Alembic migrations.
2. Take a DB backup before running migrations.
```bash
./scripts/backup_db.sh
```
3. Run migrations.
```bash
docker compose -f docker-compose.prod.yml run --rm app alembic upgrade head
```
4. Verify current migration revision.
```bash
docker compose -f docker-compose.prod.yml run --rm app alembic current
```
5. If rollback is required, prefer database restore from backup. Current Alembic downgrades are destructive and can drop schema objects.
```bash
CONFIRM_DB_RESTORE=restore-postgres ./scripts/restore_db.sh /var/backups/vibe_hub/<backup>.sql
```

## Database Backup
`./scripts/backup_db.sh` dumps the `postgres` service database from `docker-compose.prod.yml`.

Examples:
```bash
# Default: writes $HOME/.agent_hub/backups/postgres_<UTC timestamp>.sql
./scripts/backup_db.sh

# Explicit output file path
./scripts/backup_db.sh /var/backups/vibe_hub/prod_$(date -u +%Y%m%dT%H%M%SZ).sql

# Configure via env vars
COMPOSE_FILE=docker-compose.prod.yml POSTGRES_SERVICE=postgres BACKUP_OUTPUT_DIR=/var/backups/vibe_hub ./scripts/backup_db.sh
```

## Database Restore
`./scripts/restore_db.sh` restores a SQL backup into the running `postgres` service.

Safety defaults:
- Restore is blocked unless `CONFIRM_DB_RESTORE=restore-postgres` is set.
- Input path must exist and be readable.

Examples:
```bash
# Restore using positional path
CONFIRM_DB_RESTORE=restore-postgres ./scripts/restore_db.sh /var/backups/vibe_hub/prod_20260210T020001Z.sql

# Restore using env path
BACKUP_INPUT_PATH=/var/backups/vibe_hub/prod_20260210T020001Z.sql CONFIRM_DB_RESTORE=restore-postgres ./scripts/restore_db.sh

# Optional reset for restoring into an existing DB
CONFIRM_DB_RESTORE=restore-postgres RESET_BEFORE_RESTORE=1 ./scripts/restore_db.sh /var/backups/vibe_hub/prod_20260210T020001Z.sql
```

Recommended workflow:
1. Stop write traffic or place app in maintenance mode.
2. Take a fresh backup before restore.
3. Run restore.
4. Run migrations only if required by target backup/app version alignment.
5. Validate health checks and application smoke paths.

Restore notes:
- `restore_db.sh` executes `psql` with `-1 -v ON_ERROR_STOP=1` to run in one transaction and stop on the first SQL error.

## Incident Checklist
1. Declare incident owner and start time.
2. Freeze deploys and non-essential operational changes.
3. Capture current state:
```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=300 app
docker compose -f docker-compose.prod.yml logs --tail=300 postgres
```
4. Confirm scope and user impact (API errors, latency, DB saturation, queue buildup).
5. If data risk exists, immediately create backup.
```bash
./scripts/backup_db.sh
```
6. Apply the smallest safe mitigation (restart app, rollback release, restore DB).
7. Verify recovery with health checks and critical user flows.
8. Record timeline, root cause, and follow-up actions.
