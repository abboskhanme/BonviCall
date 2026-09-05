# BonviCall — where the build stands

**2026-09-05, revision 2.** Everything below is committed, verified and running.

```
server   647 tests    panel  171 tests    android  220 tests × 2 flavours
```

**68 % of the plan by effort — and 91 % of the code.** Of the 325 hours left,
**263 are field work** (M0, the enrolment gate, survivability, the acceptance
run), 27 are ops, 8 are docs, and **28 are code**. The build phase is
effectively over; what remains needs handsets and people, not more agents.

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
| **Panel** | Shell, RBAC in two places, generated types, type-level Uzbek catalogue; calls + audio player (Service Worker bridge); agents as the rollout page; devices, alerts, gap report, audit, users, settings, app versions, dashboard |
| **Android** | Both flavours; enrolment E1–E6 with real capability checks; call detection from two sources; `client_call_id` as a server-matching UUIDv5; durable queue and upload; call-log recovery; transcode to mono 16 kHz Opus; resumable audio upload; revocation; token refresh; click-to-call; heartbeat; APK signing and in-app updater |
| **Field docs** | `ON-DEVICE-TESTING.md`, `APK-SIGNING.md`, and `QOLLANMA.md` — the Uzbek page for the person carrying the phone |

**Milestone M1 is met**: a call placed on a device appears in the panel, exactly
once, with its audio or a reason there is none.

---

## Start here when resuming

### The only thing that matters now: put it on a phone

`docs/ON-DEVICE-TESTING.md` — eight steps from a laptop to a captured call.
`docs/QOLLANMA.md` is the Uzbek page to hand the person carrying the phone.

Everything in this system has been verified by `scripts/demo_data.py` or a
script driving the API. **No part of it has ever run on a handset.** That is not
a gap in the plan; it *is* the plan's next 263 hours, and the first hour of it
answers five questions at once — does the app install, is the enrolment flow
followable unaided, does detection fire, does the call arrive, and the one that
decides the project's shape: **is there audio.**

The audio chain is complete and covered end to end — record → transcode to mono
16 kHz Opus → resumable upload → server-verified checksum → local delete — and
`MediaRecorderStrategy` already works. Only `OemHarvestStrategy`'s locator is
`NoOp`. So on a Samsung the first tester may get a recording, not just a call
log. `ON-DEVICE-TESTING.md` deliberately promises the pessimistic case.

### The 28 hours of code that remain

- **T71b / T72 — the OEM harvest locators.** Genuinely blocked on M0: writing
  them before knowing which route wins on Bonvi's actual handsets is building on
  a guess. This is the only remaining task whose shape depends on field data.
- `StorageReportPage` — the last panel stub; `/reports/storage` and
  `/reports/data-usage` both answer correctly and have data behind them.
- T103, T145 and the Phase 4/5 wiring tasks.

---

## Still unbuilt

- **`AN-HARVEST` (T71b / T72)** — the real OEM capture strategies. Blocked on
  S1 + M0; the fail-closed `NoOpOemRecordingLocator` is the correct placeholder.
  Note this does **not** mean the app cannot record: `MediaRecorderStrategy` is
  functional and wins on some handsets. Only the preferred route is missing.
- `StorageReportPage`, the last panel stub.
- **Phases 7–11**: the N40 enrolment gate (3 unaided salespeople, stopwatch),
  survivability on real hardware, production deployment, the 7-day acceptance
  run. All of it needs handsets.

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

**A finished component with no caller passes every test it has.** This happened
three times: the WebSocket router complete and unreachable because nothing
included it; `DeviceCallsApi.heartbeat` with no caller, so no handset ever
reported anything after enrolment; a version-code field the server read from a
header nothing sent. Each component's own tests were green throughout, because
each test supplied the caller the product did not. The guards that now catch
this — `test_every_router_module_is_registered`, and a contract test asserting
enrolment and heartbeat read the same constant — were written after the fact.
Ask of any finished piece: *who calls this in production?*

**Make the demo data non-uniform.** Two handsets that cannot record, one that
never sends a heartbeat, one recording already past retention. Both of the
worst bugs found this week were found because the fixtures were not all healthy.
