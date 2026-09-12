# BonviCall — where the build stands

**2026-09-09, revision 3.** Everything below is verified and running.

```
server   702 tests    panel  244 tests    android  352 tests × 2 flavours
```

⚠️ **Read "The enrolment could not complete, on any handset" below first.**
Until 2026-09-09 no phone on this fleet could finish enrolment at all, so
nothing above about capture had ever been reachable in the field.

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

The audio chain is complete and, since 2026-09-06, **actually called** — record
→ transcode to mono 16 kHz Opus → resumable upload → server-verified checksum →
local delete. Until that date nothing constructed a capture router or ran the
pipeline, so every call shipped with `capture_route = none`; the parts all had
tests and none of them had a caller. `MediaRecorderStrategy` already works and
only `OemHarvestStrategy`'s locator is `NoOp`, so on a Samsung the first tester
may get a recording, not just a call log — but recording and transcoding are
the Android runtime, which no JVM test can exercise, and the first install is
where that is answered. `ON-DEVICE-TESTING.md` deliberately promises the
pessimistic case.

### The 28 hours of code that remain

- **T71b / T72 — the OEM harvest locators.** Genuinely blocked on M0: writing
  them before knowing which route wins on Bonvi's actual handsets is building on
  a guess. This is the only remaining task whose shape depends on field data.
- `StorageReportPage` — the last panel stub; `/reports/storage` and
  `/reports/data-usage` both answer correctly and have data behind them.
- T103 and the Phase 4/5 panel wiring tasks. **T145 (Android navigation and
  graph) landed 2026-09-06** — see below.

---

## The Android wiring pass, 2026-09-06 (T145)

The enrolment flow **did not navigate**: the ViewModel moved its step from E1 to
E2 and nothing was watching. A live handset sat on the code screen pressing
"Davom etish" while every redeem succeeded, because a repeat from the same
fingerprint is deliberately idempotent server-side. Looking for its siblings
found six more of the same shape — a finished component with no caller:

| Was finished, and had no caller | Now |
|---|---|
| `state.step` → the navigation graph | `Routes.forStep` + `FollowEnrolmentStep` on all six destinations |
| The SIM list → `onSimOptions` | Read at the E2 boundary; a single-SIM phone saves its subscription, without which Guard 1 rejected **every** call |
| E3 (OEM steps) | Reachable, with one exit; `OemGuidance` in `domain/` so the flow and the screen agree |
| `CaptureService` at the end of enrolment | `CaptureLauncher` starts it and sends one heartbeat at E6 |
| `Heartbeat.send()` | `HeartbeatWorker`: 15 min, plus a service start and E6 |
| `/commands` (DTOs generated, no interface) | `DeviceCommandApi` + `CommandRunner`, and the socket that makes a dial ring |
| `AppUpdater`, `Revocation`, `DialCommand` | Driven by the heartbeat, the upload worker and the command runner |
| `HomeScreen`, `MyCallsScreen` | A real home screen, and a route into the calls list |
| **`CaptureRouterFactory` and `AudioPipeline`** | The capture path is now run: recording starts when a call is answered, the outcome is written on the call row, and `AudioDrain` uploads it once the call's metadata has landed |

⚠️ **The audio path had never been called at all.** Every call was queued with
`capture_route = none` and no recording — on a product whose purpose is the
recording — because nothing constructed a router or ran the pipeline. The
strategies, the transcoder, the resumable upload and the deletion rules were
all built and tested; what was missing was the four calls between them. Room
migration 1 → 2 adds `audio_jobs` and the capture outcome on `pending_calls`,
because the service is killed between a call ending and its audio being queued
on most of this fleet — in memory, that is a recording of a call that happened,
lost. `RoomMigrationTest` compares the migration against the schema Room
exported, and was verified by deleting a column from it.

`ProductionCallersTest` now asks **who calls this in production?** of eleven
capabilities, and was verified by deleting two callers and watching it fail.
`LiveCommandChannelTest` and `LiveRealtimeSocketTest` drive the panel's own
button through a real server to a real acknowledgement.

---

## The enrolment could not complete, on any handset (2026-09-09)

The app installed, walked its six screens, and then stopped — every time, on
every phone, for a reason no test could see.

`capture_state = capturing` needs an **active** installation, and an
installation becomes active only by proving its number. There were two routes
and both are unavailable on this fleet: route 1 reads the SIM's own MSISDN,
which Uzbek SIMs do not publish, and route 2 dials a company receiver line that
has never existed. Admin attestation was the documented third way and **could
not reach the phone**: the real token pair is minted at verification, and no
device-facing endpoint existed to collect it afterwards. So the handset sat on
E5 holding a provisional token, uploading nothing, while the panel showed a
device that had never reported.

Every piece of this was individually correct and tested. What was missing was a
route out.

| Was | Now |
|---|---|
| E5 dead-ends on `callback_receiver_down` | `POST /enrolment/verify/self` — route 3, `self_declared` |
| An admin attests and the phone never finds out | `GET /enrolment/status`, polled from E5 every 5 s |
| `expires_in` says 900 s; the token lives 12 h | Derived from `DEVICE_ACCESS_TOKEN_HOURS` |
| E2: nine capabilities, one card at a time | One `RequestMultiplePermissions`, then every check at once |
| E5's only exit is "dial and wait five minutes" | "Keyinroq tasdiqlash", offered even when route 2 works |

**`self_declared` is the weakest of the four bindings and is rendered as such
everywhere** (SPEC §9.3). It claims only that whoever held the single-use code
an admin issued *for one number* typed it into this handset. It has its own
`verification_method`, its own `funnel_stage`, its own audit action, and the
panel shows it `warn` as "Raqam tasdiqlanmagan" — with attestation still
**offered**, so it is a queue an admin works through rather than a hole.
`enrolment.allow_self_declared` turns it off; the default is on, because the
alternative default is a fleet that cannot enrol.

Two crashes on the same pass, both on paths only a handset reaches:

- **`CaptureService.start()` could throw**, and `PhoneStateReceiver` called it
  unguarded. From API 31 a background `startForegroundService` is refused
  unless the app is battery-exempt — which an agent may decline (UC-14). That
  is a crash **on every incoming call**, which is exactly what "the app does
  not work" looks like from the outside. The guarantee now lives in `start()`.
- **The foreground service had no microphone-free candidate.** From API 34 the
  `microphone` type requires RECORD_AUDIO granted; without RECORD_AUDIO both
  candidates threw and the untyped fallback inherited the manifest's types and
  threw too, so the service never started — and a phone that should have logged
  calls without audio logged nothing. A `dataSync`-only last resort fixes it.

And one test suite that had quietly stopped guarding anything: `fleet.test.ts`
carried absolute timestamps against a real clock, so **48 hours after it was
written every fixture became `install_disappeared`**. Twelve of its tests were
failing. Ages are stated as ages now.

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
