# Plan — a CallSentry-shaped app on the BonviCall server

**2026-09-11.** Written after two days of driving the app on a real Redmi Note 14
(Android 15) and after reading the CallSentry source at
`~/Documents/Projects/CallSentry`.

The client's instruction, in their words: the app should be *the same as
CallSentry* — the panel hands an employee a **login and a password**, they type
it into the app, and it works. Fewer buttons, a design an ordinary person
understands. Plan first; then get as much as possible out of the app as it
stands; then, if that is not enough, execute this plan.

---

## 1. What is actually different between the two apps

Not the recording, and not the stack. Both are Kotlin + Compose + Hilt + Room +
WorkManager + Retrofit + WebSocket, both target the same handsets, and both have
six screens.

The difference is **how a phone becomes a known phone**.

| | CallSentry | BonviCall today |
|---|---|---|
| Identity | login + password → `{token, agentId, wsUrl}` | single-use enrolment code |
| Proving the number | none | SIM MSISDN, or a callback to a receiver line, or admin attestation, or self-declared |
| Device binding | none | fingerprint-bound token, rotating refresh, replay detection |
| Screens to "recording" | Login → Onboarding → Dashboard | E1 code → E2 permissions → E3 OEM → E4 SIM → E5 verify → E6 done → Home |

**Every failure found in two days of live testing was in that second column**,
and none of it exists in CallSentry:

- no route to `active` at all, so the phone captured and shipped nothing;
- a rotating refresh token that, once a response was lost, locked the handset
  out permanently;
- an upload queue that parked its whole contents after ~1 h 45 m of an
  unreachable server and never retried;
- the documented recovery — a new code — unreachable from the app's own UI.

That column is SPEC §9's privacy boundary, and it was built because the SPEC
asked for it. It is also, for a fleet of ~15 phones belonging to one company,
more machinery than the risk warrants.

## 2. Two corrections the client should have before deciding

**CallSentry DOES solve two-sided recording, and this document said the
opposite until the source was read.** The README's "Ma'lum cheklovlar" section
describes only half the app. The code does two things the README does not
mention:

1. **It targets SDK 28 on purpose.** `CallSentry/app/build.gradle.kts:18-21`:
   *"MUHIM: qo'ng'iroq yozib olish uchun ataylab 28 … targetSdk 29+ bo'lsa
   Android suhbatdosh ovozini va phoneCall FGS turini qattiq cheklaydi; 28
   'eski rejim'da ko'p qurilmalarda ikkala tomon ham yoziladi."* At 28 the
   far-side restriction and scoped storage do not apply.
2. **It harvests the handset's own call-recording file and prefers it over its
   own.** `service/recording/OemRecordingLocator.kt` scans external storage,
   matches a file to a call by time window (`answeredAt − 5 s` …
   `endedAt + 120 s`), size ≥ 2048 B and extension, and takes the newest;
   `CtiForegroundService.kt:382` then picks `oemFile ?: ownFile`. The filename
   is never parsed. Its own `MediaRecorder` is the fallback, and it probes
   `VOICE_CALL → VOICE_RECOGNITION → VOICE_COMMUNICATION → MIC`.

**BonviCall already has the same idea** — the `legacy28` flavour, `targetSdk =
28`, with a comment that reaches the same conclusion almost word for word
(`android/app/build.gradle.kts:141-146`). What it does not have is the other
two halves:

- `OemRecordingLocator` is `NoOpOemRecordingLocator` in **both** flavours —
  task `T71b`, deliberately left until a real handset could say where the files
  land. That handset is now on the desk.
- `VOICE_CALL` is excluded from `AudioSource` with the comment *"it is the best
  source and it is forbidden to non-system apps"* — true at targetSdk 34, and
  **not true at 28**, which is the flavour that was supposed to use it.

And all of this was tested with the wrong build: every install on the Redmi so
far has been **`modern34`**, the flavour that by design cannot record the far
side. One caution: CallSentry's watched directories are Samsung-shaped
(`Recordings/Call`, `Sounds/Call`, …) and include no MIUI path, so on this
Redmi its harvest would miss too; `/sdcard/MIUI/sound_recorder/call_rec` exists
and is empty because the handset's own recorder is switched off.

**CallSentry has no backend.** Its README: "Ilova quyidagi endpointlarni kutadi
(backendni o'zingiz yozasiz)" — six endpoints, sketched, unimplemented.
BonviCall's server is complete and covered by 702 tests, and its panel by 244:
calls, audio pipeline with resumable upload and retention, reports, export,
audit, alerts, RBAC, a 12-job scheduler. Migrating *to* CallSentry means
writing all of that.

So the recommendation is not "switch to CallSentry". It is **keep the BonviCall
server and panel, and give the app CallSentry's front door**.

## 3. What already exists and needs nothing

The server's `users` table already models exactly what is wanted:

- `email`, `password_hash`, `role` ∈ {admin, manager, sales}, `must_change_password`;
- `agent_id`, **mandatory when `role = 'sales'`**, enforced by a check
  constraint — a sales login *is* a salesperson;
- the agent's active assignment resolves to their registered number.

The panel already creates such users and resets their passwords
(`UsersPage.tsx`, `UserModal.tsx`, `ResetPasswordModal.tsx`), and
`POST /api/v1/auth/login` already authenticates them.

**So "login + password for the employee's phone" is one endpoint away, not a
rewrite.**

---

## 4. The plan

### Phase 1 — server: a device login (additive, nothing removed)

`POST /api/device/v1/auth/login` — public, rate-limited.

Body: `{email, password, device{...}, device_fingerprint, app{...}}`.

1. Authenticate with the existing `AuthService.login`.
2. Refuse anything but `role = 'sales'` — an admin's password must not enrol a
   handset.
3. Resolve the user's `agent_id` → the agent's assignment in force now → the
   registered number. No number, no login: the error says so.
4. Find or create the installation for (agent, number, fingerprint); an
   existing one on another handset is *replaced*, which is the rebinding path
   that already exists and already keeps the queue.
5. Activate with a new `VerificationMethod.PASSWORD`, its own funnel stage, its
   own audit row. Weaker than a proven number and rendered as such, exactly as
   `self_declared` is.
6. Return the real device token pair plus agent name and registered number.

`must_change_password` is answered on the phone with the same screen the panel
uses, or the flag is cleared for device logins — decide when building; do not
let it silently refuse.

**The enrolment-code path stays.** It is tested, the panel exposes it, and
deleting it is a separate decision from adding this one.

### Phase 2 — app: three screens instead of seven

```
Login  →  Ruxsatlar  →  Bosh sahifa
```

- **Login** — server address, login, password. Three fields, one button. The
  address is prefilled from the build and hidden behind "Boshqa server" unless
  the login fails, so the ordinary employee sees two fields.
- **Ruxsatlar** — the screen built on 2026-09-09: one button, every runtime
  permission in a single request, the two settings-screen ones offered only
  when they are not already satisfied. This part is done and works on the
  Redmi.
- **Bosh sahifa** — number, recording/not recording, queue depth, two links
  (my calls, diagnostics). Already close.

Deleted from the graph: `enrol/code`, `enrol/oem`, `enrol/sim`, `enrol/verify`,
`enrol/done`. The OEM guidance moves onto the permissions screen as one card on
the manufacturers that need it; the SIM choice moves to the same screen when
the handset has two.

### Phase 3 — panel: hand the credentials over

On the agent's page: **"Telefon uchun login"** — the employee's e-mail, a
generated password shown once, and a QR/link that opens the installed app with
the server address prefilled. Reuses the existing user create / reset-password
endpoints; no new server work beyond Phase 1.

### Phase 4 — the design pass the client actually asked for

One primary action per screen, larger type, fewer sentences, status as colour
and one word rather than a paragraph. The current screens explain themselves at
the length of a leaflet; on a phone, in a shop, that reads as clutter. This is
its own pass, done against screenshots from the real handset.

### Phase 5 — the recording question, answered with a measurement

Before building anything else here: place one real answered call on the Redmi
with the app enrolled and running, and record what comes out — which
`capture_route` wins, whether the audio contains one voice or two, and whether
MIUI's own recorder writes a file when it is switched on. Only then decide
whether to build the OEM harvest (`T71b`), which is the only path to the far
side's voice.

---

## 5. Order, and what blocks what

1. **Phase 5's measurement comes first.** It costs one phone call and it decides
   whether this product can do what the client believes it does. Everything
   else is cheaper to change than to un-build.
2. Phases 1 → 2 → 3 are a week's shape of work and can be done in that order,
   each shippable.
3. Phase 4 runs alongside 2.

## 6. What this plan deliberately does not do

- It does not delete the privacy boundary from the server. The app stops
  *walking* it; the server keeps enforcing what it enforces, and the enrolment
  code stays available for a handset that needs it.
- It does not migrate to the CallSentry codebase. That trades a finished,
  tested backend for six sketched endpoints.
- It does not promise two-sided audio. Nothing in either app can promise that
  on Android 15 without the handset's own recorder.
