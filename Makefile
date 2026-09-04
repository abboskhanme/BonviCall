# BonviCall. Nothing is installed on the host — everything runs in containers.
# Ports: panel 5190 · backend 8020 (/docs) · postgres 5443
#        (deliberately clear of BonviZvonki's 5180 / 8010 / 5433)

.PHONY: up down logs logs-backend logs-panel psql test test-server test-panel \
        lint migrate migrate-check migration contract types shell-backend build \
        android-build android-test android-lint android-dto

up:                ## Bring the stack up with hot reload
	docker compose up -d
	@echo "panel  http://localhost:5190"
	@echo "api    http://localhost:8020/docs"

down:              ## Stop. Does NOT delete data.
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

logs-panel:
	docker compose logs -f panel

psql:
	docker compose exec postgres psql -U $${POSTGRES_USER:-bonvicall} -d $${POSTGRES_DB:-bonvicall}

# --- Tests -----------------------------------------------------------------
# Tests run against bonvicall_test, never the dev database (CONVENTIONS.md §13).
test: test-server test-panel

test-server:
	docker compose run --rm backend pytest -q

test-panel:
	docker compose run --rm panel npm run test

lint:
	docker compose run --rm backend ruff check src tests conftest.py migrations
	docker compose run --rm panel npm run lint

# --- Migrations ------------------------------------------------------------
# One real Alembic history from the first commit. No create_all outside
# conftest.py, no COLUMN_PATCHES (CONVENTIONS.md §10).
migrate:
	docker compose exec backend alembic upgrade head

migration:         ## make migration m="what changed"
	docker compose exec backend alembic revision --autogenerate -m "$(m)"
	@echo "READ THE GENERATED FILE. autogenerate emits spurious DROPs."

# Models and migrations cannot drift: this must report no new operations.
# CI runs `make migrate` on an empty database and then `make migrate-check`.
migrate-check:
	docker compose run --rm backend alembic check

# --- Contract --------------------------------------------------------------
# Pydantic is the source of truth; contract/ is generated and committed.
# CI runs: make contract && git diff --exit-code contract/
contract:
	docker compose run --rm backend python -m src.contract_export

# Panel TypeScript types are GENERATED from contract/, never hand-written
# (CONVENTIONS.md §1). The panel container does not mount contract/, so this
# run adds it read-only rather than changing the service definition.
# CI runs: make contract types && git diff --exit-code contract/ panel/src/shared/api
types:
	docker compose run --rm -v $(PWD)/contract:/contract:ro panel npm run gen:types

# --- Android ---------------------------------------------------------------
# The ONE part of this project that does not run in a container. The Android
# SDK is a developer-machine tool: it needs ~2 GB of platforms and build-tools,
# an accepted licence and, for anything on a real phone, USB. Containerising it
# would buy reproducibility for a build nobody runs in CI yet. `local.properties`
# (gitignored) points Gradle at the SDK.
#
# Four artefacts: legacy28 / modern34 x debug / release (SPEC §7.2). BOTH
# flavours must build — targetSdk is what M0 measures, not what someone edits.
android-build:
	cd android && ./gradlew assemble

android-test:
	cd android && ./gradlew testLegacy28DebugUnitTest testModern34DebugUnitTest

android-lint:
	cd android && ./gradlew lint

# Kotlin DTOs are GENERATED from the device contract, never hand-written
# (CONVENTIONS.md §1, CONVENTIONS-CLIENT.md §5). A renamed field must be a
# compile error on 15 phones we cannot force-update, not a runtime null.
# CI runs: make contract android-dto && git diff --exit-code contract/ android/
android-dto:
	docker run --rm -u $$(id -u):$$(id -g) \
	  -v $(PWD)/contract:/contract:ro \
	  -v $(PWD)/android/app/src/main/kotlin:/out \
	  openapitools/openapi-generator-cli:v7.10.0 generate \
	  -i /contract/openapi-device-v1.json \
	  -g kotlin -o /out \
	  --global-property models,modelDocs=false,modelTests=false \
	  --additional-properties=packageName=uz.bonvi.call.data.remote.dto,modelPackage=uz.bonvi.call.data.remote.dto,serializationLibrary=moshi,enumPropertyNaming=UPPERCASE,sourceFolder=.

shell-backend:
	docker compose exec backend bash

# --- Demo data ------------------------------------------------------------
# Drives the real API, so a clean run is also a smoke test of the enrolment
# chain and the ingest path. Local stack only — it creates accounts with a
# password that is written down in the repo.

demo:              ## Seed a demo fleet: 5 agents, 5 devices, ~45 calls
	docker compose exec -T backend python scripts/demo_data.py

demo-reset:        ## Wipe operational data and re-seed the demo
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-bonvicall} \
		-d $${POSTGRES_DB:-bonvicall} -q < server/scripts/reset_demo.sql
	$(MAKE) demo
