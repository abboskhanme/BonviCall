# BonviCall — Technical specification (release 1)

Author: plan-architect · Date: 2026-09-04 · Status: **build from this**

**Inputs, all binding:** `docs/REQUIREMENTS.md` (rev. 3 — UC-01…UC-29, N1…N42,
scope boundary §5), `docs/STACK.md` (decided 2026-09-04, not revisited here),
`docs/S1-RECORDING.md`, `docs/RISKS.md` (17 live risks), `docs/TASKS.md`
(150 rows), `docs/BUILD-VS-ADOPT.md`, `docs/ASSUMPTIONS.md`.

**Style and layering rules are NOT in this file.** `docs/CONVENTIONS.md`
(cross-cutting + server) and `docs/CONVENTIONS-CLIENT.md` (panel + Android),
both written in parallel by `plan-conventions`, own naming, file shape, import
rules, test layout and lint configuration. Where this document names a file
path it is naming an *architectural* boundary, not a style rule. On conflict
about style, CONVENTIONS wins; on conflict about behaviour, this file wins.

**The wire contract is code-first.** Pydantic v2 models are the source of
truth; the OpenAPI document and the generated Kotlin/TypeScript clients are
build artefacts committed under `/contract/`, and CI runs
`git diff --exit-code contract/` after regeneration so no wire change can land
invisibly. This supersedes `TASKS.md` T23, which specified schema-first.

**Reference implementation — read it before writing a line.**
`../BonviZvonki/services/backend/src/modules/calls/` is the closest existing
module and is the named reference for server module shape:
`domain/` (pure Python) → `application/` (services) → `infrastructure/`
(ORM models) → `presentation/` (FastAPI router) → `tests/`.
Also load-bearing as precedent:

| Concern | Copy the pattern from |
|---|---|
| Error envelope + `AppError` subclasses | `../BonviZvonki/services/backend/src/core/exceptions.py` and the two handlers in `main.py` |
| RBAC registry, `require_permission`, `require_any_permission` | `../BonviZvonki/services/backend/src/modules/users/domain/entities.py`, `core/deps.py` |
| Own-scope narrowing (`calls:read:own` passes, the *query* narrows) | the `CanReadCalls` dependency in `modules/calls/presentation/router.py` |
| Last-9-digit phone key + the SQL expression the index is built on | `modules/calls/domain/routing.py` (`phone_key`), `modules/clients/application/identity.py` (`phone_tail`) |
| ORM base, `UUIDMixin`, `TimestampMixin` | `core/database.py` |
| The "every model must be imported or FK resolution fails at runtime" trap | `core/models.py` — reproduce that module verbatim in shape |
| Panel route gate + nav | `../BonviZvonki/services/web/src/app/router.tsx` (`Protected`, `Gate`) |
| Authenticated audio with working seek | `../BonviZvonki/services/web/src/modules/calls/audio.ts` + `public/audio-sw.js` — **the Service Worker bridge is the only approach that gives native `Range` seek with an `Authorization` header. Port it.** |

`../CallSentry` is a **sketch, not a contract** (`docs/BRIEF.md`). Its wire
format is superseded in full by §4 of this document.

---

## 1. Goal

Bonvi's ~15 salespeople make ~15,000 calls a month from SIM cards in their
**personally owned** Android phones. Today that data belongs to MoyZvonki, which
deletes audio after 30 days. BonviCall replaces it: an Android app captures each
call made on a **registered company number**, harvests or records the audio,
queues it locally, and uploads to Bonvi's own server as soon as there is
connectivity; a web panel lets an admin run the rollout and a manager listen.

Release 1 is done when a call placed on a registered number appears in the panel
with correct direction, numbers, timestamps and duration — and, where the device
allows, playable audio — **exactly once**, within minutes, and still appears
after the phone was offline, rebooted, force-stopped or out of battery.

Three facts shape every decision below and are never traded away:
**identity is the registered number, not the device** (§3.3);
**the handset is the employee's, so anything outside the registered number is
never captured** (§4.5, §7.4); **audio comes from the handset's own recorder
first, the app's own recording second, behind an interface** (§7.3).

---

## 2. Architecture at a glance

```
Employee's Android phone                  Bonvi server (one host, Docker Compose)
┌────────────────────────────┐            ┌───────────────────────────────────────┐
│ service/  foreground svc   │  HTTPS     │  api        FastAPI  /api/device/v1   │
│   call state machine       │───────────▶│                      /api/v1          │
│ capture/  strategies       │  chunked   │                      /api/service/v1  │
│ data/local Room queue      │  upload    │  worker     APScheduler jobs          │
│ data/remote Retrofit + WS  │◀──────────▶│  postgres   16                        │
│ ui/enrolment …             │  WSS/FCM   │  audio      local FS behind interface │
└────────────────────────────┘            │  caddy      TLS, static panel, APK    │
                                          └───────────────────────────────────────┘
          ▲                                              ▲
          │ dials a number                               │ reports caller ID
┌─────────┴──────────────────┐                           │
│ callback receiver          │───────────────────────────┘
│ (office SIM, fleet-wide)   │   POST /api/service/v1/callback-events
└────────────────────────────┘
```

**Repository layout** (monorepo, one repo, three deliverables — TASKS T15):

```
/server        FastAPI. src/core/, src/modules/<module>/{domain,application,infrastructure,presentation,tests}/
/server/alembic
/panel         Vite + React + TS. src/app/router.tsx, src/modules/<module>/, src/shared/
/android       Single Gradle module `:app`, package uz.bonvi.call (§7.1)
/receiver      Callback receiver agent (§9.4) — small Kotlin app or Python daemon
/deploy        docker-compose.yml, Caddyfile, .env.example, Makefile
/docs
```

**Decisions taken here, once, so nobody improvises them:**

| # | Decision | Why, in one line |
|---|---|---|
| D-01 | Audio on the **local filesystem behind an `AudioStorage` interface**; no MinIO, no S3 in release 1 | `STACK.md` decided it; ~200 GB/year on one host with one tenant does not need object storage. **This overrides `TASKS.md` T15/T42, which still say MinIO** (§11.4) |
| D-02 | Panel has **no WebSocket**. TanStack Query polling (15 s on live screens, 60 s elsewhere) | One fewer moving part; nothing in UC-17…UC-27 needs sub-15-second panel latency |
| D-03 | Device↔server realtime is **WSS, with FCM data-message as wake-up fallback** | UC-16's 5 s bar needs a live socket; FCM covers a doze-killed socket |
| D-04 | Audio upload is a **custom 3-step resumable protocol** (session → chunk at offset → commit), not tus, not S3 multipart, not multipart/form-data | §4.5 |
| D-05 | `client_call_id` is a **UUIDv5 derived from call-log-stable facts**, not a random UUID | Survives reinstall without duplicating; §3.10 |
| D-06 | `targetSdk` 28 vs 34 is a **Gradle product flavour**, decided by M0, never a constant in application code | §7.2 |
| D-07 | The device API is **path-versioned** (`/api/device/v1`, never `/api/mobile/`) and a stale client is refused **only when its queue is empty** | N34; §4.3 |
| D-08 | Call attribution uses **`started_at` against the time-boxed assignment**; ordering and cursors use **server receipt time** | UC-07 vs N36 — two different questions, two different columns |
| D-09 | No currency, money or tariff accounting anywhere in release 1 | REQUIREMENTS §5.7; stated so nobody adds a "cost" column |
| D-10 | All timestamps are `timestamptz` stored in UTC; every business-day boundary is computed in **Asia/Tashkent** | N36, UC-27 |

---

## 3. Data model

Everything in this section goes into **one Alembic migration** (`TASKS.md` T19).
No later task adds a migration; corrections amend that revision until it is
merged, after which normal rules apply.

### 3.0 Column conventions

- Primary keys: `UUID` (`uuid4`) via `UUIDMixin`, except where a monotonic
  cursor is needed (`calls.seq`, `BIGSERIAL`).
- `created_at` / `updated_at` on every table via `TimestampMixin`
  (`TIMESTAMPTZ NOT NULL DEFAULT now()`).
- All datetimes are `TIMESTAMPTZ` and stored UTC (D-10). Any `DATE` column is a
  **Asia/Tashkent calendar date** and is named `*_date` to say so.
- Enums are PostgreSQL native enums created by the migration, declared in
  `domain/entities.py` as `StrEnum`, and bound with
  `SAEnum(X, name="...", values_callable=lambda e: [i.value for i in e])`
  (the BonviZvonki idiom — without `values_callable` SQLAlchemy stores the
  *member name*, which is upper-case, and the data becomes unreadable).
- Phone columns store the E.164 string; every matching key column is
  `CHAR(9)` and holds the **last 9 digits** (N37). Where the key is derivable
  it is a `GENERATED ALWAYS AS (...) STORED` column so it can never drift from
  its source.
- Money: **there is none.** No currency, no rounding policy, no tariff (D-09).
- Soft delete exists in exactly three places and nowhere else:
  `agents.archived_at`, `installations.status`, `call_audio.deleted_at`.
  **Calls are never deleted and never soft-deleted** (UC-26).

Required PostgreSQL extensions, created by the migration:
`btree_gist` (for the assignment exclusion constraint), `citext` (emails),
`pgcrypto` is **not** used — hashing is done in Python.

### 3.1 Enumerations — every value, exhaustively

| Enum (`pg` name) | Values | Notes |
|---|---|---|
| `user_role` | `admin`, `manager`, `sales`, `viewer` | `service` is **not** a user role — machine access is a `service_tokens` row (§3.2), because a machine has no password, no session and no nav |
| `call_direction` | `incoming`, `outgoing` | Deliberately not BonviZvonki's `inbound`/`outbound`: the export (§4.9) maps ours→theirs in one place |
| `call_disposition` | `answered`, `missed`, `rejected`, `no_answer` | UC-11's five classes are direction × disposition. `missed`/`rejected` are incoming-only, `no_answer` is outgoing-only — enforced by a CHECK |
| `call_type` | `internal`, `external`, `unknown` | `unknown` is the mandatory default when the directory is empty (UC-25) |
| `call_source` | `live_capture`, `call_log_recovery` | `call_log_recovery` ⇒ `audio_missing_reason = app_not_running` unless audio was still harvestable |
| `audio_missing_reason` | `pending_upload`, `not_expected`, `recording_route_unavailable`, `oem_recorder_off`, `no_permission`, `capture_returned_silence`, `app_not_running`, `upload_expired`, `queue_space_exhausted`, `attribution_failed` | UC-14 names six. **Four are added and each is justified in §3.9** — the enum is still closed, and no free text is ever accepted |
| `capture_route` | `oem_file_harvest`, `app_voice_recognition`, `app_voice_communication`, `app_mic`, `none` | S1 requires the route per call. `none` only with `has_audio = false` |
| `audio_codec` | `opus`, `aac_lc` | `aac_lc` is the decided fallback where the device has no usable Opus encoder (§7.6) |
| `audio_container` | `ogg`, `mp4` | pairs with the codec |
| `app_variant` | `legacy28`, `modern34` | D-06. Reported on every heartbeat so capture rate is measurable per variant, not only per model |
| `installation_status` | `pending`, `active`, `replaced`, `revoked`, `revoked_pending_confirmation` | UC-07, UC-08 |
| `verification_method` | `sim_msisdn`, `callback`, `admin_attested` | UC-04 + T142 |
| `verification_state` | `pending`, `matched`, `failed`, `expired`, `attested` | |
| `funnel_stage` | `invited`, `installed`, `permitted`, `number_verified`, `verified_by_admin`, `capturing`, `needs_assisted_install`, `install_disappeared`, `revoked` | UC-17. `verified_by_admin` is **visibly distinct** from `number_verified` (T142) |
| `capability` | `phone_state`, `call_log`, `microphone`, `contacts`, `notifications`, `call_phone`, `battery_exemption`, `storage_access`, `oem_autostart`, `foreground_service`, `oem_recorder`, `subscription_resolution` | One row per installation per capability |
| `capability_state` | `granted_working`, `granted_not_working`, `denied`, `denied_permanently`, `not_applicable`, `unknown` | `granted_not_working` is the OEM-permission-manager case UC-03 names explicitly |
| `command_kind` | `dial`, `config`, `logout`, `ping`, `recheck` | No `send_sms` — out of scope (§5.5) |
| `command_status` | `pending`, `sent`, `acknowledged`, `failed`, `expired` | |
| `command_failure_reason` | `device_offline`, `no_permission`, `os_refused`, `ack_timeout`, `discarded_stale`, `unsupported`, `busy` | |
| `alert_kind` | see §10.3 — **27 values**, exhaustive | The grouped rows in §10.3 (`permission_lost_*`) are three values, not one |
| `alert_severity` | `info`, `warning`, `critical` | |
| `audit_action` | see **§3.16** — 37 values, closed | Adding one later is a migration, which is the point |
| `actor_type` | `user`, `service`, `device`, `system` | |
| `directory_rule_kind` | `exact`, `prefix`, `suffix` | UC-25's `*700` is a `suffix` rule |
| `receiver_kind` | `gsm_gateway`, `android_receiver` | §9.4 |
| `receiver_status` | `up`, `degraded`, `down` | |
| `upload_status` | `open`, `committed`, `expired`, `aborted` | |
| `network_type` | `wifi`, `cellular`, `none` | |
| `enrolment_attempt_kind` | `code_redeem`, `msisdn_check`, `callback_start`, `callback_match`, `admin_attest`, `step_timing` | `step_timing` carries the per-screen durations that make N40 measurable by the product (§8) |
| `enrolment_outcome` | `ok`, `code_not_found`, `code_already_used`, `code_expired`, `code_revoked`, `number_mismatch`, `msisdn_empty`, `no_caller_id`, `timeout`, `receiver_down`, `already_bound`, `rejected` | |

### 3.2 Identity and access

**`users`** — panel accounts.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | PK |
| `email` | CITEXT | no | — | UNIQUE |
| `password_hash` | VARCHAR(255) | no | — | argon2id |
| `full_name` | VARCHAR(255) | no | — | |
| `role` | `user_role` | no | — | |
| `is_active` | BOOL | no | `true` | |
| `agent_id` | UUID FK→`agents.id` ON DELETE SET NULL | yes | — | **Required when `role='sales'`** — CHECK `(role <> 'sales' OR agent_id IS NOT NULL)`. Without it own-scope narrowing has nothing to narrow on |
| `must_change_password` | BOOL | no | `false` | set when an admin creates the account or resets the password; the panel forces a change before anything else loads |
| `password_changed_at` | TIMESTAMPTZ | yes | — | |
| `last_login_at` | TIMESTAMPTZ | yes | — | |
| `deactivated_at` | TIMESTAMPTZ | yes | — | paired with `is_active`; who and when is in `audit_log` |

Index: `UNIQUE(email)`, `ix_users_agent_id`,
`ix_users_active_admin` on `(role)` WHERE `is_active AND role = 'admin'`
— the index the "last active admin" guard counts on.

**A `user` is a login; an `agent` is a person whose calls are attributed.**
They are separate chains and must not be conflated:

- An **agent** can exist with no user at all — the system still records and
  attributes their calls. That is the normal case for a salesperson who never
  opens the panel, and it is the reason `agents` is a separate table (the same
  reasoning as `../BonviZvonki/.../agents/infrastructure/models.py`).
- A **user** with `role='sales'` must point at exactly one agent
  (`agent_id`), because that is what own-scope narrowing filters on (§4.1
  rule 1). `admin`, `manager` and `viewer` users have `agent_id = NULL`.
- Creating a user never creates an agent, and registering an agent + work number
  (§3.3, the identity chain the whole product hangs on) never creates a user.
  An admin does both, on two different screens, for two different reasons.

**`refresh_tokens`** — panel sessions. `id`, `user_id` FK CASCADE, `token_hash`
CHAR(64) UNIQUE (sha256 of the opaque token), `issued_at`, `expires_at`,
`revoked_at`, `replaced_by_id` self-FK, `ip` INET, `user_agent` VARCHAR(255).
Rotation on every refresh; **reuse of a rotated token revokes the whole chain
for that user and raises `credential_replay`** (N24 applied to the panel too).

**`service_tokens`** — the machine role (UC-29). `id`, `name` UNIQUE,
`token_hash` CHAR(64) UNIQUE, `scopes` TEXT[] (only `export:read`,
`export:audio`, `callback:report` are accepted), `is_active`, `expires_at`
nullable, `last_used_at`, `created_by` FK→users. A service token can never be
exchanged for a user session and never appears in `users`.

### 3.3 Agents, numbers and the time-boxed mapping

This is the part `TASKS.md` and `RISKS.md` both single out, and the part
BonviZvonki got wrong with a single `agents.phone` column.

**`agents`** — a salesperson. Deliberately **has no phone column.**

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `full_name` | VARCHAR(255) | no | indexed |
| `employee_code` | VARCHAR(32) | yes | UNIQUE WHERE NOT NULL — the roster import key |
| `is_active` | BOOL | no | default `true` — "left the company" |
| `archived_at` | TIMESTAMPTZ | yes | "removed from the system"; **never delete an agent with calls** (the BonviZvonki lesson, `agents/infrastructure/models.py`) |
| `hired_at` | DATE | yes | |
| `color` | VARCHAR(16) | no | default `#6366f1`, avatar fallback |
| `note` | TEXT | yes | |

**`registered_numbers`** — a company line, independent of who holds it.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `e164` | VARCHAR(20) | no | `+998901112233`, validated server-side |
| `phone_key` | CHAR(9) | no | `GENERATED ALWAYS AS (right(regexp_replace(e164,'\D','','g'),9)) STORED`, **UNIQUE** — this is the uniqueness that matters (N37). A number typed in three formats is one row |
| `operator` | VARCHAR(32) | yes | `beeline`/`ucell`/`mobiuz`/`uzmobile`/`other` — free-form on purpose; it is a reporting axis for R19, not a control |
| `sim_owner` | VARCHAR(16) | no | `company` \| `employee` — R10: the panel must show which relationships are not Bonvi's to keep |
| `label` | VARCHAR(64) | yes | |
| `is_active` | BOOL | no | default `true` |

**`number_assignments`** — the time-boxed mapping (UC-07 **[constraint]**).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK |
| `number_id` | UUID FK→`registered_numbers` RESTRICT | no | |
| `agent_id` | UUID FK→`agents` RESTRICT | no | |
| `valid_from` | TIMESTAMPTZ | no | |
| `valid_to` | TIMESTAMPTZ | yes | NULL = open-ended |
| `created_by` | UUID FK→users | no | |
| `closed_by` | UUID FK→users | yes | |
| `note` | VARCHAR(255) | yes | |

Constraints and indexes — the non-obvious ones, with the reasoning:

```sql
-- Exactly one agent holds a number at any instant (UC-01 AC, UC-07).
-- An application-level check loses to two admins clicking at once;
-- this cannot, and it is the reason btree_gist is installed.
ALTER TABLE number_assignments
  ADD CONSTRAINT number_assignment_no_overlap
  EXCLUDE USING gist (
    number_id WITH =,
    tstzrange(valid_from, valid_to, '[)') WITH &&
  );

CHECK (valid_to IS NULL OR valid_to > valid_from);
CREATE INDEX ix_assignments_agent_range ON number_assignments (agent_id, valid_from DESC);
CREATE INDEX ix_assignments_number_range ON number_assignments (number_id, valid_from DESC);
```

**Attribution rule (D-08), stated once and referenced everywhere:** a call is
attributed to the assignment whose `[valid_from, valid_to)` contains
**`calls.started_at`** — the call's own start, after call-log reconciliation.
It is *not* the upload time and *not* the server receipt time: a call made
before a SIM handover must stay with agent A even if the old phone only comes
online a week later. Server receipt time (N36) is authoritative for **ordering
and cursors**, which is a different question (§3.10).

`calls.agent_id` and `calls.assignment_id` are resolved at ingest and **frozen**.
Rationale: a temporal join over 500k rows at p95 < 500 ms (UC-19) is avoidable
work, and — more important — history must not silently move when an admin edits
an assignment. When an assignment *is* edited, the `reattribute_calls` job
(§10.4) re-stamps the affected rows, writes one `audit_log` row per affected
assignment with the before/after counts, and raises an `info` alert. A silent
mass re-attribution is exactly the kind of change that destroys trust in a
performance report.

### 3.4 Enrolment

**`enrolment_codes`** — single-use, 24 h (UC-01).

`id`, `code` CHAR(8) UNIQUE (Crockford base32 alphabet, ambiguous characters
`I L O U` excluded — the code is read aloud and typed by a salesperson),
`number_id` FK, `agent_id` FK (frozen at issue), `issued_by` FK→users,
`expires_at` (issue + 24 h, configurable), `redeemed_at`, `redeemed_by_installation_id`
FK→installations SET NULL, `revoked_at`, `revoked_by`, `attempt_count` INT
default 0.
Index: `UNIQUE(code)`, `ix_codes_number_active` on `(number_id)` WHERE
`redeemed_at IS NULL AND revoked_at IS NULL`.
Redemption semantics: second redemption → **409** `enrolment_code_used`; past
`expires_at` → **410** `enrolment_code_expired`; both write an
`enrolment_attempts` row so they appear in the admin's list with a timestamp
(UC-01 AC).

**`enrolment_attempts`** — append-only, the funnel's evidence base.

`id`, `kind` `enrolment_attempt_kind`, `outcome` `enrolment_outcome`,
`code_id` FK nullable, `number_id` FK nullable, `installation_id` FK nullable,
`agent_id` FK nullable, `step` VARCHAR(32) nullable (`E1`…`E6`, §8),
`duration_ms` INT nullable (for `step_timing`), `detail` JSONB, `remote_ip` INET,
`app_version` VARCHAR(20), `device_model` VARCHAR(64), `created_at`.
Index: `(number_id, created_at DESC)`, `(installation_id, created_at DESC)`,
`(kind, outcome, created_at DESC)`.

**`devices`** — the handset, as reported. No hardware identifier is stored raw.

`id`, `manufacturer` VARCHAR(64), `model` VARCHAR(96), `marketing_name`
VARCHAR(96) nullable, `android_release` VARCHAR(16) (`"13"`), `api_level` INT,
`build_fingerprint_hash` CHAR(64) (sha256; UNIQUE) — change detection without
keeping an identifier that follows the employee, `first_seen_at`, `last_seen_at`.
Index: `UNIQUE(build_fingerprint_hash)`, `(manufacturer, model, api_level)`.

**`installations`** — one app installation bound to one registered number.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK; the app carries this in `X-Installation-Id` |
| `number_id` | UUID FK RESTRICT | no | |
| `agent_id` | UUID FK RESTRICT | no | frozen at bind time; the funnel and alerts name a person |
| `device_id` | UUID FK RESTRICT | no | |
| `status` | `installation_status` | no | default `pending` |
| `verification_method` | `verification_method` | yes | NULL until verified |
| `verified_at` | TIMESTAMPTZ | yes | |
| `attested_by` | UUID FK→users | yes | set only when `verification_method='admin_attested'` |
| `attest_reason` | VARCHAR(255) | yes | required when attested — an unexplained attestation is indistinguishable from a mistake |
| `bound_at` | TIMESTAMPTZ | yes | |
| `replaced_at` / `revoked_at` / `revoke_confirmed_at` | TIMESTAMPTZ | yes | |
| `revoke_pending_records` / `revoke_pending_bytes` | INT / BIGINT | yes | what was still queued when contact was lost (UC-08) |
| `credential_hash` | CHAR(64) | no | sha256 of the installation secret (N24) |
| `device_fingerprint_hash` | CHAR(64) | no | token binding, §4.2 |
| `token_version` | INT | no | default 1; incremented on revoke → all issued tokens die |
| `refresh_token_hash` | CHAR(64) | yes | current refresh token; rotation reuse ⇒ `credential_replay` |
| `app_version` / `app_variant` | VARCHAR(20) / `app_variant` | yes | |
| `sim_subscription_id` | INT | yes | the registered subscription, as the OS reports it |
| `sim_slot` | SMALLINT | yes | |
| `funnel_stage` | `funnel_stage` | no | default `invited`; maintained by the funnel job + event handlers (§10.4) |
| `funnel_changed_at` | TIMESTAMPTZ | no | |

```sql
-- UC-07: exactly one active installation per registered number, enforced
-- in the database because "the app is on two phones" is a data-integrity
-- failure that doubles every call, not a UI problem.
CREATE UNIQUE INDEX uq_installation_active_per_number
  ON installations (number_id) WHERE status = 'active';
CREATE INDEX ix_installations_agent ON installations (agent_id, status);
CREATE INDEX ix_installations_stage ON installations (funnel_stage, funnel_changed_at DESC);
```

**`number_verifications`** — one row per verification attempt (UC-04).

`id`, `installation_id` FK, `number_id` FK, `method` `verification_method`,
`state` `verification_state`, `started_at`, `expires_at` (started + 5 min),
`matched_event_id` FK→`callback_events` nullable, `failure_outcome`
`enrolment_outcome` nullable, `attested_by` FK→users nullable, `attest_reason`.
Index: `(number_id, state)` WHERE `state='pending'` — the callback matcher's
hot path; `(installation_id, started_at DESC)`.

**`callback_receivers`** — fleet-wide infrastructure (§9.4, T141).

`id`, `name`, `msisdn` VARCHAR(20), `kind` `receiver_kind`, `token_hash`
CHAR(64), `is_active`, `last_heartbeat_at`, `status` `receiver_status`,
`status_changed_at`, `note`. Health: heartbeat every 60 s; no heartbeat for
3 min → `degraded`; 5 min → `down` + **critical** alert
`callback_receiver_down`. If every active receiver is `down`, enrolment screen
E5 refuses to start a challenge and says so in Uzbek rather than letting an
agent dial into nothing.

**`callback_events`** — every inbound call the receiver saw.

`id`, `receiver_id` FK, `caller_e164` VARCHAR(20) nullable, `caller_key` CHAR(9)
nullable (generated from `caller_e164`), `cli_presented` BOOL,
`received_at` TIMESTAMPTZ (server receipt), `receiver_epoch_ms` BIGINT,
`matched_verification_id` FK nullable, `unmatched_reason` VARCHAR(32) nullable.
Index: `(caller_key, received_at DESC)`, `(receiver_id, received_at DESC)`.
Retention: 90 days, then deleted by the retention job — these are inbound call
records of employees' work numbers and have no value after the enrolment.

### 3.5 Calls

**`calls`** — the centre of the system. ~15,000 rows/month; designed and indexed
for 500,000 (UC-19).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | UUID | no | PK, server-generated |
| `seq` | BIGINT `GENERATED ALWAYS AS IDENTITY` | no | UNIQUE. Monotonic insert counter — the export cursor (§4.9). **`ALWAYS`, not `BIGSERIAL`**: an explicit insert is then an error rather than a silent hole in somebody's export |
| `client_call_id` | UUID | no | **UNIQUE.** The idempotency key (§3.10) |
| `installation_id` | UUID FK RESTRICT | no | which installation delivered it |
| `number_id` | UUID FK RESTRICT | no | the registered number the call happened on |
| `agent_id` | UUID FK RESTRICT | no | resolved via §3.3, frozen |
| `assignment_id` | UUID FK SET NULL | yes | which assignment produced the attribution — makes re-attribution auditable |
| `direction` | `call_direction` | no | |
| `disposition` | `call_disposition` | no | |
| `remote_number` | VARCHAR(32) | yes | NULL when the caller withheld the number |
| `remote_number_key` | CHAR(9) | yes | `GENERATED ALWAYS AS (CASE WHEN length(regexp_replace(coalesce(remote_number,''),'\D','','g')) >= 9 THEN right(regexp_replace(remote_number,'\D','','g'),9) END) STORED`. **NULL for short numbers on purpose** — a 4-digit extension as a "key" matches the tail of every long number (the BonviZvonki `phone_key` comment) |
| `contact_name` | VARCHAR(255) | yes | resolved on-device; decoration, never identity (L3) |
| `call_type` | `call_type` | no | default `unknown` |
| `started_at` | TIMESTAMPTZ | no | device time, call-log-reconciled |
| `answered_at` | TIMESTAMPTZ | yes | NULL ⇒ never a conversation (UC-09) |
| `ended_at` | TIMESTAMPTZ | yes | |
| `duration_sec` | INT | no | default 0; whole seconds, **truncated not rounded**, from the call log's `DURATION` |
| `ring_sec` | INT | yes | |
| `device_epoch_ms` | BIGINT | no | raw device clock at call start (N36) |
| `device_timezone` | VARCHAR(64) | no | IANA name |
| `clock_skew_sec` | INT | no | computed at receipt: `received_at − device_epoch_ms` corrected for transit |
| `received_at` | TIMESTAMPTZ | no | `default now()`. **Authoritative for ordering** |
| `sim_subscription_id` | INT | yes | the registered subscription only |
| `sim_slot` | SMALLINT | yes | |
| `source` | `call_source` | no | |
| `reconciled_with_call_log` | BOOL | no | default `false` |
| `command_id` | UUID FK SET NULL | yes | click-to-call linkage (UC-16) |
| `has_audio` | BOOL | no | default `false` — denormalised for the gap report's partial index |
| `audio_missing_reason` | `audio_missing_reason` | yes | |
| `audio_duration_mismatch` | BOOL | no | default `false`; set when the file's duration differs from `duration_sec` by > 2 s (UC-14) |
| `note` | TEXT | yes | free-text, `calls:note` only (§5.5 of the requirements) |
| `app_version` / `app_variant` | VARCHAR(20) / `app_variant` | no | denormalised so per-variant capture rate survives a later app upgrade |

**Four CHECK constraints, carrying five rules** — the two duration rules are one
constraint because they are one fact stated from both sides:

```sql
-- audio_reason_present — N5: a call without audio ALWAYS carries a reason, and
-- a call with audio never carries one. A constraint, not a convention, because
-- "100 % of calls" is the acceptance criterion.
CHECK ( (has_audio AND audio_missing_reason IS NULL)
     OR (NOT has_audio AND audio_missing_reason IS NOT NULL) );

-- direction_disposition — UC-11: the five classes are direction x disposition,
-- and the invalid combinations must be unrepresentable, not merely unused.
CHECK ( (direction = 'incoming' AND disposition IN ('answered','missed','rejected'))
     OR (direction = 'outgoing' AND disposition IN ('answered','no_answer')) );

-- answered_has_timestamp — UC-09: "answered" and "there is an answered_at"
-- are the same fact.
CHECK ( (disposition = 'answered') = (answered_at IS NOT NULL) );

-- answered_has_duration — UC-09/UC-11, both directions of one rule: zero calls
-- classified as answered that the call log shows with duration 0, and no
-- duration on a call nobody answered.
CHECK ( (disposition =  'answered' AND duration_sec > 0)
     OR (disposition <> 'answered' AND duration_sec = 0) );
```

Indexes — each one earns its place:

```sql
CREATE UNIQUE INDEX uq_calls_client_call_id ON calls (client_call_id);
CREATE UNIQUE INDEX uq_calls_seq            ON calls (seq);
CREATE INDEX ix_calls_cursor    ON calls (received_at DESC, id DESC);        -- default paging (§4.4)
CREATE INDEX ix_calls_agent     ON calls (agent_id, started_at DESC);        -- sales own-scope + agent filter
CREATE INDEX ix_calls_started   ON calls (started_at DESC, id DESC);         -- date-range filter + alt sort
CREATE INDEX ix_calls_number    ON calls (number_id, started_at DESC);
CREATE INDEX ix_calls_install   ON calls (installation_id, started_at DESC); -- device health + silence detection
CREATE INDEX ix_calls_remote    ON calls (remote_number_key) WHERE remote_number_key IS NOT NULL;
CREATE INDEX ix_calls_no_audio  ON calls (started_at DESC)
       WHERE has_audio = false;                                              -- the gap report (UC-23)
CREATE INDEX ix_calls_type      ON calls (call_type, started_at DESC);
CREATE UNIQUE INDEX uq_calls_command ON calls (command_id) WHERE command_id IS NOT NULL;
```

### 3.6 Audio

**`call_audio`** — one row per stored recording.

`id`, `call_id` UUID FK CASCADE **UNIQUE**, `storage_key` TEXT (relative path
inside the storage root, never a URL), `bytes` BIGINT, `sha256` CHAR(64),
`codec` `audio_codec`, `container` `audio_container`, `sample_rate_hz` INT,
`channels` SMALLINT, `bitrate_bps` INT, `duration_ms` INT,
`capture_route` `capture_route`, `capture_route_detail` VARCHAR(64)
(e.g. `Recordings/Call` — the folder *name*, never a full path from the
employee's phone), `recorded_at` TIMESTAMPTZ, `uploaded_at` TIMESTAMPTZ,
`upload_id` UUID, `deleted_at` TIMESTAMPTZ, `deleted_reason` VARCHAR(16)
(`retention` | `revocation`).
Index: `UNIQUE(call_id)`, `(deleted_at)` WHERE `deleted_at IS NULL`,
`(capture_route)`.

Storage layout (`AudioStorage`, D-01):
`<AUDIO_ROOT>/calls/<yyyy>/<mm>/<dd>/<call_id>.<ext>`;
partials at `<AUDIO_ROOT>/incoming/<upload_id>.part`. `storage_key` is the path
relative to `AUDIO_ROOT` so the whole tree can be moved or swapped for S3
without a data migration.

**`audio_upload_sessions`** — resumable upload state (§4.6).

`id` UUID PK (`upload_id`), `installation_id` FK, `client_call_id` UUID,
`call_id` FK nullable (resolved at session creation; NULL only if the call row
has not arrived yet — see the ordering rule in §4.6), `bytes_total` BIGINT,
`chunk_size` INT, `received_bytes` BIGINT default 0, `sha256_expected` CHAR(64),
`codec`, `container`, `duration_ms`, `capture_route`, `recorded_at`,
`part_path` TEXT, `status` `upload_status`, `expires_at` (created + 7 days),
`last_chunk_at`.
Index: `UNIQUE(installation_id, client_call_id)` WHERE `status='open'` — one
open session per call per device, so a retrying client resumes instead of
forking; `(status, expires_at)` for the sweeper.

### 3.7 Device telemetry

**`device_health`** — current state, exactly one row per installation
(`installation_id` is the PK; this table is written, never appended).

`installation_id` PK FK CASCADE, `last_heartbeat_at`, `last_call_at`,
`app_version`, `app_variant`, `api_level`, `battery_level` SMALLINT,
`battery_charging` BOOL, `battery_optimisation_exempt` BOOL, `power_save_mode`
BOOL, `free_storage_bytes` BIGINT, `queue_records` INT, `queue_bytes` BIGINT,
`queue_oldest_at` TIMESTAMPTZ, `parked_records` INT, `clock_skew_sec` INT,
`device_timezone` VARCHAR(64), `network_type` `network_type`,
`cellular_bytes_month` BIGINT, `service_running` BOOL,
`capture_enabled` BOOL, `recording_route` `capture_route`,
`recording_route_ok` BOOL, `ws_connected` BOOL, `updated_at`.

`is_online` is **derived, not stored**:
`last_heartbeat_at > now() - (settings.alerts.device_offline_minutes)`.
Storing it would need a job to falsify it and would be wrong between runs.

**Deliberately not built:** a `device_health_history` time series. Nothing in
UC-17…UC-27 asks for a battery chart, and a 2-minute-per-device append is
~11k rows/device/month for a graph nobody requested. State transitions — the
thing alerts actually need — live in `capability_transitions` and `alerts`.

**`capability_states`** — current per-capability state.
`id`, `installation_id` FK CASCADE, `capability`, `state`, `checked_at`,
`changed_at`, `detail` VARCHAR(255), `UNIQUE(installation_id, capability)`.

**`capability_transitions`** — append-only history, the evidence behind UC-06
and UC-18 alerts.
`id`, `installation_id`, `capability`, `from_state`, `to_state`, `at`,
`source` VARCHAR(16) (`device_report` | `admin_recheck` | `inferred`),
`detail`. Index `(installation_id, at DESC)`, `(capability, at DESC)`.

**`call_log_deltas`** — the production measurement rig (§4.1 B of the
requirements, N1's only post-acceptance denominator).

`id`, `installation_id` FK, `number_id` FK, `period_date` DATE
(Asia/Tashkent), `device_counted` INT, `uploaded_count` INT,
`subscription_unknown_count` INT, `delta` INT
`GENERATED ALWAYS AS (device_counted - uploaded_count) STORED`,
`first_reported_at`, `last_reported_at`, `closed_at` TIMESTAMPTZ nullable.
`UNIQUE(installation_id, period_date)`; index `(period_date, delta)` WHERE
`closed_at IS NULL`.
A delta that is non-zero and still open after 24 h feeds the gap report (N3).
`subscription_unknown_count` is reported **separately and never folded into the
numerator or the denominator** — that is the fail-closed rule made visible.

**`data_usage_daily`** — N14/N15 counters.
`id`, `installation_id` FK, `period_date` DATE, `cellular_bytes` BIGINT,
`wifi_bytes` BIGINT, `requests` INT, `UNIQUE(installation_id, period_date)`.
Server-side counting is authoritative (request body sizes + response sizes per
installation); the device's own figure is stored in `device_health` for
comparison but is not the number the cap is enforced on.

### 3.8 Commands, alerts, audit, reference data

**`commands`** — `id`, `installation_id` FK, `kind`, `payload` JSONB,
`created_by` FK→users nullable (NULL for system-issued), `status`,
`failure_reason`, `created_at`, `sent_at`, `acked_at`, `expires_at`
(created + 120 s for `dial`, + 24 h for `config`/`logout`/`recheck`),
`result_call_id` FK nullable, `latency_ms` INT
(`acked_at − created_at`, stored so UC-16's 5-second bar is **measured**, not
assumed — see §4.6). Index `(installation_id, status, created_at DESC)`,
`(status, expires_at)`.

**`alerts`** — `id`, `kind` `alert_kind`, `severity`, `agent_id` nullable,
`installation_id` nullable, `number_id` nullable, `device_model` VARCHAR(96)
nullable, `title_uz` VARCHAR(200), `body_uz` TEXT, `detail` JSONB,
`dedupe_key` VARCHAR(200), `first_seen_at`, `last_seen_at`,
`occurrence_count` INT default 1, `acknowledged_at`, `acknowledged_by`
FK→users, `resolved_at`, `notified_at`.
```sql
-- One open alert per cause: a phone that reports a revoked permission every
-- two minutes must not produce 720 rows a day.
CREATE UNIQUE INDEX uq_alerts_open ON alerts (dedupe_key)
  WHERE acknowledged_at IS NULL AND resolved_at IS NULL;
CREATE INDEX ix_alerts_feed ON alerts (severity, last_seen_at DESC);
```
`dedupe_key` composition: `<kind>:<installation_id|agent_id|model|fleet>`.
Only `admin` may acknowledge; nothing in the device API can touch this table
(UC-06, UC-18: "the agent cannot dismiss or suppress the alert").

**`audit_log`** — append-only (UC-24, N27).
`id`, `at` TIMESTAMPTZ default now(), `actor_type`, `actor_user_id` FK nullable,
`actor_service_token_id` FK nullable, `action` `audit_action`, `object_type`
VARCHAR(32), `object_id` UUID nullable, `ip` INET, `user_agent` VARCHAR(255),
`detail` JSONB.
Append-only is enforced in the database, not by convention:
```sql
CREATE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$ LANGUAGE plpgsql;
CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
```
There is no API route that updates or deletes an audit row, and now no code
path can either.
Index: `(at DESC)`, `(actor_user_id, at DESC)`, `(object_type, object_id, at DESC)`.

**`line_directory_entries`** — the admin's extras for UC-25.
`id`, `pattern` VARCHAR(32), `kind` `directory_rule_kind`, `label` VARCHAR(64),
`is_active`, `created_by`. `UNIQUE(pattern, kind)`.
The derived half of the directory (every row in `registered_numbers`) is
**not** copied here — it is computed. Copying it would reintroduce L5, where the
directory starved because someone had to maintain it.

**`supported_models`** — the M0 baseline as data, not prose (T14, T128).
`id`, `manufacturer`, `model`, `api_level`, `app_variant`, `capture_route`,
`baseline_audio_capture_rate` NUMERIC(5,2), `baseline_sample_calls` INT,
`measured_at`, `is_supported` BOOL, `callback_verification_ok` BOOL nullable,
`note`. `UNIQUE(manufacturer, model, api_level, app_variant)`.

**`model_capture_stats`** — the rolling window the regression alert compares
against the baseline (UC-23, N4). Written nightly by a job.
`id`, `manufacturer`, `model`, `api_level`, `app_variant`, `window_start` DATE,
`window_end` DATE, `answered_calls` INT, `calls_with_audio` INT,
`rate` NUMERIC(5,2), `baseline_rate` NUMERIC(5,2), `delta_pp` NUMERIC(5,2),
`alert_raised` BOOL. `UNIQUE(manufacturer, model, api_level, app_variant, window_end)`.
Computing this on the fly would be cheap at this volume; it is materialised
anyway so that "what did the system see on the day it alerted" is answerable
six months later.

**`app_versions`** — the self-hosted update channel (N33, N34).
`id`, `version` VARCHAR(20), `version_code` INT, `variant` `app_variant`,
`apk_path` TEXT, `apk_sha256` CHAR(64), `size_bytes` BIGINT, `min_api_level` INT,
`release_notes_uz` TEXT, `is_mandatory` BOOL, `published_at`, `is_current` BOOL,
`created_by`. `UNIQUE(variant, version_code)`; partial unique index on
`(variant)` WHERE `is_current` — one current build per variant.

**`storage_usage_daily`** — `period_date` PK, `audio_bytes_total` BIGINT,
`audio_files` INT, `bytes_added` BIGINT, `bytes_deleted` BIGINT. Feeds N18's
"current GB + 30-day growth" panel without a `du` over 200 GB.

**`app_settings`** — `key` VARCHAR(100) PK, `value` JSONB NOT NULL,
`value_type` VARCHAR(16), `description_uz` TEXT, `updated_by` FK→users,
`updated_at`. Every key that exists is seeded by the migration with its default,
so a missing key is a bug and not a silent `None`:

| Key | Default | Used by |
|---|---|---|
| `retention.audio_months` | `12` | UC-26, N19 |
| `retention.confirm_below_months` | `3` | N19 |
| `retention.callback_events_days` | `90` | §3.4 |
| `alerts.device_offline_minutes` | `10` | UC-17 |
| `alerts.silence_hours` | `4` | UC-27 |
| `alerts.fleet_silence_hours` | `2` | UC-27 |
| `alerts.capture_regression_pp` | `10` | UC-23, N4 |
| `alerts.email_to` | `[]` | T39 |
| `app.min_supported_version_code` | `1` | N34 |
| `upload.chunk_size_bytes` | `524288` | §4.5 |
| `upload.session_ttl_days` | `7` | §4.5 |
| `upload.max_chunk_bytes` | `4194304` | §4.5 |
| `data.cellular_cap_bytes_month` | `1073741824` | N14 |
| `data.deferred_daily_cap_bytes` | `5242880` | N15 |
| `audio.defer_to_wifi_hours` | `24` | N7 |
| `queue.max_records` | `2000` | N8 |
| `queue.max_audio_bytes` | `1073741824` | N8 |
| `queue.min_free_space_bytes` | `1073741824` | N10 |
| `device.heartbeat_seconds` | `120` | UC-17 |
| `device.capability_recheck_hours` | `6` | N42 |
| `device.call_log_sweep_hours` | `6` | §4.1 B |
| `working_hours.start` / `.end` | `"08:00"` / `"20:00"` | UC-27, N38 |
| `working_hours.timezone` | `"Asia/Tashkent"` | D-10 |
| `working_hours.workdays` | `[1,2,3,4,5,6]` | Mon–Sat. **Assumption** — Uzbek sales weeks usually include Saturday; correcting it is a settings change, not a code change |
| `working_hours.holidays` | `[]` | dates excluded from UC-27's "working hours" |
| `enrolment.code_ttl_hours` | `24` | UC-01 |
| `enrolment.callback_window_seconds` | `300` | §9.2 |

### 3.9 The `audio_missing_reason` enum — why ten values, not six

UC-14 names six. Four more are required for the enum to stay *closed*, which is
what N5 actually demands. Each addition, and the rule that keeps the acceptance
criterion honest:

| Added value | When set | Counted in the gap report? |
|---|---|---|
| `pending_upload` | The call row arrived before its audio. Set at ingest | **No** while < 24 h. At 24 h the sweeper rewrites it to `upload_expired` and it becomes visible. Without this value the alternative is a nullable reason, which breaks N5 |
| `not_expected` | `disposition <> 'answered'` — a missed, rejected or unanswered call never had a conversation to record | **No.** UC-23 reports "% of answered calls"; an unanswered call in that denominator makes the number meaningless |
| `queue_space_exhausted` | N10 fired: the queue was full or free space < 1 GB, so recording was stopped deliberately | **Yes** — it is a real loss and it is the admin's problem to fix |
| `attribution_failed` | A recording existed but its time window did not match a registered-number call, so it was discarded on the device (N28) | **Yes**, and separately — a rising count here means the harvest window is mistuned, which is the difference between a bug and a privacy incident |

**Acceptance reading:** UC-14's six-value test applies to answered calls where
audio was attempted. The gap report's denominator is answered calls with
`audio_missing_reason NOT IN ('pending_upload','not_expected')`.

### 3.10 Idempotency: `client_call_id`

The prototype used a Room autoincrement, which restarts at 1 after a reinstall
and collides (R5). A random UUIDv4 per call fixes collisions but **not** the
reinstall case: after the app's database is lost, the call-log recovery sweep
(UC-13) rediscovers the same calls and would mint new ids, uploading every call
a second time. Duplicate rate must be **0** (N2).

**Decision (D-05).** `client_call_id` is a **UUIDv5** over a canonical string of
facts that survive a reinstall, because they come from the OS call log rather
than from app state:

```
namespace = 8f6e5a30-0d7e-5c9b-9d3f-6f1c0a5d4b21   (fixed BonviCall constant)
name      = "<registered_phone_key>|<direction>|<started_at_epoch_ms>|<remote_key_or_'unknown'>"
client_call_id = uuid5(namespace, name)
```

Rules that make this work, all of them mandatory:

1. **`started_at_epoch_ms` is the call log's `DATE` value**, verbatim. That is
   the only timestamp two independent app installs will agree on.
2. A record is **not uploaded until it has been reconciled against the call log**
   (which UC-11 requires anyway), or 15 minutes have elapsed since call end with
   no matching call-log row. In the second case the id is derived from the
   live-captured start time truncated to whole seconds and
   `reconciled_with_call_log = false`.
3. **The id is computed once and stored locally forever** (until the record is
   confirmed and pruned). If reconciliation later corrects the start time, the
   app sends a **correction to the same `client_call_id`** — it never derives a
   new one. This is the rule that prevents the ±1 s case from producing two rows.
4. Server: `UNIQUE(client_call_id)`; `POST /calls` is an upsert. A repeat of an
   identical payload returns `200` with the same `id` and `status: "unchanged"`.
   A repeat with changed reconcilable fields returns `200` and
   `status: "updated"`.
5. **Cross-installation replay guard:** if a `client_call_id` already exists and
   belongs to a different `number_id`, the server returns `409`
   `call_identity_conflict`, stores nothing, and raises a `credential_replay`
   alert. Two devices claiming one call is either a bug or a stolen credential;
   both need a human.
6. Fields the server will accept as corrections: `direction`, `disposition`,
   `started_at`, `answered_at`, `ended_at`, `duration_sec`, `ring_sec`,
   `contact_name`, `remote_number`, `reconciled_with_call_log`,
   `audio_missing_reason`, `source`. Everything else is **immutable after first
   write** — in particular `number_id`, `agent_id`, `installation_id`,
   `received_at`, `seq`.

Audio uses the same key: an upload session is opened against
`client_call_id`, not against the server id, so the device never has to have
seen a response before it can start uploading.

### 3.11 Retention and deletion (N19, UC-26)

| Data | Retention | Mechanism |
|---|---|---|
| Audio files + `call_audio.storage_key` contents | `retention.audio_months`, default **12** | Nightly `audio_retention` job: deletes the blob, sets `deleted_at` + `deleted_reason='retention'`, keeps the row |
| Call metadata, `calls` rows | **Indefinite** | Never deleted. `DELETE /calls/{id}` returns **405 for every role including `admin`** |
| `audit_log` | **Indefinite** | Append-only, immutable by trigger |
| `callback_events` | 90 days | Nightly sweep |
| `audio_upload_sessions` + `.part` files | 7 days after `expires_at` | Sweeper marks `expired`, deletes the partial, sets the call's reason to `upload_expired` |
| `enrolment_attempts` | Indefinite | Small, and it is the funnel's evidence |
| `device_health` | Current only | Overwritten |
| `capability_transitions`, `alerts`, `call_log_deltas`, `data_usage_daily`, `model_capture_stats`, `storage_usage_daily` | Indefinite | Small |
| Local audio on the device | Deleted **only** after the server confirms the checksum (N11); all of it deleted on revocation (UC-08) |

Playing an expired recording returns **410** `audio_expired` with an Uzbek
message — never a 500, never an empty 200 (UC-26 AC).
Lowering `retention.audio_months` below `retention.confirm_below_months`
requires `PUT /settings` to carry `"confirm": true`; without it the server
returns 409 `retention_confirmation_required` and changes nothing.

### 3.12 Ordering, cursors and the clock

- **Ordering and cursors use `received_at` (server receipt).** Devices lie about
  time and users change it (N36).
- **Attribution and business dates use `started_at`** (D-08). A call made
  yesterday and uploaded today belongs to yesterday in the gap report and to
  yesterday's assignment.
- `clock_skew_sec` is computed at receipt as
  `EXTRACT(EPOCH FROM received_at) - device_epoch_ms/1000`, corrected by the
  round-trip estimate the client sends. It is shown in device health (UC-17) and
  is **never** used to rewrite `started_at`: a corrected timestamp that disagrees
  with the device's own call log would break the reconciliation that everything
  else depends on.
- The export cursor (§4.9) uses `seq` with a **10-second settling window**:
  `seq` is a sequence, and under concurrency a lower `seq` can commit after a
  higher one, so a naive `WHERE seq > cursor` can skip a row forever. The export
  therefore never returns rows with `received_at > now() - interval '10 seconds'`.
  That is what makes UC-29's "two consecutive full passes return identical row
  sets" true rather than nearly true.

### 3.16 `audit_action` — the closed value list

*(Numbered 3.16 and placed last: §3.8 cited that id, the shipped
`core/enums.py` cites it back, and renumbering a reference two documents already
resolve against buys nothing. Ids are stable in this project even when they are
ugly — the same discipline as UC-28 and N29.)*

Referenced from §3.8. **This section is the authority**; `core/enums.py` follows
it. Adding a value later is a migration, which is the point — "everything that
happened" must be answerable from one column, not from one column plus a habit.

35 values were derived by `build-backend` from the operations §4.7/§4.8 audit.
They are confirmed, **plus two additions named below**, giving **37**.

| Group | Values |
|---|---|
| Session | `login_succeeded`, `login_failed`, `logout` |
| Credentials | `password_changed`, `password_reset` |
| Users | `user_created`, `user_updated`, `user_deactivated` |
| Agents | `agent_created`, `agent_updated`, `agent_archived`, `agents_imported` |
| Numbers and the identity chain | `number_created`, `number_updated`, `assignment_created`, `assignment_closed`, `calls_reattributed` |
| Enrolment | `enrolment_code_issued`, `enrolment_code_revoked`, `installation_attested`, `installation_revoked`, `installation_rebound` |
| Calls | `call_note_updated`, `calls_exported` |
| Audio | `audio_play`, `audio_download`, `audio_deleted` |
| Alerts | `alert_acknowledged` |
| Configuration | `setting_updated`, **`retention_changed`**, `line_directory_updated`, `supported_model_updated`, `app_version_published` |
| Machine access | `service_token_created`, `service_token_revoked`, `export_read` |
| Device control | **`command_issued`** |

**The two additions, and why they are worth a migration now rather than a
regret later:**

- **`retention_changed`** — technically a `setting_updated`, but it is the one
  setting whose change *destroys data*: lowering `retention.audio_months`
  deletes everything older on the next nightly run (§3.11). "Who shortened
  retention, and when" must be one filter, not a JSONB dig through every
  settings edit ever made.
- **`command_issued`** — click-to-call, a config push, or a remote logout is a
  user reaching into an employee's **personally owned** phone (§4.6). The
  `commands` table records it operationally, but the admin's single view of
  "what did people do" is the audit log, and this is the one action in the
  product that acts on someone else's hardware. `detail` carries `kind` and, for
  `dial`, the target number.

**Disambiguation rules, so two actions never describe one event:**
- Panel CSV export ⇒ `calls_exported`. Service-API metadata export ⇒
  `export_read`. Service-API audio streaming ⇒ `audio_play` with
  `actor_type='service'` (§4.9), never `export_read`.
- Retention-driven and revocation-driven audio deletion both ⇒ `audio_deleted`,
  distinguished by `detail.reason` — the deletion is the same event either way.
- `installation_rebound` is written by the server when verification rebinds a
  number (§9.3); `installation_revoked` is written when a human revokes.

**Deliberately absent:** anything per-read. Viewing a call list, a report or a
device page writes nothing. Audio playback is audited because it is the
sensitive artefact (UC-24, N27); auditing every page view would bury it.

---

## 4. API contract

Three surfaces, three prefixes, three audiences. They never share a router and
never share an auth dependency.

| Surface | Prefix | Consumer | Auth |
|---|---|---|---|
| Device | `/api/device/v1` | The Android app, which **cannot be force-updated** | Installation-bound bearer token |
| Panel | `/api/v1` | The web panel | User bearer token (+ refresh cookie) |
| Service | `/api/service/v1` | BonviZvonki's future ingest adapter, the callback receiver | Service token, scoped |

### 4.0 Cross-cutting rules

**Error envelope (N35).** Every non-2xx response, without exception:

```json
{"error": {"code": "enrolment_code_expired",
           "message": "Ushbu kod muddati tugagan. Administratordan yangi kod so'rang.",
           "detail": {"expired_at": "2026-09-03T10:00:00+05:00"},
           "request_id": "01J9…"}}
```

`code` is a stable snake_case string and is part of the contract — clients
branch on it, never on `message`. `message` is **Uzbek** wherever an end user
sees it (device surface, panel-facing validation), English for internal-only
failures. `detail` is optional and machine-readable. `request_id` is echoed
from the `X-Request-Id` header or generated.

Status codes used, and what each means here:

| Code | Meaning in BonviCall |
|---|---|
| 200 | OK, including idempotent repeats |
| 201 | Created (first write only) |
| 204 | Accepted, nothing to return (acks, heartbeat with no config change) |
| 206 | Partial content — audio Range (N43) |
| 400 | Malformed request |
| 401 | No token, bad token, expired token, installation/token mismatch |
| 403 | Authenticated but the role lacks the permission |
| 404 | Not found **or wrong owner** — a `sales` user asking for another agent's call gets 404, never 403 (UC-21) |
| 405 | `DELETE` on a call or its audio, for every role (UC-26) |
| 409 | Conflict: number already assigned, code already used, active installation exists, chunk offset mismatch, retention confirmation missing |
| 410 | Gone: enrolment code expired, audio expired |
| 413 | Body too large |
| 422 | Validation (Pydantic), same envelope, `detail` carries the field list |
| 426 | `app_version_unsupported` — the stale-client refusal, and **only** after the queue is empty (§4.3) |
| 429 | Rate limited, with `Retry-After` |
| 500 | Unhandled — never leaks a stack trace to a client |

**Timestamps on the wire (N36).** ISO-8601, always with an explicit offset —
never a naive local time.

- **Inbound** (device → server, panel → server): an explicit offset is
  **required**. The device sends its own, normally `+05:00`
  (`2026-09-04T13:59:02.412+05:00`). A timestamp without an offset is a 422, not
  a guess.
- **Outbound** (server → anyone): **UTC-normalised, `Z` form**
  (`2026-09-04T08:59:02Z`). Everything is stored UTC (D-10) and rendered as it
  is stored; a server that echoed each client's offset back would make two rows
  from two phones incomparable by string.
- **Every client must accept both forms.** This matters more than it looks:
  **the device sends `+05:00` and gets `Z` back**, so a client that round-trips
  a timestamp through the server sees the *string* change while the *instant*
  does not. Compare parsed instants, never strings. The Android DTOs are
  generated from the contract but the date parsing is hand-written, which is
  exactly where this becomes a comparison bug nobody can reproduce.

Every device-originated object that carries a timestamp **also** carries
`device_epoch_ms` (integer) and `device_timezone` (IANA), so the server can
compute skew rather than trust the offset (§3.12). Server responses carry
`server_time` on every device endpoint so the app can compute skew without an
extra round trip.

**Phone numbers on the wire.** Devices send what they saw
(`"+998 90 111-22-33"`, `"901112233"`, `""`). The server normalises to E.164 and
derives the 9-digit key (N37); an unparseable number is stored raw in
`remote_number` with a NULL key rather than rejected — losing a call because its
number was odd is worse than an unkeyed row.

**Pagination.** Two formats, deliberately different because the problems differ.

*Panel lists* — keyset (cursor):
`?limit=50&cursor=<opaque>&with_total=false`
```json
{"items": [...], "next_cursor": "eyJyIjoi…", "has_more": true, "total": null}
```
- `limit` default 50, max 200 (max 1000 for `/calls` because UC-19 renders 1000).
- `cursor` is base64url of `{"k": [<sort value>, "<id>"]}` — the sort column
  plus `id` as tiebreaker. **Every sort must include `id`**, or paging duplicates
  rows whose sort values tie.
- Default and guaranteed-stable sort is `received_at DESC, id DESC`.
- Guarantee, stated precisely because "stable" is otherwise unfalsifiable:
  **no row that existed when paging started is skipped or returned twice.**
  Rows inserted during the pass may or may not appear; they never displace
  others. That is exactly UC-19's requirement and it is what keyset gives.
- `total` is computed only when `with_total=true`. The panel asks once per
  filter change, not per page — a `COUNT(*)` over a filtered 500k table is
  affordable once and not eleven times.

*Service export* — sequence cursor: `?since=<seq>&limit=500` with the settling
window of §3.12. Response carries `next_since` and `count`.

**Rate limits** (429 + `Retry-After`), per the identified principal:

| Endpoint class | Limit |
|---|---|
| Device ingest (`/calls`, `/heartbeat`, `/capabilities`, `/call-log-delta`, `/events`) | 120 req/min per installation |
| Audio chunk `PUT` | 600 req/min per installation |
| `POST /enrolment/redeem` | 10/hour per IP, 5 per code (then the code is auto-revoked and an alert raised) |
| Panel `POST /auth/login` | 10 per 5 min per (IP, email); 20 per hour per IP |
| Service export | 60 req/min per token |

**Payload limits.** Call batch: 50 items or 256 KiB. Audio chunk: `chunk_size`,
never > `upload.max_chunk_bytes` (4 MiB). APK upload: 200 MiB. Anything larger
is 413 `payload_too_large`.

**Logging redaction (N26).** A logging filter redacts `password`,
`access_token`, `refresh_token`, `credential`, `code`, `token_hash`,
`Authorization`, `Cookie` — replaced with `…` + last 4 characters. There is a
test that posts a login and an enrolment redeem and greps the captured log
stream for the secret; it fails if found.

**Transport (N22).** HTTPS/WSS only. HSTS on. The app pins nothing (a pinned
cert on a fleet we cannot force-update is a self-inflicted outage) but treats
every TLS error as fatal and never offers a bypass.

### 4.1 RBAC registry — the complete permission set

Declared once in **`server/src/core/permissions.py`**, referenced by every
router, extended by nobody (T18). It lives in `core/` and not in the `users`
module deliberately: BonviZvonki puts the matrix in
`modules/users/domain/entities.py`, which makes `core/deps.py` import a module —
the dependency inversion this project is avoiding. `Perm.*` constants are used
in `Depends`, never bare strings, and an unknown permission raises at **import
time**, so a typo is a server that refuses to start rather than an endpoint that
quietly refuses everybody.

```
users:read users:write
agents:read agents:write agents:archive
numbers:read numbers:write
enrolment:read enrolment:write enrolment:attest
installations:read installations:revoke
devices:read devices:read:own
calls:read calls:read:own calls:note
audio:play audio:play:own audio:download
commands:dial
alerts:read alerts:ack
reports:read reports:export
audit:read
settings:read settings:write
appversions:read appversions:write
monitor:read
export:read export:audio
callback:report
```

| Permission | admin | manager | sales | viewer | service |
|---|:--:|:--:|:--:|:--:|:--:|
| `users:read` / `users:write` | ✔ | | | | |
| `agents:read` | ✔ | ✔ | | | |
| `agents:write` / `agents:archive` | ✔ | | | | |
| `numbers:read` | ✔ | ✔ | | | |
| `numbers:write` | ✔ | | | | |
| `enrolment:read` | ✔ | ✔ | | | |
| `enrolment:write` / `enrolment:attest` | ✔ | | | | |
| `installations:read` | ✔ | ✔ | | | |
| `installations:revoke` | ✔ | | | | |
| `devices:read` | ✔ | ✔ | | | |
| `devices:read:own` | | | ✔ | | |
| `calls:read` | ✔ | ✔ | | | |
| `calls:read:own` | | | ✔ | | |
| `calls:note` | ✔ | ✔ | | | |
| `audio:play` / `audio:download` | ✔ | ✔ | | | |
| `audio:play:own` | | | ✔ | | |
| `commands:dial` | ✔ | ✔ | | | |
| `alerts:read` | ✔ | ✔ | | | |
| `alerts:ack` | ✔ | | | | |
| `reports:read` / `reports:export` | ✔ | ✔ | | | |
| `audit:read` | ✔ | | | | |
| `settings:read` | ✔ | ✔ | | | |
| `settings:write` | ✔ | | | | |
| `appversions:read` | ✔ | ✔ | | | |
| `appversions:write` | ✔ | | | | |
| `monitor:read` | ✔ | ✔ | | ✔ | |
| `export:read` / `export:audio` | ✔ | | | | ✔ |
| `callback:report` | | | | | ✔ |

Rules that are not visible in the table and must not be re-litigated:

1. **`sales` scope is narrowed by the query, not by a second permission.**
   `calls:read:own` passes the dependency
   (`require_any_permission("calls:read", "calls:read:own")`), and the service
   layer adds `WHERE agent_id = current_user.agent_id`. Identical to
   `AnalyticsService._scoped()` in BonviZvonki.
2. **Wrong owner is 404, not 403** (UC-21). 403 confirms the row exists, which
   tells a salesperson that a colleague spoke to a given number.
3. **`viewer` never receives a full remote number.** The monitor endpoint returns
   its own DTO with `remote_number_masked` (`•••• 4455`) computed server-side.
   Masking in CSS is not masking.
4. **`service` cannot read users, cannot read the audit log, cannot write
   anything** (UC-29). Its token scopes are checked in addition to the
   permission.
5. **No endpoint is unprotected except these named routes**, listed in one
   place as `PUBLIC_ROUTES` in `core/permissions.py`, each with its reason
   inline. The RBAC harness asserts the set matches exactly — *the set, not a
   count: a count is a fact that rots.*

   | Route | Why it is public |
   |---|---|
   | `GET /healthz` · `GET /readyz` | liveness and readiness; they return no data |
   | `POST /api/v1/auth/login` | the front door |
   | `GET /i/{code}` | the install landing page (§8.1); the single-use code *is* the credential |
   | `GET /api/v1/app/download/{version_code}` | the APK, which carries no credential; the per-agent link is for attribution, not secrecy |
   | `POST /api/device/v1/enrolment/redeem` | a phone that has not enrolled has no token yet; the code is the credential, and it is rate-limited to 10/hour per IP and 5 per code (§4.0) |

### 4.2 Device API — authentication and enrolment

Every device request carries:

```
Authorization: Bearer <access_token>
X-Installation-Id: <uuid>
X-App-Version: 1.4.0
X-App-Version-Code: 140
X-App-Variant: legacy28 | modern34
X-Device-Fingerprint: <sha256 hex>
X-Request-Id: <uuid>            (optional, echoed)
```

Token model (N24, N25):
- **Access token**: JWT, 12 h, claims `sub` (installation id), `num`
  (number_id), `agent`, `fp` (device fingerprint hash), `tv` (token_version).
- **Refresh token**: opaque 32-byte, 90 days, hashed at rest, **rotated on every
  use**. Reuse of a rotated token ⇒ the installation's `token_version` is
  incremented (all tokens die), status stays `active`, and a `credential_replay`
  alert is raised.
- A request whose `X-Installation-Id` or `X-Device-Fingerprint` disagrees with
  the token's claims ⇒ **401** `installation_mismatch` + `credential_replay`
  alert. This is what N24's "a token copied to another device is rejected on
  first use and raises an admin alert" means concretely.
- **Honest limit, written down so nobody oversells it:** fingerprint binding
  raises the cost of credential theft; it does not defeat an attacker with root
  on the phone. There is no MDM and no attestation here.

12 hours (not 15 minutes) because a phone can be offline for a day and N25's
requirement is that expiry never loses data, not that the window is tiny. On
expiry the app holds its queue and reports `auth_expired` (§4.5, `POST /events`).

---

**`POST /api/device/v1/enrolment/redeem`** — public (no token; rate-limited).

```json
{ "code": "K7M4PQ2X",
  "device": {"manufacturer":"Xiaomi","model":"Redmi Note 12","marketing_name":"Redmi Note 12",
             "android_release":"13","api_level":33,"build_fingerprint_hash":"<sha256>"},
  "app": {"version":"1.0.0","version_code":100,"variant":"legacy28"},
  "device_fingerprint":"<sha256>",
  "device_epoch_ms": 1788000000000, "device_timezone":"Asia/Tashkent" }
```
`201`:
```json
{ "installation_id":"…", "status":"pending",
  "provisional_token":"…", "expires_in":900,
  "agent":{"id":"…","full_name":"Aziz Karimov"},
  "number":{"e164":"+998901112233","display":"+998 90 111-22-33"},
  "verification":{"required":true,"callback_msisdn":"+998712000000",
                  "receiver_status":"up","window_seconds":300},
  "server_time":"2026-09-04T14:03:11+05:00" }
```
Errors: `404 enrolment_code_not_found` · `409 enrolment_code_used`
(detail names when and by which device model) · `410 enrolment_code_expired` ·
`409 installation_already_active` (an active installation exists for this
number — the panel must revoke it first, or the agent must complete
verification, which rebinds; §9.3) · `429`.

**The provisional token is scoped.** It may call only
`/enrolment/verify/*`, `/capabilities`, `/events` and `GET /config`.
Anything else ⇒ `403 verification_required`. This is what stops an unverified
phone uploading a single call — the privacy boundary starts here, not at the
first `POST /calls`.

**`POST /api/device/v1/enrolment/verify/msisdn`** — route 1.
```json
{"line1_number":"+998901112233","subscription_id":2,"sim_slot":1,
 "carrier_name":"Beeline UZ"}
```
- `line1_number` null, empty, whitespace, or fewer than 9 digits ⇒
  **`409 msisdn_unavailable`**, `enrolment_attempts(outcome='msisdn_empty')`,
  and the app moves to route 2. **`getLine1Number()` returning null is never a
  match** (UC-04, non-negotiable, asserted by test).
- Key mismatch against the registered number ⇒ `409 number_mismatch`, attempt
  recorded, installation stays `pending`.
- Match ⇒ `200` with the full token pair and `status:"active"` (§9.1).

**`POST /api/device/v1/enrolment/verify/callback/start`** — route 2.
Body: `{"subscription_id":2,"sim_slot":1}`.
`200`: `{"verification_id":"…","callback_msisdn":"+998712000000",
"expires_at":"…","poll_after_ms":2000}`.
`503 callback_receiver_down` when every active receiver is `down` — with an
Uzbek message telling the agent to contact the admin. Raising a challenge the
agent cannot possibly satisfy is worse than saying so.

**`GET /api/device/v1/enrolment/verify/callback/status?verification_id=…`**
Poll every 2 s, ≤ 5 min. `200`:
`{"state":"pending|matched|failed|expired","failure":"no_caller_id|number_mismatch|null"}`.
On `matched` the same response carries the token pair and `status:"active"`.
On `failed:"no_caller_id"` the app shows the admin-assisted path (§9.3) and the
server sets `funnel_stage='needs_assisted_install'`.

**`POST /api/device/v1/auth/refresh`** — `{"refresh_token":"…"}` →
new pair. `401 refresh_reused` (chain revoked, alert raised) ·
`401 installation_revoked` · `426` per §4.3.

### 4.3 The stale-client rule (N34) — exactly how the refusal works

A client we cannot force-update will fall behind. Refusing it must never destroy
data, so the refusal is deferred, not conditional on politeness:

1. **Ingest endpoints never refuse on version.** `POST /calls`,
   `PATCH /calls/{id}`, the whole audio upload chain, `POST /heartbeat`,
   `/capabilities`, `/call-log-delta`, `/events` and `/commands/{id}/ack`
   are accepted from **any** version, forever.
2. Every device-API response carries an `update` block:
   ```json
   "update": {"required": true, "min_version_code": 140,
              "latest_version":"1.4.0","latest_version_code":140,
              "apk_url":"https://…/api/v1/app/download/140",
              "message_uz":"Ilovani yangilash kerak. Navbatdagi yozuvlar yuborilgandan so'ng ilova bloklanadi."}
   ```
3. **The refusal fires on `POST /auth/refresh` only, and only when the last
   heartbeat reported `queue_records = 0 AND queue_bytes = 0`.** Then: `426`
   `app_version_unsupported`. Until the queue drains, refresh keeps working.
4. The app, on seeing `update.required`, keeps capturing and draining, shows the
   Uzbek update screen, and blocks *new* enrolment actions only.
5. Test (T50/T83): an old client with 20 queued calls uploads all 20
   successfully, then receives 426 on its next refresh — in that order.

### 4.4 Device API — call ingest

**`POST /api/device/v1/calls`** — batch upsert, ≤ 50 items.

```json
{"calls":[{
  "client_call_id":"7c1f…",              // UUIDv5, §3.10
  "direction":"outgoing",
  "disposition":"answered",
  "remote_number":"+998935554433",
  "contact_name":"Anvar do'kon",
  "started_at":"2026-09-04T13:59:02+05:00",
  "answered_at":"2026-09-04T13:59:11+05:00",
  "ended_at":"2026-09-04T14:07:44+05:00",
  "duration_sec":513,
  "ring_sec":9,
  "sim_subscription_id":2,
  "sim_slot":1,
  "source":"live_capture",
  "reconciled_with_call_log":true,
  "audio_expected":true,
  "audio_missing_reason":null,
  "capture_route":"oem_file_harvest",
  "command_id":null,
  "device_epoch_ms":1788000000000,
  "device_timezone":"Asia/Tashkent",
  "device_rtt_ms":180
}]}
```

`200`:
```json
{"results":[{"client_call_id":"7c1f…","id":"…","status":"created",
             "audio_upload":"required"}],
 "server_time":"…","update":{…}}
```
`status` ∈ `created | unchanged | updated`; `audio_upload` ∈
`required | not_expected | already_present`.

Server behaviour, in order:
1. Reject the whole batch with `403 verification_required` if the installation
   is not `active`.
2. Per item: resolve `number_id` from the installation (**never from the
   payload** — the device does not get to say which number it is);
   resolve `agent_id`/`assignment_id` from `started_at` (§3.3); if no assignment
   covers `started_at`, attribute to the assignment in force at
   `installation.bound_at` and set an `info` alert `attribution_out_of_range`
   — dropping the call would be worse.
3. Compute `call_type` (§10.2), `clock_skew_sec`, `remote_number_key`.
4. Upsert on `client_call_id`; immutable fields per §3.10 rule 6.
5. Set `has_audio=false` with `audio_missing_reason = pending_upload` when
   `audio_expected`, `not_expected` when the disposition is not `answered`, or
   the client-supplied reason otherwise.
6. Partial failure is per item, not per batch: an item that fails returns
   `{"client_call_id":…,"error":{"code":…}}` in the same array and the rest are
   committed. A batch that fails wholesale is a batch the device will retry
   forever.

**`PATCH /api/device/v1/calls/{client_call_id}`** — reconciliation correction,
same idempotent semantics, only the fields listed in §3.10 rule 6.
`404 call_not_found` if the id is unknown (the device should `POST` instead);
`409 call_identity_conflict` on cross-installation replay.

**`POST /api/device/v1/call-log-delta`** — the production rig.
```json
{"period_date":"2026-09-04","device_counted":31,"uploaded_count":30,
 "subscription_unknown_count":2,"swept_at":"…"}
```
Upsert on `(installation_id, period_date)`; `device_counted` is monotonic
non-decreasing within a day (a lower value is ignored and logged — a partial
sweep must not erase a full one).

**`POST /api/device/v1/heartbeat`** — every 120 s while the service is alive.
Body: the whole `device_health` payload (§3.7) plus `ws_connected`,
`pending_commands_seen`. Response: `server_time`, `update`, `config` (hash +
body only when changed — `{"config_hash":"…","config":null}` when unchanged, so
the 5 MB/day cellular budget in N15 is not spent on unchanged settings),
`pending_command_count`.

**`POST /api/device/v1/capabilities`** — array of
`{"capability":"microphone","state":"granted_working","checked_at":"…","detail":"1s test capture 32 kB"}`.
Server upserts `capability_states`, appends `capability_transitions` on change,
and raises the UC-06/UC-18 alerts within the same request — the 10-minute bound
is then a device-reporting-interval question, not a server-latency question.

**`POST /api/device/v1/events`** — device events that are not calls:
`service_not_running`, `capture_toggled_off`, `queue_full`, `storage_low`,
`poisoned_record`, `auth_expired`, `boot_completed`, `app_updated`,
`recording_route_lost`, `oem_recorder_missing`, `attribution_discarded`,
`revocation_completed`. Each maps to an alert kind or a counter; the mapping
table lives in `modules/alerts/rules.py` and is exhaustive — an
unknown event is stored and raises `info`, never dropped.

**`POST /api/device/v1/commands/{command_id}/ack`** —
`{"status":"acknowledged|failed","failure_reason":"…","at":"…","result_client_call_id":"…"}`.

### 4.5 Device API — resumable audio upload (D-04)

**Why a custom 3-step protocol and not the alternatives.** `tus` is a good
protocol and brings a spec, a server library and a client library for a problem
that is four endpoints wide; S3 multipart is not available because storage is
the local filesystem (D-01); `multipart/form-data` re-POST is precisely the
CallSentry weakness that N7/UC-14 exist to fix (a 60 MB file on 3G restarting
from zero — at our bitrate a 20-minute call is ~3.5 MB, but a 90-minute call on
a bad edge connection is exactly the case that never completes). The protocol
below is byte-offset resumable, needs no third-party dependency on either side,
and reassembles by appending to one `.part` file.

**1. Open** `POST /api/device/v1/calls/{client_call_id}/audio/session`
```json
{"bytes_total":3512044,"sha256":"…","codec":"opus","container":"ogg",
 "sample_rate_hz":16000,"channels":1,"bitrate_bps":24000,"duration_ms":513400,
 "capture_route":"oem_file_harvest","capture_route_detail":"Recordings/Call",
 "recorded_at":"2026-09-04T14:07:46+05:00"}
```
`201`: `{"upload_id":"…","chunk_size":524288,"received_bytes":0,"expires_at":"…"}`
Repeating the call for the same `client_call_id` returns the **existing** open
session with its true `received_bytes` — that is the resume path after an app
restart, and it is why the unique index in §3.6 is partial on `status='open'`.

Server-side checks at open time — this is the **attribution guard** (N28, T44):
- the call exists, belongs to this installation, and is `answered`;
- `recorded_at` and `duration_ms` overlap the call window
  `[started_at − 5 s, ended_at + 120 s]` (the OEM writer flushes late — the
  window comes straight from `S1-RECORDING.md`);
- otherwise **409 `audio_not_attributable`**, nothing is stored, the call's
  reason becomes `attribution_failed`, and the event is logged.
  The device-side guard (§7.4) is the primary defence; this is the backstop, and
  it exists because the shared OEM folder also holds the employee's private
  recordings.
- If the call row has not arrived yet: `409 call_not_found` with
  `detail.retry_after_ms` — the app posts the metadata first. Metadata before
  audio, always: the cheap and important half lands first (R7).

**2. Send** `PUT /api/device/v1/audio/{upload_id}/chunk?offset=<bytes>`
`Content-Type: application/octet-stream`, `Content-Length: <n>`,
`X-Chunk-SHA256: <hex>`.
- `200 {"received_bytes":1048576}`
- `409 chunk_offset_mismatch` with `{"expected_offset": 524288}` — the client
  seeks and retries; it never restarts.
- `422 chunk_checksum_mismatch` — the chunk is discarded, `received_bytes`
  unchanged, the client resends the same chunk.
- `410 upload_expired` — session past TTL; the call's reason becomes
  `upload_expired` and the device deletes its local copy.

**3. Commit** `POST /api/device/v1/audio/{upload_id}/commit`
Server verifies `received_bytes == bytes_total` and the whole-file SHA-256,
moves the `.part` into `AudioStorage`, writes `call_audio`, sets
`calls.has_audio=true`, `audio_missing_reason=NULL`, and sets
`audio_duration_mismatch` when `|duration_ms/1000 − duration_sec| > 2`.
`200 {"audio_id":"…","sha256":"…","bytes":3512044,"stored":true}` — **idempotent**:
committing twice returns the same body. Only after this response does the device
delete its local file (N11).
`422 checksum_mismatch` → session `aborted`, partial deleted, client restarts
the upload once; a second failure parks the record (N9).

**4. Probe** `GET /api/device/v1/audio/{upload_id}` →
`{"received_bytes":…,"status":"open","expires_at":"…"}`.

Chunk size default 512 KiB (~2.5 minutes of 24 kbps audio), server-adjustable
per response; the client always obeys the server's `chunk_size`.

Upload policy the app must follow (N7, N14, N15) is delivered in `config`, not
compiled in: Wi-Fi preferred; audio older than `audio.defer_to_wifi_hours`
(24 h) uploads over cellular regardless; stop cellular audio upload when
`data.cellular_cap_bytes_month` is reached and report `cellular_cap_reached`
(metadata and heartbeat continue — they are ~5 MB/day, N15).

### 4.6 Realtime channel

**Transport.** `wss://<host>/api/device/v1/ws`, opened by the foreground service
while it is alive. Auth: `Authorization: Bearer <access_token>` **on the
handshake** (an app client can set handshake headers; a browser cannot — which
is one more reason the panel does not use this channel, D-02). No token in the
query string: query strings land in access logs and N26 forbids that.

**Frames** (JSON, `type` discriminator):

server → app
```json
{"type":"command","command_id":"…","kind":"dial","payload":{"number":"+998935554433"},
 "issued_at":"…","expires_at":"…"}
{"type":"config","config_hash":"…","config":{…}}
{"type":"ping","at":"…"}
{"type":"logout","reason":"revoked|replaced|version_unsupported"}
```
app → server
```json
{"type":"ack","command_id":"…","status":"acknowledged","at":"…"}
{"type":"presence","state":"online","queue_records":3,"at":"…"}
{"type":"pong","at":"…"}
```

**Presence.** The socket being open means "reachable", not "healthy". `is_online`
in the panel is driven by **`last_heartbeat_at`** (REST, every 120 s, OFFLINE
after 10 min = 5 missed, UC-17), because a socket can be alive while capture is
dead. `ws_connected` is shown as a separate field on the device page — the two
answer different questions and conflating them is how a broken phone looks fine.

**Keepalive.** Server pings every 30 s; no pong within 15 s closes the socket.
Client reconnect: exponential backoff 1 s → 5 min with ±20 % jitter, reset on a
successful frame.

**When the socket is down** (this is the interesting half):
1. The command is created with `status='pending'` and `expires_at = now + 120 s`
   (UC-16's 2-minute rule, enforced server-side as well as on the device).
2. The server sends an FCM **high-priority data message** as a wake-up
   (`{"cmd":"poll"}` — never the command payload; FCM is a transport we do not
   control and the dial target is not going through it).
3. If no ack within **15 s** → `status='failed'`,
   `failure_reason='device_offline'`, and the panel shows it with a reason
   (UC-16 AC). **No call row is ever linked to a failed command** — enforced by
   the partial unique index on `calls.command_id` plus a service-layer check
   that refuses to link a command not in `acknowledged`.
4. Commands that expire unsent become `expired`; the app additionally discards
   any command whose `expires_at` has passed **on arrival**, so a phone that
   wakes up after 3 minutes never dials (UC-16 AC).

**The honest note about UC-16's 5-second bar.** `RISKS.md` (R3) and
`TASKS.md` §10 item 6 both flag it as possibly unachievable on doze-restricted
OEMs. This design does everything available in user space — a live socket held
by a foreground service, plus FCM high-priority as the wake-up — and then
**measures it**: `commands.latency_ms` is stored on every acknowledgement and
the device page shows p50/p90 per model. If p90 exceeds 5 s on any fleet model
during the acceptance window, the bar is renegotiated with evidence rather than
quietly missed. `commands.latency_ms` exists for exactly that conversation.

### 4.7 Panel API (`/api/v1`)

All endpoints require a user token unless marked public. All lists are cursor
paginated per §4.0. `{perm}` is the required permission.

**Auth** — `POST /auth/login` (public, rate-limited) → access token + refresh
cookie; `POST /auth/refresh`; `POST /auth/logout`; `GET /auth/me` → user +
resolved permission list + `must_change_password` (the panel's `can()` reads
this, never a hard-coded map).

**Refresh cookie: `HttpOnly; SameSite=Lax; Path=/api/v1/auth`, `Secure` in
production.** The path is the whole `/auth` group and **not**
`/api/v1/auth/refresh`, because `POST /auth/logout` needs the cookie too — under
the narrower path the browser would never send it, and logout would return 200
while silently failing to revoke the refresh token. That is a security bug
hiding in one path segment, so the wider value is deliberate: do not "tighten"
it back. `Secure` is set whenever the request arrives over TLS — i.e. always in
production behind Caddy — and is absent over plain HTTP in local development,
where a `Secure` cookie would simply never be stored and nobody could log in.

Password rules, decided so they are not invented three times: argon2id,
minimum 10 characters, no other composition rule, no expiry, no history check.
A password never appears in any response, any log or any audit `detail`.
`seed.py` creates the **first admin** from `SEED_ADMIN_EMAIL` /
`SEED_ADMIN_PASSWORD` with `must_change_password=true`, and refuses to run in
production with the default password still in place — an unreachable panel and a
panel with a known password are both deployment failures, and only one of them
is loud.

| Method + path | Perm | Notes |
|---|---|---|
| `GET /users` | `users:read` | filterable by role and `is_active`; never returns a hash or a token |
| `POST /users` | `users:write` | body `{email, full_name, role, agent_id?, password}`. **`role='sales'` requires `agent_id`** (409 `sales_user_requires_agent` otherwise); `agent_id` must reference a non-archived agent; `must_change_password=true` is set |
| `PATCH /users/{id}` | `users:write` | `full_name`, `role`, `agent_id`, `is_active`. Guards: a user cannot deactivate or demote **themselves** (409 `cannot_modify_self`), and the **last active `admin`** can be neither deactivated nor demoted (409 `last_admin`) — a panel with no admin can only be repaired from a shell |
| `POST /users/{id}/password` | `users:write` | admin sets a new password; sets `must_change_password=true`, revokes every refresh token of that user, writes an audit row |
| `POST /auth/password` | any authenticated | self-change: `{current_password, new_password}`; wrong current ⇒ 401; success revokes all other sessions of that user |
| `GET /agents` · `POST /agents` · `PATCH /agents/{id}` | `agents:read/write` | |
| `POST /agents/{id}/archive` | `agents:archive` | 409 if the agent holds an open assignment |
| `POST /agents/import` | `agents:write` | CSV/XLSX, ≤ 500 rows, dry-run first (`?dry_run=true` returns the diff) |
| `GET /numbers` · `POST /numbers` · `PATCH /numbers/{id}` | `numbers:*` | |
| `GET /numbers/{id}/assignments` | `numbers:read` | full history |
| `POST /numbers/{id}/assignments` | `numbers:write` | **409 `number_already_assigned`, `detail` names the current holder** (UC-01 AC) |
| `PATCH /assignments/{id}` | `numbers:write` | closes with `valid_to`; triggers `reattribute_calls` |
| `POST /numbers/{id}/enrolment-code` | `enrolment:write` | 201 with code + install URL + a copy-paste Uzbek message |
| `GET /enrolment-codes` · `POST /enrolment-codes/{id}/revoke` | `enrolment:read/write` | |
| `GET /enrolment/funnel` | `enrolment:read` | one row per agent: stage, since, blocking capability, last attempt outcome |
| `GET /enrolment/attempts` | `enrolment:read` | filterable; this is where UC-01's failures appear with timestamps |
| `POST /installations/{id}/attest` | `enrolment:attest` | body requires `reason`; writes audit; sets `verification_method='admin_attested'`, stage `verified_by_admin` (T142) |
| `POST /installations/{id}/revoke` | `installations:revoke` | UC-08; response includes queued records/bytes at last contact |
| `GET /installations` · `GET /installations/{id}` | `installations:read` | |
| `GET /devices` · `GET /devices/{installation_id}` | `devices:read` / `devices:read:own` | every UC-17 field |
| `POST /devices/{installation_id}/commands` | `commands:dial` (dial) / `settings:write` (config, logout, recheck) | 202 + command id |
| `GET /commands/{id}` | `devices:read` | status, latency_ms, failure reason |
| `GET /calls` | `calls:read` \| `calls:read:own` | filters below |
| `GET /calls/{id}` | same | 404 for wrong owner |
| `PATCH /calls/{id}` | `calls:note` | `note` only |
| `DELETE /calls/{id}` | — | **405 for every role** (UC-26) |
| `GET /calls/{id}/audio` | `audio:play` \| `audio:play:own` | Range, §4.8 |
| `DELETE /calls/{id}/audio` | — | **405 for every role** |
| `GET /calls/export` | `reports:export` | streaming CSV, §4.8 |
| `GET /reports/gap` | `reports:read` | UC-23 |
| `GET /reports/capture-regression` | `reports:read` | per model vs M0 baseline |
| `GET /reports/storage` · `GET /reports/data-usage` | `reports:read` | N18, N14/N15 |
| `GET /alerts` · `POST /alerts/{id}/ack` | `alerts:read` / `alerts:ack` | |
| `GET /audit` | `audit:read` | admin only |
| `GET /settings` · `PUT /settings` | `settings:read/write` | `PUT` takes `{key, value, confirm?}` |
| `GET /line-directory` · `POST /line-directory` · `DELETE /line-directory/{id}` | `settings:*` | recompute job runs on change |
| `GET /supported-models` · `PUT /supported-models/{id}` | `settings:*` | M0 baseline |
| `GET /app-versions` · `POST /app-versions` · `POST /app-versions/{id}/publish` | `appversions:*` | APK upload, sha256 computed server-side |
| `GET /callback-receivers` | `enrolment:read` | status, last heartbeat |
| `GET /monitor/board` | `monitor:read` | masked DTO |
| `GET /healthz` · `GET /readyz` | public | `readyz` checks DB + storage writability |

**`GET /calls` filters** (all optional, all combinable, all indexed):
`agent_id[]`, `number_id[]`, `installation_id`, `direction`, `disposition`,
`call_type`, `has_audio`, `audio_missing_reason[]`, `capture_route[]`,
`date_from`, `date_to` (Asia/Tashkent calendar dates, inclusive),
`remote_number` (matched on the 9-digit key), `q` (contact name, ILIKE with
metacharacters escaped — copy `_ilike_ekranla` from the reference module),
`min_duration_sec`, `max_duration_sec`, `device_model`, `app_variant`.
Sort: `received_at` (default, stable) | `started_at` | `duration_sec`, each
`asc|desc`, each paired with `id`.

**Call response shape.** Two rules decide what a call carries, and both exist
because the first version of this section got them wrong:

1. **Every id that the UI must show as a name comes back with its display
   value.** A list response of pure ids forces the panel to build a client-side
   directory and re-fetch it on every filter change, and it produced a
   `device_model` *filter* whose column could not be rendered. Filtering on a
   value the response cannot display is a contract defect, not a UI gap.
2. **Capture route and the audio reason are part of the call, not of the file.**
   They live on `call_audio` (§3.6) but they answer questions about the *call*,
   and they are read by more than the detail page: `capture_route` is what the
   M0 baseline is computed from and what UC-23's regression alert compares
   against (N4). A field the alerting depends on cannot be absent from the API
   that everything else reads.

```json
// GET /calls — list item. GET /calls/{id} returns the same object plus
// `note`, `ring_sec`, `clock_skew_sec`, `command_id` and the audit trail.
{ "id": "…", "client_call_id": "…",
  "direction": "outgoing", "disposition": "answered", "call_type": "external",
  "remote_number": "+998935554433", "contact_name": "Anvar do'kon",
  "started_at": "2026-09-04T08:59:02Z", "answered_at": "2026-09-04T08:59:11Z",
  "ended_at": "2026-09-04T09:07:44Z", "duration_sec": 513,
  "received_at": "2026-09-04T09:08:02Z",
  "agent":  {"id": "…", "full_name": "Aziz Karimov"},
  "number": {"id": "…", "e164": "+998901112233"},
  "device": {"installation_id": "…", "model": "Xiaomi Redmi Note 12",
             "app_variant": "legacy28"},
  "audio":  {"available": true,
             "missing_reason": null,
             "capture_route": "oem_file_harvest",
             "duration_ms": 513400,
             "duration_mismatch": false,
             "deleted_at": null,
             "url": "/api/v1/calls/…/audio"} }
```

- `audio.available` is `has_audio` **and** `deleted_at IS NULL`. A call whose
  audio expired under retention returns `available: false`,
  `missing_reason: null` and a non-null `deleted_at` — the panel must say
  "muddati tugagan", not "yozuv yo'q", because they are different facts and only
  one of them is somebody's fault.
- `audio.missing_reason` is never null when `available` is false and
  `deleted_at` is null (the §3.5 constraint, surfaced).
- `audio.url` is present only when `available`; it is a path, never a signed or
  public URL (N20).
- For a `sales` caller the `agent` object is still returned — it is always their
  own — but the panel hides the column; the API does not special-case it.
- `viewer` never reaches this endpoint: `/monitor/board` has its own DTO with
  the masked number (§4.1 rule 3).

### 4.8 Audio playback (UC-20, N43) and export

**`GET /api/v1/calls/{id}/audio`** — `audio:play` or `audio:play:own`.

- **Range is mandatory (N43).** `Accept-Ranges: bytes` on every response;
  `Range: bytes=start-end` ⇒ **206** with `Content-Range: bytes start-end/total`
  and `Content-Length` of the slice. No Range ⇒ 200 with the whole body.
  Unsatisfiable range ⇒ 416 with `Content-Range: bytes */total`.
- `Content-Type: audio/ogg` (Opus) or `audio/mp4` (AAC fallback).
  `Content-Disposition: attachment; filename="<agent>_<yyyymmdd-hhmm>.<ext>"`
  **only** when `?download=true`; inline otherwise, so the player streams.
- No token ⇒ **401 and zero bytes** (UC-20 AC). Wrong owner ⇒ 404.
  Deleted by retention ⇒ **410 `audio_expired`**.
- **Audit (UC-24):** an `audit_log` row (`action='audio_play'`) is written when
  the request has **no Range header or a range starting at byte 0**, deduped
  per `(user_id, call_id)` within 60 s. Subsequent ranges at offset > 0 — which
  is what a seek is — write nothing. Result: exactly one row per playback start,
  which is the acceptance criterion, and seeking a 20-minute file does not
  produce 40 audit rows. `?download=true` always writes `action='audio_download'`.
- **The panel cannot put an `Authorization` header on `<audio src>`.** The
  Service Worker bridge from `../BonviZvonki/services/web/public/audio-sw.js` is
  ported wholesale: the SW intercepts `/api/v1/calls/*/audio`, adds the header,
  and the browser's own player issues real Range requests, so seek is native.
  Fallback where a Service Worker is unavailable (non-secure origin, old
  browser): `fetch` + `blob:`, which still seeks but downloads the whole file
  first. Both paths are required; the fallback is not optional politeness, it is
  what keeps a LAN/`http://` demo working.

**`GET /api/v1/calls/export`** — same filters as `GET /calls`, streamed CSV
(UTF-8 **with BOM**, `;` delimiter — Excel in a ru/uz locale otherwise renders
one column). No audio, no columns the role may not see (a `sales` export is
own-rows-only and carries no other agent's name). Row count **must equal** the
`total` shown for the same filter (UC-22) — the export re-runs the same filter
builder, never a parallel implementation. Target 50,000 rows < 30 s; the query
is a server-side cursor, not `fetchall`.

### 4.9 Service API (`/api/service/v1`) — the committed export contract

Release 1 must not make release 2 impossible (§5.4). This is a **contract**,
versioned, and changes to it are breaking changes.

**`GET /export/calls?since=<seq>&limit=500`** — `export:read`.
```json
{"items":[{
  "id":"…","seq":184213,
  "agent":{"id":"…","full_name":"Aziz Karimov"},
  "agent_number_e164":"+998901112233","agent_number_key":"901112233",
  "remote_number_e164":"+998935554433","remote_number_key":"935554433",
  "direction":"outgoing","bonvizvonki_direction":"outbound",
  "disposition":"answered","answered":true,
  "call_type":"external",
  "started_at":"…","answered_at":"…","ended_at":"…","duration_sec":513,
  "received_at":"…",
  "has_audio":true,"audio_missing_reason":null,
  "audio_ref":"/api/service/v1/export/calls/<id>/audio",
  "audio_sha256":"…","audio_duration_ms":513400,
  "capture_route":"oem_file_harvest",
  "device_model":"Xiaomi Redmi Note 12","app_variant":"legacy28"
}],"next_since":184713,"count":500}
```
Everything BonviZvonki's pipeline needs is present: direction, both numbers **in
its own last-9 key form**, timestamps, duration, agent identity,
internal/external, and a stable audio reference (§5.4 consequence 1). Ordering
is `seq ASC` with the settling window of §3.12, so two consecutive full passes
over an unchanging dataset return identical row sets (UC-29 AC).

**`GET /export/calls/{id}/audio`** — `export:audio`. **Range support is
mandatory here too (N43, §5.4 consequence 2)**: BonviZvonki streams audio rather
than copying it, so 206 + `Content-Range` is the whole point. Same 401/404/410
behaviour, and every access writes an audit row with
`actor_type='service'`.

**`GET /export/agents`** — `export:read`. `id`, `full_name`, `is_active`, and
the agent's number history as `[{e164, key, valid_from, valid_to}]`. Needed
because BonviZvonki's L3 failure was exactly this mapping arriving wrong.

**`POST /callback-events`** — `callback:report`, used by the callback receiver
(§9.4), not by BonviZvonki:
`{"caller_e164":"+998901112233","cli_presented":true,"receiver_epoch_ms":…,"received_at":"…"}`.

A `service` token **cannot** write anything else, cannot read `/users`, and
cannot read `/audit` — asserted by the RBAC harness for every route
(UC-29 AC).

---

## 5. Web panel

Desktop-first, Uzbek only, last two versions of Chrome and Edge. Create/edit is
**modal-only** — the house convention. Structure mirrors the reference:
`panel/src/app/router.tsx`, `panel/src/modules/<module>/`, `panel/src/shared/`.

### 5.1 RBAC is enforced in three places, and only one of them is security

1. **Server** — the only real control (§4.1).
2. **Route gate** — `<Gate anyOf={[...]}>` around every route element, copied
   from `../BonviZvonki/services/web/src/app/router.tsx`. A user who types a URL
   they lack the permission for is redirected to `/`.
3. **Nav menu** — items filtered by `can(perm)`.

**Hiding a menu item is not access control.** The nav filter exists so people
are not shown doors they cannot open; the gate exists so a bookmark does not
render a broken page; the server exists so neither of the first two matters.
A test asserts that for each role, every route reachable through the nav is also
permitted by the gate **and** returns 2xx from the API — and that at least one
gated route returns 403/404 from the API when requested directly.

`can()` reads the permission list from `GET /auth/me`. It never contains a
hard-coded role→permission map; a second copy of the matrix is a second thing to
forget to update.

### 5.2 Pages

| Route | Page | Gate (`anyOf`) | Contents |
|---|---|---|---|
| `/login` | Login | public | Email + password, Uzbek errors from the N35 envelope |
| `/` | Dashboard | any authenticated | Today: calls captured, devices online/offline, open alerts by severity, enrolment progress bar, storage used. Every tile links to the page that explains it |
| `/enrolment` | **Rollout funnel** | `enrolment:read` | One row per agent: stage chip (`invited → installed → permitted → number_verified → capturing`, plus `needs_assisted_install`, `install_disappeared`, `verified_by_admin`), time in stage, the **blocking capability by name**, last attempt outcome, buttons: issue/reissue code, copy install link, attest (admin), revoke (admin). Callback-receiver status banner at the top — if the receiver is down, nobody can enrol and the page says so before anyone tries |
| `/agents` | Agents | `agents:read` | List + modal create/edit; archive with the "has calls" guard; roster import (dry-run diff first) |
| `/agents/:id` | Agent detail | `agents:read` | Number history as a **timeline** (this is where the time-boxed mapping becomes visible), calls, devices, alerts |
| `/numbers` | Registered numbers | `numbers:read` | Number, operator, SIM owner (company/employee — R10), current holder, active installation, history. Assign modal surfaces 409 by **naming the current holder** |
| `/devices` | Device health | `devices:read` | Online/offline, last contact, app version + variant, OS, battery, battery-optimisation exemption, **capability matrix (one column per capability, colour = state)**, recording route + whether it currently works, queue depth (records and MB), clock skew in seconds, cellular MB this month. `install_disappeared` rendered distinctly from `offline` |
| `/devices/:installationId` | Device detail | `devices:read` \| `devices:read:own` | The above plus capability transition history, command history with `latency_ms`, call-log delta per day, "Re-check now" (`recheck` command), "Dial" (`commands:dial`), "Revoke" (admin) |
| `/calls` | Call list | `calls:read` \| `calls:read:own` | Filters of §4.7, **fixed 50-row keyset pages** (the page-size picker was withdrawn at the client's request — `docs/ASSUMPTIONS.md`, 2026-09-13; the endpoint still accepts `limit` up to 1000), inline audio button. `sales` sees its own rows and the agent column is hidden |
| `/calls/:id` | Call detail | same | All metadata, capture route, why audio is missing (in Uzbek), player, note (`calls:note`), audit trail of who listened (admin) |
| `/reports/gap` | **Gap report** | `reports:read` | Calls without audio grouped by reason × agent × device model, totals and % of answered; per-device call-log delta; per-model regression flag vs the M0 baseline. Totals reconcile exactly with `/calls?has_audio=false` — the same filter builder produces both |
| `/reports/storage` | Storage & data | `reports:read` | GB now, 30-day growth, projection against the 250 GB provision; per-device cellular MB against the 1 GB cap |
| `/alerts` | Alerts inbox | `alerts:read` | Severity, cause, agent, device, first/last seen, count; acknowledge (`alerts:ack`, admin only) |
| `/audit` | Audit log | `audit:read` | Who, what, which object, when, from which IP. Read-only, no delete affordance anywhere |
| `/users` | Users | `users:read` | Panel accounts only — **not** agents. List with role and linked agent; modal create/edit; "reset password"; deactivate. The `sales` role field forces an agent picker, and the form explains in one Uzbek line that this creates a login, not a salesperson. Effectively admin-only, because `users:read` is admin-only (§4.1) |
| `/settings` | Settings | `settings:read` | Retention (confirmation dialog below 3 months), alert thresholds, minimum app version, line-directory extras with suffix rules, supported-model table, working hours/holidays. Write requires `settings:write` |
| `/settings/app-versions` | App releases | `appversions:read` | Upload APK per variant, sha256 shown, publish, which devices are on which version |
| `/monitor` | TV board | `monitor:read` | **No AppShell, full screen.** Who is online, calls today, capture health. Numbers masked to last 4 digits **server-side**, no audio, no names of clients |
| `/i/:code` | Install landing | **public** | §8.1 — the agent-facing install page |

### 5.3 Panel behaviour rules

- **No WebSocket** (D-02). TanStack Query with `refetchInterval`: 15 s on
  `/enrolment`, `/devices`, `/alerts`, `/monitor`; 60 s elsewhere; `staleTime`
  30 s. Every list is `keepPreviousData` so paging does not flash.
- **Errors** are rendered from `error.code` through an Uzbek message catalogue;
  `error.message` is the fallback. No raw stack trace, no English string reaches
  a user (T100).
- **The audio player** uses the Service Worker bridge (§4.8) and shows, for a
  call without audio, the Uzbek reason text rather than a dead control.
- **Empty states are explicit**: "hali qo'ng'iroq yo'q" is different from
  "filtr bo'yicha topilmadi" is different from "qurilma ulanmagan".
- **Dates** render in Asia/Tashkent with the offset visible on hover; durations
  as `mm:ss`.

---

## 6. Server composition

Layout and layering are `CONVENTIONS.md` §2–§3; repeated here only where this
document depends on them.

```
core/        clock.py config.py database.py deps.py enums.py errors.py logging.py
             messages_uz.py models.py permissions.py phone.py storage.py
api/device/  the Android client   — versioned, additive-only  (§4.2–§4.5)
api/panel/   the web panel        — ships with the server     (§4.7–§4.8)
api/service/ machine export       — versioned, additive-only  (§4.9)
modules/<m>/ models.py · schemas.py · service.py · rules.py (only if it has content) · tests/
main.py      routers registered here, and nowhere else
worker.py    the scheduler process (§10.4)
seed.py      app_settings defaults, first admin, supported-model seed
```

**Three files, not four directories.** A module is `models.py` (SQLAlchemy only,
no queries), `schemas.py` (Pydantic), `service.py` (business logic, owns the
transaction) and an optional `rules.py` (pure functions). Routers live outside
the module in `api/<surface>/<name>.py`, because a module is reached from more
than one surface — `calls` is read by the panel, written by the device and
exported to the service API, and three routers over one service is the shape
that makes that true. An empty layer created "for symmetry" is a review failure.

**Release-1 module set, fixed** (`CONVENTIONS.md` §3): `auth`, `users`,
`agents`, `numbers`, `enrolment`, `installations`, `devices`, `calls`, `audio`,
`alerts`, `gaps`, `commands`, `exports`, `audit`, `settings`, `catalog`.

Three names differ from earlier drafts of this document and the built code is
right: **`gaps`** (not `reports`) — the gap report and the regression watch;
**`exports`** (not `export`); **`catalog`** — the line directory, the
supported-model table, `model_capture_stats` and `app_versions`, i.e. the
reference data an admin curates. There is no `callback` module: the receiver,
its events and `number_verifications` belong to **`enrolment`**, because
"prove this phone is on this number" is one workflow and splitting it would put
half a state machine in each half.

**`gaps` and `exports` have no `models.py`.** They own no table — they compute
their answers from `calls`, `call_audio`, `call_log_deltas` and
`model_capture_stats`. A module with a service and no model is normal here and
must not be "fixed" by inventing a table for it.

Two rules carried from the reference project because both were paid for once:

- **`core/models.py` imports every ORM module** with `# noqa: F401`. Without it
  `NoReferencedTableError` appears at runtime, on one code path, in production —
  not in tests. Every process entry point (`main.py`, `worker.py`, `seed.py`)
  imports that one module, and a test asserts the list is complete.
- **`AppError` subclasses know nothing about FastAPI**; `main.py` translates
  them into the envelope. Two handlers: `AppError` and `RequestValidationError`
  (the latter rewritten into Uzbek).

**Tests build the schema with `alembic upgrade head`, never `create_all`.**
`conftest.py` runs the real migration against a real PostgreSQL. `create_all`
would build a schema from the models — which is precisely the schema the
migration is supposed to be checked against, so the one thing that can go wrong
would be the one thing untested. It also means the CHECK constraints, partial
indexes, the exclusion constraint and the audit trigger of §3 are exercised by
every test, not just by the migration test.

**`core/storage.py`** defines the seam D-01 depends on:

```python
class AudioStorage(Protocol):
    def put(self, key: str, source_path: Path) -> StoredObject: ...
    def open_range(self, key: str, start: int, end: int | None) -> IO[bytes]: ...
    def stat(self, key: str) -> ObjectStat: ...
    def delete(self, key: str) -> None: ...
```
`LocalFsAudioStorage` is the release-1 implementation. An `S3AudioStorage` is
*not* written now; the interface exists so that writing it later is a
configuration change and not a refactor. **No code outside
`modules/audio/service.py` and `core/storage.py` may open an audio file by
path.**

---

## 7. Android app architecture

Kotlin, Compose, Hilt, Room, WorkManager, Retrofit/OkHttp. `minSdk 26` (N32).
`../CallSentry` is readable reference for call detection and OEM harvesting, and
its `RecordingStrategy` interface is adopted as-is (§7.3). What is *not* copied
is the freedom its layout gave the recording code to reach into `/sdcard` from
anywhere — here that is confined to one package and, more importantly, to one
**type** (§7.4).

### 7.1 One Gradle module, package-level separation

**`:app` is the only Gradle module** (`CONVENTIONS-CLIENT.md` §5). Multi-module
Gradle buys build-time parallelism and enforced dependency boundaries; this
project needs neither — there is one app and no second consumer of any layer —
and two product flavours multiplied by several modules is exactly where Hilt
binding becomes fiddly for no benefit. The boundary that actually matters is
the privacy boundary, and that is enforced by a **type signature**
(`OemHarvestStrategy.locate(Decision.Capture, …)`), which a Gradle module
boundary would not improve.

Package root `uz.bonvi.call`:

```
core/          Result, AppError, time, phone key (last-9, same vectors as the server),
               Capabilities.kt  ← the ONLY place Build.VERSION.SDK_INT may appear
domain/        pure Kotlin types + use cases (CallRecord, CaptureRoute, Capability,
               Decision, PrivacyBoundary)
data/local/    Room (queue, records, capability cache), DataStore (session, config)
data/remote/   Retrofit API, generated DTOs from contract/openapi-device-v1.json,
               OkHttp, WS client
data/repository/
capture/       RecordingStrategy + CaptureRouter + OemHarvestStrategy +
               MediaRecorderStrategy + transcode (Opus/Ogg, AAC fallback)
service/       foreground service, receivers, workers, the call state machine
ui/            enrolment (E1–E6, §8), home, calls, diagnostics — Compose + ViewModels
di/            Hilt modules; flavour-specific bindings live in src/<flavour>/…/di/
```

**Architectural rules, enforced by test rather than by review:**
- `MediaStore`, `MediaRecorder`, `AudioRecord`, `Environment.getExternalStorageDirectory()`
  and any external-path `java.io.File` appear **only under `capture/`**.
  `grep -rn` outside that package must return nothing.
- `Build.VERSION.SDK_INT` appears **only in `core/Capabilities.kt`**
  (`CONVENTIONS-CLIENT.md` §7). Everything else asks a capability, not a version.
- `ui/` never touches `data/remote` or `capture/` directly; it goes through
  `domain/` use cases. This is the one layering rule worth enforcing without a
  module system, because it is the one that decides whether the enrolment screens
  can be tested without a phone.

### 7.2 The `targetSdk` decision is a build variant, not an assumption

`S1-RECORDING.md` proves `targetSdk 28` is load-bearing for the prototype's
audio; `ASSUMPTIONS.md` (2026-09-04) then decided both variants are built and
**M0 measures which wins, defaulting to 34**. Therefore:

```kotlin
flavorDimensions += "captureTarget"
productFlavors {
    create("legacy28") { dimension = "captureTarget"; targetSdk = 28
        buildConfigField("String", "APP_VARIANT", "\"legacy28\"") }
    create("modern34") { dimension = "captureTarget"; targetSdk = 34
        buildConfigField("String", "APP_VARIANT", "\"modern34\"") }
}
```

- Permissions differ **per flavour manifest**, never at runtime:
  `src/legacy28/AndroidManifest.xml` adds `READ_EXTERNAL_STORAGE` /
  `WRITE_EXTERNAL_STORAGE`; `src/modern34/AndroidManifest.xml` adds
  `MANAGE_EXTERNAL_STORAGE` and `READ_MEDIA_AUDIO`, and declares the
  foreground-service types Android 14 requires
  (`microphone`, `phoneCall`, `dataSync`).
- The **only** flavour-specific source is `src/<flavour>/…/di/CaptureModule.kt`
  (which locator `OemHarvestStrategy` is given) plus the two manifests. With a
  single Gradle module that is two small source sets, not a flavour × module
  binding matrix.
- `BuildConfig.APP_VARIANT` is sent on **every** request and stored on every
  call and heartbeat, so per-variant capture rate is a query, not an experiment
  someone has to remember they ran.
- **Nothing branches on `targetSdk`, and `Build.VERSION.SDK_INT` appears only in
  `core/Capabilities.kt`.** Capture code asks
  `Capabilities.canReadOemRecordings()` / `canUseVoiceRecognitionSource()`,
  never a version number — a version check scattered through the capture path is
  how the two variants silently diverge.

The build produces four artefacts (`legacy28`/`modern34` × `debug`/`release`).
Release 1 ships whichever variant M0 selects; the other stays buildable, which is
what makes R9 ("a future Android release breaks the app") a rebuild rather than
a rewrite.

### 7.3 The capture-strategy seam

`RecordingStrategy` is adopted from `../CallSentry/service/recording/RecordingStrategy.kt`
unchanged — `isSupported()`, `start(File)`, `stop(): File?`
(`CONVENTIONS-CLIENT.md` §6) — and every implementation additionally declares
the route it represents and the reason it failed:

```kotlin
// capture/ — the seam. Two implementations ship on day one.
interface RecordingStrategy {
    val route: CaptureRoute                    // recorded per call, drives the M0 baseline
    fun isSupported(): Boolean                 // has a test for the FALSE branch (it is the common one)
    fun start(target: File)
    fun stop(): File?
    fun lastFailure(): AudioMissingReason?     // from the closed enum, never free text
}
```

`CaptureRouter` holds the ordered list, takes the first result that produces a
file, and **records which strategy produced it**:

1. **`OemHarvestStrategy`** — preferred. S1 established that the handset's own
   recorder is what captures both voices. Its `locate()` is the privacy
   boundary (§7.4). Which locator it uses is a *capability*, not a variant:
   `Capabilities.canReadOemRecordings()` selects the legacy raw-path locator or
   the MediaStore locator, bound in the flavour's `di/CaptureModule.kt`.
2. **`MediaRecorderStrategy`** — fallback, one class, trying audio sources in
   descending order of quality:
   `VOICE_RECOGNITION` (captures the far end on Samsung and some others) →
   `VOICE_COMMUNICATION` → `MIC` (near side only). The source that succeeded is
   what `route` reports, so `app_voice_recognition` and `app_mic` remain
   distinguishable in the data even though they are one class.

The interface, `CaptureRouter`, `CaptureRoute`, the reason enum and a stub
second implementation are **not blocked on S1 or M0** — only the real locators
are (§11.4 item 8). Every attempt writes `capture_route` plus the outcome, so
the panel can show which mechanism produced each recording. A strategy that
returns no file yields a **reason from the closed enum** and the call is still
uploaded (UC-14: a call is never dropped because audio failed).

### 7.4 The privacy boundary, in code (N28, R18, UC-15)

Two guards, in this order, and both are mandatory:

**Guard 1 — subscription resolution, fail closed.** Before *anything* is
recorded or even written to the local queue, `SubscriptionResolver` must
positively identify the call's subscription and match it to the enrolled
`sim_subscription_id`. Sources, in order: `TelephonyManager` subscription
callbacks / `EXTRA_SUBSCRIPTION_INDEX`, the call-log `PHONE_ACCOUNT_ID` /
`SUBSCRIPTION_ID` column, the `PhoneAccountHandle` from the Telecom API.
If none of them yields a confident answer, the call is **unregistered**: no
metadata, no number, no duration, no audio, nothing queued — and the local
`subscription_unknown` counter for the day is incremented and reported in the
call-log delta (§4.4). Capturing a private call by accident is a worse failure
than missing a work call, and this is where that sentence becomes code.

**Guard 2 — time-window matching in the shared folder, enforced by a type.**
The OEM recordings folder holds the employee's private recordings too.
`OemHarvestStrategy.locate()` takes a **`Decision.Capture`**, not a raw number
and not a call id — the only way to obtain a `Decision.Capture` is through
`PrivacyBoundary`, which Guard 1 above is the sole producer of
(`CONVENTIONS.md` §8). A caller that has not proved the call is on the
registered subscription cannot even express the call to the locator. That
signature is the boundary; the checks below are what it then enforces. It may
read **only** files whose `lastModified` falls inside
`[answered_at − 5 s, ended_at + 120 s]` of a *captured registered-number call*
(the window from `S1-RECORDING.md`), larger than 2 KB, with an audio extension.
It never lists the folder for any other purpose, never copies an unmatched file,
never deletes or modifies anything, and retries the match 4× at 1 s intervals
because the OEM writer flushes late. An unmatched recording is discarded on the
device with reason `attribution_failed` — **never uploaded and then sorted out
server-side.**

Test that must exist (T117, §10 DoD): place calls on the unregistered SIM and a
private recording in the same folder; assert the server received zero bytes
about it **and the local queue is empty**.

### 7.5 Call lifecycle state machine

One state machine in `service/`, owned by the foreground service, persisted to
Room on every transition so a process death resumes rather than restarts.

```
        ┌──────────── unregistered subscription ───────────► DISCARDED
        │                                                     (counter only)
IDLE ──► IDENTIFYING ──► RINGING/DIALING ──► ACTIVE ──► ENDED
                                │                        │
                                └── not answered ─────────┤
                                                          ▼
                                                   RECONCILING ──► METADATA_QUEUED
                                                          │              │
                                                          │              ▼
                                                          │        AUDIO_PENDING ──► AUDIO_QUEUED ──► COMPLETE
                                                          │              │
                                                          └──────────────┴──► NO_AUDIO(reason) ──► COMPLETE
```

- `IDENTIFYING` runs Guard 1. A call that cannot be attributed to the registered
  subscription reaches `DISCARDED` before any field is written.
- `RECONCILING` reads the device call log for this call (retry up to 15 min at
  30 s intervals): corrects `direction`, `disposition`, `started_at`,
  `duration_sec`; computes `client_call_id` (§3.10). Unanswered outgoing gets
  `answered_at=null, duration=0` — never reported as a conversation (UC-09).
- **Call waiting / second RINGING during an active call is a separate machine
  instance keyed by call id**, not ignored — the prototype ignored it and that is
  in R5. Concurrency cases are named tests (UC-15 AC).
- Recovery sweep (UC-13): on every start, and every
  `device.call_log_sweep_hours`, the service scans the call log for the
  registered subscription since the last watermark, creates records for anything
  missing with `source='call_log_recovery'` and
  `audio_missing_reason='app_not_running'`, and reports the counts
  (`POST /call-log-delta`). If the call log itself was cleared, the sweep reports
  the gap rather than inventing rows.
- Boot (`BOOT_COMPLETED`, `LOCKED_BOOT_COMPLETED`), `MY_PACKAGE_REPLACED`,
  `onTaskRemoved` + AlarmManager restart, and a 15-minute `WatchdogWorker` all
  restart the service; if the OS refuses, the app reports `service_not_running`
  on its next contact (UC-05).

### 7.6 Audio format, and the decided fallback

Target (N17, N21): **mono, 16 kHz, Opus ≤ 24 kbps, in Ogg, transcoded on the
device before upload.** `capture/transcode/` uses `MediaCodec` (`audio/opus`)
plus a small Ogg page writer, because `MediaMuxer` only gained OGG output at
API 29 and the `legacy28` variant must run on API 26–28.

**Decision, so nobody improvises it at 2 a.m.:** where a device has no usable
Opus encoder, the app transcodes to **AAC-LC 24 kbps mono 16 kHz in MP4**, sets
`codec="aac_lc"`, `container="mp4"`, and uploads normally. The panel plays it
(Chrome/Edge play AAC-in-MP4 natively), N21 still holds (ASR engines accept
AAC), and the storage budget is unchanged. The fallback is **counted**: the
device page and the gap report show how many recordings used it, because a fleet
quietly running on the fallback is a fact M0 should have caught.

Never: a second lossy transcode on the server (the server never re-encodes),
uploading the OEM file untranscoded (44.1 kHz stereo AAC is ~5× the data, spent
from the employee's plan — R14), or storing raw PCM.

### 7.7 Durable queue and upload policy

Room tables: `call_records` (the queue), `audio_items`, `outbox_events`,
`capability_reports`, `sweep_watermarks`.

- **Oldest-first**, always. Metadata and audio are separate queues; metadata
  wins every tie (R7: the cheap and important half lands first).
- `MetadataUploadWorker`: constraint `CONNECTED`, exponential backoff 30 s → 4 h.
- `AudioUploadWorker`: constraint `UNMETERED`; an item older than
  `audio.defer_to_wifi_hours` is re-enqueued with `CONNECTED` and uploads over
  cellular subject to the monthly cap (N7, N14).
- `HeartbeatWorker`: periodic 15 min — WorkManager's floor. **The 120-second
  heartbeat comes from a coroutine timer inside the foreground service**, not
  from WorkManager; the worker is the safety net for when the service is dead,
  and that distinction is the difference between UC-17's 10-minute detection
  working and not.
- **Poison parking (N9):** 5 failed attempts → `parked`, `POST /events`
  `poisoned_record`, queue continues. Parked items are visible in the panel and
  in `ui/diagnostics`.
- **Capacity (N8, N10):** ≥ 30 days / ≥ 2000 records / ≥ 1 GB audio. On
  exhaustion, or when free space < 1 GB, the app **stops recording new audio**,
  raises `queue_full` / `storage_low`, and marks subsequent calls
  `queue_space_exhausted`. It never deletes captured audio and never drops
  metadata — 30 days of metadata is under 2 MB.
- **Local audio is deleted only after the commit response confirms the SHA-256**
  (N11). Revocation deletes all of it, uploaded or not, then confirms (UC-08).
- **Uninstall warning (N12):** if the queue is non-empty the app warns before it
  can be uninstalled from within the app and shows the depth on the home screen;
  Android cannot block an uninstall from Settings and the product does not
  pretend otherwise.

### 7.8 Capability tracking (UC-03, UC-06, N42)

`CapabilityChecker` per capability, and **every check exercises the capability,
never reads the permission flag**:

| Capability | The actual check |
|---|---|
| `microphone` | 1-second `AudioRecord` capture to a temp file; bytes > threshold and not all-zero; file deleted immediately |
| `phone_state` | read the current call state |
| `call_log` | 1-row query against the call-log provider |
| `contacts` | 1-row query; **optional** — degrades `contact_name` only |
| `notifications` | `areNotificationsEnabled()` + the foreground-service channel is not blocked |
| `call_phone` | permission + `ACTION_CALL` resolvable (needed for UC-16) |
| `battery_exemption` | `PowerManager.isIgnoringBatteryOptimizations()` |
| `storage_access` | variant-specific: legacy — read a known folder; modern — `Environment.isExternalStorageManager()` or a MediaStore audio query |
| `oem_autostart` | OEM-specific where the platform exposes a check; otherwise `unknown` with the user-attested flag, never silently `granted` |
| `foreground_service` | the service is running and its notification is posted |
| `oem_recorder` | a recordings folder exists and is readable, or MediaStore returns call-recording entries |
| `subscription_resolution` | the enrolled `sim_subscription_id` is currently present and resolvable |

Reported on: enrolment step completion, app start, every
`device.capability_recheck_hours` (6 h), `MY_PACKAGE_REPLACED`, the `recheck`
command, and immediately on any observed change.

**Never-false-ready (UC-03 AC):** `capture_state = capturing` requires *every*
required capability in `granted_working` **and** a verified installation. The
home screen and the state sent to the server are computed from the same
function; there is no second code path that could disagree. A test denies each
permission in turn and asserts both.

---

## 8. The enrolment flow, screen by screen

**This is R17, the project's top practical risk, and N40 is a measured gate:
3 of 3 unaided salespeople reach `capturing` in under 15 minutes each.** The
design below is built to pass that specific test. Every screen has: what it
shows, the exact check that turns it green, what happens on failure, and the
server event it emits. Uzbek strings are given where the wording is
load-bearing; the rest is the string catalogue's business.

**Time budget** (target 11 min, 4 min of slack against the 15-minute bar):
landing + download 3 min · install past the warnings 3 min · code 1 min ·
permissions 3 min · number verification 1 min.

**Instrumentation:** the app timestamps every step and posts
`enrolment_attempts(kind='step_timing', step='E3', duration_ms=…)`. N40 is
therefore measured by the product on every future enrolment, not only by a
stopwatch on test day — which matters because the fleet grows and phones get
replaced.

### 8.1 Before the app: the install landing page

`GET /i/{code}` — **public** (the code is the only secret; it is single-use and
expires in 24 h). The page is Uzbek, mobile-first, and one column.

1. **Header**: "Salom, Aziz. Bu ilova +998 90 111-22-33 raqamidagi ish
   qo'ng'iroqlaringizni yozib boradi." The number the app will record is on
   screen before anything is installed — N41 starts here, not after login.
2. **Four lines of what it does and does not do**: work-number calls are
   recorded; the second SIM is never touched; the contact book, SMS, photos and
   location are never uploaded; the data cost and who pays it.
3. **Step 1 — download.** Big button → `GET /i/{code}/apk` (302 to
   `/api/v1/app/download/{version_code}` for the M0-selected variant). The APK
   itself carries no credential — the link is per-agent so the panel can show
   who downloaded and when, which is the first funnel signal after `invited`.
4. **Step 2 — the browser's "this file may harm your device" warning.** Shown in
   advance as a **photograph of the actual screen for this Android version**,
   with the button to tap circled. The OS version is detected from the
   User-Agent, with a manual selector under "Boshqa Android versiyasi".
5. **Step 3 — "Install unknown apps" for the browser**, per-OEM path, photograph
   + caption.
6. **Step 4 — Play Protect: "Xavfli ilova bloklandi"**, photograph, and the
   plain sentence that this warning is expected because the app is not
   distributed through Google Play (N33), with the exact tap sequence
   ("Batafsil" → "Baribir o'rnatish").
7. **Step 5 — open the app.** A `bonvicall://enrol?code=XXXXXXXX` deep link so
   the code does not have to be typed; the code is also displayed for manual
   entry.
8. **Stuck?** A permanent "Yordam kerak" button that posts
   `enrolment_attempts(outcome='rejected', step='landing')` and moves the agent
   to `needs_assisted_install` in the panel. **A stalled enrolment must be an
   event, not silence** — a silently stalled rollout looks exactly like a working
   one until go-live.

If Play Protect removes the app after a successful install, the missing
heartbeat turns the agent into `install_disappeared` (distinct from `offline`)
within `alerts.device_offline_minutes` (UC-02 AC).

### 8.2 In the app: E1 → E6

**E1 — "Kodni kiriting".** Prefilled from the deep link. Verify →
`POST /enrolment/redeem`. On success the screen shows the agent's name and the
number being registered and moves on. Failures, each with its own Uzbek
sentence and its own next action, never a generic error: code not found ·
already used (naming when, and on which device model) · expired (with "yangi kod
so'rang") · an active installation already exists on another phone (offers
"Bu telefonga ko'chirish", which is the UC-07 rebinding path).

**E2 — "Ruxsatlar" — one permission at a time.** A vertical checklist where
exactly one row is expanded. Each row: one Uzbek sentence of *purpose and
consequence* ("Mikrofon bo'lmasa suhbat yozilmaydi, lekin qo'ng'iroq baribir
qayd etiladi"), a single button, and a live result chip. The row turns green
**only when the capability check of §7.8 passes** — not when the dialog was
dismissed.

Order, chosen so the alarming ones come after the agent has seen two easy
successes: `phone_state` → `call_log` → `notifications` → `microphone` →
`call_phone` → `contacts` (marked *ixtiyoriy*, skippable) → `battery_exemption`
→ `storage_access` → OEM steps.

- **`granted_not_working`** (an OEM permission manager reporting granted while
  blocking) shows a distinct state — "Ruxsat berilgan, lekin ishlamayapti" —
  with the OEM's own screen path, because retrying the system dialog will never
  fix it.
- **`denied_permanently`** switches the row to "Sozlamalardan yoqing" with an
  "Ochish" button deep-linking to the app's settings page.
- Every outcome posts to `POST /capabilities` immediately, so the panel shows
  where the agent is stuck **within 2 minutes** (UC-03 AC).

**E3 — OEM-specific steps.** Shown **only** on the OEMs that need them (MIUI,
EMUI/HarmonyOS, ColorOS/Realme, One UI, Vivo/Funtouch): autostart, battery lock,
"allow background activity". Each has that OEM's screen path and a photograph.
Where the platform exposes no check, the step is user-attested and is recorded
as `unknown`, never as `granted` — a false green here is exactly how R3 stays
invisible.

**E4 — "Qaysi SIM ish raqami?"** Shown only on dual-SIM handsets: slot, carrier,
and MSISDN where the OS knows it. The choice sets `sim_subscription_id` and is
what Guard 1 (§7.4) enforces from then on. On a single-SIM phone the screen is
skipped silently.

**E5 — "Raqamni tasdiqlash".** Route 1 runs automatically and invisibly
(§9.1). If it cannot prove the match — which is the common case on Uzbek SIMs —
the screen becomes the callback route (§9.2): the receiver number in large type,
a "Qo'ng'iroq qilish" button that dials it, a 5-minute countdown, and live
status. **The agent is never told the app "checked the SIM and failed"; they are
told what to do next.**

**E6 — "Tayyor".** Reached **only** when every required capability is
`granted_working` and the installation is `active` (§7.8). It shows the number
being recorded, the data policy in one line, and a link to the diagnostics
screen. From here the home screen permanently displays the recorded number
(N41).

### 8.3 The assisted path, and why it is a first-class state

Some steps cannot be completed unaided — developer options where the chosen
variant needs them, and any Play Protect exemption Android does not let an app
request. Where that happens the flow **says so plainly**, offers the admin an
assisted install, and the panel shows `needs_assisted_install` rather than a
stalled `installed`. `RISKS.md` R17 mitigation 6 is explicit that if unaided
enrolment is unachievable the answer is a budget line (a person doing device
visits), not a longer instruction — this state is what makes that visible early
enough to decide.

---

## 9. Number verification (UC-04, R19)

Two routes in order, and — since SMS was removed from scope — the second one is
load-bearing. A third, admin-attested path exists behind them (T142) and is
deliberately weaker and deliberately visible.

### 9.1 Route 1 — the SIM's own MSISDN

`TelephonyManager.getLine1Number()` (and, where available, the
`SubscriptionInfo.number`). Match rule: normalise to E.164 and compare the
**last 9 digits** (N37) with the registered number's key.

**`null`, empty, whitespace, or fewer than 9 digits is never a match** — it is
`msisdn_empty` and the flow moves to route 2. This is stated in UC-04 as an
explicit requirement and is asserted by a test, because the failure mode it
prevents (treating "I don't know" as "yes") would attribute a phone to a number
it does not hold.

### 9.2 Route 2 — the callback code

1. App calls `POST /enrolment/verify/callback/start`. The server creates a
   `number_verifications` row (`state='pending'`, 5-minute window) and returns
   the receiver's MSISDN. If every receiver is `down`, it returns **503
   `callback_receiver_down`** and the app tells the agent to contact the admin
   instead of dialling into nothing.
2. The agent dials the receiver from the phone being enrolled, on the SIM chosen
   at E4.
3. The receiver reports the inbound caller ID to
   `POST /api/service/v1/callback-events`. It **does not answer the call** —
   ringing is enough, so the agent is not charged and no audio exists.
4. The matcher takes the event's `caller_key` (last 9 digits) and finds a
   `pending` verification for the registered number with that key inside the
   window. Match ⇒ `state='matched'`, installation `active`, tokens issued.
5. Failure modes, each distinct and each recorded:
   - **`no_caller_id`** — the operator withheld CLI (`cli_presented=false` or a
     null caller). The agent cannot pass this route on this operator; the app
     shows the assisted path and the panel marks
     `needs_assisted_install`. **This is R19 happening, and it is why route 3
     exists.**
   - **`number_mismatch`** — the call came from a different number (usually the
     wrong SIM). The Uzbek message names which SIM to use. The installation
     stays `pending` — a callback from a different number must leave the device
     **unenrolled** (UC-04 AC).
   - **`timeout`** — window expired; the agent may retry, and each retry is a
     new `number_verifications` row so the funnel shows how many attempts a
     person needed.
6. An event that matches nothing is stored with `unmatched_reason` and ignored.
   Two pending verifications cannot share a `caller_key`, because a number has
   exactly one active assignment (§3.3) — if it ever happens, the matcher fails
   closed and raises an alert rather than guessing.

### 9.3 Route 3 — admin attestation (T142), and rebinding

`POST /installations/{id}/attest` with a mandatory `reason`. It writes an audit
row, sets `verification_method='admin_attested'` and stage
`verified_by_admin` — **rendered differently from `number_verified` everywhere
it appears**, because attested is weaker evidence than proven and the identity
anchor must never silently degrade. `TASKS.md` §9a and §10 item 10 both note
this extends UC-04 beyond its three named routes; it therefore also needs the
change-request line in T137, and its acceptance criterion is: *an agent whose
operator suppresses CLI reaches `capturing`, and the panel shows the binding as
attested rather than verified.*

**Rebinding (UC-07).** When verification succeeds for a number that already has
an `active` installation: the new installation becomes `active`, the previous
becomes `replaced`, and the previous is refused with **401 only after its queued
records have been accepted** — implemented as: `replaced` installations keep
working on ingest endpoints and are refused on `POST /auth/refresh` once their
last heartbeat reported an empty queue (the same rule as §4.3, for the same
reason). An admin notification is raised, because an unexpected rebinding is
what a stolen credential looks like. The agent's call list still contains the
calls made from the old phone — they are attached to the **number**, not to the
installation.

### 9.4 The callback receiver is fleet-wide infrastructure

If it is down, **nobody can enrol**. That makes its health a monitored product
state, not an operational detail.

**It is also on the critical path.** With SMS out of scope and route 1 empty on
most Uzbek SIMs, T141 sits between the foundations and every enrolment, which
makes **W12 — the inbound number and the always-on receiver hardware — the most
schedule-critical thing the client owes**, alongside W01. A build that is
otherwise finished cannot enrol a single phone without it, and the fallback
(admin attestation, §9.3) is a manual step per agent, repeated on every phone
change. Nothing in the software can shorten that wait; asking for it early is
the only available mitigation.

- **What it is** (W12): an office SIM in a GSM gateway, or a permanently
  connected Android phone running `/receiver` in receiver mode. Either way it
  observes inbound caller ID and posts it with a `service` token scoped to
  `callback:report` and nothing else.
- **Heartbeat** every 60 s to `POST /api/service/v1/callback-events` (a
  heartbeat is an event with no caller). No heartbeat for 3 min ⇒ `degraded`;
  5 min ⇒ `down` + **critical** alert `callback_receiver_down` naming the
  receiver.
- **The enrolment surfaces know about it**: E5 refuses to start a challenge when
  every receiver is down, and `/enrolment` shows a banner. Absence of enrolment
  must be an event, not a quiet stall — the same principle as UC-27's silence
  detection.
- **More than one receiver may be registered.** Matching accepts an event from
  any active receiver, so a second SIM in a second gateway is a configuration
  change, not a code change. Release 1 ships with one and the panel makes the
  single point of failure visible.
- **Per-operator verification is measured**: `registered_numbers.operator` ×
  `callback_events.cli_presented` gives the pass/fail table T143 needs, and
  `supported_models.callback_verification_ok` records the per-OEM half.

---

## 10. Derived data, rules and scheduled work

### 10.1 Enrolment funnel stages (UC-17)

Derived by one function, `resolve_funnel_stage(installation)`, and persisted to
`installations.funnel_stage` so the list is one query. Precedence top to bottom
— the first matching rule wins:

| Stage | Condition |
|---|---|
| `revoked` | `status IN ('revoked','revoked_pending_confirmation')` |
| `install_disappeared` | was `active` and has been silent > 24 h **and** its last heartbeat reported healthy capture (a phone in a lift is `offline`; an app Play Protect removed never comes back) |
| `needs_assisted_install` | a `needs_assisted_install` flag was set by the landing page's help button, by `no_caller_id`, or by a `denied_permanently` on a required capability |
| `capturing` | `status='active'` **and** every required capability `granted_working` **and** `service_running` |
| `verified_by_admin` | `status='active'` and `verification_method='admin_attested'` |
| `number_verified` | `status='active'` and verified by `sim_msisdn` or `callback` |
| `permitted` | installation exists and every required capability is `granted_working`, but not yet verified |
| `installed` | installation row exists (code redeemed) |
| `invited` | a live enrolment code exists, no installation yet |

`funnel_changed_at` is updated on every transition, and a transition into
`needs_assisted_install` or `install_disappeared` raises an alert. Time-in-stage
is what the admin actually watches during a rollout.

### 10.2 Internal vs external classification (UC-25, L4)

Computed at ingest, stored on `calls.call_type`, recomputed by a job when the
directory changes.

```
digits = only digits of remote_number
if directory is EMPTY                      -> unknown      # never 'external'
elif len(digits) < 6                       -> internal     # PBX extension
elif last9(digits) in registered_numbers   -> internal
elif matches any active line_directory rule (exact | prefix | suffix) -> internal
else                                       -> external
```

The empty-directory rule is the one that must never be "simplified": BonviZvonki
defaulted to external, an AI classifier then had to guess, and 82 of 98 calls
were mislabelled. A test empties the directory and asserts that **no** call is
labelled `external` (UC-25 AC).

### 10.3 Alert rules — the complete set

`alert_kind` values and what raises each. Severity in brackets.

| Kind | Raised by | Sev |
|---|---|---|
| `capture_disabled` | device event `capture_toggled_off` | warning |
| `permission_lost_microphone` / `_phone_state` / `_call_log` | capability transition → `denied`/`denied_permanently`/`granted_not_working` | warning |
| `battery_optimisation_reenabled` | `battery_exemption` transition | warning |
| `app_force_stopped` | `service_running=false` + heartbeat gap pattern | warning |
| `install_disappeared` | §10.1 rule | critical |
| `recording_route_lost` | `oem_recorder` or `recording_route_ok` → false | warning |
| `service_not_running` | device event | warning |
| `device_offline` | no heartbeat for `alerts.device_offline_minutes` | warning |
| `device_silent` | active in the last 7 working days, zero calls for `alerts.silence_hours` working hours while ≥ 1 other device reports (UC-27) | warning |
| `fleet_silent` | whole fleet zero for `alerts.fleet_silence_hours` working hours | **critical** |
| `capture_rate_regression` | model's 7-day audio capture rate > `alerts.capture_regression_pp` below its M0 baseline (N4) | critical |
| `queue_full` / `storage_low` | device events (N10) | warning |
| `poisoned_record` | device event (N9) | warning |
| `auth_expired` | device event / refresh failures (N25) | warning |
| `credential_replay` | installation/fingerprint mismatch, refresh-token reuse (N24) | **critical** |
| `installation_rebound` | a number bound to a new installation (UC-07) | warning |
| `callback_receiver_down` | §9.4 | **critical** |
| `enrolment_stalled` | an agent in one non-terminal stage > 48 h | info |
| `attribution_out_of_range` | a call whose `started_at` falls outside every assignment (§4.4) | info |
| `attribution_discarded_spike` | `attribution_failed` count for one installation > 5/day | warning |
| `retention_job_failed` / `backup_failed` | job failure | critical |
| `storage_capacity_low` | free disk < 20 % of the provisioned 250 GB | critical |
| `min_version_refusals` | ≥ 3 installations refused on version in 24 h | info |

Delivery: in-panel always; email to `alerts.email_to` for `critical` and for
`warning` when it is new (not a repeat within 24 h). **Acknowledgement is
`admin`-only and nothing in the device API can acknowledge, dismiss or suppress
anything** (UC-06, UC-18).

**Detection latency budget.** UC-06/UC-18 require the admin to see it within
10 minutes. The chain is: device detects (immediately on change, else ≤ 6 h
periodic) → reports on the next heartbeat (≤ 2 min) → the ingest handler raises
the alert **inside the same request**. The only unbounded link is a device that
is offline, which is itself an alert.

### 10.4 Scheduled jobs (`worker.py` + one `jobs.py` per module, APScheduler in a separate container)

| Job | Cadence | Does |
|---|---|---|
| `offline_sweep` | 1 min | marks devices offline, raises `device_offline`, updates funnel stages |
| `command_timeout` | 10 s | fails commands with no ack after 15 s, expires stale ones |
| `silence_detection` | 5 min | UC-27, working-hours aware (Asia/Tashkent, workdays, holidays) |
| `upload_session_sweeper` | 15 min | expires sessions past TTL, deletes `.part` files, sets `upload_expired` |
| `pending_audio_sweeper` | 1 h | `pending_upload` older than 24 h → `upload_expired` (§3.9) |
| `funnel_refresh` | 5 min | recomputes stages, raises `enrolment_stalled` |
| `call_log_delta_close` | 1 h | closes deltas that reconciled; feeds the gap report those that did not (N3) |
| `model_capture_stats` | nightly 01:00 | 7-day windows per model, raises `capture_rate_regression` (N4) |
| `audio_retention` | nightly 02:00 | deletes audio past `retention.audio_months`, sets `deleted_at` (UC-26) |
| `callback_event_retention` | nightly 02:15 | deletes `callback_events` older than 90 days |
| `storage_usage` | nightly 02:30 | writes `storage_usage_daily`, raises `storage_capacity_low` |
| `data_usage_rollup` | hourly | writes `data_usage_daily` from request accounting |
| `reattribute_calls` | on demand | re-stamps `agent_id`/`assignment_id` after an assignment edit, with an audit row |
| `reclassify_calls` | on demand | recomputes `call_type` after a directory change |
| `backup_verify` | nightly 03:00 | asserts last night's DB dump exists and restores into a scratch schema |

Every job is idempotent, holds a PostgreSQL advisory lock so two workers cannot
overlap, and logs a start/finish row. A job that raises does so loudly — three
consecutive failures raise `retention_job_failed`.

---

## 11. Modules, phases, and reconciliation with `TASKS.md`

### 11.1 Build units

**Dependencies are on *units*, not on task ids.** "Parallel?" answers: can two
agents work on this at the same time without touching the same file?

**Server** — each unit owns `modules/<name>/` (three files, §6) plus its routers
under `api/<surface>/<name>.py`. None adds a migration, a permission constant or
a router registration — those are §11.2.

| Unit | Owns | Depends on | Parallel? |
|---|---|---|---|
| SV-CORE | `core/*`, `main.py` skeleton, envelope, logging, config | — | **No** — foundation, everything imports it |
| SV-RBAC | `core/permissions.py` (registry + `PUBLIC_ROUTES`) | SV-CORE | **No** — single shared file (T18) |
| SV-SCHEMA | every `modules/*/models.py`, `core/enums.py`, `core/models.py`, the one migration | SV-RBAC | **No** — single Alembic head (T19) |
| SV-AUTH | `auth`, `users` (login, refresh rotation, users CRUD, password reset, **first-admin seed**) | SV-SCHEMA | Yes |
| SV-IDENTITY | `agents`, `numbers` (assignments, exclusion constraint, roster import) | SV-SCHEMA | Yes |
| SV-ENROL | `enrolment` — codes, attempts, verification, **the callback receiver and its events**, funnel stages | SV-IDENTITY | Yes |
| SV-INSTALL | `installations` (bind, replace, revoke, token model, version gate) | SV-AUTH, SV-IDENTITY | Yes |
| SV-DEVICE | `devices` (heartbeat, health, capabilities, events, call-log delta) | SV-INSTALL | Yes |
| SV-ALERTS | `alerts` (model, dedupe, mapping, delivery, silence) | SV-DEVICE | Yes |
| SV-CALLS | `calls` (ingest upsert, classification, list, own-scope, CSV export) | SV-INSTALL | Yes |
| SV-AUDIO | `audio` (sessions, chunks, commit, storage adapter, Range endpoint, retention) | SV-CALLS | Yes |
| SV-COMMANDS | `commands` (WS hub, lifecycle, FCM) | SV-DEVICE | Yes |
| SV-GAPS | `gaps` — gap report, regression watch, storage and data-usage reporting. **No `models.py`**: it computes from `calls`, `call_audio`, `call_log_deltas`, `model_capture_stats` | SV-CALLS, SV-DEVICE | Yes |
| SV-AUDIT | `audit` (+ the immutability trigger lives in SV-SCHEMA) | SV-SCHEMA | Yes |
| SV-SETTINGS | `settings` (`app_settings`) and `catalog` (line directory, supported models, app versions/APK) | SV-SCHEMA | Yes |
| SV-EXPORTS | `exports` — the service API. **No `models.py`** | SV-CALLS, SV-AUDIO | Yes |
| SV-JOBS | `worker.py`, one `jobs.py` per module it schedules | the module it schedules | Partly — one file per module, `worker.py` is shared (§11.2) |

**Panel** (`panel/src/modules/<name>/`; routes and nav are §11.2):

| Unit | Depends on | Parallel? |
|---|---|---|
| PN-SHELL (scaffold, auth, i18n, `router.tsx` stubs, nav, error catalogue, `api/client.ts`) | — | **No** — foundation |
| PN-ENROL (funnel, agents, numbers, install landing page) | PN-SHELL, SV-ENROL | Yes |
| PN-DEVICES (health list + detail, capability matrix, dial button) | PN-SHELL, SV-DEVICE | Yes |
| PN-CALLS (list, detail, **player + `audio-sw.js`**, own-scope view) | PN-SHELL, SV-CALLS, SV-AUDIO | Yes |
| PN-REPORTS (gap, storage, data usage) | PN-SHELL, SV-GAPS | Yes |
| PN-ALERTS | PN-SHELL, SV-ALERTS | Yes |
| PN-AUDIT | PN-SHELL, SV-AUDIT | Yes |
| PN-SETTINGS (+ app versions upload) | PN-SHELL, SV-SETTINGS | Yes |
| PN-USERS (`/users` — panel accounts, admin only) | PN-SHELL, SV-AUTH | Yes |
| PN-MONITOR (TV board) | PN-SHELL, SV-DEVICE | Yes |

**Android** — **one Gradle module** (§7.1), so the units below are *packages*,
not modules. They are still independently assignable, but "parallel" here means
"owns a disjoint package", and the shared files in §11.2 (manifests, Hilt graph,
navigation) are what serialises them.

| Unit | Owns (package under `uz.bonvi.call`) | Depends on | Parallel? |
|---|---|---|---|
| AN-SCAFFOLD (single `:app` module, **both flavours**, manifests, Hilt, Room, WorkManager, `core/Capabilities.kt`) | `core/`, `di/`, build files | — | **No** — foundation |
| AN-NET (Retrofit, generated DTOs, auth interceptor, refresh, WS client) | `data/remote/` | AN-SCAFFOLD, wire contract | Yes |
| AN-CAPTURE-API (`RecordingStrategy`, `CaptureRouter`, route + reason enums, **stub second implementation**) | `capture/` (interfaces only) | AN-SCAFFOLD | **Yes — and NOT blocked on S1/M0** (§11.4 item 8) |
| AN-SUB (subscription resolution, `PrivacyBoundary`, `Decision`) | `domain/privacy/` | AN-SCAFFOLD | Yes |
| AN-CALL (lifecycle SM, reconciliation, `client_call_id`, recovery sweep, self-measurement) | `service/`, `domain/call/` | AN-SUB, AN-NET | Yes |
| AN-QUEUE (Room queue, workers, poison parking, capacity policy) | `data/local/`, `service/work/` | AN-CALL | Yes |
| AN-HARVEST (`OemHarvestStrategy` + both locators, `MediaRecorderStrategy`) | `capture/oem/`, `capture/recorder/` | AN-CAPTURE-API, **S1 + M0** | Blocked |
| AN-TRANSCODE (Opus + Ogg writer, AAC fallback) | `capture/transcode/` | AN-CAPTURE-API | Yes |
| AN-AUDIOUP (resumable client, Wi-Fi/cellular policy) | `data/remote/upload/` | AN-QUEUE, AN-TRANSCODE, SV-AUDIO | Yes |
| AN-ENROL (E1–E6, capability checkers, OEM steps) | `ui/enrolment/` | AN-NET, SV-ENROL | Yes |
| AN-HOME (number banner, own calls, diagnostics) | `ui/home/`, `ui/diagnostics/` | AN-NET | Yes |
| AN-CMD (WS client, FCM, dial) | `service/command/` | AN-NET, SV-COMMANDS | Yes |
| AN-DIST (signing, in-app updater, min-version screen, revocation handling) | `service/update/`, `ui/update/` | AN-SCAFFOLD, SV-SETTINGS | Yes |

**Receiver**: RC-AGENT (`/receiver`) — inbound CLI observation + heartbeat.
Depends on SV-ENROL's `POST /callback-events`. Parallel with everything.

### 11.2 Shared files — sequential, never parallel

| File | Owned by | Rule |
|---|---|---|
| Alembic head (`server/migrations/versions/001_create_release1_schema.py`) | SV-SCHEMA | **One migration for the whole release-1 schema.** No other unit adds one |
| `server/src/core/permissions.py` (permission registry + `PUBLIC_ROUTES`) | SV-RBAC | Every permission for all 29 UCs declared up front (§4.1). Modules reference `Perm.*`, never add. It is in `core/` so nothing in `core` imports a module |
| `server/src/main.py` (router registration) | wiring step | Modules create routers only |
| `server/src/core/models.py` (ORM import list) and `core/enums.py` | SV-SCHEMA | New model ⇒ one line in `models.py`, or FK resolution fails at runtime. Every PostgreSQL enum lives in `core/enums.py`, bound with `pg_enum()` |
| `server/worker.py` (job registry) | wiring step | Modules export job callables only |
| `server/src/core/settings_keys.py` + the `app_settings` seed | SV-SETTINGS | Every threshold in §3.8; nothing hard-coded elsewhere |
| `modules/alerts/rules.py` (device event → alert kind) | SV-ALERTS | Exhaustive; a pure function, so it is `rules.py` and not `service.py` |
| `panel/src/app/router.tsx` + nav | PN-SHELL, then wiring | Every route and nav entry created as a stub first; units fill page bodies only |
| `panel/public/audio-sw.js` | PN-CALLS | Ported once from BonviZvonki |
| `android/app/src/main/AndroidManifest.xml` + the two flavour manifests | AN-SCAFFOLD, then wiring | Full permission set declared up front, **every `<uses-permission>` carrying a comment naming the UC that needs it**; minimised once, **before the install screens are photographed** (§11.4 item 4) |
| Android Hilt graph (`di/`) + navigation graph | AN-SCAFFOLD, then wiring | The single-module cost: these three files are the only real contention point between the Android units, so they are edited in the wiring step, not by feature work |
| `/contract/` (OpenAPI + generated clients) | SV-CORE + each module | Code-first; regenerate + `git diff --exit-code contract/` in CI |
| `deploy/docker-compose.yml`, `Caddyfile` | ship-devops | |

### 11.3 Phases

Mapped onto `TASKS.md`'s phases, keeping its ids so cross-references resolve.

| Phase | Content | Units |
|---|---|---|
| **0** — day one | Waits W01–W12; spikes S1/S2; M0 harness and field runs | — |
| **1** — foundations (sequential) | SV-CORE → SV-RBAC → SV-SCHEMA; PN-SHELL; AN-SCAFFOLD; contract generation | T15–T24 |
| **2** — M1 thin thread | Minimal `POST /calls` + AN-CALL + PN-CALLS list + dev enrolment shortcut; **a real call on a real phone in the panel, metadata only** | T25–T30 |
| **3** — server modules (parallel, ≤ 5) | SV-AUTH, SV-IDENTITY, SV-ENROL, SV-INSTALL, SV-DEVICE, SV-ALERTS, SV-CALLS, SV-AUDIO, SV-COMMANDS, SV-GAPS, SV-AUDIT, SV-SETTINGS, SV-EXPORTS, SV-JOBS, RC-AGENT | T31–T60, T141–T142 |
| **4** — Android (parallel, ≤ 5) | AN-NET, AN-CAPTURE-API, AN-SUB, AN-CALL, AN-QUEUE, AN-TRANSCODE, AN-ENROL, AN-HOME, AN-CMD, AN-DIST; **AN-HARVEST blocked on S1+M0** | T61–T85 |
| **5** — panel (parallel, ≤ 5) | PN-ENROL, PN-DEVICES, PN-CALLS, PN-REPORTS, PN-ALERTS, PN-AUDIT, PN-SETTINGS, PN-MONITOR | T86–T100 |
| **6** — wiring (sequential) | Router registration, permission sweep, alembic head check, panel routes + nav, **manifest minimisation**, Uzbek string pass, envelope/pagination conformance | T101–T106 |
| **7** — M2 gate (field) | Callback route per OEM+operator; photograph the real install screens; dry run; **N40 with 3 unaided salespeople**; one revise-and-retest iteration; write the reproducible procedure | T143, T107–T113 |
| **8** — M3 survivability (field) | Reboot, offline exactly-once, force-stop recovery, **UC-15 negative proof**, dual-SIM concurrency, battery, data, click-to-call, performance at 500k rows, security pass | T114–T123 |
| **9** — production (ops) | Deploy, APK channel, monitoring, secrets/signing handover, seed M0 baseline | T124–T128 |
| **10** — M4 acceptance (field) | 7-day run, per-model analysis, remediation, production rig live check | T129–T133 |
| **11** — docs | `QOLLANMA.md`, admin runbook, handover pack, change log, risk review | T134–T138 |

### 11.4 Where I disagree with `TASKS.md`, and what to change

These are structural, not stylistic. Each is a defect that would surface as
rework.

1. **Storage: T15 and T42 still specify MinIO / an S3-compatible object store.**
   `STACK.md` (decided later, same day) chose the **local filesystem behind an
   interface** and rejected object storage explicitly. *Change:* drop `minio`
   from the Compose file; T42 becomes "`LocalFsAudioStorage` + retention job",
   and the `AudioStorage` protocol (§6) is the seam that keeps S3 a later
   configuration change. Roughly −8 h of ops, and one fewer credential to hold.

2. **T19's table list is incomplete — 15 named, ~27 needed.** Missing from the
   one-migration list: `service_tokens`, `refresh_tokens`,
   `number_assignments` (named only inside `registered_numbers`),
   `enrolment_attempts`, `number_verifications`, `callback_receivers`,
   `callback_events`, `commands`, `audio_upload_sessions`,
   `capability_transitions`, `data_usage_daily`, `storage_usage_daily`,
   `model_capture_stats`, `app_versions`, `devices`. *Change:* T19's estimate
   (O6/L8/P14) is for about half the work; §3 of this document is its input and
   the row should be re-sized.

3. **T23 says schema-first; the project has since decided code-first.** *Change:*
   T23 becomes "Pydantic models + generated OpenAPI and clients under
   `/contract/`, with `git diff --exit-code contract/` in CI".

4. **Ordering defect: T104 (manifest minimisation) sits in Phase 6, after
   T107 photographs the install screens.** Every permission removed is one fewer
   alarming screen — so minimising *after* the screens are photographed makes the
   Uzbek guide wrong on day one and forces a re-shoot. *Change:* T104 must
   precede T107; it depends on T03 (the `targetSdk` answer), not on all of
   Phase 4.

5. **`CALL_PHONE` must survive minimisation.** UC-16 needs it and T62's
   permission list does not mention it. *Change:* add `call_phone` to the
   enrolment capability list (§7.8, §8.2 E2) and to T104's keep-list.

6. **No task creates the panel's Service Worker audio bridge.** T90 says "player
   with Range seek and an `Authorization` header", which is not achievable with
   a plain `<audio src>` — N43 and the BonviZvonki precedent make the SW bridge
   plus the `blob:` fallback a distinct artefact. *Change:* split T90 into the
   player and `panel/public/audio-sw.js` + fallback.

7. **No task owns the enrolment funnel on the server.** T86 is a frontend task
   depending on T35/T37, but §10.1's stage machine —including
   `needs_assisted_install`, `install_disappeared` and `verified_by_admin` — is
   server logic with its own alerts. *Change:* add a backend row before T86.

8. **T71 is over-blocked.** It bundles the `RecordingStrategy` interface with the
   concrete route, so the whole audio path waits for M0. The interface, the
   coordinator, the route enum, the reason enum and the second stub
   implementation depend on nothing. *Change:* split into T71a (interface +
   coordinator + reporting, unblocked, day 1) and T71b (the real strategies,
   blocked on S1+M0). This moves real work off the critical path — CP-1's head
   — at no cost.

9. **There was no users module** — T17 created the auth core, T59 imported the
   agent roster, and nothing ever created the panel accounts that `sales`,
   `manager` and `viewer` log in with, or linked a `sales` user to an agent.
   `plan-manager` has since added **T148** (users module + seed) and **T149**
   (the `/users` screen). Those two rows now have a specification to build
   against: §3.2 (columns, the last-admin guard, and the deliberate separation
   of *login* from *agent*), §4.7 (endpoints, guards, password rules,
   first-admin seed) and §5.2 (the page). **The identity chain — agent, work
   number, time-boxed assignment, enrolment code — is §3.3 and is a different
   thing; `/users` must not grow number-registration controls.**

10. **There is no scheduler.** The retention job (T42), silence detection (T38),
    the regression alert (T53), storage stats (T57) and the data counters (T56)
    are all periodic, and no task creates the worker process, its locking or its
    failure alerting. *Change:* add an SV-JOBS row (`worker.py` + Compose
    service), which is also where BonviZvonki's `core/models.py` import trap
    bites hardest.

11. **T143 needs SIMs, not just handsets.** It verifies the callback route per
    **OEM × operator**, but W07 supplies borrowed *handsets* and W12 supplies the
    *receiver*. Nothing supplies a SIM from each operator in the fleet.
    *Change:* add a wait — "one working SIM per operator present in the fleet
    (Beeline, Ucell, Mobiuz, Uzmobile), available for the M0 field session".
    Without it T143 cannot produce the per-operator table R19 depends on.

12. **UC-27 needs a working-hours calendar and there is no source for it.**
    Silence detection is defined in "working hours" with no definition of the
    working week or holidays. *Change:* the defaults in §3.8
    (`working_hours.*`, Mon–Sat, empty holiday list) are settings, seeded by the
    migration; correcting them is a data change. Recorded as an assumption.

13. **Phase 4 Wave A cannot start "as soon as Phase 1 is done".** T61/T64 depend
    on T32/T34, which are Phase 3 Wave A. The phase header claims otherwise.
    *Change:* state the dependency, or stub the enrolment endpoints in Phase 1.

Everything else in `TASKS.md` — the one-migration rule, the up-front permission
registry, the stub route table, the 5-in-flight cap, and the insistence that the
`field` and `wait` rows do not accelerate — is right, and this SPEC is built to
fit it.

---

## 12. Definition of Done

Machine-checkable unless marked **[field]**. A build agent may not call a unit
done on any other basis.

**Schema and data**
- [ ] `alembic upgrade head` on an empty database creates every table in §3;
      `downgrade base` runs clean; the generated SQL contains no unintended
      `DROP` (read it — autogenerate emits spurious drops).
- [ ] `conftest.py` builds the test schema with `alembic upgrade head` against a
      real PostgreSQL, **never `create_all`** — otherwise the migration is
      checked against a schema generated from the same models it is supposed to
      be checked against, and the CHECK constraints, partial indexes, exclusion
      constraint and audit trigger go untested.
- [ ] `btree_gist` and `citext` are created by the migration, not by hand.
- [ ] Inserting two overlapping `number_assignments` for one number **fails at
      the database level**, not in Python.
- [ ] Two `active` installations for one number are impossible (partial unique
      index test).
- [ ] `UPDATE`/`DELETE` on `audit_log` raises; there is no route that attempts it.
- [ ] Every `app_settings` key in §3.8 exists after `seed.py` with the stated default.
- [ ] The four `calls` CHECK constraints (§3.5, five rules in four constraints)
      reject: audio-less without a reason, `incoming`+`no_answer`, `answered`
      with `duration_sec = 0`, unanswered with `duration_sec > 0`, and
      `answered` without `answered_at`.
- [ ] An explicit insert into `calls.seq` is rejected (`GENERATED ALWAYS`).
- [ ] `audit_action` contains exactly the 37 values of §3.16.

**API**
- [ ] RBAC harness walks the route table and asserts, for **every** endpoint:
      401 without a token, 403 with the wrong role, 404 with the right role and
      the wrong owner. It fails when a new endpoint is added without a case (N23).
- [ ] `PUBLIC_ROUTES` matches the six named routes in §4.1 rule 5 exactly — no more, no fewer.
- [ ] `DELETE /calls/{id}` and `DELETE /calls/{id}/audio` return **405** for all
      of admin, manager, sales, viewer, service.
- [ ] Every non-2xx response matches the N35 envelope — asserted by one test that
      walks the OpenAPI document.
- [ ] Every list endpoint is cursor-paginated and returns `next_cursor`/`has_more`.
- [ ] `POST /calls` twice with an identical payload → one row, same id,
      `status:"unchanged"` (N2).
- [ ] A `client_call_id` replayed from a different installation → 409 and a
      `credential_replay` alert.
- [ ] Audio upload interrupted at ~50 % and resumed produces an **identical
      SHA-256** and re-sends no transferred bytes (UC-14).
- [ ] `GET /calls/{id}/audio` with `Range: bytes=1000-2000` returns **206** with
      `Content-Range`; without a token returns 401 **and zero bytes**; after
      retention returns **410 `audio_expired`** (N43, UC-20, UC-26).
- [ ] The service-to-service audio endpoint also returns 206 + `Content-Range`
      (N43, §5.4).
- [ ] Exactly one `audit_log` row per playback start; seeking a 20-minute file
      adds none (UC-24).
- [ ] A stale client uploads its whole backlog successfully **and then** receives
      426 on refresh — in that order (N34).
- [ ] Two consecutive full export passes over an unchanging dataset return
      identical row sets (UC-29).
- [ ] `service` token: cannot write, cannot read `/users`, cannot read `/audit`.
- [ ] Export row count equals the `total` for the same filter (UC-22).
- [ ] `GET /calls` returns agent name, number and device model alongside their
      ids, and an `audio` sub-object carrying `capture_route` and
      `missing_reason` — every filterable field is also displayable.
- [ ] Outbound timestamps are UTC `Z`; an inbound timestamp without an explicit
      offset is rejected with 422.
- [ ] The refresh cookie is scoped `Path=/api/v1/auth`, and `POST /auth/logout`
      actually revokes the refresh token — asserted by using the old token
      afterwards and getting 401.
- [ ] With an empty line directory, **no** call is classified `external` (UC-25).
- [ ] No token, code or password appears in captured logs (N26).

**Android**
- [ ] Both flavours of the single `:app` module build; `BuildConfig.APP_VARIANT`
      reaches the server on heartbeat, call and enrolment.
- [ ] Architecture test: no `MediaRecorder`/`MediaStore`/`AudioRecord`/external
      `File` outside `capture/`, and no `Build.VERSION.SDK_INT` outside
      `core/Capabilities.kt`.
- [ ] `OemHarvestStrategy.locate()` cannot be called without a `Decision.Capture`
      — asserted by the type system, and by `OemLocatorPrivacyTest`, which is
      one of the three undeletable tests.
- [ ] Denying each permission in turn: the app never displays or reports
      `capturing` (UC-03).
- [ ] A call on an unregistered SIM produces **no metadata, no queue row, no
      audio**; a private recording in the shared folder is never read (UC-15,
      N28) **[field for the real-SIM case]**.
- [ ] Where the OS cannot resolve the subscription, the call is treated as
      unregistered and counted as `subscription_unknown`.
- [ ] After `adb reboot`, screen locked, a call 5 minutes later is captured
      (UC-05) **[field]**.
- [ ] After `am force-stop`, 4 calls placed while dead appear within 15 minutes,
      each once, flagged `app_not_running` (UC-13) **[field]**.
- [ ] An airplane-mode call appears within 5 minutes of reconnection, exactly
      once, with the app killed immediately after send (UC-12) **[field]**.
- [ ] Every audio-less call carries a reason from the closed enum — 100 %, never
      null, never free text (N5).
- [ ] Audio is mono/16 kHz/Opus ≤ 24 kbps (or the declared AAC fallback, counted)
      with duration within 2 s of `duration_sec`.
- [ ] Simulated full disk stops new audio, keeps metadata, raises the alert
      (N10).

**Users and accounts**
- [ ] `seed.py` creates the first admin and refuses to run in production with the
      default password unchanged.
- [ ] Creating a `sales` user without `agent_id` returns 409.
- [ ] The last active `admin` cannot be deactivated or demoted (409 `last_admin`),
      and no user can deactivate themselves.
- [ ] An admin password reset revokes every refresh token of that user and forces
      a change at next login.
- [ ] No response, log line or audit `detail` ever contains a password or a hash.

**Panel**
- [ ] `npm run build` passes; no untranslated user-facing string (N39).
- [ ] For each role: every nav item is reachable and permitted; at least one
      gated route is refused by the API when called directly (§5.1).
- [ ] Audio seek works through the Service Worker bridge and through the `blob:`
      fallback.
- [ ] Gap-report totals reconcile exactly with `/calls?has_audio=false`.
- [ ] `viewer` never receives a full remote number in any payload (server-side
      masking asserted in the response, not the DOM).
- [ ] A filtered page of 1000 rows renders < 2 s; API p95 < 500 ms at 500k rows
      (UC-19). **Measured against the endpoint** — `GET /calls?limit=1000` at
      500k rows — because the panel now renders a fixed 50 per page
      (`docs/ASSUMPTIONS.md`, 2026-09-13) and can no longer be asked for 1000.

**Field gates (no machine can close these)**
- [ ] **N40: 3 of 3 unaided salespeople reach `capturing` in under 15 minutes
      each**, on real phones, using only the landing page and the in-app flow.
- [ ] The callback route passes on every OEM × operator pair in the fleet, or
      the failures are routed to admin attestation and named.
- [ ] M0 published as **data** (`supported_models` seeded), not prose.
- [ ] 7-day acceptance run meets N1–N7 per model; capture rate ≥ 99.5 %,
      duplicate rate 0.
- [ ] Battery ≤ 4 %/8-h shift and data ≤ 1 GB/month **measured**, not estimated.
- [ ] A restore from backup has been performed once.

---

## 13. Open questions

Each has a decision already applied. If nobody objects, these stand — build
agents must not re-open them.

| # | Question | **Decision in force** | Why |
|---|---|---|---|
| Q-A | Which `targetSdk` ships? | **Build both flavours; M0 decides; default `modern34` if it captures both voices** (D-06) | `ASSUMPTIONS.md` 2026-09-04. 34 wins on every axis except proof: no developer mode, no Play Protect fight, no deprecation clock |
| Q-B | Is the AAC fallback acceptable when a device has no Opus encoder? | **Yes, declared and counted** (§7.6) | The alternative is no audio at all on that model; N21 holds |
| Q-C | Who pays for mobile data? | **Wi-Fi-first + 1 GB/month cap, stated plainly in `QOLLANMA.md`** | B2/W05. Reimbursement removes the objection entirely for less than the MoyZvonki bill, if Bonvi prefers |
| Q-D | Working week for silence detection? | **Mon–Sat, 08:00–20:00 Asia/Tashkent, empty holiday list — all settings** | Correcting it is a data change, not a deploy |
| Q-E | Are out-of-hours calls on the work number in scope? | **Yes** | W11's recorded default |
| Q-F | May a `sales` user see their own device health in the panel? | **Yes — `devices:read:own`, their own installation only** | They must be able to see what is wrong with the app on their own phone; the alternative is a phone call to the admin for every red chip |
| Q-G | Who may write a call note? | **`admin` and `manager` (`calls:note`); `sales` cannot** | A salesperson annotating their own record before review changes what the review is |
| Q-H | Panel realtime? | **Polling, no WebSocket** (D-02) | Nothing needs sub-15-second panel latency |
| Q-I | Export format? | **Streaming CSV, UTF-8 with BOM, `;` delimiter. No XLSX in release 1** | Opens correctly in a ru/uz Excel; XLSX at 50k rows adds a dependency for no requirement |
| Q-J | Second callback receiver? | **Schema supports many; release 1 ships one and shows the single point of failure in the panel** | R19. A second gateway is then a configuration change |
| Q-K | UC-16's 5-second bar on doze-restricted OEMs | **Ship the best user-space design and measure `commands.latency_ms` per model; renegotiate with evidence if p90 > 5 s** | `TASKS.md` §10 item 6 flags it as possibly unachievable; a measured miss is a decision, an unmeasured one is a surprise |
| Q-L | Attribution when a call falls outside every assignment | **Attribute to the assignment in force at `installation.bound_at` and raise an `info` alert** | Dropping the call is worse; a silent guess is worse still |

**Genuinely unresolved, owned by the client, and not blocking this SPEC:**
**W01** the fleet inventory (models, OS versions, iPhone count) — it gates M0 and
therefore AN-HARVEST; **W12** the inbound number and always-on receiver hardware
— now on the critical path (§9.4), and without it nobody can enrol at all; and
the **per-operator SIM set** identified in §11.4 item 11, which still does not
exist as a task or a wait.
