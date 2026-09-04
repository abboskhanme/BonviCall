# BonviCall — Task plan (release 1)

Author: plan-manager · Date: 2026-09-04 · Source of truth: `docs/REQUIREMENTS.md`
(UC-01…UC-29, N1…N42, scope boundary §5, spikes §3, DoD §10), `docs/RISKS.md`
(R1…R18 + the S1 box), `docs/ASSUMPTIONS.md`.

This file feeds `docs/ESTIMATE.md`. It contains no expected values and no
totals-with-multipliers — that arithmetic belongs to the estimator.

> **Revision 2 — 2026-09-04. Scope reduction, settled by the client:** the legal
> opinion, the notice/policy paperwork and the SMS parts are out — this is an
> internal company project. **W02, W04, W09, T33 and T77 are withdrawn in place**
> (id kept, zero hours) so that `REQUIREMENTS.md`, `RISKS.md` and `ESTIMATE.md`
> cross-references keep resolving. `plan-analyst` is withdrawing UC-28, N29, N30
> and B1 the same way. Three compensating rows are added — **T141, T142, T143**
> and wait **W12** — because dropping the SMS route leaves the callback route as
> the only working number-verification path (see §9a).
>
> **Revision 3 — 2026-09-04, after `docs/SPEC.md`.** `plan-architect` found 13
> structural defects; all are addressed. Nothing is renumbered. **T71 is split
> into T71a/T71b** (the interface was never blocked on S1/M0 — this takes the
> whole audio path off the critical path); **T104 moves from Phase 6 to Phase 1**
> (minimising permissions *after* photographing the install screens would have
> forced a re-shoot on real phones); **T19 is re-scoped and split into
> T19/T146/T147** against the SPEC's ~30 tables; MinIO is dropped for
> `LocalFsAudioStorage` per `STACK.md`; and nine rows are added for units nothing
> owned — **T144** receiver agent, **T145** Hilt/nav, **T148** users module,
> **T149** `/users` screen, **T150** scheduler, **T151** the unowned jobs,
> **T152** server-side funnel, **T153** the Service Worker audio bridge,
> **T154** test infrastructure — plus wait **W13** (per-operator SIMs).
> Estimated against `STACK.md`, `CONVENTIONS.md` and `CONVENTIONS-CLIENT.md`.

---

## 0. Estimating assumptions — read before using the numbers

**The stack is now chosen** — `docs/STACK.md`, decided with the user on
2026-09-04 (W06). Revision 1 estimated against the user's default and that
default was confirmed, so **no estimate moved because of the stack**. What
follows is the decided stack, not an assumption:

| Layer | Assumed for estimating |
|---|---|
| Server | FastAPI + SQLAlchemy + Alembic + PostgreSQL, Pydantic v2 |
| Panel | React 18 + Vite + TypeScript + TailwindCSS |
| Infra | Docker Compose + Caddy, single self-hosted instance |
| Audio storage | **Local filesystem behind an `AudioStorage` protocol** (`STACK.md`; object storage explicitly rejected as premature at ~200 GB/year) |
| Android | Kotlin + Jetpack Compose + Room + WorkManager + Hilt |
| Tests | pytest + a **separate `bonvicall_test` database** (CONVENTIONS §13), Vitest (panel), JUnit/Robolectric (app) |

**How much a different choice moves the total:** the server and panel are
roughly 45 % of `code` hours, and a mainstream substitution inside that 45 %
(Node/NestJS, Go, Django, Vue instead of React) moves the total by **±10 % at
most** — the work is dominated by domain rules, not framework syntax. Two
choices move it much more: (a) storage — **`STACK.md` settled this on the local
filesystem behind an interface**, which removed a container, a credential and
~8 h of ops versus the object store this plan first assumed; (b) **anything
other than native Kotlin on Android is not a
choice at all** — N31 requires a foreground service of a call/microphone type,
a boot receiver and OEM file access, so cross-platform frameworks would add a
native layer rather than remove one. Assume the Android half of the estimate is
stack-invariant.

### Estimate conventions

- Three-point hours per task: **O** optimistic / **L** likely / **P** pessimistic.
  The estimator computes the expected value; this file does not.
- **Every task's O and L are ≤ 8 h.** `P` is allowed above 8 h where the
  uncertainty is genuinely irreducible: all `spike` and `field` rows, and the
  `code` rows that touch OEM behaviour, the audio path or resumable transport.
  Forcing those into an 8 h box would hide the uncertainty, not remove it.
- `wait` rows carry **chase/coordination hours only**. Their calendar cost is in
  §7 and is not team time — it is schedule.
- Type tags, used by the estimator to pick a multiplier:

| Type | Meaning | Agent speedup |
|---|---|---|
| `code` | Writing software | yes — the only category that accelerates well |
| `spike` | Investigation with an unknown answer (S1, S2) | partial |
| `field` | Real phones, real people, wall-clock | **none** |
| `wait` | Blocked on a third party | **none** |
| `ops` | Deploy, infra, configuration | partial |
| `doc` | Documentation, incl. Uzbek `docs/QOLLANMA.md` | partial |

### Parameterised assumptions that will move the number

- **Fleet model count assumed = 6 distinct model+OS combinations.** Unknown until
  W01 lands. Add **6 / 8 / 12 h** of `field` per additional model to M0 (T12/T13)
  and **2 / 3 / 5 h** per additional model to the battery/data measurement (T124).
- **Agent count assumed 15, registered numbers ≤ 25, ~15 000 calls/month.**
- **One N40 revise-and-retest iteration is budgeted** (T118/T119). A second
  iteration costs another **10 / 16 / 24 h**, mostly `field`.

### Owner legend

`lead` (senior dev, spikes and field) · `build-backend` · `build-frontend`
(panel) · `build-android` — **roster gap: the agent list in CLAUDE.md has no
Android role**; treat it as `build-frontend` operating in Kotlin, or add the
role · `test-backend` · `test-frontend` · `qa-review` · `qa-security` ·
`qa-performance` · `ship-devops` · `ship-docs` · `client` (Bonvi) ·
`orchestrator` (shared-file wiring, never parallel).

### Concurrency rule

**At most 5 tasks in flight at any moment, across all phases.** Waves below are
sized to 5 so that one wave = one dispatch. Phases 3, 4 and 5 may interleave,
but the cap is global, not per-phase.

### How parallel phases are kept collision-free

Four files in this project are shared and would otherwise be edited by several
tasks at once. The plan removes them from parallel work up front:

| Shared file | Removed from parallel work by |
|---|---|
| Alembic head | **T19 defines the entire release-1 schema in one migration** (Phase 1). No Phase 3/4/5 task adds a migration. One consolidation check in Phase 6 (T102). |
| RBAC permission registry | **T18 declares every permission constant for all 29 UCs up front.** Module tasks reference constants, never add them. Final registration in T101. |
| FastAPI router registration (`main.py`) | Module tasks create routers only. **T101** includes them, sequentially. |
| Panel route table + nav menu | **T21 creates every route and nav entry as a stub.** Module tasks fill page components only. Final wiring in T103. |
| `AndroidManifest.xml` (per flavour) + Hilt graph | **T22 declares the full permission set up front, per `legacy28`/`modern34` flavour**; **T104 minimises it once, in Phase 1, before T107 photographs the screens** (R17 mitigation 3). T145 finalises the Hilt graph and navigation in Phase 6. |
| `server/worker.py` (job registry) | **T150** creates it; modules export job callables only. |
| `server/src/core/models.py` (ORM import registry) | **T147.** A new model without a line here fails FK resolution at runtime, on one code path, in production — not in tests. |
| `panel/public/audio-sw.js` | **T153.** Ported once from BonviZvonki, owned by the calls module. |
| `core/settings_keys.py` + the settings seed | **T58.** Every threshold in SPEC §3.8; nothing hard-coded elsewhere. |

---

## 1. Milestone map

| Milestone | Phases | Proves |
|---|---|---|
| **S1 / S2** | 0 | We know what we are building on |
| **M0** | 0 | Supported-model table with measured per-model capture rate |
| **M1** | 2 | A real call on a real phone appears in the panel — **metadata only, no audio** |
| **M2** | 4–7 | Install + permission + number-verification journey passes N40 unaided |
| **M3** | 8 | Offline / reboot / force-stop / dual-SIM / exactly-once |
| **M4** | 10 | 7-day acceptance run meets N1–N7 |

---

## Phase 0 — Day one [parallel: all waits + spike wave]

Everything here starts on calendar day 1. The waits (W01…W12) cost the team
almost nothing and cost the schedule everything.

> The 12 rows below (three withdrawn 2026-09-04) exceed the 5-in-flight cap
> deliberately: a `wait` consumes no team capacity. Only the chase hours are
> ours, and they are minutes each. The spike waves that follow are capped at 5.

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| W01 | [ ] | **D2 — fleet inventory from client**: per employee model, Android version, SIM ownership, whether a built-in call recorder exists and is on, which phones were in the CallSentry trial, how many iPhones | client | wait | — | Y | 1 | 2 | 4 | A table covering every salesperson; iPhone count stated explicitly (R11) |
| W02 | [~] | **Withdrawn 2026-09-04 — out of scope (internal project)** (was: legal opinion, ZRU-547) | — | wait | — | — | 0 | 0 | 0 | — |
| W03 | [ ] | **D5 — server + storage procurement**, ≥ 250 GB steady state. **No jurisdiction constraint — buy wherever is cheapest. Startable on day 1, blocked by nothing** | client | wait | — | Y | 1 | 3 | 6 | SSH access to a provisioned host with 250 GB usable |
| W04 | [~] | **Withdrawn 2026-09-04 — out of scope (internal project)** (was: client-side notice wording) | — | wait | — | — | 0 | 0 | 0 | — |
| W05 | [ ] | **D6 — who pays for mobile data** | client | wait | — | Y | 1 | 1 | 2 | Decision recorded; default is Wi-Fi-first + 1 GB cap if no answer |
| W06 | [ ] | **`plan-stack` session with the user** — server/panel stack + where audio lives | lead + user | wait | — | N | 2 | 3 | 4 | `docs/STACK.md` exists with a reason per deviation |
| W07 | [ ] | **Acceptance handset set** — one phone per fleet model+OS, bought or borrowed with agreement (§4.1 A) | client | wait | W01 | Y | 1 | 3 | 6 | ≥ 5 phones physically available for the acceptance window |
| W08 | [ ] | **Book 3 unaided salespeople** for the N40 test, plus a room and a stopwatch slot | client | wait | W01 | Y | 1 | 1 | 3 | Three named people and a date; none has seen the app |
| W09 | [~] | **Withdrawn 2026-09-04 — out of scope (internal project)** (was: SMS gateway account) | — | wait | — | — | 0 | 0 | 0 | — |
| W13 | [ ] | **One working SIM per operator present in the fleet** (Beeline, Ucell, Mobiuz, Uzmobile), available for the M0 field session (added 2026-09-04) | client | wait | — | Y | 1 | 2 | 4 | T143 can produce the per-OEM × per-operator table. **Caller-ID presentation is decided by the network, so handsets alone (W07) cannot produce it** |
| W12 | [ ] | **Dedicated inbound number + always-on receiver** for the callback verification route — an office SIM in a GSM gateway or a permanently connected Android device (added 2026-09-04: the callback route is now the only working verification path) | client | wait | — | Y | 1 | 2 | 4 | A number the server can observe inbound caller ID on, reachable from every operator in the fleet |
| W11 | [ ] | **Are out-of-hours calls on the work number in scope?** (R18 mitigation 5) | client | wait | — | Y | 1 | 1 | 2 | Decision recorded. Default applied if silent: yes, in scope |
| W10 | [ ] | **R13 guard — book the BonviZvonki ingest-adapter work in *that* repo** and the one-month parallel run | client | wait | — | Y | 1 | 1 | 2 | A dated line in BonviZvonki's own plan. Not release-1 work; if unbooked, the pressure to cancel MoyZvonki arrives before the evidence |

### Phase 0 — Spike wave A [parallel, max 5] — the S1 chain

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T01 | [ ] | **S1a — read `../CallSentry/app/.../service/recording/`** (`RecordingManager`, `OemRecordingLocator`, `CtiForegroundService.onIdle`) and name the mechanism that produced two-sided audio | lead | spike | — | Y | 3 | 5 | 8 | One-page note naming the route, the exact permissions and the install steps it required |
| T02 | [ ] | **S1b — reproduce it on one phone in default state**: Play Protect ON, developer mode OFF | lead | spike | T01 | N | 3 | 6 | 14 | Note answers yes/no with evidence. "No" makes S2 (T04/T05) urgent |
| T03 | [ ] | **S1c — `targetSdk` floor**: does the route survive at targetSdk 33/34 via MediaStore or `MANAGE_EXTERNAL_STORAGE`, or is it locked to 28 (N32, deprecation clock) | lead | spike | T01,T02 | N | 4 | 8 | 16 | A stated targetSdk for release 1 with the install-friction consequence written down |
| T04 | [ ] | **S2a — Android Enterprise work profile: can we enrol a personal phone at all** (BYOD, no factory reset) | lead | spike | — | Y | 3 | 6 | 12 | Enrolled test phone, or a written reason it is impossible |
| T05 | [ ] | **S2b — the question that kills S2: can an app inside the work profile see/record calls from the personal dialer** | lead | spike | T04 | N | 3 | 5 | 10 | §10 DoD "S2 answered" is satisfiable either way. **Do not design around S2 until this is green** |

### Phase 0 — Spike wave B [parallel, max 5] — install, dual-SIM, M0 rig

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T06 | [ ] | **Play Protect / signing spike (R8, R17)**: does a properly signed, registered APK still get flagged; per-Android-version install path | lead | spike | T01 | Y | 3 | 6 | 12 | Written install path per Android version in the fleet; measured Play Protect interference rate |
| T07 | [ ] | **Dual-SIM subscription-ID reliability spike (UC-15, R18)**: is `PHONE_ACCOUNT_ID`/`SUBSCRIPTION_ID` populated on the fleet's OEMs, and on which is it ambiguous | lead | spike | W01 | Y | 3 | 6 | 12 | Per-OEM table: reliable / unreliable / absent. Drives the fail-closed rule in T77 |
| T08 | [ ] | **Read prototype call-detection + service survivability** (`CallDetector`, `PhoneStateReceiver`, `KeepAliveWorker`, `BootReceiver`) and extract the patterns worth keeping | lead | code | — | Y | 3 | 5 | 8 | A short note listing what to reuse and what the prototype got wrong (localId, 44.1 kHz, MISSED inference) |
| T09 | [ ] | **M0 harness — call-log ground-truth exporter** (`adb shell content query --uri content://call_log/calls`, filtered to the registered subscription) | lead | code | — | Y | 3 | 5 | 8 | Script emits a CSV of call-log rows for one subscription on any fleet phone |
| T10 | [ ] | **M0 harness — matcher and rate calculator** (§4.1 A: capture rate, audio capture rate, duplicate rate; match on number + direction + start ±60 s) | lead | code | T09 | N | 4 | 6 | 10 | Fed two CSVs it prints the three rates; used again unchanged in T126 |

### Phase 0 — M0 field measurement [sequential, wall-clock]

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T11 | [ ] | **M0 protocol**: 10 scripted calls per phone covering answered in/out, missed, rejected, unanswered | lead | doc | T10 | N | 2 | 3 | 5 | A one-page script another person can execute |
| T12 | [ ] | **M0 run — models 1–3** (10 calls each, both routes tried, per-model rate recorded) | lead | field | W01,W07,T02,T11 | N | 6 | 10 | 18 | Three rows of the supported-model table with measured audio capture rate |
| T13 | [ ] | **M0 run — models 4–6** (+6/8/12 h per model beyond 6) | lead | field | T12 | N | 6 | 10 | 18 | Remaining rows complete |
| T14 | [ ] | **M0 published**: supported-model table + per-model baseline recorded as data, not prose (feeds N4 and UC-23) | lead | doc | T13 | N | 3 | 4 | 6 | §10 DoD "M0 published" satisfied; the baseline is a seeded DB table, not a wiki page |

---

## Phase 1 — Foundations [sequential — every task here touches a shared file]

Nothing in this phase is parallelisable: it is the schema, the permission
registry, the router table and the manifest. It exists so that Phases 3–5 can be
parallel at all. Can start on day 1 in parallel with Phase 0 (different people),
but is internally strictly ordered.

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T15 | [ ] | Repo scaffold: monorepo layout (`server/`, `panel/`, `android/`, `receiver/`, `docs/`), Docker Compose (postgres, api, **worker**, panel, caddy — **no object store; audio is on the local filesystem per `STACK.md`**), `.env.example`, Makefile | ship-devops | ops | W06 | N | 2 | 4 | 6 | `docker compose up` gives a reachable "hello" on every service; no S3 credential exists to hold |
| T16 | [ ] | FastAPI skeleton: settings, structured logging with token/code redaction (N26), **uniform error envelope `{"error":{"code","message"}}` (N35)** with Uzbek messages for user-facing codes | build-backend | code | T15 | N | 4 | 6 | 9 | Any raised `AppError` renders the envelope; a test asserts no token appears in logs |
| T17 | [ ] | SQLAlchemy base + session + Alembic init; **auth core**: users, password hashing, short-lived access + refresh tokens (N25), installation-bound credential model (N24) | build-backend | code | T16 | N | 5 | 8 | 12 | Login returns a token pair; a token replayed from a different installation is rejected |
| T18 | [ ] | **RBAC registry — declare every permission constant for UC-01…UC-29 up front**, the role→permission map for `admin`/`manager`/`sales`/`viewer`/`service`, and the `require(perm)` dependency | build-backend | code | T17 | N | 4 | 6 | 10 | Registry is complete for all 29 UCs; module tasks may reference but never add constants |
| T19 | [ ] | **Schema part 1 of 3 — identity and enrolment** (SPEC §3.1–3.4, re-scoped 2026-09-04: the SPEC defines ~30 tables and ~30 native enums, not the 15 this row originally listed). `users`, `refresh_tokens`, `service_tokens`, `agents`, `registered_numbers`, **`number_assignments`** (time-boxed, R18/UC-07), `enrolment_codes`, `enrolment_attempts`, `devices`, `installations`, `number_verifications`, `callback_receivers`, `callback_events` | build-backend | code | T18 | N | 5 | 8 | 12 | Tables and their enums exist in **one** Alembic revision; all three parts amend that same revision until merge |
| T146 | [ ] | **Schema part 2 of 3 — calls, audio, telemetry, operations** (SPEC §3.5–3.8): `calls` (incl. `seq BIGSERIAL` cursor), `call_audio`, `audio_upload_sessions`, `device_health`, `capability_states`, `capability_transitions`, `call_log_deltas`, `data_usage_daily`, `commands`, `alerts`, `audit_log`, `line_directory_entries`, `supported_models`, `model_capture_stats`, `app_versions`, `storage_usage_daily`, `settings` | build-backend | code | T19 | N | 5 | 8 | 12 | Same single revision; every enum bound with `values_callable` (without it SQLAlchemy stores the upper-case member name and the data becomes unreadable) |
| T147 | [ ] | **Schema part 3 of 3 — the constraints that are the product** (SPEC §3, §12): create **`btree_gist` and `citext` extensions in the migration**; `EXCLUDE USING gist` on `number_assignments`; `GENERATED ALWAYS AS … STORED` last-9 key columns; the four `calls` CHECKs; the partial unique index for one `active` installation per number; the `audit_log` immutability trigger; and `core/models.py`'s ORM import registry | build-backend | code | T146 | N | 4 | 6 | 10 | **Two overlapping assignments fail at the database level, not in Python.** `btree_gist` omitted ⇒ the constraint silently fails to create ⇒ two admins can fork the identity anchor. `downgrade base` runs clean and the generated SQL has no unintended DROP |
| T20 | [ ] | RBAC test harness: parameterised over the route table, asserts 401 no token / 403 wrong role / 404 wrong owner for every registered endpoint (N23, §10) | test-backend | code | T18 | N | 4 | 6 | 9 | Harness fails loudly when a new endpoint is added without an RBAC case |
| T21 | [ ] | Panel scaffold (PN-SHELL): Vite + React + TS + Tailwind + **TanStack Query** (`refetchInterval` polling — **the panel uses no WebSocket**, SPEC D-02), `api/client.ts`, auth flow, Uzbek i18n catalogue + **error-code catalogue**, AppShell, **and every route + nav entry from SPEC §5.2 created as a stub** | build-frontend | code | T15 | N | 5 | 8 | 12 | All panel routes render a placeholder behind the correct role; later tasks add page bodies only |
| T22 | [ ] | Android scaffold (AN-SCAFFOLD): Compose + Hilt + Room + WorkManager + Retrofit, and **two `captureTarget` product flavours — `legacy28` and `modern34` — each with its own manifest and permission set** (SPEC §7.2); `BuildConfig.APP_VARIANT` sent on every request so capture rate is measurable per variant. Full permission set declared up front | build-android | code | T15 | N | 6 | 8 | 14 | Four artefacts build (`legacy28`/`modern34` × `debug`/`release`); the app installs on an API 26 device and starts a foreground service. **Conflict to settle first: SPEC §7.1/§11.1 specifies multiple Gradle modules, `CONVENTIONS-CLIENT.md` §5 specifies one `:app` module — estimated against the single-module shape** |
| T23 | [ ] | **Device↔server wire contract — code-first** (amended 2026-09-04, see `CONVENTIONS.md` §1): Pydantic models are the source of truth; OpenAPI + Kotlin DTOs are **generated** from them into `contract/`, and CI enforces `git diff --exit-code contract/` so no wire change lands invisibly. Covers enrolment, call upsert, audio chunk, heartbeat, capability report, call-log delta, commands. ISO-8601 + raw epoch millis + timezone (N36); E.164 last-9 key (N37); error envelope (N35) | build-backend | code | T19 | N | 5 | 8 | 12 | Generated `contract/` committed, CI diff gate green, Kotlin DTOs compile against it; **frozen before Phase 3 starts**. *Was spec-first: hand-written OpenAPI rots against FastAPI, and a spec people still trust is worse than none* |
| T154 | [ ] | **Test infrastructure** (CONVENTIONS §13): separate `bonvicall_test` database in Compose and CI, `conftest.py`, the thirteen named fixtures and factories (`db`, `client`, `admin`/`manager`/`sales`/`viewer`, `service_token`, `agent_factory`, `registered_number_factory`, `installation_factory`, `call_factory`, `audio_factory`, `frozen_clock`) | test-backend | code | T147 | N | 5 | 8 | 12 | **No test can touch real data by construction rather than by discipline** — the shared-DB sweeper rule is the one that failed in BonviZvonki. `alembic upgrade head` runs on every suite run, which is the check T102 wants anyway |
| T104 | [ ] | **Android manifest permission minimisation — moved here from Phase 6 (2026-09-04).** Drop every permission the S1 route does not need, per flavour manifest. **Ordering defect fixed: minimising *after* T107 photographs the install screens makes the Uzbek guide wrong on day one and forces a re-shoot on real phones — `field` hours, the expensive kind.** **Keep-list must retain `CALL_PHONE`** (UC-16 click-to-call fails silently without it) | orchestrator | code | T03,T22 | N | 4 | 6 | 10 | Permission set is final before T107 shoots a single screen; every removed permission is one fewer alarming screen; T62's checks and UC-16 both still pass |
| T24 | [ ] | E.164 normalisation + last-9-digit matching key, plus **`contract/phone-vectors.json` — the shared vector file the server test and the Android test both read** (CONVENTIONS §7, §13), which is what stops the two implementations drifting (N37, R6) | build-backend | code | T17 | N | 3 | 5 | 7 | `+998 90 111-22-33`, `998901112233`, `901112233` resolve to one key, in both languages, from one file |

---

## Phase 2 — M1: a real call appears in the panel [thin thread]

**The early demonstrable milestone. Metadata only, no audio, no enrolment
polish.** Deliberately does not depend on S1/M0 — it is the work that runs in
parallel with the spikes and proves the wire end to end.

### Wave A [parallel, max 5]

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T25 | [ ] | Server: `POST /device/calls` — idempotent upsert on client-generated `client_call_id` (UC-12, R5); resend returns the same id, HTTP 200, no second row | build-backend | code | T23 | Y | 4 | 6 | 10 | Same payload twice → one row, same id |
| T26 | [ ] | Android: call detection — phone-state listener + call-log read, minimal (patterns from T08) | build-android | code | T08,T22 | Y | 5 | 8 | 12 | An outgoing and an incoming call each produce one local record with direction and duration |
| T27 | [ ] | Android: Room queue + WorkManager metadata upload with network constraint and retry/backoff | build-android | code | T26 | Y | 4 | 6 | 10 | A record survives app kill and uploads on next network |
| T28 | [ ] | Panel: call list page (unfiltered) reading the real API | build-frontend | code | T21,T25 | Y | 3 | 5 | 8 | Rows render with direction, number, timestamps, duration |
| T29 | [ ] | Android: manual enrolment shortcut for M1 only (paste base URL + number, no verification) — **throwaway, replaced by T61/T64** | build-android | code | T22 | Y | 2 | 3 | 5 | Dev can point a phone at a local server in under a minute |

### Wave B [sequential]

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T30 | [ ] | **M1 demo on a real phone**: sideload, place a call, watch the row appear in the panel | lead | field | T25,T26,T27,T28,T29 | N | 3 | 5 | 10 | A call placed on a real handset is visible in the panel within 60 s (N6). **This is the milestone the client is shown** |

---

## Phase 3 — Server modules [parallel waves, max 5 each]

No task in this phase adds a migration, a permission constant or a router
registration — those were done in Phase 1 and are wired in Phase 6.

### Wave A — identity and enrolment (UC-01, UC-04, UC-07, UC-08)

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T31 | [ ] | Agents CRUD + **time-boxed number↔agent mapping** (`valid_from`/`valid_to`); registering an active number returns 409 naming the current holder (UC-01, R18) | build-backend | code | T147,T24 | Y | 5 | 8 | 12 | A number reassigned from A to B leaves A's earlier calls attributed to A — asserted by test |
| T32 | [ ] | Enrolment codes: single-use, 24 h TTL; second redemption 409, expired 410, both listed with timestamps (UC-01) | build-backend | code | T31 | Y | 3 | 5 | 8 | Both failure paths appear in the admin's list |
| T33 | [~] | **Withdrawn 2026-09-04 — out of scope (internal project)** (was: SMS verification route 2) | — | code | — | — | 0 | 0 | 0 | — |
| T34 | [ ] | **Number verification route 3 — callback code, now the PRIMARY verification path** (route 2 withdrawn 2026-09-04). Agent dials the inbound number, caller ID confirms the match against the pending enrolment within a time window | build-backend | code | T32,T141 | Y | 6 | 8 | 14 | **Works on every OEM and every operator in the fleet, with MSISDN empty — the common case.** It is no longer a fallback: if it fails, that agent cannot enrol at all (see T142) |
| T35 | [ ] | Installation lifecycle: bind, `replaced`, revoke; **exactly one active installation per registered number** enforced server-side; old install accepted until its queue drains, then 401; admin notified (UC-07, UC-08, N24) | build-backend | code | T31 | Y | 5 | 8 | 12 | Second phone binds, first returns 401 only after its queued records are accepted |

### Wave B — device health, drift and silence (UC-06, UC-17, UC-18, UC-27, R3)

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T36 | [ ] | Heartbeat + device-health ingest: online/offline (2 min beat, 5 missed = OFFLINE within 10 min), app/OS version, battery, queue depth (records + MB), **clock skew from raw epoch vs receipt time** (UC-17, N36) | build-backend | code | T23 | Y | 5 | 8 | 12 | Every UC-17 field is present and checkable against the device |
| T37 | [ ] | **Capability/permission drift detection (R3, R17)**: capability-state ingest, transition working→not-working raises an admin alert within 10 min naming agent + device + capability; recording loss reported distinctly from capture loss (UC-06, UC-18, N42) | build-backend | code | T36 | Y | 5 | 8 | 12 | Each of UC-18's six causes produces a distinct alert; agent cannot suppress it |
| T38 | [ ] | **Silence detection (R3, UC-27)**: device active in last 7 working days reports zero calls for 4 working hours while others report → alert; whole fleet zero for 2 working hours → critical | build-backend | code | T36 | Y | 4 | 6 | 10 | Simulated silence raises the alert by name. **Working hours come from the `working_hours.*` settings seeded by the migration (Mon–Sat, empty holiday list, Asia/Tashkent) — correcting them is a data change, not a code change.** Recorded as an assumption; no other source exists |
| T39 | [ ] | Alert model + delivery (in-panel + email), severity, dedup, acknowledgement by admin only | build-backend | code | T147 | Y | 4 | 6 | 9 | Alerts are durable, deduped, and not dismissible from the app |
| T40 | [ ] | **Production rig (§4.1 B)**: call-log-delta ingest, per-device-per-day delta, `subscription_unknown` counted separately, deltas open > 24 h feed the gap report (N3) | build-backend | code | T23 | Y | 4 | 6 | 10 | Panel can show a non-zero delta per device per day |

### Wave C — audio pipeline (UC-14, UC-20, UC-24, UC-26)

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T41 | [ ] | Resumable chunked audio upload + server-side reassembly + SHA-256 confirmation; interrupt at 50 % and resume without re-sending bytes (UC-14, N11) | build-backend | code | T23 | Y | 5 | 8 | 14 | Identical SHA-256 after a resumed upload |
| T42 | [ ] | **`LocalFsAudioStorage` behind the `AudioStorage` protocol** (SPEC §6 — object storage rejected as premature, `STACK.md`) + **`audio_retention` job**: audio past `retention.audio_months` deleted, row and audit kept, `deleted_at` set; below 3 months requires explicit confirmation (UC-26, N19) | build-backend | code | T147 | Y | 4 | 6 | 9 | Expired playback returns 410 `audio_expired`, not a 500. **No module outside `modules/audio/infrastructure/` opens an audio file by path** — the seam that keeps S3 a config change |
| T43 | [ ] | Audio streaming endpoint: HTTP Range → 206 + `Content-Range`, token required (401 + zero bytes without), **writes an audit row per playback start** (UC-20, UC-24, N20) | build-backend | code | T42 | Y | 4 | 6 | 10 | Seek to 15:00 on a 20-min file starts playback there; audit count +1 exactly |
| T44 | [ ] | **Attribution guard (N28, R18)**: audio is attached only when its time window matches a captured call **on the registered subscription**; anything unmatched is rejected, never stored | build-backend | code | T25 | Y | 4 | 6 | 10 | An upload with no matching registered-number call is refused and logged |
| T45 | [ ] | No-delete policy: `DELETE` on a call or its audio returns **405 for every role including `admin`** (UC-26) | build-backend | code | T18 | Y | 2 | 3 | 5 | Test asserts 405 for all five roles |

### Wave D — call query, scope and classification (UC-19, UC-21, UC-22, UC-25, N34)

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T46 | [ ] | Calls list API: filters + **stable cursor pagination** (no row on two pages, none skipped when new calls arrive) + indexes sized for 500 000 rows (UC-19) | build-backend | code | T25 | Y | 5 | 8 | 12 | Paging stability asserted while inserting concurrently |
| T47 | [ ] | `sales` own-scope filtering in the service layer (`calls:read:own` passes, query narrows by `agent_id`); another agent's call or audio returns **404, not 403** (UC-21) | build-backend | code | T46 | Y | 3 | 5 | 8 | RBAC harness green for the 404 case on every call/audio endpoint |
| T48 | [ ] | Export endpoint (UC-22): row count equals the filtered UI count, no audio, no columns the role may not see | build-backend | code | T46 | Y | 3 | 5 | 8 | 50 000 rows produced in under 30 s |
| T49 | [ ] | **Internal/external classification (UC-25, L4)**: directory auto-assembled from all registered numbers + admin extras with suffix rules (`*700`); < 6 digits = internal; **empty directory ⇒ `unknown`, never `external`** | build-backend | code | T24,T31 | Y | 4 | 6 | 9 | Test empties the directory and asserts no call is labelled `external` |
| T50 | [ ] | **Minimum supported app version gate (N34)**: an old client is refused with a distinct code and an Uzbek "update" message — **but its queued records are accepted first**, so refusal never destroys data | build-backend | code | T25,T36 | Y | 4 | 6 | 10 | Test: old client uploads its backlog successfully, then receives the refusal |

### Wave E — export contract, audit, commands (UC-16, UC-23, UC-24, UC-29, §5.4)

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T51 | [ ] | **Read-only `service` export (UC-29, §5.4 — a committed contract, not a convenience)**: `GET /export/calls?since=<cursor>`, paginated, ordered, cursor-stable, versioned; carries direction, both numbers, timestamps, duration, agent identity, internal/external, stable audio reference | build-backend | code | T46,T49 | Y | 5 | 8 | 12 | Two consecutive full passes over an unchanging dataset return identical row sets |
| T52 | [ ] | Service-to-service audio endpoint with Range support, scoped token, no public URL (§5.4.2, N20) | build-backend | code | T43,T51 | Y | 3 | 5 | 8 | `service` token cannot write, cannot read users, cannot read the audit log — asserted by RBAC test |
| T53 | [ ] | **Gap report API (UC-23)**: calls with `has_audio=false` grouped by reason / agent / model with totals and % of answered; plus the §4.1 B delta per device; **per-model alert when audio capture rate falls > 10 pp below the M0 baseline** (N4) | build-backend | code | T40,T44,T14 | Y | 5 | 8 | 12 | Totals reconcile exactly with the call list filtered on `has_audio=false` |
| T54 | [ ] | Audit log: append-only through the API (no endpoint updates or deletes), admin-only read (UC-24, N27) | build-backend | code | T43 | Y | 3 | 4 | 7 | Attempted update/delete has no route; count increases by exactly one per playback |
| T55 | [ ] | **Command channel (UC-16)**: WebSocket/push wake-up, click-to-call command lifecycle `sent → acknowledged → failed`, 15 s ack timeout, commands older than 2 min discarded; resulting call row carries `command_id` | build-backend | code | T36 | Y | 5 | 8 | 14 | No call row is ever linked to a failed command |

### Wave F — counters, settings, seeding

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T56 | [ ] | Per-device cellular data counter, monthly cap and daily deferred-mode budget (N14 ≤ 1 GB/month, N15 ≤ 5 MB/day) | build-backend | code | T36 | Y | 3 | 5 | 8 | Counter visible per device and drives the app's upload policy |
| T57 | [ ] | Storage usage + 30-day growth reporting (N18, R14) | build-backend | code | T42 | Y | 2 | 4 | 6 | Panel can show current GB and 30-day trend |
| T58 | [ ] | Settings API + `core/settings_keys.py`: retention, alert thresholds, minimum app version, line-directory extras, supported-model table, **`working_hours.*` and the holiday list** (SPEC §3.8) — `admin` only | build-backend | code | T18,T49 | Y | 4 | 6 | 9 | **Every threshold in SPEC §3.8 exists after `seed.py` with the stated default**; nothing is hard-coded elsewhere |
| T59 | [ ] | One-off agent roster import (~33 rows, CSV/XLSX, manual) | build-backend | code | T31 | Y | 2 | 4 | 6 | Roster loads or is typed; not a live integration |
| T60 | [ ] | Health/readiness endpoint + availability instrumentation for N38 | build-backend | code | T16 | Y | 2 | 3 | 5 | Uptime during 08:00–20:00 Asia/Tashkent is measurable, not asserted |

### Wave G — enrolment identity after the SMS route was withdrawn [added 2026-09-04]

Compensating work for the removal of T33. With route 2 gone and route 1 (SIM
MSISDN) empty on most Uzbek SIMs, **route 3 is the only verification path left**
— so it needs infrastructure of its own and a fallback behind it.

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T141 | [ ] | **Callback receiver service**: an always-on inbound-number receiver (office SIM in a GSM gateway, or a permanently connected Android device in receiver mode) reporting caller ID to the server; server matches it to the pending enrolment within a time window; **receiver health is a monitored state, because if it dies nobody in the fleet can enrol** | build-backend | code | T32,W12 | Y | 5 | 8 | 14 | A dialled callback binds the right installation; receiver downtime raises an admin alert, it does not silently stall the rollout |
| T142 | [ ] | **Admin-attested verification fallback** — the panel lets an `admin` confirm a number↔installation binding when routes 1 and 3 both fail; writes an audit row; the agent shows as `verified_by_admin`, **visibly distinct from `number_verified`**, so an attested binding is never mistaken for a proven one | build-backend | code | T35,T54,T88 | Y | 4 | 6 | 10 | An agent whose operator suppresses caller ID can still be enrolled, and the panel says how they were verified. **Extends UC-04 beyond its three stated routes — raise as a change request in T137** |

### Wave H — units nothing owned before [added 2026-09-04, SPEC §11.4 items 7, 9, 10]

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T148 | [ ] | **Users module — the gap that would have shipped a panel nobody can log into.** `admin`-only CRUD for panel accounts, the `role='sales' ⇒ agent_id NOT NULL` link that own-scope narrowing depends on, activation/deactivation, password set by admin; plus `seed.py` (settings defaults, first admin, supported-model seed) | build-backend | code | T147,T18 | Y | 4 | 6 | 10 | A `sales` user exists, is linked to an agent, and `GET /calls` narrows on that link. Before this row, T47 and T95 had role-gated pages and no way to create the roles |
| T150 | [ ] | **Scheduler process — `worker.py` + APScheduler in its own container** (SPEC §10.4). Job registry, **PostgreSQL advisory lock so two workers cannot overlap**, start/finish logging, and `retention_job_failed` after three consecutive failures | build-backend | code | T147,T15 | Y | 5 | 8 | 12 | A job runs exactly once with two workers up; a raising job is loud, not silent. **Five periodic jobs already in the plan (T38, T42, T53, T56, T57) had no process to run in** |
| T151 | [ ] | The scheduled jobs no module task owns (SPEC §10.4): `offline_sweep`, `command_timeout`, `upload_session_sweeper`, `pending_audio_sweeper`, `funnel_refresh`, `call_log_delta_close`, `callback_event_retention`, `reattribute_calls`, `reclassify_calls`, `backup_verify` | build-backend | code | T150 | Y | 5 | 8 | 12 | Every job is idempotent and holds the advisory lock; `reattribute_calls` re-stamps `agent_id` after an assignment edit **with an audit row**, which is what makes the time-boxed mapping correctable |
| T152 | [ ] | **Enrolment funnel state machine, server side** (SPEC §10.1): one `resolve_funnel_stage()` with the nine stages in precedence order, persisted to `installations.funnel_stage`, `funnel_changed_at` on every transition, and alerts on entry to `needs_assisted_install` / `install_disappeared` | build-backend | code | T35,T37 | Y | 5 | 8 | 12 | The funnel list is **one query**, not a per-row computation; `install_disappeared` (Play Protect removed it) is distinguishable from `offline` (a phone in a lift) |
| T144 | [ ] | **Receiver agent (`/receiver`, RC-AGENT)** — the fourth deliverable: observes inbound caller ID, posts events and a 60 s heartbeat with a `service` token scoped to `callback:report` and nothing else. Supports both `gsm_gateway` and `android_receiver` kinds | build-backend | code | T141,W12 | Y | 4 | 6 | 10 | An inbound call on the receiver SIM reaches the server within seconds; **no heartbeat for 3 min ⇒ `degraded`, 5 min ⇒ `down` + critical alert** |

---

## Phase 4 — Android app [parallel waves, max 5 each]

**Gating — corrected 2026-09-04 (SPEC §11.4 item 13).** The earlier claim that
"Waves A, B, D start as soon as Phase 1 is done" was wrong: **Wave A's enrolment
rows depend on Phase 3 Wave A** — T61 on T32 (enrolment codes) and T64 on T34
(the callback route), which in turn needs T141. Wave A therefore starts when
SV-ENROL lands, not when Phase 1 ends. The alternative, if that ordering hurts,
is to stub the enrolment endpoints in Phase 1 and let the app build against the
stub; that is a decision for the dispatcher, not a relabelling.

Waves B, D and **C1** genuinely do start as soon as Phase 1 is done. **Only Wave
C2 (T71b, T72) is blocked on S1 (T01–T03) and M0 (T14)** — the file-harvest rules
and the per-model route are unknown until then. Wave E's install path depends on
T06.

### Wave A — enrolment and permissions (UC-02, UC-03, UC-04) — **R17, the top risk**

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T61 | [ ] | Enrolment: redeem the single-use code, bind the installation, store the installation-bound credential (UC-01, UC-04) | build-android | code | T22,T32 | Y | 4 | 6 | 10 | A redeemed code produces a bound installation; a reused code fails visibly |
| T62 | [ ] | **Guided permission flow with per-step capability verification (UC-03)**: one screen per permission, one Uzbek sentence of purpose, and after each grant a real check — mic by a 1-second test capture, call state by reading current state, call log by a 1-row query, battery exemption by querying the power manager. **Covers all twelve capabilities in SPEC §3.1 including `call_phone`** — UC-16 fails silently without it, and T104's keep-list protects it | build-android | code | T22 | Y | 6 | 8 | 14 | A step goes green only when the capability actually works, not when the flag is set; `granted_not_working` (the OEM permission-manager case) is a reportable state, not a green tick |
| T63 | [ ] | **OEM-specific steps (R3)**: autostart, battery lock, "allow background activity" for MIUI / EMUI / ColorOS / Samsung — shown **only** on the OEMs that need them, with that OEM's screen path, verified where the platform exposes a check | build-android | code | T62,W01 | Y | 5 | 8 | 14 | On a non-affected OEM the steps do not appear; on an affected one they cannot be skipped |
| T64 | [ ] | Number verification client (UC-04): route 1 SIM MSISDN, then **route 3 callback code** (route 2 SMS withdrawn 2026-09-04). **`getLine1Number()` null/empty is never a match** | build-android | code | T61,T34 | Y | 3 | 5 | 8 | Enrolment completes with MSISDN empty via the callback route; a callback from a different number leaves the device unenrolled |
| T65 | [ ] | **Never-false-ready state machine (UC-03)**: the app cannot display or report `capturing` while any required capability is missing; each step's outcome (granted / denied / denied-permanently / granted-but-non-functional) reported to the server within 2 min | build-android | code | T62,T37 | Y | 4 | 6 | 10 | Test denies each permission in turn and asserts both the UI state and the state sent to the server |

### Wave B — capture core (UC-05, UC-11, UC-12, UC-13, UC-15)

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T66 | [ ] | **Dual-SIM resolution, fail-closed (UC-15, R18)**: identify the subscription before recording anything; where the OS cannot tell, treat as **unregistered** and count `subscription_unknown` | build-android | code | T07,T26 | Y | 5 | 8 | 14 | A call on the unregistered SIM produces nothing — no metadata, no queue entry, no audio |
| T67 | [ ] | Call-log reconciliation sweep on every start; direction and duration corrected against the call log before upload; unanswered outgoing gets `answered_at=null, duration=0` (UC-11, UC-13) | build-android | code | T26 | Y | 5 | 8 | 12 | Zero calls classified as answered that the call log shows as duration 0 |
| T68 | [ ] | `client_call_id` UUID created at call start; at-least-once delivery, exactly-once storage; survives reinstall (UC-12, R5) | build-android | code | T27,T25 | Y | 3 | 5 | 8 | Killing the app right after send and retrying creates no second row |
| T69 | [ ] | **Service survivability (R3, UC-05)**: boot-completed receiver, `onTaskRemoved` + AlarmManager restart, watchdog worker, and `service_not_running` reported on next contact when the OS refuses | build-android | code | T26 | Y | 5 | 8 | 14 | A call 5 min after reboot, screen locked, is captured |
| T70 | [ ] | **Self-measurement sweep (§4.1 B)**: on start and every 6 h, count own call-log entries for the registered subscription and report that count next to what was uploaded | build-android | code | T67,T40 | Y | 4 | 6 | 9 | Server receives both counts; the panel delta is non-zero when calls are missing |

### Wave C1 — capture API and audio transport [**UNBLOCKED, startable day 1**]

**Restructured 2026-09-04 (SPEC §11.4 item 8).** The old T71 bundled the
interface with the concrete route and parked the whole audio path behind S1+M0.
Only the real strategies are actually blocked (`AN-HARVEST`); the API, the
transcode and the upload client are not. This moves four rows off CP-1's head at
no cost.

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T71 | [~] | **Split 2026-09-04 into T71a and T71b** — see those rows; hours are counted there | — | code | — | — | 0 | 0 | 0 | — |
| T71a | [ ] | **`RecordingStrategy` interface + `CaptureRouter` + route reporting** (`isSupported()`/`start()`/`stop()`, adopted as-is from `../CallSentry`), the `capture_route` enum, and the **stub second implementation** that proves the seam. R1 mitigation 5, R9's "rebuild not rewrite" | build-android | code | T22 | Y | 4 | 6 | 10 | Two implementations bind; **the route that produced the audio is recorded per call** — the M0 baseline and the panel both depend on that field |
| T73 | [ ] | On-device transcode to **mono 16 kHz Opus ≤ 24 kbps**, with the **decided `aac_lc` fallback** where the device has no usable Opus encoder (SPEC §7.6, N17, N21, R14) | build-android | code | T71a | Y | 4 | 6 | 12 | Mono/16 k, duration within 2 s of `duration_sec`, ASR-usable without a second lossy pass; codec and container recorded per file |
| T74 | [ ] | Resumable chunked upload client; **Wi-Fi-first, cellular after 24 h regardless (N7)**, monthly cellular cap (N14) with the policy visible in the app | build-android | code | T73,T41,T56 | Y | 5 | 8 | 14 | Resume after a 50 % interruption sends no duplicate bytes |
| T75 | [ ] | **The ten-value `audio_missing_reason` enum wired on every failure path** (SPEC §3.9 — UC-14 names six, the SPEC justifies four more: `pending_upload`, `not_expected`, `queue_space_exhausted`, `attribution_failed`). **Never null, never free text; a call is never dropped because audio failed** (N5) | build-android | code | T71a,T67 | Y | 3 | 5 | 8 | 100 % of audio-less calls carry a reason from the closed enum |

### Wave C2 — the real capture strategies [**BLOCKED on S1 + M0**]

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T71b | [ ] | **The concrete strategies** — `OemHarvestStrategy` (preferred) and `MediaRecorderStrategy` (fallback), bound per flavour, implementing the route S1 named on the models M0 supports | build-android | code | T71a,T14,T03 | Y | 5 | 8 | 14 | The identified route produces two-sided audio on a supported model, under both flavours |
| T72 | [ ] | **OEM file harvest with the privacy boundary (N28, R18)**: `locate()` takes a `Decision.Capture`, not a raw number — read **only** files whose time window matches a captured registered-number call; everything else in the shared recordings folder is ignored and never uploaded | build-android | code | T71b,T66 | Y | 5 | 8 | 14 | A private-SIM recording sitting in the same folder is never read or sent — asserted by test |

### Wave D — device UX, queue, credentials (N8–N12, N25, N41, UC-16)

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T76 | [ ] | **Visible boundary (N41)**: the main screen permanently shows which number is being recorded, and the agent can see their own captured calls | build-android | code | T61 | Y | 4 | 6 | 9 | The recorded number is on screen at all times, not behind a menu |
| T77 | [~] | **Withdrawn 2026-09-04 — out of scope (internal project)** (was: recording-notice artefact, UC-28/N30 — withdrawn from the requirements in parallel) | — | code | — | — | 0 | 0 | 0 | — |
| T78 | [ ] | Queue policy (N8–N10): ≥ 30 days / ≥ 2 000 calls / ≥ 1 GB; oldest-first; a poisoned record parked after 5 attempts and reported instead of blocking the queue; **on queue exhaustion or < 1 GB free space, stop recording new audio and alert — never delete captured audio, never drop metadata** | build-android | code | T27 | Y | 5 | 8 | 14 | Simulated full disk stops audio, keeps metadata, raises the alert |
| T79 | [ ] | Token refresh + `auth_expired` device state; expiry holds the queue and never loses data (N25) | build-android | code | T61,T17 | Y | 3 | 5 | 8 | An expired token produces a device alert, not silent data loss |
| T80 | [ ] | Click-to-call receive and dial within 5 s; commands older than 2 min discarded and never attached to a manually dialled call (UC-16) | build-android | code | T55,T61 | Y | 4 | 6 | 10 | Panel shows `acknowledged` within 5 s; stale command is dropped |

### Wave E — distribution and lifecycle (N33, N34, UC-08, R8)

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T81 | [ ] | **APK signing setup + key backup + documented (R8)** — losing the key means no device can ever be updated again | ship-devops | ops | T22 | Y | 3 | 4 | 7 | Signed release APK builds reproducibly; key backed up in two places, procedure written |
| T82 | [ ] | **In-app updater against the self-hosted APK channel (N33, R8)** — the update path must reach every phone without an office visit | build-android | code | T81 | Y | 5 | 8 | 14 | A pushed version reaches an enrolled phone and installs with the user's single confirmation |
| T83 | [ ] | Client side of the minimum-version gate (N34): drain the queue, then show the Uzbek "update" screen; no data loss | build-android | code | T50,T82 | Y | 3 | 4 | 7 | Old client uploads its backlog, then blocks itself with an actionable message |
| T84 | [ ] | Revocation handling (UC-08): stop capture, delete all local audio uploaded or not, confirm; **warn before uninstall if the queue is non-empty (N12)** | build-android | code | T35,T78 | Y | 4 | 6 | 10 | Server shows `revoked_pending_confirmation` with records + MB still queued when contact was lost |
| T85 | [ ] | Transport hardening: HTTPS/WSS only, cleartext disabled in the manifest, certificate errors fatal and never bypassed (N22); outbound payload schema reviewed against N28 | build-android | code | T22 | Y | 3 | 4 | 7 | Cleartext request fails to build; payload carries nothing outside the N28 allow-list |

---

## Phase 5 — Web panel [parallel waves, max 5 each]

Page bodies only — routes and nav entries already exist as stubs from T21.

### Wave A — the rollout surfaces (UC-01, UC-17, UC-19, UC-20)

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T86 | [ ] | **Rollout funnel page (UC-17, R17 mitigation 2)**: stage chip, time in stage, **the blocking capability by name**, last attempt outcome, issue/reissue code, copy install link, attest, revoke — plus the **callback-receiver banner** (if the receiver is down nobody can enrol, and the page says so before anyone tries) | build-frontend | code | T21,T152,T141 | Y | 5 | 8 | 12 | An admin can see exactly who is stuck and at which step, during a live rollout |
| T87 | [ ] | Device health view (UC-17): online/offline, last contact, app + OS version, battery, battery-optimisation exemption, **each capability's verified state**, recording route and whether it works, queue depth (records + MB), **clock skew in seconds** | build-frontend | code | T21,T36 | Y | 5 | 8 | 12 | Every listed value renders and is checkable against the device |
| T88 | [ ] | Agents + registered numbers admin screens, **modal-only per house convention**; conflict 409 surfaced by naming the current holder; enrolment code issue/reissue (UC-01) | build-frontend | code | T21,T31,T32 | Y | 5 | 8 | 12 | Time-boxed reassignment is expressible in the UI, not only in the DB |
| T89 | [ ] | Call list with filters and pagination (UC-19) | build-frontend | code | T21,T46 | Y | 4 | 6 | 10 | A filtered page of 1 000 rows renders in under 2 s |
| T90 | [ ] | Audio player UI: transport, position, Uzbek reason text instead of a dead control when audio is absent (UC-20) | build-frontend | code | T21,T43,T153 | Y | 3 | 5 | 8 | Audio starts within 3 s on a 20-min recording; dragging to 15:00 plays from there |

### Wave B — oversight surfaces (UC-18, UC-21, UC-23, UC-24, UC-27)

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T91 | [ ] | **Gap report screen (UC-23)**: no-audio calls grouped by reason / agent / model, totals and % of answered, per-device §4.1 B delta, per-model regression flag against the M0 baseline | build-frontend | code | T21,T53 | Y | 5 | 8 | 12 | Totals reconcile with the call list filtered on `has_audio=false` |
| T92 | [ ] | Alerts inbox: severity, cause, agent, device, acknowledgement; covers UC-18's six causes and UC-27's silence alerts | build-frontend | code | T21,T39 | Y | 4 | 6 | 10 | An alert cannot be cleared from the app, only acknowledged by an admin |
| T93 | [ ] | Settings screens: retention (explicit confirmation below 3 months), alert thresholds, minimum app version, line-directory extras with suffix rules, supported-model table | build-frontend | code | T21,T58 | Y | 4 | 6 | 10 | No threshold in the product is hard-coded out of reach |
| T94 | [ ] | Audit log viewer, `admin` only (UC-24) | build-frontend | code | T21,T54 | Y | 3 | 4 | 7 | Who / which call / when / from which IP, read-only |
| T95 | [ ] | `sales` own-calls view — own rows and own audio only (UC-21, N41) | build-frontend | code | T21,T47 | Y | 3 | 5 | 8 | Another agent's call id returns 404 in the UI path too |

### Wave C — public and secondary surfaces (UC-02, UC-22, viewer)

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T96 | [ ] | `viewer` TV board: who is online, calls today, capture health; **numbers masked to last 4 digits, no audio, no personal data** | build-frontend | code | T21,T36 | Y | 4 | 6 | 10 | Nothing on the board identifies a client to a visitor walking past |
| T97 | [ ] | Export UI + download (UC-22) | build-frontend | code | T21,T48 | Y | 3 | 4 | 7 | Row count matches the filtered count on screen |
| T98 | [ ] | **Personalised install landing page in Uzbek (UC-02)** — per-agent link, APK download, slots for the per-Android-version warning screens filled by T107 | build-frontend | code | T21,T32,T81 | Y | 4 | 6 | 10 | Opening the link on a phone leads to a signed APK and the right guide for that OS version |
| T99 | [ ] | Storage and data-usage dashboards (N14, N18, R14) | build-frontend | code | T21,T56,T57 | Y | 3 | 5 | 8 | Current usage and 30-day growth visible without a DB query |
| T100 | [ ] | Panel-side error handling against the N35 envelope, Uzbek messages end to end | build-frontend | code | T21,T16 | Y | 3 | 5 | 8 | No raw stack trace or English string reaches a user |

### Wave D — added 2026-09-04 [parallel]

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T149 | [ ] | **`/users` panel screen, `admin` only** — create and edit panel accounts, assign the role, link a `sales` user to an agent. **Missing from SPEC §5.2's page table as well as from this plan; raise as a change request in T137** | build-frontend | code | T21,T148 | Y | 3 | 5 | 8 | An admin can create the `manager`, `sales` and `viewer` accounts the rest of the panel is gated on, without a database console |
| T153 | [ ] | **`panel/public/audio-sw.js` — the Service Worker audio bridge (N43)**, ported wholesale from `../BonviZvonki/web/public/audio-sw.js`: the SW adds the `Authorization` header so the browser's own player issues real Range requests and seek is native. Plus the **`fetch`+`blob:` fallback** for non-secure origins, which is what keeps a LAN/`http://` demo working | build-frontend | code | T21,T43 | Y | 4 | 6 | 10 | Seek on a 20-minute file issues 206 responses, not a full download; the fallback path is exercised by a test. **`<audio src>` cannot send an `Authorization` header — without this row T90 is not achievable** |

---

## Phase 6 — Wiring [sequential, orchestrator — shared files, never parallel]

Every task here edits a file that several earlier tasks referenced. Running any
two of these at once is the failure mode this plan exists to prevent.

> **T104 left this phase on 2026-09-04.** Manifest minimisation is a shared-file
> edit, but it must happen *before* T107 photographs the install screens, not
> after — so it now sits at the end of Phase 1, gated on T03. What remains here
> is T145, the Hilt/navigation wiring that genuinely belongs at the end.

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T101 | [ ] | Register every router in `main.py`; sweep the permission registry so **no endpoint is unprotected** (N23) | orchestrator | code | Phase 3 | N | 3 | 5 | 8 | Route table and permission registry agree; T20's harness covers every route |
| T102 | [ ] | Alembic head verification: `upgrade head` from an empty DB, `downgrade` sanity, **read the generated SQL for spurious DROPs** | test-migration | code | T101 | N | 3 | 4 | 7 | Clean DB reaches head; no unintended DROP |
| T103 | [ ] | Panel route table + nav menu finalisation, role-based menu visibility (hiding a menu item is not a permission — server still enforces) | orchestrator | code | Phase 5 | N | 3 | 4 | 7 | Each role sees only its own nav; the API still refuses what the nav hides |
| T104 | [→] | **Moved to Phase 1 (2026-09-04)** — manifest minimisation must precede T107, not follow it. Hours are counted in Phase 1, not here | — | code | — | — | 0 | 0 | 0 | — |
| T145 | [ ] | Android Hilt graph + navigation finalisation, and the flavour-specific `CaptureModule` bindings (SPEC §7.2) — the part of the old T104 that genuinely is wiring | orchestrator | code | Phase 4 | N | 3 | 4 | 7 | One Hilt graph per flavour, both compile; navigation has no orphan destination |
| T105 | [ ] | Uzbek string catalogue pass across panel and app (N39); code and identifiers stay English | orchestrator | doc | T103,T104 | N | 4 | 6 | 9 | No untranslated user-facing string remains |
| T106 | [ ] | Conformance sweep: N35 error envelope and pagination on **every** list endpoint (UC-19) | qa-review | code | T101 | N | 3 | 5 | 8 | One test walks the OpenAPI document and fails on any non-conforming response |

---

## Phase 7 — M2 gate: the enrolment journey [sequential, field — no agent speedup]

**This is R17, the project's top practical risk, and N40 is a measured
acceptance bar.** It cannot be simulated, parallelised or accelerated: it needs
real phones and three real people who have never seen the app.

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T143 | [ ] | **Verify the callback route on every fleet OEM and operator** (added 2026-09-04; runs before T109). Caller-ID presentation varies by handset and by operator, and it is now the only verification path | lead | field | T141,T144,W01,W07,W13 | N | 4 | 6 | 12 | A pass/fail per OEM × operator pair, from `registered_numbers.operator` × `callback_events.cli_presented`. Any fail is routed to T142's attested path, not left as a stalled enrolment |
| T107 | [ ] | **Capture the actual warning screens (UC-02)**: walk a real install on **each Android version in the fleet**, photograph every Android and Play Protect warning the user will meet | lead | field | T06,T82,W01,T104 | N | 5 | 8 | 16 | A photo set per OS version, **shot against the already-minimised permission set** so it does not need re-shooting — no step in the flow will be a surprise |
| T108 | [ ] | Assemble the Uzbek install + permission guide from those screens into T98's page and the in-app flow | ship-docs | doc | T107,T98 | N | 4 | 6 | 10 | Every warning the user meets appears in advance, in Uzbek, with what to tap |
| T109 | [ ] | Internal dry run: two people outside the project enrol two phones end to end | lead | field | T108,T62,T64 | N | 4 | 6 | 10 | Both reach `capturing`; obvious dead ends removed before burning a real salesperson |
| T110 | [ ] | **N40 acceptance test — 3 unaided salespeople, stopwatch, target < 15 min each** (UC-02, N40, §10) | lead | field | T109,W08 | N | 5 | 8 | 16 | 3 of 3 reach `capturing` unaided. **If any needs rescuing, the flow is revised and re-tested** |
| T111 | [ ] | Revise the flow against N40 findings (budgeted: one iteration) | build-android | code | T110 | N | 5 | 8 | 14 | Each observed failure has a specific fix, not a longer instruction |
| T112 | [ ] | N40 re-test with three **different** unaided salespeople | lead | field | T111,W08 | N | 4 | 6 | 12 | 3 of 3, under 15 min. A second failure costs another 10/16/24 h — not budgeted |
| T113 | [ ] | Write the reproducible install procedure **per Android version**, executable by someone who was not present (N40, §10) | ship-docs | doc | T112 | N | 3 | 5 | 8 | A person outside the project follows it and enrols a phone |

---

## Phase 8 — M3: survivability and the negative proofs

### Wave A — device behaviour [field, parallel max 5 but wall-clock bound]

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T114 | [ ] | UC-05: `adb reboot`, device untouched, screen locked; call 5 min after boot. Same after `adb install -r`; binding survives both without re-verification | lead | field | T69,T82 | Y | 3 | 5 | 10 | Both calls appear with correct direction and duration |
| T115 | [ ] | UC-12: airplane-mode call appears within 5 min of reconnection, **exactly once**; kill the app right after the request and let it retry | lead | field | T68 | Y | 3 | 5 | 10 | Duplicate rate 0 |
| T116 | [ ] | UC-13: `am force-stop`, then 4 calls while dead; all 4 appear within 15 min of restart, each flagged `app_not_running` | lead | field | T67,T75 | Y | 3 | 5 | 10 | 4 of 4, each exactly once |
| T117 | [ ] | **UC-15 negative proof (§10 DoD)**: scripted calls on the unregistered SIM produce **nothing** on the server and nothing in the local queue | lead | field | T66,T72 | Y | 4 | 6 | 12 | Server receives zero bytes about the private SIM; local queue inspected and empty |
| T118 | [ ] | UC-15 concurrency: call waiting held+resumed, call waiting rejected, SIM 1 then SIM 2 within 30 s | lead | field | T66 | Y | 4 | 6 | 12 | Panel shows exactly the registered-number calls, correct subscription, no recording on the wrong row |

### Wave B — budgets, performance, security [parallel, max 5]

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T119 | [ ] | **N13 battery measurement**: `dumpsys batterystats` per package, 3 shifts per model, 30 calls/shift (+2/3/5 h per model beyond 6) | lead | field | T71b,T78 | Y | 6 | 10 | 18 | ≤ 4 % of a full charge per 8-hour shift, **measured not estimated** (§10) |
| T120 | [ ] | **N14 / N15 data measurement** against the server-side counter | lead | field | T74,T56 | Y | 4 | 6 | 12 | ≤ 1 GB/month and ≤ 5 MB/day deferred, measured per device |
| T121 | [ ] | UC-16 click-to-call acceptance on a real device: dialling within 5 s, `failed` with a reason after 15 s | lead | field | T80 | Y | 3 | 4 | 8 | No call row is ever linked to a failed command |
| T122 | [ ] | Performance test at 500 000 call rows: list p95 < 500 ms, 1 000-row page < 2 s, 50 000-row export < 30 s (UC-19, UC-22) | qa-performance | code | T46,T48,T89 | Y | 4 | 6 | 10 | Numbers produced against a seeded dataset, not a demo DB |
| T123 | [ ] | `qa-security` pass: N22 transport, N24 installation-bound credential replay, N26 log redaction, **N28 outbound payload schema review**, append-only audit (§10) | qa-security | code | T85,T54,T104 | Y | 5 | 8 | 12 | Each of N22/N24/N26/N28 has a passing test or a written finding |

---

## Phase 9 — Production [sequential, ops]

**Blocked on W03 only** since 2026-09-04. W03 is startable on day 1, so this
chain no longer sets the release date — provided it is actually started.

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T124 | [ ] | Production deploy on the procured host: Compose, Caddy + TLS, PostgreSQL, **local audio volume with capacity monitoring** (N18, N20), worker container, backups | ship-devops | ops | W03,T15,T150 | N | 4 | 7 | 11 | Panel reachable over HTTPS; a restore from backup has been performed once; `backup_verify` is green |
| T125 | [ ] | APK hosting + update channel in production (N33, R8) | ship-devops | ops | T124,T82 | N | 3 | 5 | 8 | An enrolled phone updates itself from production |
| T126 | [ ] | Production monitoring: server alerts, disk growth, availability against N38, alert email delivery | ship-devops | ops | T124,T60 | N | 4 | 6 | 10 | An outage during 08:00–20:00 notifies a human |
| T127 | [ ] | Secrets and signing-key handover procedure; nothing in git, `.env` never committed | ship-devops | ops | T124,T81 | N | 2 | 4 | 6 | A second person can rebuild and re-sign without asking the first |
| T128 | [ ] | Seed production: supported-model table + M0 baseline, line directory, roster, retention and alert thresholds | ship-devops | ops | T124,T14,T58,T59 | N | 3 | 4 | 7 | UC-23's regression alert has a baseline to compare against on day one |

---

## Phase 10 — M4: the 7-day acceptance run [field, wall-clock — cannot be compressed]

7 consecutive working days is calendar, not effort. No number of agents changes
it. Only its setup and analysis are compressible.

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T129 | [ ] | Acceptance rig setup on the ≥ 5 handsets (§4.1 A): enrol, baseline exports, T09/T10 harness in place | lead | field | W07,T113,T128,T72,T74 | N | 5 | 8 | 14 | Every fleet model + OS combination is represented and enrolled |
| T130 | [ ] | **7-day acceptance run** — 7 consecutive working days of normal use | lead | field | T129 | N | 6 | 10 | 20 | Window completed with the call-log ground truth exported at the end |
| T131 | [ ] | Acceptance analysis against N1–N7 per model: capture rate ≥ 99.5 %, duplicate rate 0, reason codes 100 %, latency N6/N7 | lead | code | T130,T10 | N | 4 | 6 | 12 | A per-model report; any model below 90 % of its M0 baseline is removed from the supported list (N4) |
| T132 | [ ] | Remediation of acceptance findings (buffer — this is where the pessimistic case lives) | build-android | code | T131 | N | 4 | 8 | 24 | Every N1–N7 miss is fixed or accepted in writing as a change request |
| T133 | [ ] | **Production rig live check (§10)**: §4.1 B deltas reporting in the panel for every enrolled device, so N1 stays verifiable after the window closes | lead | code | T131,T91 | N | 3 | 4 | 8 | A deliberately missed call shows up in the gap report within 24 h |

---

## Phase 11 — Documentation and handover [parallel, max 5]

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T134 | [ ] | **`docs/QOLLANMA.md` — Uzbek employee manual**: what is recorded and what is **not** (the other SIM), which number is recorded, what the data costs and who pays, how to install past the security warnings, what happens if you turn it off | ship-docs | doc | T113,W05 | Y | 4 | 6 | 10 | A salesperson reads it without help. R4 and R18 mitigation |
| T135 | [ ] | Admin runbook: enrolment, assisted install, revocation, **leaver process (R10)**, number reassignment, retention change, alert triage | ship-docs | doc | T113,T84 | Y | 4 | 6 | 10 | Each procedure names who does it and what "done" looks like |
| T136 | [ ] | Handover pack: architecture note, wire-contract version, supported-model table, signing-key location, secrets inventory | ship-docs | doc | T127,T14 | Y | 4 | 6 | 10 | Someone who was not present can operate and rebuild the system |
| T137 | [ ] | Change-request log + §5 scope-boundary sign-off (§10 DoD) | ship-docs | doc | — | Y | 2 | 3 | 5 | §5 is unchanged, or every change has a signed request |
| T138 | [ ] | `docs/RISKS.md` release review: owner + mitigation still current per risk (§10 DoD); **R13 note handed to the BonviZvonki owner with the parallel-run comparison design** | ship-docs | doc | W10,T51 | Y | 3 | 4 | 7 | Every risk has an owner; the one-month parallel run is booked in the other repo |

---

## Phase 4 / 5 — Wave F [parallel, added for completeness]

| ID | St | Task | Owner | Type | Deps | Par | O | L | P | Done criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| T139 | [ ] | Contact-name resolution on-device; a name is uploaded **only** for a captured registered-number call, never the contact book (N28, §7, L3) | build-android | code | T67 | Y | 3 | 4 | 7 | Payload carries an optional name; a test asserts no bulk contact data leaves the device |
| T140 | [ ] | Panel: `install_disappeared` vs `offline` distinction driven by sustained heartbeat absence (UC-02, UC-18) | build-frontend | code | T86,T36 | Y | 3 | 4 | 7 | A Play-Protect-removed app is visibly different from a phone in a lift |

---

## 5. Dependency graph — what gates what

```
DAY 1 (all start together)
  W01 fleet inventory ─┬─> T12/T13 M0 runs ──> T14 M0 table ──┐
  W03 procurement ──> T124 deploy ──> T128 seed ───────────────┤   (no longer
  W07 handsets ────────────────────────────────────────────────┤   W02 withdrawn
  W12 inbound number ─┬─> T141 ──> T144 ──> T34 ──> T64 ───────┤
  W13 operator SIMs ──┴──────────────> T143 ──────────────────┤
  W08 3 salespeople ───────────────────────────────────┐       │
  T01 S1a ──> T02 S1b ──> T03 targetSdk ───────────────┼───────┤
  T04 S2a ──> T05 S2b  (closes the work-profile question)       │
  T06 Play Protect / install path ─────────────────────┤       │
  T07 dual-SIM reliability ──> T66                     │       │
  T08 prototype read ──> T26                           │       │
  T09/T10 M0 harness ──> T11 ──> T12                   │       │
                                                        │       │
PHASE 1 (independent of every spike)                    │       │
  T15..T24 foundations ──> Phase 2 M1 ──> T30 DEMO      │       │
                        └─> Phase 3 server              │       │
                        └─> Phase 5 panel               │       │
                        └─> Phase 4 waves A/B/D/F       │       │
                                                        │       │
UNBLOCKED — moved off the blocked set on 2026-09-04            │       │
  T22 ──> T71a capture API ──> T73 transcode ──> T74 upload ──> T75 reasons
  T18 ──> T19 ──> T146 ──> T147 ──> ALL of Phase 3   (one migration, three parts)
  T03 ──> T104 manifest minimisation ──> T107   (must precede the photo shoot)

STILL GATED BY S1 + M0                                  │       │
  T14 ──> T71b real strategies ──> T72 harvest ─────────┼──> T129
  T14 ──> T53 gap report ──> T91 panel ──> T133         │       │
  T06 + T82 + T104 ──> T107 screens ──> T108 guide ─────┤       │
                                                        v       │
PHASE 7 (M2)  T109 dry run ──> T110 N40 ──> T111 fix ──> T112 N40 retest ──> T113 procedure
                                                                │
PHASE 10 (M4)                            T113 + T128 ──> T129 ──┘──> T130 (7 working days)
                                                        ──> T131 ──> T132 ──> T133
```

### What can start in parallel with S1 and M0 — and what genuinely cannot

**Can start on day 1, unblocked (roughly 60 % of all `code` hours):**
Phase 1 in full (T15–T24); Phase 2 M1 thin thread (T25–T30) — deliberately
metadata-only so it does not touch the audio question; Phase 3 server waves A, B,
D, F and most of C (T41–T45 are transport and storage, not capture); Phase 5
panel waves A, B, C except the gap report; Phase 4 waves A, B, D, F.

**Cannot start until S1 (T01–T03) answers** — *materially smaller since
2026-09-04:*
- **T71b and T72 only** — the two concrete strategies and the OEM file harvest.
  T71a (interface, router, route reporting), T73 (transcode), T74 (upload client)
  and T75 (the reason enum) were wrongly blocked in revision 1 and are now day-1
  work. That is four rows and 25 likely hours moved off the blocked set.
- T104 manifest minimisation — it minimises against a permission set S1 defines,
  and it now gates T107 rather than following it.
- T107/T108 install guide — the screens depend on the flavour and therefore on
  the route. **T22 is no longer gated: `targetSdk` is a build flavour, both are
  built, and M0 selects one** (SPEC §7.2).

**Cannot start until M0 (T14) publishes the baseline:**
- T53 gap report's per-model regression alert (N4) — no baseline, nothing to
  compare to.
- T91 gap report screen's regression column, T128 seeding, T131's per-model
  verdict.
- T63 OEM-specific enrolment steps need the OEM list from **W01**, not from M0 —
  which is why W01 is the single most schedule-critical thing the client owes.

---

## 6. Critical path

Recomputed 2026-09-04 by walking the dependency table, not by hand. **The
critical path has changed shape, and it is no longer the audio path.**

### CP-1 — the only path that sets the date (**148 likely hours / 261 pessimistic**)

```
W06 → T15 → T16 → T17 → T18 → T19 → T146 → T147 → T31 → T32 → T141
    → T34 → T64 → T109 → T110 → T111 → T112 → T113 → T129 → T130 → T131 → T132
```

Read it as three segments:

1. **Foundations and the single migration** (T15–T147, 43 h). The T19 re-scope
   put T146 and T147 directly on this chain — **+14 likely hours straight onto
   CP-1**, which is the largest single cost of revision 3.
2. **The enrolment identity chain** (T31 → T32 → T141 → T34 → T64, 38 h). This
   is new to CP-1. It arrived when the SMS route was withdrawn: the callback
   route became the only verification path, and T141's receiver infrastructure
   became a prerequisite for anyone enrolling at all.
3. **The field tail** (T109 → T132, 67 h) — unchanged, and still the part no
   agent team accelerates.

### What left the critical path

**The audio path.** Splitting T71 dropped it to a 86-hour branch
(`T09 → T10 → T11 → T12 → T13 → T14 → T71b → T72 → T129 → …`) with **≈ 62 hours
of slack against CP-1**. In revision 2 it was the head of the whole plan. That is
the single largest structural improvement in this revision, and it cost nothing —
the work was never actually blocked; the task boundary was drawn in the wrong
place.

**Caveat the hours model cannot see:** the audio branch carries **W01's calendar
head** (3 / 8 / 20 working days) and M0's field runs, which are wall-clock days,
not hours. W01 therefore still deserves the same urgency it always had — it just
no longer dominates the *effort* path.

### CP-2 — external / calendar (still not critical)

```
W03 procurement (5/10/25 working days) → T124 → T128 → T129 → T130 → T131
```

Unchanged since W02's withdrawal, and comfortably inside CP-1's slack provided
procurement is started on day 1.

### The three things that shorten the schedule most

1. **W01** — the fleet inventory. It heads the audio branch and gates T63, T107
   and W07. Still a photo of Settings → About phone per salesperson.
2. **W12 + W13 together** — the inbound number and the per-operator SIMs. T141
   sits on CP-1, so a late receiver delays the release directly, not merely the
   enrolment tests.
3. **Getting T19/T146/T147 right the first time.** They are on CP-1 and they are
   one migration; a schema correction after Phase 3 starts is not a task, it is a
   rebase across every module.

---

## 7. External blocking waits — start every one of these on day 1

They cost the team almost nothing and the calendar a great deal. Calendar
estimates are **working days**, and are schedule, not effort.

| ID | Wait | Owner | Blocks | Cal. days O/L/P | If it is late |
|---|---|---|---|---|---|
| W01 | Fleet inventory (models, OS, SIM ownership, built-in recorder, trial phones, iPhone count) | client | T12, T13, T14 → **the whole audio path**; T63, T107; W07 | 3 / 8 / 20 | M0 cannot start. Build against 3 models we can borrow and re-run M0 later — a second M0 pass costs 12/16/24 h `field` |
| W02 | ~~Legal opinion, ZRU-547~~ | — | — | — | **Withdrawn 2026-09-04 — out of scope (internal project).** It was CP-2's head |
| W03 | Server + storage procurement, ≥ 250 GB. **Blocked by nothing since 2026-09-04 — no jurisdiction constraint, buy wherever is cheapest** | client | T124, T125, T126, T128 | 5 / 10 / 25 | Acceptance run slips one working day per day of delay — **but only once the delay exceeds CP-1's slack, which is now several weeks**. Formerly the release-date driver; now it is not |
| W04 | ~~Client-side notice wording~~ | — | — | — | **Withdrawn 2026-09-04 — out of scope (internal project)** |
| W05 | Who pays for the mobile data | client | T134 | 2 / 5 / 15 | Apply the recorded default (Wi-Fi-first, 1 GB cap) and state it in the manual |
| W06 | `plan-stack` session with the user | lead + user | T15 → **all code** | 1 / 2 / 5 | Nothing starts. This is the cheapest wait to close |
| W07 | Acceptance handset set (≥ 5, one per model+OS) | client | T129, T130 | 5 / 10 / 20 | M4 cannot begin. Bonvi may not routinely debug an employee's personal phone (§4.1 A) |
| W08 | Three unaided salespeople booked, plus three more for the re-test | client | T110, T112 | 2 / 5 / 15 | **M2 cannot be closed.** N40 is a measured gate, not a review |
| W09 | ~~SMS gateway account~~ | — | — | — | **Withdrawn 2026-09-04 — out of scope (internal project).** The single point of failure it warned about is now real by choice; compensated by T141/T142/T143 |
| W12 | **Dedicated inbound number + always-on receiver** for the callback verification route | client | T141 → T144 → T34 → T64 → T143 | 3 / 7 / 15 | **Nobody in the fleet can complete number verification, and it now delays the release directly — T141 sits on CP-1.** Enrolment falls entirely to T142's admin-attested path, a manual step per agent |
| W13 | **One working SIM per operator in the fleet** (Beeline, Ucell, Mobiuz, Uzmobile), for the M0 field session | client | T143 | 3 / 7 / 15 | T143 cannot produce the per-operator half of its table. Caller-ID presentation is decided by the **network**, so borrowed handsets (W07) do not substitute. Ship with an unverified operator and the first agent on it cannot enrol |
| W10 | BonviZvonki ingest adapter + one-month parallel run booked **in that repo** | client | Nothing in release 1 — it protects release 2 (R13) | 1 / 3 / 10 | The pressure to cancel MoyZvonki arrives before the evidence does. The single most expensive available mistake |
| W11 | Are out-of-hours calls on the work number in scope? (R18 mitigation 5) | client | T66 default | 1 / 3 / 10 | Default applied: yes, in scope. Recorded in ASSUMPTIONS |

**Total chase effort across the ten surviving waits: 11 / 19 / 37 hours.** Their
calendar span is now dominated by **W01** (3 / 8 / 20 working days), which sits at
the head of CP-1. No surviving wait exceeds 20 working days at the likely case.

---

## Blocked

- **T71b and T72 only** — blocked on T01/T02/T03 (S1) and T14 (M0). **T71a, T73,
  T74 and T75 were unblocked on 2026-09-04** and are day-1 work. If T02 answers
  "no, it needs developer mode", T04/T05 (S2) become urgent and Wave E is
  redesigned.
- **T12–T14 (M0)** — blocked on **W01, requested 2026-09-04, not yet received.**
- **T124–T128 (production)** — blocked on W03 only (W02 withdrawn 2026-09-04).
  Requested 2026-09-04, startable immediately.
- **T110 / T112 (N40)** — blocked on W08.
- **T34 / T64 / T141 / T144 (number verification)** — blocked on **W12**, the
  inbound number for the callback route. This replaces the withdrawn W09, it is
  the enrolment path's only hardware dependency, **and it is on CP-1**.
- **T143 (per-operator callback verification)** — blocked on **W13**, the
  per-operator SIM set. New 2026-09-04.

**Withdrawn 2026-09-04, kept in place for id stability:** W02, W04, W09, T33, T77.

---

## 8. Requirements coverage

| Requirement | Task(s) |
|---|---|
| UC-01 | T31, T32, T88 |
| UC-02 | T98, T107, T108, T110, T112, T113, T140 |
| UC-03 | T62, T63, T65 |
| UC-04 | T34, T64, T141, T142, T143, T144 — **route 2 (SMS) withdrawn; T142 adds an admin-attested route the requirements do not yet contain** |
| UC-05 | T69, T114 |
| UC-06 | T37, T65 |
| UC-07 | T31, T35 |
| UC-08 | T35, T84 |
| UC-09 / UC-10 | T26, T67 — acceptance ACs verified in T130/T131 |
| UC-11 | T67, T131 |
| UC-12 | T25, T68, T115 |
| UC-13 | T67, T116 |
| UC-14 | T41, T44, T71–T75 |
| UC-15 | T66, T72, T117, T118 |
| UC-16 | T55, T80, T121 |
| UC-17 | T36, T50, T86, T87, **T152** (the stage machine is server logic, not a panel concern) |
| UC-18 | T37, T39, T92 |
| UC-19 | T46, T89, T106, T122 |
| UC-20 | T43, T90, **T153** (N43 Service Worker bridge — `<audio src>` cannot send an `Authorization` header) |
| UC-21 | T47, T95 |
| UC-22 | T48, T97, T122 |
| UC-23 | T40, T53, T91 |
| UC-24 | T43, T54, T94 |
| UC-25 | T49 |
| UC-26 | T42, T45 |
| UC-27 | T38, T92 |
| UC-28 | ~~T77~~ — withdrawn 2026-09-04 with UC-28 itself |
| UC-29 | T51, T52 |
| N1–N7 | T10, T40, T70, T130, T131, T133 |
| N8–N12 | T78, T84 |
| N13–N16 | T119, T120, T56 |
| N17–N21 | T42, T73, T57 |
| N22–N28 | T17, T18, T20, T54, T85, T123 — N29/N30 withdrawn 2026-09-04 |
| N31–N34 | T22, T50, T81, T82, T83, T104 |
| N35–N38 | T16, T23, T24, T60, T100, T106 |
| N43 (Range + SW bridge) | T43, T153 |
| Users and access provisioning | **T148, T149** — nothing owned this before 2026-09-04 |
| Scheduled work (SPEC §10.4) | **T150, T151**, plus T38, T42, T53, T56, T57 |
| Test infrastructure (CONVENTIONS §13) | **T154**, T20 |
| N39–N42 | T37, T65, T76, T105, T110, T113 |
| §10 DoD | T05, T14, T20, T110, T113, T117, T119, T120, T123, T130, T131, T133, T134, T137, T138 |

### Risk mitigations that are tasks (RISKS.md)

| Risk | Mitigation tasks |
|---|---|
| **R17** install + permission friction (critical) | T01–T03, T06, T62, T63, T65, T86, T98, T104, T107–T113 |
| R1 device-dependent recording | T09–T14, T53, T71 (strategy interface), T75, T91, T131 |
| R2 notice + ZRU-547 | **Withdrawn 2026-09-04** — the client has taken this out of scope as an internal project. No tasks remain |
| R3 OEM battery managers | T38, T63, T69, T70, T87 |
| R4 employee resistance | T37, T39, T76, T92, T134 |
| R5 weak identity key | T25, T68, T115 |
| R6 number normalisation drift | T24, T49 |
| R7 local queue loss | T67, T78, T84 |
| **R18** private calls on a personal phone | T07, T44, T66, T72, T117, T118, T139, W11 |
| R8 no Play distribution | T06, T81, T82, T125, T127 |
| R9 future Android breaks it | T71 (route behind an interface), T38, T104 |
| R10 leaver keeps the phone | T31 (time-boxed mapping), T35, T84, T135 |
| R11 iPhone users | W01 (count them) — otherwise out of scope by §5.2 |
| R12 calls move to WhatsApp | Documented blind spot only (§5.6); no task can close it |
| R13 cancelling MoyZvonki early | W10, T51, T138 |
| R14 storage growth | T42, T57, T73, T99 |
| R15 client owes data | W01, W05, W07, W08, W11, W12, W13 |
| R16 requirements drift | T137 |

---

## 9. Three-point totals — split by type

**Revision 3, after `docs/SPEC.md`.** 154 task ids (T01–T154, plus T71a/T71b, of
which T71 is now a split marker) and 13 wait ids (W01–W13). **7 rows are
withdrawn or relocated markers at zero hours** (W02, W04, W09, T33, T77, T71,
T104's Phase 6 pointer) — kept in place so cross-references keep resolving.
**163 active rows.** Machine-computed sums; no expected values applied.

| Type | Tasks | O (h) | L (h) | P (h) | Δ vs rev. 2 (L) | Note for the estimator |
|---|---:|---:|---:|---:|---:|---|
| `code` | 111 | 444 | 689 | 1130 | **+79** | T19 re-scope (+14), Wave H's five unowned units (+36), T153 + T149 (+11), T154 (+8), T71 split (+6), scaffolds (+4) |
| `spike` | 7 | 22 | 42 | 84 | 0 | Unchanged |
| `field` | 18 | 78 | 124 | 238 | 0 | Unchanged — and still the block no agent accelerates |
| `wait` | 10 | 11 | 19 | 37 | **+2** | +W13 (per-operator SIMs) |
| `ops` | 7 | 21 | 34 | 55 | **−2** | MinIO dropped from T15 and T124 (`STACK.md`) |
| `doc` | 10 | 33 | 49 | 80 | 0 | Unchanged |
| **Total** | **163** | **609** | **957** | **1624** | **+79** | |

### Same figures by phase

| Phase | Tasks | O | L | P | Δ (L) |
|---|---:|---:|---:|---:|---:|
| 0 — Day one: waits, spikes, M0 | 24 | 60 | 104 | 194 | +2 |
| 1 — Foundations [sequential] | 14 | 61 | 95 | 147 | **+28** |
| 2 — M1 thin thread | 6 | 21 | 33 | 55 | 0 |
| **3 — Server modules (incl. Waves G, H)** | **36** | **145** | **227** | **361** | **+36** |
| 4 — Android app | 25 | 104 | 160 | 271 | +6 |
| 4/5 — Wave F | 2 | 6 | 8 | 14 | 0 |
| 5 — Web panel | 17 | 65 | 101 | 162 | +10 |
| 6 — Wiring [sequential] | 6 | 19 | 28 | 46 | −2 |
| 7 — M2 enrolment gate [field] | 8 | 34 | 53 | 98 | 0 |
| 8 — M3 survivability | 10 | 39 | 61 | 114 | 0 |
| 9 — Production [ops] | 5 | 16 | 26 | 42 | −1 |
| 10 — M4 acceptance [field] | 5 | 22 | 36 | 78 | 0 |
| 11 — Docs and handover | 5 | 17 | 25 | 42 | 0 |

**Does the T19 re-scope change which phase is the largest? No.** Phase 3 was the
largest and still is, by a wide margin (227 h likely), and it **grew more than
Phase 1 did** — +36 against +28 — because Wave H's five unowned units are all
server modules. Phase 1 moves from sixth place to fourth. The schema re-scope is
the single largest *sequential* addition (it cannot be parallelised — one
migration, one head), but it is not the largest block of work.

**Three numbers to carry into `ESTIMATE.md`:**

1. **`field` + `wait` = O 89 / L 143 / P 275 h** — 15 % of the likely total,
   17 % of the pessimistic, and **none of it moves when you add agents.** It did
   not grow in this revision; everything added was `code`.
2. **`code` is 72 % of likely hours, up from 69 %.** The SPEC made the project
   more accelerable, not less: the additions are all agent-friendly server and
   panel work. Halving `code` now moves the total by ~36 %.
3. **Pessimistic is 1.70× likely.** Concentrated in the schema (T19/T146/T147,
   +14 over likely), the audio path (+27), acceptance remediation (+16) and the
   field rows (+114).

---

## 9a. The enrolment single point of failure created by dropping SMS

Answering the question directly: **yes, it creates one, and it needed
compensating work — which is why T141, T142, T143 and W12 exist.**

UC-04 specified three verification routes in order. The requirements themselves
state that route 1 (SIM MSISDN) is **empty on most Uzbek SIMs** — that is why
routes 2 and 3 existed at all. Removing route 2 leaves **route 3 as the only
route that works for the typical agent**, and route 3 is the one with an external
hardware dependency: it needs an inbound number the server can observe caller ID
on. §5.1 rules out a PBX or SIP, so that means an office SIM in a GSM gateway or
a permanently connected Android device in receiver mode. That box did not exist
in revision 1 — it was hiding inside T34 as a fallback that nobody expected to
carry the load.

Three consequences, each now a task:

- **T141 — the receiver is fleet-wide infrastructure, not a detail.** If it is
  down, *nobody* can enrol. Its health is therefore a monitored state with an
  admin alert, on the same principle as R3's silence detection: absence of
  enrolment must be an event, not a quiet stall.
- **T143 — caller-ID presentation varies by operator and handset**, and it is
  now load-bearing rather than incidental. It has to be measured per OEM +
  operator pair before N40, not discovered during it.
- **T142 — an admin-attested fallback behind it.** Without one, an agent whose
  operator suppresses caller ID simply cannot be enrolled, and R17's rollout
  stalls at exactly the step the whole project already identifies as its top
  practical risk. The attested state is deliberately **visibly distinct** from a
  proven one, so the identity anchor never silently degrades.

**Two things the estimator should know about this.** First, T142 extends UC-04
beyond the three routes the requirements name, so it needs a change request
(T137) and an acceptance criterion from `plan-analyst` — its estimate is
currently a guess at an unspecified feature. Second, W12's calendar
(3 / 7 / 15 working days) is new and sits on the enrolment path; it is short
enough not to threaten CP-1, but only if it is requested in the same batch as
W01.

---

## 10. What could NOT be turned into a bounded task

The estimate is weakest here. Each item is a real cost that this plan cannot
size, listed so it is priced as a contingency rather than discovered later.

1. **T132 — acceptance remediation is a buffer, not a task.** Its content is
   unknown by construction: it is whatever the 7-day run finds. Sized at
   4 / 8 / 24 h, which is a guess. If M0 shows the OEM-recorder route is fragile
   across the fleet rather than absent on a couple of models, this becomes weeks.

2. **The fleet model count is unknown (W01) and everything field-shaped scales
   with it.** Six is assumed. M0 (+6/8/12 h per model), battery (+2/3/5 h per
   model), install-screen capture per Android version and the acceptance handset
   set all grow linearly. Twelve models would add roughly **70–110 h of `field`**
   — a 60–90 % increase in the one category no agent accelerates.

3. **If S1 concludes the route requires `targetSdk 28`, the install friction is
   permanent and there is no engineering fix.** The honest consequences are
   either an assisted-install visit per phone (a recurring `field` cost of about
   1–2 h per device per event, not in this plan and not a one-off) or a
   recording route that does not currently exist. §5.7 forbids root/Magisk, so
   there is no third option. I cannot bound the remediation, only name the fork.

4. **If S2 turns out viable, a large part of Phases 4A and 4E is replaced by
   different, unestimated work** — EMM provider selection, enterprise enrolment,
   policy push. Estimated in neither direction, because the requirements
   explicitly say "not recommended, not assumed" (§3.1). Treat T04/T05 as a
   branch point, not a task with a known follow-on.

5. **A second N40 failure.** One revise-and-retest iteration is budgeted
   (T111/T112). A second costs another 10 / 16 / 24 h. A third means the flow is
   wrong at the concept level and the answer is R17 mitigation 6 — **a person
   doing device visits**, which is a permanent budget line, not a task.

6. **UC-16's 5-second click-to-call bar may be unachievable on doze-restricted
   OEMs.** T55/T80 assume a WebSocket or push wake-up reaches a MIUI/EMUI phone
   in under 5 s with the app in the background. The requirements state the bar
   but give no fallback. Estimated as if it works; if it does not, the requirement
   needs renegotiating, not more hours.

7. **Play Protect is not a stable target.** T06 measures its behaviour once.
   Google can change it between the spike and go-live, or after go-live, and no
   task in this plan prevents that. It is a recurring maintenance risk (R8, R9)
   that release 1 does not price.

8. **N4's remedy is a purchasing decision, not engineering.** When a model falls
   below its baseline, Bonvi either buys that person a handset or accepts that
   they are uncovered (ASSUMPTIONS, withdrawn line). No task can be written; the
   cost depends on how many people, which depends on W01.

9. **The callback route's caller-ID behaviour is not under our control.**
   T141/T34 assume the inbound number sees a usable caller ID from every operator
   and handset in the fleet. T143 measures it, but if an operator suppresses or
   rewrites caller ID for some agents, those agents can only be enrolled through
   T142's admin-attested path — a manual step per person, repeated on every phone
   change. Priced as if T143 mostly passes.

10. **T142 extends UC-04 beyond the three routes the requirements name.** An
    admin-attested binding is weaker evidence than a proven one, and the
    requirements have no acceptance criterion for it. It needs a change request
    (T137) and an AC from `plan-analyst`; until then its estimate is a guess at
    an unspecified feature.

11. **The 7-day acceptance window is 7 working days of wall clock, and a failure
    means repeating it.** A second window is another 7 working days that no
    amount of parallelism, staffing or agent tooling touches. Only one window is
    in the plan.

12. **Two new documents contradict each other on the Android build shape.**
    `SPEC.md` §7.1/§11.1 specifies multiple Gradle modules (`:capture:api`,
    `:capture:oem`, `:capture:mediastore`, `:capture:transcode`);
    `CONVENTIONS-CLIENT.md` §5 specifies **one `:app` module** with a `capture/`
    package and calls multi-module "parallel builds this project does not need".
    T22, T71a and T71b are estimated against the **single-module** shape, which
    is the cheaper of the two. If the multi-module shape wins, add roughly
    **4 / 6 / 10 h** to T22 and re-check the flavour × module Hilt binding.
    Owner: `plan-architect`; it is one sentence to settle and it should be
    settled before T22 starts.

13. **T142's `/users`-adjacent surfaces are missing from the SPEC too.**
    `SPEC.md` §5.2's page table has no `/users` route, so T149 implements a
    screen the specification does not describe. Raised in T137 as a change
    request; until it is answered, T149's estimate is a guess at an unspecified
    feature — the same defect T142 already carries.

14. **Release-2 coupling work (R13) is not in this estimate at all.** The
    BonviZvonki ingest adapter and the one-month parallel run live in that
    repository (§5.4). W10 books it; it is not costed here, and if it is
    forgotten the release-1 investment is exposed to the most expensive available
    mistake.

---

## Status

**Not started.** 0 done · 0 in progress · 10 active external waits (W01, W03,
W05, W06, W07, W08, W11, W12, W13 outstanding; W06 `plan-stack` **closed** —
`docs/STACK.md` exists). 7 rows withdrawn or relocated.

**On the critical path right now:** **W12** (the inbound number for the callback
receiver) — T141 sits on CP-1, so a late receiver moves the release date.
**W01** heads the audio branch, which has ~62 h of slack in effort but carries
its own wall-clock days. Nothing technical is blocked; T15 can start today.

**Next concrete action:** send the client one batch request covering W01, W03,
W05, W07, W08, W11, **W12** and **W13** (per-operator SIMs) today, then start
T15 and T01 in parallel — T01 being the read of
`../CallSentry/app/src/main/java/uz/callsentry/service/recording/`) — it needs
nobody's permission and it unblocks the entire audio path.
