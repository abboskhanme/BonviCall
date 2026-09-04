# BonviCall — Risk register

Companion to `docs/REQUIREMENTS.md` §9. One row per risk: what could happen,
how likely, what it costs, and **what we do about it**. A risk without a
mitigation and an owner is not managed, it is just written down.

Scale: **Likelihood** L / M / H. **Impact** L / M / H, where H = the release
date moves or the project's value is lost.

Review at every phase boundary. Last updated **2026-09-04**, after the client
answered the open questions in `REQUIREMENTS.md` §8.

**What those answers changed.** Three things moved, and two of them moved a
lot:

- **CallSentry was trialled on real phones and it captured both voices** — the
  employee's and the client's. R1, which was the risk most likely to end this
  project, drops from "unknown, possibly fatal" to "works on some models, needs
  to be pinned down and watched".
- **The real friction was installation and permissions**, not capture: the app
  only worked after putting the phone into developer mode and/or disabling Play
  Protect. That is now the top practical risk — **R17**, new in this revision.
  Notably, the client reported *no* lost calls, *no* overnight service death,
  *no* battery or data complaints and nobody switching it off; those were the
  four failure modes we expected, and the trial rejected all of them.
- **The phones are the employees' personal property** (SIMs are usually the
  company's). This removes managed-device provisioning from the options and adds
  R18.

**And one hypothesis that ties the first two together — see the S1 box below.**
It is the most consequential open technical question on the project.

**Scope reduction, 2026-09-04.** The client removed the legal opinion, the
consent/notice paperwork and SMS: this is an internal company project. **R2 is
withdrawn**, and with it the longest external wait in the plan — server
procurement no longer sits behind a lawyer's turnaround. Removing SMS did add
one risk back — **R19**, number verification now resting on a single
operator-controlled route. **17 live risks.**

---

## 0. Start on day one — the external waits

These are the items whose clock runs whether or not we are working. Every one
of them can be started **before the first line of code**, and each becomes a
schedule risk the day it is deferred.

| # | What must start now | Why it cannot wait | Owner |
|---|---|---|---|
| D0 | **Identify which mechanism produced two-sided audio in the CallSentry trial** — read `../CallSentry/app/src/main/java/uz/callsentry/service/recording/`, and establish what "developer mode" was actually needed for | Everything about the permission journey (R17) and about which models work (R1) hangs off this one fact, and it costs an afternoon of reading, not a procurement cycle | Developer |
| D1 | **The M0 recording spike** — 10 real calls on one phone of every model in the fleet, measured | Purpose has changed: no longer "does audio work at all" but "which models, at what rate, by which route" — the baseline we later watch for regressions. R1 | Developer |
| D2 | **Fleet inventory from the client** — per employee: phone model, Android version, whether the SIM is the company's, and **which models were in the trial** | Still unanswered and still blocking. D1 cannot start without it, N32's supported-model list depends on it, and the trial models are the known-good set | Client |
| D5 | **Server and storage procurement** — ≥ 250 GB steady state, hosted wherever is cheapest and most convenient | Ordering hardware or a hosting contract after the code is done is a pure idle wait. **Withdrawn 2026-09-04: this no longer waits on a legal opinion, so it can start today.** N18 | Client |
| D6 | **Decide who pays for the mobile data** the app spends uploading audio from a personal phone | It is the employee's data plan unless someone says otherwise, and that is exactly the kind of small unfairness that loses a fleet. R14, R18 | Client |

> D0 and D2 are the critical path: until we know which mechanism worked and on
> which phones, the enrolment flow — the project's biggest practical problem —
> cannot be designed.
>
> **Scope change 2026-09-04.** The client removed the legal opinion, the
> consent/notice paperwork and SMS from the project: *"bu shunchaki kompaniya
> ichki loyihasi"* — it is just an internal company project. D3 and D4 are
> withdrawn, R2 with them, and D5 is no longer blocked behind a lawyer. That
> removed the longest external wait in the plan.

---

## S1 — The hypothesis that may collapse R1 and R17 into one risk

**Status: strong, testable, unconfirmed. Resolve it first (D0).**

Reading the prototype's `service/recording/` suggests the two headline risks are
not independent — they may be **the same decision seen from two sides**:

- `CtiForegroundService.onIdle()` **prefers the phone's own OEM recording file**
  over the app's recording, with a comment that the built-in recorder "ikkala
  tomon ovozini toza yozadi" — records both sides cleanly.
- `RecordingManager` concedes that `VOICE_CALL` is forbidden to non-system apps
  and that its own fallbacks capture mainly the local side.
- `OemRecordingLocator` reaches `Recordings/Call` **by raw file path**, and
  documents that this works "because the app uses legacy storage
  (`targetSdk 28`)".

So the likely chain is: **the two voices came from the phone's built-in call
recorder, harvested as a file — and the `targetSdk 28` trick that makes that
file readable is very probably also what forced developer mode and disabling
Play Protect.** One mechanism, both symptoms.

If it holds, three things follow, and each is worse than it looks:

1. **Audio exists only on models whose built-in recorder is present and turned
   on.** Recording is then a property of the handset the employee happened to
   buy — which, since Bonvi does not own the phones (R18, R10), is outside the
   company's control. D2's fleet inventory stops being administrative and
   becomes the decisive input.
2. **The employee must enable their own phone's call recorder — for every
   call**, including private ones on the other SIM. That is a privacy boundary,
   not a configuration step: the shared recordings folder will contain the
   employee's personal calls, and the time-window match against a registered
   call is the only thing keeping them out of our server (N28, UC-14).
3. **It is on a deprecation clock.** Google raises the minimum installable
   `targetSdk` over time; a `targetSdk 28` app will eventually refuse to install
   on new Android versions at all. This is not a risk that can be mitigated,
   only survived for a while and planned around — it belongs in the release-2
   conversation from the start, not discovered when a new phone cannot install
   the app.

**Deliverable of D0:** a one-page note naming the actual mechanism and answering
one question — *does it still work on a phone that has NOT been put into
developer mode?* If yes, R17 shrinks dramatically. If no, R17 stands and the
work-profile spike (S2, in R17) becomes urgent.

---

## 1. Risks that can end the project

### R1 — Call recording is device-dependent and a vendor update can remove it
**Likelihood M · Impact H · Severity: high** *(was: likelihood H, critical —
downgraded on trial evidence)*

Since Android 10 the `VOICE_CALL` audio source is refused to non-system apps.
**But the CallSentry trial captured both sides of the conversation on real
phones**, so a working route exists on at least part of Bonvi's fleet. The
question is no longer whether audio can be captured; it is *which* route worked,
on which models, and how we find out when it stops working.

**The likely route is already identified — see S1 above**, and if that
hypothesis holds, "which models" reduces to "which phones ship a built-in call
recorder that the owner has enabled". The candidate routes, each with a
different failure mode:

| Route | Reality |
|---|---|
| Harvest the OEM recorder's output files | Works only where the vendor ships a recorder and only where it writes to a readable path; the prototype's `OemRecordingLocator` already scans `Recordings/Call` and similar. Vendor-specific and update-fragile |
| Accessibility service | Play forbids it for this purpose; behaviour varies; users can revoke it |
| Device owner / enterprise provisioning | Would be the most reliable — **but it is unavailable here.** It requires factory-resetting a company-owned device, and Bonvi's handsets belong to the employees |
| Microphone-only (speaker on) | Captures one side well and the other badly; unusable for scoring; depends on the employee holding the phone a certain way |

**What could happen:** the route that worked in the trial turns out to be
specific to the trial phones, so half the fleet silently produces no audio; or
it works everywhere until a vendor update removes it and nobody notices for a
month.

**Mitigation.**
1. **D0 first** — establish from the CallSentry source what actually produced
   two-sided audio. We are guessing about our own prototype, which is free to
   stop doing.
2. **D1 spike before app code**, with its purpose changed: measure per model,
   publish a supported-model table with real capture rates, and treat those
   numbers as a regression baseline rather than a one-off go/no-go.
3. **Recording capability is a per-model property in the data model** from day
   one, so a mixed fleet is normal and the panel shows exactly what is covered.
   Any model that fails becomes a hardware conversation with the client, not a
   silent zero in production.
4. **The fallback is a designed product state, not a failure:** UC-14 logs the
   call *always*, with a reason code from a closed enum, even when audio is
   impossible. BonviZvonki's stray `audiosiz_qongiroqlar_zaxira.csv` ("calls
   without audio") is this situation handled badly; here it is first-class.
5. Keep the capture route behind an interface so a second route can be added
   without touching the rest of the app.
6. The **PBX** path (§5.1) remains the honest answer if the fleet turns out to
   be mostly unrecordable — far cheaper to conclude in week one than in month
   four.

**Early warning:** capture rate per model is monitored continuously (N1) against
the M0 baseline, and UC-23 raises the per-model regression alert — not measured
once at go-live. A vendor OS update that breaks recording shows up as a
drop on one model, which is only visible if the number is watched.

---

### R17 — Installation and permissions: the friction that actually bit
**Likelihood H · Impact H · Severity: critical** *(new — promoted directly from
the client's trial report)*

This is the one problem the trial actually produced. The client's report: there
were no operational problems; the difficulty was **obtaining the permissions
from the device in its default state**, and it only worked after putting the
phone into developer mode and/or **disabling Play Protect**.

Everything about that is worse on a personal phone:

- Someone must sit with each salesperson and walk their **own** phone through
  enabling developer options and switching off a Google security feature. The
  screens say, in effect, "this is dangerous" — and to a non-technical user they
  are right.
- Play Protect can re-enable itself, and Google can flag or remove a sideloaded
  call-recording app at any time.
- The employee can revoke any of it later, by accident or on purpose, and
  nothing tells the admin.
- It must be repeated on every new phone, after some OS updates, and after a
  factory reset.
- It cannot be done remotely, so a fleet-wide fix means physically reaching
  every device.

**What could happen:** the rollout stalls at the enrolment step. The platform
works perfectly and covers four salespeople, because getting to the fifth
requires an afternoon with their personal phone.

**S1 may explain this risk and R1 at once** — if the two-sided audio came from
harvesting the OEM recorder's files under `targetSdk 28`, then that same choice
is what tripped Play Protect. Confirming it (D0) could shrink this risk or make
it permanent, and we should know which before designing the flow.

**Mitigation.**
1. **Treat enrolment as a first-class feature, not a README.** A guided,
   step-by-step flow in Uzbek, one screen per permission, each with a real
   "is this actually granted right now" check rather than a "did you press it?"
   checkbox.
2. **Server-side permission visibility**: the panel shows, per device, which
   permissions are missing, and raises an alert when a previously granted one
   disappears. A silently de-permissioned phone is R3's invisible-failure
   problem wearing a different hat.
3. **Minimise what must be granted.** Once D0 tells us which mechanism produced
   two-sided audio, drop every permission not needed for that route. Each one
   removed is one fewer scary screen per employee.
4. **Sign the APK properly and register it** so Play Protect has the best chance
   of leaving it alone; measure how often it interferes, and treat the install
   path and the permission path as a single user journey (see R8).
5. **Spike: Android Enterprise work profile / BYOD enrolment.** It is the
   standard answer to exactly this friction and it does not require owning the
   device or factory-resetting it. **Reservation, and it may be fatal:** a work
   profile is isolated from the personal dialer, so it may be unable to see or
   record calls made from the phone's normal dialer — which would make it
   useless here. Resolve this before the enrolment flow is finalised; do not
   plan on it.
6. Acceptance criterion worth writing down: **a non-technical salesperson
   completes enrolment unaided, from a link, in under N minutes.** If that is
   not achievable, the rollout needs a person doing device visits, and that is a
   budget line the client must see now rather than discover later.

**Early warning:** enrolment time per device during the pilot. If the second
employee takes as long as the first, the flow has not been solved.

---

### R2 — Consent, notice and data jurisdiction — **WITHDRAWN**

**Withdrawn 2026-09-04 at the client's instruction.** The legal opinion
(ZRU-547 / biometric data), the client-side notice wording and the consent
paperwork are out of scope: *"loyihadan yurist hulosasi, siyosiy hujjatlar …
olib tashla, kerakmas, bu shunchaki kompaniya ichki loyihasi."*

Consequences carried elsewhere rather than lost:

- **Audio hosting location is now a free engineering choice** — pick for cost,
  latency and backup convenience. This removed a 10/20/40-working-day wait that
  sat in front of server procurement, and it is the single largest schedule
  improvement in the project.
- **Retention stays 12 months** (N19) as a storage-cost decision.
- **Audio access is still audited** (N27, UC-24) — that was always an
  operational control, not a legal one, and it stays.
- The employee-side position (installation is mandatory, all staff are Bonvi's
  own) is unchanged and now stands on its own.

Kept for the record so the decision is traceable; not tracked as a live risk.
---

## 2. Risks that quietly destroy the data

### R3 — OEM battery managers kill the capture service
**Likelihood H · Impact H · Severity: high**

MIUI, EMUI, Samsung, Oppo and Vivo aggressively kill background services, often
silently and often only after several days. The prototype already needed
`onTaskRemoved` + an AlarmManager restart + a 15-minute `KeepAliveWorker`
watchdog — **and still had no way to notice when it lost**.

**Trial evidence:** the client reported no overnight service death and no
missing calls. That is encouraging but not conclusive — a short trial on a few
phones is exactly the sample size that misses a killer which fires after five
days on one vendor's build. Keep the risk, lower the alarm.

**What could happen:** the panel looks healthy and simply contains fewer calls
than reality. This is the worst failure mode in the product, because it is
invisible.

**Mitigation.** Server-side silence detection: the *server* raises the alarm
when a device stops reporting (UC-27), and device health is visible per device
(UC-17), so absence of data is itself an event. Guided per-vendor battery-exemption setup during enrolment, with the app
refusing to report itself healthy until the exemption is granted. Periodic
reconciliation of the device call log against the server (UC-13) so a gap is
detected and backfilled rather than lost — and on personal phones this
self-measurement, not `adb`, is the only production capture-rate metric we get. Per-model health in the panel.

---

### R4 — Employees resist, or deliberately evade
**Likelihood M · Impact H · Severity: high** *(likelihood lowered on trial
evidence, impact unchanged)*

Turn the app off, revoke a permission, uninstall it, fly airplane mode, use a
second phone, or move the conversation to WhatsApp. BonviZvonki's own plan rates
human resistance the risk **most likely to kill the project** — and that
platform only watched calls; this one lives on the employee's **personally
owned** phone.

**Trial evidence cuts both ways.** Nobody switched it off during the trial and
nobody complained about battery, which is real and worth weighing. But a trial
is short, visible and usually staffed by willing volunteers; and the Q2 answer
means the app is now mandatory on hardware the employee bought. R17's permission
grants are also the exact surface this risk acts on — revoking a permission is
easier and more deniable than uninstalling an app.

**Mitigation.** Every kill action raises an admin alert within 10 minutes
(UC-18) — five distinct actions are enumerated, so evasion is visible rather
than prevented; we do not pretend a user-space app can win against the device
owner. Company-owned SIMs — which Bonvi mostly already issues — make the *number*
company property even when the handset is not, so evasion becomes a policy
matter on the part we control. Honest framing to staff, with
the Uzbek one-page manual (`docs/QOLLANMA.md`) stating exactly what is recorded
and what happens if you disable it. Battery and data budgets (N13–N15) kept low
enough that there is no *legitimate* reason to disable it — an app that eats a
personal phone's battery gets uninstalled and the employee is right. Settle D6,
who pays for the uploaded data: expecting an employee to fund the company's
recording out of their own plan is a small unfairness with an outsized effect on
willingness.

**Early warning:** a rise in "device offline" alerts concentrated on particular
employees; captured call count diverging from SAP sales activity.

---

### R5 — Duplicate or lost calls from a weak identity key
**Likelihood M · Impact H · Severity: high**

The prototype used a Room autoincrement `localId` as its only deduplication
key, so a reinstall restarts numbering at 1 and collides with existing server
records. Add device clock skew, timezone changes, dual-SIM, call waiting and
VoLTE — the prototype's state machine explicitly ignored a second RINGING during
an active call — and both duplicates and silent misattribution follow.

**Mitigation.** Client-generated UUID per call as the idempotency key (UC-12);
server rejects duplicates by that key, so at-least-once delivery becomes
exactly-once storage. Device sends raw epoch millis + timezone alongside
ISO-8601 so the server can compute skew (N36); **server receipt time is
authoritative for ordering**. Dual-SIM and call-waiting cases are named test
scenarios in the 7-day acceptance run, not discovered in production.

---

### R6 — Number normalisation drifts from BonviZvonki
**Likelihood M · Impact M · Severity: medium**

`+998 90 111-22-33`, `998901112233` and `901112233` must be one number. This
team has already paid for this once — BonviZvonki's git history contains a
chain of fixes about which client a number belongs to.

**Mitigation.** E.164 on the server with **last-9-digits** as the matching key
(N37), deliberately identical to BonviZvonki so a future join is possible even
though the systems are independent. Unit tests with the real formats seen in
that project's contact export.

---

### R7 — The local queue is lost before upload
**Likelihood M · Impact M · Severity: medium**

Uninstall, "clear data", a factory reset or a full disk destroys calls the
device has not yet uploaded.

**Mitigation.** Upload metadata immediately and audio separately, so the cheap
and important half lands first. Bounded local queue with an explicit policy when
it fills, surfaced in device health rather than dropped silently. Reconciliation
against the device call log (UC-13) recovers metadata even after audio is gone.
Note the local queue budget was halved to **1 GB** (N8) because the storage being
consumed is the employee's own, which shortens the safe offline window.
Storage headroom is part of the device health report.

---

### R19 — Number verification now rests on one route, and the operator controls it
**Likelihood M · Impact M · Severity: medium** *(new — a consequence of removing
SMS on 2026-09-04)*

Proving that the app is running on the registered work number had three routes:
read the SIM's MSISDN, an SMS code, or a callback (the agent dials a short
server number and the inbound caller ID confirms who they are). SMS is now out
of scope, and the MSISDN route is unreliable — many Uzbek SIMs simply do not
populate it, which is why `getLine1Number()` returning null must never count as
a match.

That leaves **the callback as the load-bearing route**, and its weak point is
not our code: **whether a caller's number is presented on an inbound call is
decided by the mobile operator**, not by the handset and not by us. A silent or
withheld caller ID means the agent cannot be verified and enrolment stops at the
last step — the one the whole product depends on (R17).

**What could happen:** enrolment works on the test phone and fails for the
salesperson on a different operator, with no fallback left to try.

**Mitigation.**
1. **Verify the callback on every OEM *and every operator* combination in the
   fleet** — Beeline, Ucell, Mobiuz, Uzmobile. This is per-operator, not
   per-model, and it is a different axis from the M0 recording matrix. Fold it
   into the same field session: one phone, one SIM, one real call each.
2. Keep the MSISDN read as the fast path where it works, and treat the callback
   as the fallback that must always work — not the reverse.
3. If the callback proves unreliable on some operator, the honest remaining
   answer for an internal project is **admin-side manual confirmation**: the
   admin sees the incoming attempt in the panel and approves the pairing. It is
   cheap to build and it removes the dependency on caller-ID presentation
   entirely. Worth building anyway as the escape hatch.

**Early warning:** any enrolment that fails at the number-verification step
during the pilot. There is no second route left to mask it.

---

### R18 — Capturing the employee's private calls on their own phone
**Likelihood M · Impact H · Severity: high** *(new — a consequence of the Q2
answer)*

The handset is the employee's. It very often carries a personal SIM alongside
the company one, and it is used in the evening and at the weekend. An app that
captured "calls on this phone" rather than "calls on the registered work number"
would be recording the employee's doctor, their family and their bank — on
hardware they paid for.

This risk is **not** affected by the 2026-09-04 scope change. It is not a
paperwork problem; it is a technical requirement the client asked for directly:
*"eng muhimi ularning tel raqamini bizning bazaga kiritib qo'ysak shu bo'yicha
record qilish."* Capture is scoped to the registered number because that is the
specification, and getting it wrong is the fastest available way to lose the
fleet's cooperation.

**Mitigation.**
1. **Capture is scoped to the registered number, not to the device.** This is
   also exactly what the client asked for: "eng muhimi ularning tel raqamini
   bizning bazaga kiritib qo'ysak shu bo'yicha record qilish". Calls on any
   other SIM are **not captured and not uploaded** — not captured-then-discarded
   server-side, but never sent.
2. Dual-SIM is a **first-class case with its own tests**, not an edge case: the
   app must identify which SIM a call belongs to before it records anything, and
   must fail closed when it cannot tell.
3. Handle "the company SIM was moved to a different phone" explicitly, since on
   personal hardware that will happen.
4. Say it plainly in the Uzbek employee manual (`docs/QOLLANMA.md`). The single
   most useful sentence in this project is "your private calls are not
   recorded" — and it is only worth saying if the code makes it true.
5. Out-of-hours calls on the **work** number default to in scope (W11).

---

## 3. Platform and distribution

### R8 — No Google Play distribution
**Likelihood H (certain) · Impact M · Severity: medium**

Play policy prohibits call-recording apps (N33). Self-hosted signed APK plus an
in-app updater is therefore **load-bearing infrastructure, not a detail** — and
the update path must reach every device without the employee coming to the
office, or an emergency fix cannot be shipped.

**The trial already hit this**: it worked only after Play Protect was disabled
(R17). So distribution is not a separate late-stage concern — the install path
and the permission path are one user journey and must be designed together.

**Mitigation.** Treat the update channel as a release-1 feature with its own
acceptance criterion. Keep signing keys backed up and documented in the handover
— losing them means no device can ever be updated again. MDM is **not** an
option here: the handsets belong to the employees. The work-profile spike in
R17 is the nearest equivalent and carries its own reservation.

---

### R9 — A future Android release breaks the app
**Likelihood M · Impact H · Severity: high**

Android 14/15/16 continue to tighten foreground-service types, background
starts and permissions. The app is always one OS version away from breaking, and
fleets update themselves.

**Mitigation.** Pin the supported OS range explicitly (N32) and test the next
Android beta before the fleet reaches it. Keep the capture strategy behind an
interface so a route can be swapped without touching the rest of the app.
Server-side silence detection (R3) means a break is detected in hours, not at
the next quarterly report. Budget maintenance for this — it is a recurring cost,
not a one-off.

---

### R10 — A leaver takes the phone, and sometimes the number
**Likelihood M · Impact M · Severity: medium**

Bonvi mostly issues the SIM but never the handset, so on departure the company
reclaims the number and the employee keeps the device the app is installed on.
Where the SIM is also the employee's — which the client says happens — the
client relationship and the number leave with them and the call history's
continuity breaks.

**Mitigation.** A documented leaver process: revoke the device's token
server-side (it must be possible without physical access, because we will not
get the phone back), reassign the number to the new salesperson, and keep
history attached to the **number** rather than only to the person — which is
already the identity model the client asked for. Flag employee-owned SIMs in the
panel so the client can see which relationships are not theirs to keep.

---

### R11 — iPhone users are simply uncovered
**Likelihood L · Impact M · Severity: low-medium**

There is no software fix; iOS has no equivalent capability (§5.2).

**Mitigation.** D2 establishes whether any salesperson carries one. If so it is
a **procurement decision for the client** — issue an Android work phone — and
that decision must be made during requirements, not discovered at go-live.

---

### R12 — Calls migrate to WhatsApp and Telegram
**Likelihood M · Impact M · Severity: medium**

These are not capturable (§5.6), so the captured call count can understate real
activity — and worse, it gives an evasion route (R4) that looks innocent.

**Mitigation.** Named as an explicit blind spot in the scope boundary so nobody
reads the panel as a complete picture. Cross-check captured volume against SAP
sales activity; a salesperson with sales and no calls is a question worth asking.

---

## 4. Project and process

### R13 — Cancelling MoyZvonki too early
**Likelihood M · Impact H · Severity: high**

The client has confirmed BonviZvonki will be connected to BonviCall later
("bonvizvonkini keyinchalik bu projectga ulaymiz"), so this is now a **scheduled
event with a date attached**, not a hypothetical — which raises the chance of it
happening at the wrong moment rather than lowering it. Cancelling the incumbent
before BonviCall is proven loses both data flows at once, and BonviZvonki —
which the client uses daily — goes blind with it.

**Mitigation.** **One full month of parallel running** against MoyZvonki with a
side-by-side count before anything is cancelled. Note the ordering trap: the
BonviZvonki ingest adapter is work in *that* repository, so the parallel month
cannot even begin until someone schedules it there — if it is forgotten, the
pressure to cancel arrives before the evidence does. This is the single most
expensive available mistake and the cheapest to avoid: the mitigation is
patience. Make the parallel-run comparison a report in the panel, so the
decision is evidence-based.

---

### R14 — Storage and cost growth beyond the model
**Likelihood M · Impact L · Severity: low**

The base model is 11,700 calls / 1,560 hours per month → ≈ 17 GB/month,
≈ 200 GB/year (N18). Headcount growth, longer calls or a higher bitrate
multiply it.

**Mitigation.** Transcode on the device to mono 16 kHz Opus ≤ 24 kbps (N17) so
the data bill and the storage bill are the same number — the prototype's
44.1 kHz / 128 kbps setting was ≈ 5× larger and would have cost roughly
6 GB per agent per month in mobile data alone, **spent from the employee's own
plan** (D6). Prefer Wi-Fi for audio upload where the queue can wait, and make
that policy visible in the app so the employee can see what it costs them. Panel shows current usage and
30-day growth. 12-month retention with automatic deletion (N19).

---

### R15 — The client owes data we cannot proceed without
**Likelihood M · Impact M · Severity: medium**

Specifically: the fleet inventory (D2) — including **which phone models were in
the CallSentry trial**, the known-good set we are now relying on — the agent ↔
phone number map, the branch and org structure, the client-notice wording (D4),
the hosting decision (D5), and who pays for mobile data (D6).
BonviZvonki has already been through this — its `STATUS.md` records that
employee names arriving from the provider were often a place name instead of a
person, because the provider's data model did not match Bonvi's org structure.

**Mitigation.** Ask for all of it in one batch now, with a named owner and a
date per item. Where an item is late, build against the assumption recorded in
`docs/ASSUMPTIONS.md` and keep the mapping in configuration so a correction is
a data change, not a code change.

---

### R16 — Requirements drift during the build
**Likelihood M · Impact M · Severity: medium**

Three deliverables (Android app, server, panel) and 25 use cases is enough
surface for scope to creep, especially toward analytics — which BonviZvonki
already does and which §5.3 deliberately excludes.

**Mitigation.** The scope boundary (§5) is the contract; changing it requires an
explicit change request, and that is already a line in the release-1 Definition
of Done. Release 1's value is stated in one sentence (§3) — anything not serving
that sentence is release 2.

---

## Summary

| # | Risk | L | I | Severity |
|---|---|---|---|---|
| **R17** | **Installation and permission friction** | **H** | **H** | **critical** |
| R1 | Recording is device-dependent, vendors can remove it | M | H | high |
| R3 | OEM battery managers kill the service | H | H | high |
| R4 | Employee resistance and evasion | M | H | high |
| R5 | Duplicate/lost calls from weak identity | M | H | high |
| **R18** | **Capturing private calls on a personal phone** | **M** | **H** | **high** |
| **R19** | **Number verification rests on one operator-controlled route** | **M** | **M** | **medium** |
| R9 | Future Android release breaks the app | M | H | high |
| R13 | Cancelling MoyZvonki too early | M | H | high |
| R6 | Number normalisation drift | M | M | medium |
| R7 | Local queue lost before upload | M | M | medium |
| R8 | No Play distribution, Play Protect blocks the install | H | M | medium |
| R10 | Leaver takes the phone, sometimes the number | M | M | medium |
| R12 | Calls migrate to WhatsApp/Telegram | M | M | medium |
| R15 | Client owes data | M | M | medium |
| R16 | Requirements drift | M | M | medium |
| R11 | iPhone users uncovered | L | M | low-medium |
| R14 | Storage and cost growth | M | L | low |

**Cross-cutting: S1** — R1 and R17 may share a single root cause and a single
deprecation clock. Not a separate row; it changes how two of them are read.

**Withdrawn: R2** (consent, notice, data jurisdiction) — out of scope as of
2026-09-04. **New: R19**, created by the same change. **17 live risks.**

**Movement since the first draft.** R1 down (the trial captured both voices);
R4 down (nobody switched it off, nobody complained about battery); R17 and R18
new, and R17 goes straight to the top — it is the only problem the trial
actually produced.

Server outage was assessed and is **not** carried as a register entry: the
devices' durable queue (N8) turns it into delay rather than data loss, and
availability is already specified in N38.
