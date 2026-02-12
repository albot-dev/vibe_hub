.PHONY: install test smoke run docker-build db-upgrade db-downgrade verify-image-signature prod-preflight prod-config prod-build prod-verify-image-signature prod-pull prod-up prod-down prod-ps prod-logs prod-db-upgrade prod-db-downgrade prod-deploy prod-backup prod-restore

PROD_COMPOSE = docker compose --env-file .env -f docker-compose.prod.yml

install:
	uv sync --extra dev

test:
	uv run --extra dev pytest -q

smoke:
	bash scripts/smoke.sh

run:
	uv run uvicorn app.main:app --reload

docker-build:
	docker build -t agent-hub:latest .

db-upgrade:
	uv run --extra dev alembic upgrade head

db-downgrade:
	uv run --extra dev alembic downgrade -1

verify-image-signature:
	bash scripts/verify_image_signature.sh

prod-preflight:
	bash scripts/validate_production_env.sh
	$(PROD_COMPOSE) config >/dev/null

prod-up:
	$(PROD_COMPOSE) up -d --no-build

prod-down:
	$(PROD_COMPOSE) down

prod-config:
	$(PROD_COMPOSE) config

prod-build:
	@echo "prod-build is deprecated for immutable image deploys; using prod-pull."
	$(MAKE) prod-pull

prod-verify-image-signature: verify-image-signature

prod-pull: prod-preflight prod-verify-image-signature
	$(PROD_COMPOSE) pull

prod-ps:
	$(PROD_COMPOSE) ps

prod-deploy: prod-pull
	$(PROD_COMPOSE) up -d --no-build postgres
	$(MAKE) prod-db-upgrade
	$(MAKE) prod-up

prod-logs:
	$(PROD_COMPOSE) logs -f app postgres prometheus

prod-db-upgrade:
	@if [ "$$CONFIRM_DB_BACKUP" != "1" ]; then \
		echo "error: CONFIRM_DB_BACKUP=1 is required before prod-db-upgrade. Run make prod-backup first."; \
		exit 1; \
	fi
	$(PROD_COMPOSE) up -d postgres
	$(PROD_COMPOSE) exec -T postgres sh -lc 'until pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"; do sleep 1; done'
	$(PROD_COMPOSE) run --rm app alembic upgrade head

prod-db-downgrade:
	$(PROD_COMPOSE) run --rm app alembic downgrade -1

prod-backup:
	bash scripts/backup_db.sh

prod-restore:
	bash scripts/restore_db.sh
