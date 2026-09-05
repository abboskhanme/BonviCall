# BonviCall. Nothing is installed on the host — everything runs in containers.
# Ports: panel 5190 · backend 8020 (/docs) · postgres 5443
#        (deliberately clear of BonviZvonki's 5180 / 8010 / 5433)

.PHONY: up down logs logs-backend logs-panel psql test test-server test-panel \
        lint migrate migrate-check migration contract types shell-backend build \
        android-build android-test android-lint android-dto \
        android-install android-release

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

logs-worker:
	docker compose logs -f worker

# T102. A throwaway database, created and dropped here, so verifying the head
# never involves typing `downgrade` at the development one. `-x db_url` is the
# ONLY way to point alembic somewhere else — POSTGRES_DB does not, because
# DATABASE_URL is one whole string, and that misreading emptied the dev
# database once already (migrations/env.py now refuses it).
migrate-head-check: ## Verify a clean database reaches head, on a scratch copy
	@set -e; \
	url=$$(grep '^DATABASE_URL=' .env | cut -d= -f2- | sed 's#/[^/]*$$#/bonvicall_headcheck#'); \
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-bonvicall} -d postgres -q \
		-c "DROP DATABASE IF EXISTS bonvicall_headcheck;" \
		-c "CREATE DATABASE bonvicall_headcheck;"; \
	docker compose run --rm backend alembic -x db_url="$$url" upgrade head; \
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-bonvicall} \
		-d bonvicall_headcheck -qtA \
		-c "SELECT 'tables: '||count(*) FROM information_schema.tables WHERE table_schema='public';" \
		-c "SELECT 'settings: '||count(*) FROM app_settings;"; \
	docker compose run --rm backend alembic -x db_url="$$url" downgrade base; \
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-bonvicall} -d postgres -q \
		-c "DROP DATABASE bonvicall_headcheck;"; \
	echo "head reached from empty, downgrade clean, scratch database removed"

job:               ## make job n=silence_detection — run one job once, now
	docker compose run --rm backend python -m src.worker --once $(n)

psql:
	docker compose exec postgres psql -U $${POSTGRES_USER:-bonvicall} -d $${POSTGRES_DB:-bonvicall}

# --- Tests -----------------------------------------------------------------
# Tests run against bonvicall_test, never the dev database (CONVENTIONS.md §13).
test: test-server test-panel

test-server:
	docker compose run --rm backend pytest -q

test-panel:
	docker compose run --rm panel npm run test

# Endpoints the contract declares and no client calls. Six things in this
# project were built, tested and unreachable — see the script's docstring.
# Runs on the host, not in a container: only the repository root can see the
# server, the panel and the app at once.
check-endpoints:   ## Report endpoints no client calls
	python3 scripts/find_unused_endpoints.py

lint:
	docker compose run --rm backend ruff check src tests conftest.py migrations scripts
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

# Install the debug APK on a connected handset. Set bonvicall.devHost in
# android/local.properties first — see docs/ON-DEVICE-TESTING.md.
android-install:
	cd android && ./gradlew installLegacy28Debug

# A signed release. Needs android/keystore.properties; without it the same
# command produces -unsigned.apk rather than failing (docs/APK-SIGNING.md).
android-release:
	cd android && ./gradlew assembleLegacy28Release assembleModern34Release

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

seed:              ## Create the first admin (idempotent; prints the password once)
	docker compose run --rm backend python -m src.seed

demo:              ## Seed a demo fleet: 5 agents, 5 devices, ~45 calls, real audio
	docker compose exec -T backend python scripts/demo_data.py
# The demo uploads one recording that is already older than
# retention.audio_months. Running the real job — not an UPDATE — is what turns
# it into the panel's "expired" state, and proves the job works while it is at it.
	$(MAKE) job n=audio_retention
# One storage snapshot, so the report has a point on its growth curve. The
# current totals are read live, so the page is right either way — this makes
# the *history* non-empty, which is the half only the nightly job can give.
	$(MAKE) job n=storage_usage

demo-reset:        ## Wipe operational data and re-seed the demo
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-bonvicall} \
		-d $${POSTGRES_DB:-bonvicall} -q < server/scripts/reset_demo.sql
# The SQL drops call_audio rows but cannot reach the blobs. Clearing them here
# keeps the two in step; leaving them would accumulate files that no row points
# at, which is exactly the state the retention job can never clean up.
	docker compose exec -T backend sh -c \
		'rm -rf $${AUDIO_STORAGE_PATH:-/data/audio}/* || true'
	$(MAKE) demo
