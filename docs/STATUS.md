# BonviCall — where the build stands

**2026-09-05.** Paused at the client's request. Everything below is committed,
verified, and running. Start here when work resumes.

```
server   580 tests    panel  120 tests    android  133 tests × 2 flavours
```

Stack up with `make up` · panel **5190** · api **8020** (`/docs`) · postgres **5443**

**Demo fleet:** `make demo` (or `make demo-reset`). 5 agents, 5 devices, 45 calls,
23 recordings, 2 alerts. Login `admin@bonvi.uz` / `Bonvi2026!` — also
`manager@`, `sales@` (own-scope only).

---

## Done

| Area | State |
|---|---|
| **Docs** | REQUIREMENTS, SPEC (2.8k lines), TASKS, RISKS, CONVENTIONS ×2, ESTIMATE, STACK, S1-RECORDING, BUILD-VS-ADOPT, ASSUMPTIONS |
| **Server** | 30 tables in one migration; device/panel/service APIs; enrolment chain end to end; audio pipeline (resumable upload, attribution gate, Range playback, retention); calls, reports, export, audit, settings, alerts; scheduler with 12 jobs; WebSocket hub |
| **Panel** | Shell, RBAC in two places, generated types, type-level Uzbek catalogue; calls list + detail + audio player (Service Worker bridge); agents (rollout page), devices, alerts, gap report, audit |
| **Android** | Scaffold, both flavours, capture seam, call lifecycle, durable queue, privacy boundary as a type, enrolment E1–E6 |

**Milestone M1 is met**: a call placed on a device appears in the panel, exactly
once, with its audio or a reason there is none.

---

## Start here when resuming

### 1. `int64` on the wire — the one real correctness bug outstanding

Pydantic's `int` is unbounded, so nine 64-bit fields reach the contract as a
formatless `integer`, and **openapi-generator maps that to Kotlin's 32-bit
`Int`**. `System.currentTimeMillis()` is ~1.77e12 against `Int.MAX_VALUE` of
2.1e9. The server stores them as BIGINT — the data model is right and only the
wire schema is under-specified, which is why neither side looks wrong on its own.

Fix in `server/src/api/device/schemas.py`:

```python
Int64 = Annotated[int, Field(json_schema_extra={"format": "int64"})]
device_epoch_ms: Int64
```

Affects `device_epoch_ms` on `DeviceRedeemIn` / `DeviceCallIn` /
`DeviceHeartbeatIn`, plus the byte counters on `DeviceHeartbeatIn` and
`DeviceEventDetailIn`. Android has a machine-applied stopgap
(`android/scripts/widen_int64.py`) and `Int64WireContractTest` fails the moment
a listed field *gains* the format — that is the signal to delete the entry and,
with the last one, the script.

### 2. Phase 6 — wiring

Deliberately deferred while three agents worked in parallel. `docs/PENDING_WIRING.md`
lists what is waiting; the WebSocket router needs one `include_router` line in
`src/api/device/__init__.py`. Shared files (`main.py`, `core/permissions.py`,
alembic head, panel `router.tsx`) have been frozen throughout and are safe to
touch once nothing is running.

### 3. Smaller items, each with a note where it lives

- `IssuedTokensOut` carries no `verification_method`, so an admin-attested
  binding cannot be told from a proven one after a token refresh without the
  client's persisted copy (SPEC §9.3).
- Alert `title_uz` is English (`"Device offline"`) and `body_uz` is the same
  generic sentence for every kind. The panel routes around it with its own
  `AlertKind` maps; the device API and any notification path would carry the
  English straight through.
- `capability_states` is empty in the demo fleet — a seeder gap, not an
  endpoint bug; the device page's capability matrix renders empty everywhere.
- `backup_verify` is written but deliberately unregistered: there is no backup
  mechanism until T124, and an alert nobody can act on trains people to ignore
  alerts.

---

## Still unbuilt

- **`AN-HARVEST` (T71b)** — the real OEM capture strategies. Genuinely blocked
  on S1 + M0; the fail-closed `NoOpOemRecordingLocator` is the correct
  placeholder until then.
- Panel Wave C (users, settings, app versions, dashboard tiles).
- Android waves D–E (device UX, distribution, in-app update).
- Phases 7–11: the N40 enrolment gate, survivability, production, the 7-day
  acceptance run, the Uzbek `QOLLANMA.md`.

---

## Still owed by the client — all three block field work, not code

1. **The fleet list** — model, Android version, and whether each handset has a
   built-in call recorder. This gates M0, and M0 gates the audio path.
2. **An inbound number and an always-on receiver** — a company SIM in a gateway,
   or one Android left plugged in. **Without it nobody can enrol at all**, and it
   sits on the critical path.
3. **One SIM per operator** (Beeline, Ucell, Mobiuz, Uzmobile) — caller-ID
   presentation is the network's decision, so the callback verification route
   has to be measured per operator, not per phone model.

---

## Habits this build earned, worth keeping

**Make a test fail before believing it passes.** Seven separate cases here of a
test reporting safety it was not testing: a shared app instance authenticating
every role as admin, a frozen clock that never reached the service, an audio
root the service never read, a leaked row inflating eleven unrelated counts.
Each one *passed* while testing nothing.

**When you are handed one instance of a bug, go looking for its siblings.** The
inner join that hid a never-reporting phone was in three places, and the two the
report did not mention were the ones that mattered — the sweeps that were
supposed to raise the alarm.

**Make the demo data non-uniform.** Two handsets that cannot record, one that
never sends a heartbeat, one recording already past retention. Both of the
worst bugs found this week were found because the fixtures were not all healthy.
