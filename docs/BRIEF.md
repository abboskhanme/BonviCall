# BonviCall — input brief for plan-analyst

Written 2026-09-04 from the user's answers and from sibling projects on this
machine. This is raw input, NOT the requirements document.

## What the user decided (asked and answered, 2026-09-04)

1. **BonviCall is our own telephony platform — a replacement for MoyZvonki.**
   Numbers, call recording, call history, click-to-call — all owned by us.
   Bonvi stops paying MoyZvonki monthly and the call audio stays on our servers.
2. **Completely independent of BonviZvonki.** New repo, new database, its own UI.
   BonviZvonki keeps running on its own. No shared database, no API coupling
   required for the first release.
3. Built from scratch ("bu project yangi quramiz").
4. **CallSentry was only a throwaway sample.** The user's words: "callsentry ga
   o'xshash undan yaxshiroq yasashimiz kerak, u namuna project edi" — we must
   build something like CallSentry but *better*; it was a demo project.
   So BonviCall is the WHOLE platform, all of it new:
   **a new Android app + the server behind it + a web panel.**
   CallSentry is a reference to learn from and to beat, NOT a component to
   reuse and NOT a contract we are bound by.

## Why this project exists (inferred from BonviZvonki, must be validated)

`../BonviZvonki` is Bonvi's call-analytics + sales-control platform. It pulls
call recordings from **MoyZvonki** (an external SaaS telephony provider), runs
ASR, scores the conversation with an LLM against a rubric, collects client
ratings via a Telegram bot, and imports SAP `.xlsx` exports to compute a
"suspicious sales" queue.

Its documented pain points with MoyZvonki, taken from `../BonviZvonki/STATUS.md`:

- "Call audio is NOT stored by us. It is streamed from MoyZvonki." — no
  ownership of the company's own recordings.
- Employee names arriving from MoyZvonki are frequently a place name instead of
  a person — the provider's data model does not match Bonvi's org structure.
- Internal vs external call classification depends on a hand-maintained admin
  setting (`moizvonki.internal_numbers`, e.g. `*700`).
- The company line list only fills up if MoyZvonki is configured correctly.
- Configuration lives in `MOIZVONKI_DOMAIN` / `MOIZVONKI_USER` /
  `MOIZVONKI_API_KEY`; if those break, no new calls arrive at all.

So the motivation is: vendor lock-in, no audio ownership, poor data quality,
and a recurring bill.

## The reference prototype — `../CallSentry`

The user has explicitly downgraded this from "asset" to "sample": it is a demo
that proves the shape of the idea. Read it for what it got right and, more
usefully, for what it got wrong. **BonviCall's Android app is written new.**

`../CallSentry` is a **prototype Android CTI app** (Kotlin, Jetpack
Compose, MVVM + Clean Architecture, Hilt, Room, WorkManager, DataStore,
Retrofit/OkHttp/Moshi, OkHttp WebSocket, FCM, Media3). Its own README describes
it as "a MoyZvonki-style CTI app that turns each employee's SIM-equipped Android
phone into a call-center terminal: it detects calls, records them where
possible, syncs history to the server, dials on a command from the CRM
(click-to-call), and stays connected in real time over WebSocket/FCM."

It has screens for: login, onboarding, dashboard, call history, call detail,
settings, CRM selection, and **AmoCRM setup** (there is an `AmoCrmApiService` +
`AmoAuthInterceptor` — the app can talk to AmoCRM directly).
It has services for: call detection, recording, SMS, and a sync queue.

**CallSentry's API is a starting sketch of the contract, not a requirement.**
It is worth reading because a real client had to make these calls work, so it
records which operations actually turned out to be necessary. Improve it freely
— the version below has visible weaknesses (no pagination, no idempotency key
beyond `localId`, no chunked/resumable audio upload, no token refresh, no
call-recording consent flag, no device or SIM identity, no error contract).
Taken verbatim from `../CallSentry/app/src/main/java/uz/callsentry/data/remote/`:

REST (`api/ApiService.kt`):
```
POST api/mobile/auth/login          {login, password} -> {token, agentId, wsUrl}
POST api/mobile/calls               CallMetadataRequest -> {id}
POST api/mobile/calls/{id}/audio    multipart file -> 200
POST api/mobile/calls/{id}/events   {type, at} -> 200      type: ringing|answered|ended
POST api/mobile/agents/heartbeat    {agentId, timestamp, online} -> 200
POST api/mobile/agents/fcm-token    {token} -> 200
```

`CallMetadataRequest` fields:
`direction, remoteNumber, contactName?, agentId?, startedAt, answeredAt?,
endedAt?, durationSec, localId`. Dates are **ISO-8601 strings**, not epoch
millis — a DTO comment notes the app was written against a **.NET** server that
expected `DateTime`. BonviCall's stack is an open question (see below), but the
wire format is already fixed by the shipped app.

WebSocket (`ws/WsMessages.kt`):
- server -> app commands: `dial` (commandId, number), `ping`, `logout`,
  `config_update` (commandId, config object), `send_sms` (commandId, to, text)
- app -> server: `{"type":"ack","commandId":..,"status":"done|failed"}` and
  `{"type":"presence","agentId":..,"online":..}`

Use this to size the server's minimum surface, then design a better one.

## What the analyst must work out

The user gave the destination, not the route. In particular:

- **What "our own telephony" actually means here.** There are two very different
  readings and they lead to different systems:
  (a) a *SIM-phone fleet* platform — the CallSentry model, where the calls ride
      on ordinary mobile SIM cards in employees' Android phones and the server
      only orchestrates, stores and reports; no SIP, no PBX, no telecom operator
      contract; or
  (b) a *real PBX* — SIP trunks from an operator, Asterisk/FreeSWITCH, company
      numbers, IVR, queues, transfers, softphones.
  CallSentry is a working proof that (a) is buildable, and (a) is far cheaper
  and has no operator/licensing wait. Recommend one, state the trade-off, and
  put the other in the scope boundary.
- **What "better than CallSentry" concretely means.** This is the user's actual
  brief and it must not stay a slogan. Turn it into testable acceptance
  criteria. Candidate dimensions, to be confirmed and prioritised:
  no call is ever lost (guaranteed at-least-once sync with idempotency, survives
  reboot / force-stop / airplane mode / battery optimisation); recording that
  actually works on the OEM devices Bonvi owns, with an honest fallback when it
  cannot; battery and data cost low enough that employees do not disable it;
  the employee cannot silently turn it off without the admin seeing;
  a real admin web panel (CallSentry has no server-side UI at all);
  multi-device and device-change handling; audio quality and storage cost;
  observability — the admin can see which phone stopped reporting and why.
  Ask the user which of these hurt in the CallSentry trial, if it was trialled.
- Who the users are and what each role must be able to do. BonviZvonki uses
  `admin` / `manager` / `sales` / `viewer` with `sales` seeing only their own
  records — reuse that shape unless there is a reason not to.
- Call recording legality. CallSentry's own README carries a legal warning that
  in many jurisdictions the other party must be told the call is recorded. This
  is a real requirement, not a footnote: consent, notice, retention period,
  who may listen.
- Android call-recording reality. Since Android 10 the platform blocks
  third-party call recording for normal apps; the workable paths (accessibility
  services, vendor-specific APIs, device-owner/enterprise provisioning, rooted
  or specific OEM devices, or a Bluetooth/loopback trick) each have a different
  cost and reliability. This is the single biggest technical risk in the
  project and must be in RISKS.md with a mitigation and a fallback (e.g. calls
  are still logged even when audio cannot be captured — note that BonviZvonki
  already carries a file literally named
  `audiosiz_qongiroqlar_zaxira.csv`, "calls without audio, backup").
- Audio storage: volume, format, retention, where it physically lives, and how
  much disk that is per month.
- What happens to the MoyZvonki data that already exists — migrate, or leave it
  in BonviZvonki? The user said "completely independent", which suggests leave
  it, but confirm.
- Whether AmoCRM matters. CallSentry has an AmoCRM client and a CRM selection
  screen. Does BonviCall need to push calls into AmoCRM, or was that scaffolding
  for a different customer?
- The split of work across the three pieces (Android app, server, web panel) and
  what the smallest end-to-end release 1 looks like — a call placed on a real
  phone appearing in the web panel is the natural first milestone.
- Whether SMS sending (already in the WS contract and in `service/sms`) is in
  scope for release 1.
- iPhone users. If any Bonvi salesperson carries an iPhone, the CallSentry
  approach covers none of them — iOS has no equivalent capability. Find out
  whether that is a real gap.

## Constraints to respect

- The user's global rules: FastAPI + SQLAlchemy + Alembic + PostgreSQL +
  Pydantic v2 backend, React 18 + Vite + TS + Tailwind frontend, Docker Compose,
  pytest — but that is the *starting point*, and `plan-stack` (a later step,
  which always asks the user) confirms or overrides it. Do not lock the stack in
  REQUIREMENTS.md — and note that since CallSentry is being replaced, the mobile
  wire format is ours to design, not inherited. The Android side is Kotlin +
  Compose unless there is a named reason to change.
- Documents are written in English. Client-facing output is Uzbek.
- Every new endpoint must be RBAC-protected.

## Deliverable

`docs/REQUIREMENTS.md`: problem, roles, use cases, acceptance criteria,
**scope boundary** (what is explicitly NOT in release 1), data sources, and
open questions. Mark each open question with your own recommended answer so the
user only has to confirm or correct it. Keep at most five questions genuinely
worth the user's time; everything else you decide yourself and it goes to
`docs/ASSUMPTIONS.md`.
