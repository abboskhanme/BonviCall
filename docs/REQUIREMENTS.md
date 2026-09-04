# BonviCall — Requirements

Status: draft, all five questions answered · Author: plan-analyst · Date: 2026-09-04
Decisions taken without asking are recorded in [`ASSUMPTIONS.md`](ASSUMPTIONS.md).
Risk candidates flagged here belong in `docs/RISKS.md` (owned by the coordinator).

> **Revision 2 — 2026-09-04.** The client answered all five open questions and
> two answers changed the shape of the project.
>
> - **Q1 — decided: SIM fleet.** Recorded on the handset, transferred to Bonvi's
>   server as soon as the internet returns. That is the offline-queue model this
>   document already specified.
> - **Q2 — the handsets are the employees' personal property.** SIMs are usually
>   company-issued, sometimes personal. **The identity anchor is the registered
>   phone number, not the device.** This removed managed-device provisioning,
>   rewrote enrolment (§4.3), made dual-SIM a first-class case (UC-15), split the
>   measurement rig in two (§4.1), and turned the battery and data budgets from
>   engineering targets into adoption requirements (§6.3).
> - **Q3 — no employee consent gate; installation is mandatory.** All staff are
>   Bonvi's own.
> - **Q5 — CallSentry was trialled, and recording captured both voices.** The
>   risk we both ranked first — Android blocking call recording — is empirically
>   survivable on at least some of Bonvi's phones. **The real problem was getting
>   the app installed and permitted on a default-configuration phone.** §4.2 is
>   now ordered by that evidence, and installation/permissions is promoted from
>   a footnote to the number one product problem (§4.3).

> **Revision 3 — 2026-09-04, scope reduction.** The client removed the legal
> opinion, the consent/notice paperwork and SMS: *"bu shunchaki kompaniya ichki
> loyihasi"* — this is just an internal company project. See §5.8. Withdrawn ids
> are kept in place rather than renumbered: **UC-28, N29, N30, B1**. Number
> verification is now the callback route only (UC-04).

This document says **what to build and how it will be checked**. It does not
choose a technology stack — `plan-stack` does that with the user. Where a
requirement genuinely constrains the stack, it is marked **[constraint]**.

---

## 1. Problem

### 1.1 How the process works today

Bonvi's sales department works the phone. Roughly 15 salespeople call shops and
distributors from SIM-equipped mobile phones. Every call is a business event:
an order taken, a price quoted, a complaint handled, a client lost.

Today none of that is Bonvi's own data. It is collected by **MoyZvonki**, an
external SaaS telephony provider, and consumed by Bonvi's own analytics
platform, BonviZvonki, which pulls the recordings, transcribes them, scores them
with an LLM and reports on the sales team.

The chain is: employee's phone → MoyZvonki cloud → BonviZvonki. Bonvi owns only
the last link.

### 1.2 Where it loses money and time

Taken from BonviZvonki's own `STATUS.md`, `CLAUDE.md` and `docs/PLAN.md` —
these are recorded failures, not speculation.

| # | Loss | Evidence |
|---|---|---|
| L1 | **Bonvi does not own its own call audio.** It is streamed from MoyZvonki on demand; writing it to disk is explicitly forbidden in BonviZvonki's rules. MoyZvonki keeps recordings for **30 days**. Anything older than 30 days is gone forever. | `CLAUDE.md` rule 20; `PLAN.md` §5.1 "🔴 KRITIK: 30 kunlik saqlash limiti" |
| L2 | **A recurring bill for data Bonvi already generates.** 230 ₽/device/month ≈ $37/month for 15 devices, rising with headcount, for calls made on Bonvi's own SIM cards. | `PLAN.md` §5.1 |
| L3 | **Employee identity arrives wrong.** MoyZvonki frequently returns a place name instead of a person ("Навои", "Джиззах склад"). BonviZvonki had to stop trusting it and freeze `agents.full_name`. Wrong attribution means wrong performance data. | `CLAUDE.md` "Tuzoqlar" |
| L4 | **Internal vs external calls cannot be told apart reliably.** Classification depends on a hand-maintained admin setting (`moizvonki.internal_numbers`). When it was empty, an AI classifier had to guess and got it badly wrong: of 98 classified calls, **82 were labelled "internal"** and only 9 as sales — most real sales conversations went unscored. | `STATUS.md` §"qo'ng'iroq turi" |
| L5 | **The company line list only fills if MoyZvonki is configured correctly.** Of 33 employees, only 10 have a phone number on file. The directory that drives L4 is starved. | `STATUS.md` |
| L6 | **A single point of failure outside Bonvi's control.** If `MOIZVONKI_DOMAIN` / `MOIZVONKI_USER` / `MOIZVONKI_API_KEY` break, or the vendor changes its API, **no new calls arrive at all** and nobody is told. | `README.md` env table |
| L7 | **Calls silently arrive with no audio.** The repo carries a file literally named `audiosiz_qongiroqlar_zaxira.csv` — "calls without audio, backup", 47 rows, all `status=skipped`, `duration_sec=0`, empty `audio_key`. Nothing explains *why* audio was missing or who should fix it. | `audiosiz_qongiroqlar_zaxira.csv` |

### 1.3 What the CallSentry trial actually proved

`../CallSentry` is a throwaway Android CTI demo. It **was** run on real phones,
and the result is the most valuable input this project has:

- ✅ **Recording captured both voices** — the employee's and the client's. The
  central technical doubt is resolved in the affirmative, on at least some of
  Bonvi's actual handsets.
- ✅ **No lost calls, no overnight service death, no battery complaints, no data
  complaints, and nobody turned it off.** These were the four failure modes I
  expected to dominate. The client rejected all four. That is as informative as
  the positive result and it is why §4.2 is no longer ordered by my judgement.
- ❌ **Installation and permissions were the problem.** In the client's words:
  the difficulty was obtaining permissions from the device *in its default
  state*, and it only worked by putting the phone into developer mode and/or
  turning off Play Protect.

So the project's centre of gravity moves. This is not a research problem about
whether audio can be captured. It is a **deployment and consent-of-the-device**
problem: getting a legitimate app installed and permitted on fifteen phones that
Bonvi does not own, and keeping it permitted.

### 1.4 What BonviCall is

BonviCall is **Bonvi's own telephony data platform**: a new Android app, a
server, and a web admin panel. Calls made on **registered company numbers** are
captured and recorded on the handset, transferred to Bonvi's server as soon as
the phone has internet, and stored on Bonvi-controlled infrastructure, where
they are visible and playable in a web panel that Bonvi runs.

It is **not** a rewrite of BonviZvonki and shares no database or API with it.

### 1.5 The three facts that shape everything else

All three confirmed by the client on 2026-09-04.

1. **The identity anchor is the phone number, not the device.** An `admin`
   enters an agent's work number into the panel; capture and attribution happen
   against that registered number. This is *better* than device identity — it is
   the same key BonviZvonki already uses (last 9 digits) and it survives the
   employee changing phones.
2. **The handsets belong to the employees.** SIMs are usually company-issued,
   sometimes personal. Bonvi supplies the SIM and the software; the hardware is
   not Bonvi's to manage, wipe, provision or replace.
3. **Two-sided recording works, but nobody has written down how.** The trial
   produced two-sided audio and the mechanism that produced it was never
   identified. Until it is (spike S1, §3), every statement about which phones
   will work is a guess.

Facts 2 and 3 compound: the installation friction the trial hit is friction on
hardware Bonvi cannot administer, and it must be absorbed by a non-technical
salesperson on their own phone, once per device and again after some OS updates.

---

## 2. Users and roles

Same four-role shape as BonviZvonki (`admin` / `manager` / `sales` / `viewer`),
plus one machine role. Reusing the shape means the same person has the same
mental model in both systems.

Permissions are enforced **server-side** on every endpoint; hiding a menu item is
not a permission. **[constraint]** every endpoint is RBAC-protected.

| Role | Who | What they do | How often | Must **not** see / do |
|---|---|---|---|---|
| `admin` | IT / operations owner (1–2 people) | Registers agents and their numbers, guides and monitors enrolment, revokes installations, edits the company line directory, sets retention and alert thresholds, reads the audit log, exports data | Daily during rollout, weekly after | — (full access, but every audio playback is audited and no call can be individually deleted, UC-26) |
| `manager` | Sales director, supervisors (2–4) | Reviews call lists, listens to recordings, checks device health, exports reports | Daily | User management, settings changes, retention settings, audit log, installation revocation |
| `sales` | The salesperson, on their **own** phone, using a company SIM (≈15, may grow) | Makes and receives calls on the registered number; sees **only their own** call history and plays **only their own** recordings | Continuously (the app runs all day) | Any other agent's calls, recordings, numbers or statistics; other devices' health; deleting a call or its audio; disabling capture without the admin being told (UC-18). **Bonvi must not see anything from a second, unregistered SIM in the same phone** — UC-15 |
| `viewer` | Sales-room wall display (`/monitor`-style TV) | Read-only live board: who is online, calls today, capture health | Always on | Audio playback, full client phone numbers (masked to last 4 digits), any personal data — the TV is visible to visitors |
| `service` (machine) | A downstream system, e.g. BonviZvonki later | Read-only paginated export of call metadata and audio via a scoped token | Scheduled | Write access of any kind; user data; audit log |

Notes carried over from BonviZvonki's experience:

- `sales` scope is narrowed **by the query**, not by a separate permission —
  `calls:read:own` passes the permission check, the service layer filters by
  `agent_id`. Same pattern as `AnalyticsService._scoped()`.
- The employee **sees their own data**, and the app permanently displays which
  number it is recording. On a personal phone this stops being a courtesy and
  becomes the main adoption lever — N41.

---

## 3. Scope of release 1, and the two spikes that precede it

> A call placed or received **on a registered company number** appears in the web
> panel — with correct direction, number, timestamps, duration and, where the
> device allows it, a playable recording — exactly once, within minutes, and it
> still appears if the phone was offline, rebooted, force-stopped or out of
> battery.

### 3.1 Spikes — before app code is written

**S1 — Identify the mechanism that produced two-sided audio in the trial.**
This is the single highest-value unknown in the project, and it is answerable
from material already on this machine plus one phone.

Read `../CallSentry/app/src/main/java/uz/callsentry/service/recording/` and
establish which path actually delivered the client's voice. The source contains a
strong hypothesis, and its own comments state it:

- `RecordingManager` tries four audio sources in order — `VOICE_CALL`,
  `VOICE_RECOGNITION`, `VOICE_COMMUNICATION`, `MIC` — and its comment concedes
  `VOICE_CALL` is "taqiqlangan" (forbidden) to non-system apps and that
  `VOICE_COMMUNICATION`/`MIC` capture mainly the local side.
- `CtiForegroundService.onIdle()` **prefers the OEM file over its own recording**,
  and comments that the device's built-in recorder "ikkala tomon ovozini toza
  yozadi" — records both sides cleanly.
- `OemRecordingLocator` scans `Recordings/Call`, `Recordings/Voice Recorder`,
  `Call`, `Sounds/Call`, `CallRecordings` by raw file path, and its docstring
  notes this works because "ilova legacy storage (targetSdk 28) ishlatgani uchun".

**Working hypothesis: the two voices came from the phone's own OEM call recorder,
harvested as a file — not from the app's microphone capture.** If that is right,
three consequences follow immediately and all three are testable:

1. Audio exists **only on models with a built-in call recorder that is enabled**.
   Models without one produce no two-sided audio by any route. This makes the
   outstanding fleet-model question (§8.2 D1) decisive rather than administrative.
2. The `targetSdk 28` legacy-storage trick is what makes the file readable — and
   it is very likely also **what required developer mode and disabling Play
   Protect**, because modern Android blocks installation of apps targeting old
   SDK levels and flags them. The install problem and the audio mechanism may be
   the *same* problem.
3. That trick is on a deprecation clock. Android raises the minimum installable
   `targetSdk` over time; a mechanism that depends on staying at 28 has a limited
   life and will fail on the next phone somebody buys.

**S1 deliverable:** a one-page note naming the mechanism, the exact permissions
and install steps it required, and whether it survives on a phone that has *not*
been put into developer mode.

**S2 — Android Enterprise work profile (BYOD) — feasibility only. Not
recommended, not assumed.**
A work profile is the standard answer to "install and permit a corporate app on
an employee-owned phone without factory-resetting it": it can push the APK and
grant permissions administratively, which would remove the entire friction
described in §1.3. **The reservation that may kill it: a work profile is isolated
from the personal side, so an app inside it may be unable to observe or record
calls placed from the phone's normal dialer** — which is the only dialer the
salesperson uses. If that isolation holds, the work profile is useless here
regardless of how good the enrolment story is. Resolve before §4.3's flow is
finalised; do not design around it until then.

### 3.2 Milestone ladder

| M | Deliverable | Proves |
|---|---|---|
| **S1, S2** | Recording mechanism identified; work-profile question closed | We know what we are building on |
| **M0** | Recording capability confirmed **per model** across the real mix, with measured capture rates as a baseline | Which phones are supported, by which route |
| **M1** | One real call on one real phone → visible in the panel with audio | End-to-end wire works |
| **M2** | **Install + permission + number-verification journey**, RBAC panel, call list + player, device health | The hard part is solved |
| **M3** | Survivability: offline / reboot / force-stop / battery-saver, exactly-once | It is trustworthy |
| **M4** | 7-day acceptance run against §4.1 thresholds | It can replace MoyZvonki |

> **M0's question has changed.** It is no longer "can we capture audio at all" —
> the trial answered that. It is "**on which models, by which route, and how do
> we notice when a vendor update takes it away**". Its output is a supported-model
> table with a measured per-model capture rate, which becomes the baseline that
> N4 and the regression alert (UC-23) watch.

---

## 4. Use cases and acceptance criteria

### 4.1 The measurement rig (all criteria below reference it)

Every reliability number is checked against a fixed harness, so a person who was
not in this conversation can run it. **The phones are the employees' property, so
the rig has two halves.**

**(A) Lab rig — for acceptance, on devices Bonvi controls.**
- **Acceptance set** — one phone of every model + Android version present in the
  fleet, minimum 5, obtained for the acceptance window: company-purchased test
  handsets, or an employee's phone borrowed with their agreement. Bonvi may not
  attach a debugger to an employee's personal phone as a matter of routine.
- **Acceptance window** — 7 consecutive working days of normal use.
- **Ground truth** — the device's own call log, exported at the end of the
  window: `adb shell content query --uri content://call_log/calls`, filtered to
  the **registered subscription**. This is the denominator; the panel is the
  numerator.
- **Capture rate** = calls in the panel ÷ call-log entries on the registered
  number, matched on (registered number, direction, start time ±60 s, remote
  number).
- **Audio capture rate** = panel calls with playable audio ÷ answered panel
  calls, reported **per device model**.
- **Duplicate rate** = panel rows with no matching call-log entry, or two panel
  rows matching one call-log entry.

**(B) Production rig — for the other 51 weeks, with no adb.**
Once the app is on personal phones, nobody can run `adb` to check whether calls
are missing. The app therefore **measures itself**: on every start and every
6 hours it sweeps its own call log for the registered subscription, counts the
entries in the period, and reports that count alongside what it has uploaded.
The server stores both; the panel shows the delta per device per day; a non-zero
delta that does not close within 24 h enters the gap report (UC-23). This makes
the capture-rate denominator a product feature rather than a one-off test, and it
is the only way N1 stays verifiable after go-live.

> ⚠️ **Dual-SIM warning that invalidates naive measurement.** On a personal phone
> the call log contains **both** SIMs' calls. Every count above must be filtered
> to the registered subscription. The call log's subscription column
> (`PHONE_ACCOUNT_ID` / `SUBSCRIPTION_ID`) is populated inconsistently across
> OEMs; where it is missing or ambiguous the entry is counted as
> `subscription_unknown` and reported separately — never silently attributed to
> the registered number, because that would both inflate the denominator and risk
> uploading a private call.

### 4.2 "Better than CallSentry" — ordered by what the trial actually showed

The trial (§1.3) replaced my guesses with evidence. Priority bands below are
**derived from that evidence**, not from judgement.

**Band 1 — installation and permissions. The number one product problem.**
It was the only thing the client reported as difficult, and Q2 makes it worse:
the friction lands on a non-technical salesperson, on a phone they own.

| CallSentry gap | BonviCall requirement | UC |
|---|---|---|
| Install required developer mode and/or disabling Play Protect; nothing guided the user | Guided install journey in Uzbek that treats the security warnings as expected steps, with a fallback to admin-assisted install | UC-02 |
| Permissions requested as a flat list; no verification that they actually took effect | Step-by-step flow with a per-step "is this genuinely granted" check, and no false "ready" state | UC-03 |
| A permission silently revoked later is invisible | Permission drift detected on-device and alerted to the admin within 10 min | UC-06 |
| No server-side view of who is stuck where during rollout | Enrolment funnel visible per agent: invited → installed → permitted → verified → capturing | UC-17 |

**Band 2 — recording capability per model.** Confirmed working; now a
verification and monitoring job, not research.

| CallSentry gap | BonviCall requirement | UC |
|---|---|---|
| Which mechanism produced two-sided audio was never recorded | S1 (§3.1) names it; the supported-model table records the route per model | §3.1, UC-14 |
| Silent degradation — a vendor update disables the OEM recorder and audio just stops | Per-model capture rate monitored against the M0 baseline; a drop raises an alert | UC-23, N4 |
| No visibility into *why* audio is missing | Every call without audio carries a machine-readable reason code | UC-14, UC-23 |
| Audio at 44.1 kHz / 128 kbps AAC ≈ 57.6 MB per hour | Mono 16 kHz Opus ≤ 24 kbps ≈ 10.8 MB per hour | §6.4 |
| No chunked or resumable audio upload — a 60 MB file over 3G restarts from zero | Resumable chunked upload with server-side reassembly | UC-14 |

**Band 3 — admin visibility and data integrity.**

| CallSentry gap | BonviCall requirement | UC |
|---|---|---|
| Calls that happen while the app is dead are never captured — `CallLog` is only read inside a live call cycle | Reconciliation sweep of the device call log on every start | UC-13 |
| Idempotency key is `localId`, a per-install Room autoincrement — reinstall restarts it at 1 and collides | Client-generated UUID per call, server upsert | UC-12 |
| Employee can stop the service from the Dashboard ("Xizmatni o'chirish") and nobody is told | Disabling capture raises an admin alert within 10 min | UC-18 |
| No server-side UI at all | Full web admin panel | UC-17…UC-24 |
| No device or SIM identity in the wire format; a login is just a person | Registered number is the identity, verified at enrolment and re-checked | UC-01, UC-04 |
| Records whatever the microphone hears on whatever SIM — unacceptable on a personal phone | Only the registered number is captured; other SIMs never recorded or uploaded | UC-15 |
| `MISSED` inferred from a state machine that CallLog then contradicts | Direction and duration reconciled against the call log before upload | UC-11 |
| Device clock trusted blindly for `startedAt` | Clock skew measured every sync, shown in device health | UC-17 |
| No pagination on any endpoint | Every list endpoint paginated and filterable | UC-19 |
| No token refresh; a dead token silently stops all sync | Refresh token + installation-bound credential; expiry surfaces as a device alert | UC-17 |
| No error contract — every failure is an opaque throwable | Uniform `{"error":{"code","message"}}` envelope | N35 |

**Band 4 — battery and mobile data.** Nobody complained in the trial, so these
no longer lead. They remain **mandatory** because the phone and, unless Bonvi
pays, the data plan belong to the employee. Budgets unchanged: N13–N15.

### 4.3 Installation, permissions and identity — the hard part

The client's instruction on identity: *"eng muhimi ularning tel raqamini bizning
bazaga kiritib qo'ysak shu bo'yicha record qilish"* — put their phone number in
our database and record against that.

**UC-01 — Admin registers an agent and their work number**
`admin` creates an agent (name, role) and registers one or more company numbers
to them, each with a `valid_from` date. The panel issues a single-use enrolment
code tied to that number.
*Failure:* the number is already registered to another agent → the panel refuses
and names the current holder.
**AC:** a number in E.164 form (matched on the last 9 digits, N37) is active for
exactly one agent at a time. Registering an already-active number returns HTTP
409 naming the current holder and creates nothing. An enrolment code is redeemable
once; a second redemption returns 409, a code older than 24 h returns 410. Both
failures appear in the admin's list with a timestamp.

**UC-02 — The agent installs the app on their own phone, past the security warnings**
The single hardest step in the product. The app is not on Google Play (N33), so
Android and Play Protect will both object, and the person seeing those warnings
is a salesperson on their own phone who has every reason to be alarmed.
*Main flow:* the agent opens a personalised install link, sees an Uzbek page that
shows the exact warning screens they are about to see, with a photo of each and
what to tap, and installs.
*Failure:* Play Protect blocks or removes the app; the OS refuses the install;
the agent abandons.
**AC:**
- The install guide is written against the **actual** screens of each Android
  version in the fleet, and every warning the user will meet is shown in advance
  — no step in the flow is a surprise.
- **3 out of 3 salespeople who have never seen the app complete installation and
  reach "capturing" unaided, in under 15 minutes each**, using only the in-app
  and on-page guidance. Measured with a stopwatch on real phones; if any of the
  three fails or needs rescuing, the flow is revised and re-tested. This is the
  acceptance gate for M2.
- Where a step **cannot** be done unaided (developer options, or a Play Protect
  exemption that Android does not let an app request), the flow says so plainly,
  offers the admin-assisted path, and the panel shows that agent as
  `needs_assisted_install` rather than silently stalled.
- The exact install path, per Android version, is written down and reproducible
  by someone who was not present — it is an operational procedure, not tribal
  knowledge. **[constraint]** it must not require the employee to surrender the
  phone permanently or to factory-reset it.
- If Play Protect removes the app after a successful install, the server notices
  via the missing heartbeat (UC-17) and the agent appears as
  `install_disappeared`, distinct from `offline`.

**UC-03 — Guided permission setup with per-step verification**
The trial's reported blocker: obtaining permissions from a default-state device.
*Main flow:* the app requests each permission one at a time, each preceded by one
Uzbek sentence saying what it is for and what breaks without it, and **verifies
after each grant that it actually took effect**.
*Failure:* a permission is denied, denied permanently, or granted but
non-functional (an OEM permission manager that reports granted while blocking).
**AC:**
- Each step re-checks the capability, not the permission flag: microphone by a
  1-second test capture, call state by reading the current state, call log by a
  1-row query, battery-optimisation exemption by querying the power manager. A
  step is green only if the capability works.
- The app **never shows "ready"/"capturing" while any required capability is
  missing.** Asserted by a test that denies each permission in turn and checks
  the app's reported state and the state sent to the server.
- Every step's outcome (granted / denied / denied-permanently / granted-but-
  non-functional) is reported to the server and visible per agent in the panel
  within 2 minutes.
- OEM-specific steps — autostart, battery lock, "allow background activity" on
  MIUI/EMUI/ColorOS — are shown **only on the OEMs that need them**, with the
  correct screen path for that OEM, and are verified where the platform exposes
  a check.

**UC-04 — The app proves it is on the registered number**
Capture is worthless if attributed to the wrong number, and on a personal phone
it is also a privacy failure.
**AC:** before capture begins the app must positively establish that the
registered number is present, by one of two routes in order:
1. the SIM's own MSISDN, where the operator populated it;
2. a **callback code** — the agent dials a short server-side number and the
   inbound caller ID confirms the match.
The test asserts that with route 1 unavailable (MSISDN empty — the common case on
Uzbek SIMs) enrolment still completes via route 2, and that a callback placed
from a *different* number fails with a distinct error, leaving the device
unenrolled. **`TelephonyManager.getLine1Number()` returning null or empty must
never be treated as a match.**
With only two routes the **callback path is load-bearing**: it must be verified
to work on every OEM *and* operator combination present in the fleet, because
inbound caller-ID presentation is decided by the network, not by us. That
verification belongs in M0 alongside the recording-capability table.
After enrolment the server holds: registered number, the SIM subscription id
carrying it, device model, Android version, app version, an installation-bound
token, and the agent id.

**UC-05 — Capture survives reboot and app update**
*Failure:* the OS refuses to start the service → the app retries and reports
`service_not_running` on its next contact.
**AC:** after `adb reboot`, device untouched and screen locked, a call placed
5 minutes after boot completes appears in the panel with correct direction and
duration. Same after `adb install -r` of a new APK, and the registered-number
binding survives both without re-verification.
**[constraint]** the platform must support a boot-completed receiver and a
long-running foreground service of a call/microphone type.

**UC-06 — A permission or capability disappears after enrolment**
The employee revokes a permission, an OS update resets it, Play Protect
re-enables itself, or a vendor update disables the OEM call recorder.
**AC:** the app re-verifies every capability (same checks as UC-03) on start and
at least every 6 hours, and on any transition from working to not-working the
admin sees an alert **within 10 minutes** naming the agent, the device and the
specific capability. Loss of *recording* capability is reported distinctly from
loss of *call capture* capability — the first degrades the product, the second
stops it. The agent cannot dismiss or suppress the alert from the app.

**UC-07 — The company SIM moves to a different phone**
The number is the identity, so history follows the number.
*Failure:* the app is installed on two phones both claiming the same number.
**AC:** installing and verifying on a second phone binds the number to the new
installation and sets the previous to `replaced`; the previous is refused with
401 on its next contact **after** its queued records have been accepted. Both
remain visible with the changeover timestamp. **Exactly one active installation
per registered number**, enforced server-side, and the change raises an admin
notification — an unexpected re-binding is what a stolen credential looks like.
After the changeover the agent's call list still contains calls made from the old
phone.
**[constraint]** the number↔agent mapping is **time-boxed** (`valid_from` /
`valid_to`), not a plain column. When a company SIM is reassigned from agent A to
agent B, calls made before the handover stay attributed to A. BonviZvonki stores
this as a single `agents.phone` column and cannot express it — do not copy that
shape.

**UC-08 — The agent leaves; Bonvi reclaims the SIM but not the phone**
**AC:** deactivation immediately (a) closes the number↔agent mapping with a
`valid_to`, (b) revokes the installation token so the next request returns 401,
and (c) instructs the app to stop capture and delete all local audio, uploaded or
not. Calls already uploaded stay in the panel, attributed to the ex-employee for
the period they held the number. If the phone never comes online again the panel
shows `revoked_pending_confirmation` with how many records and megabytes were
still queued when contact was lost — **Bonvi cannot wipe a phone it does not own,
and the product must say so rather than imply the revocation completed.**

### 4.4 Capture

**UC-09 — Outgoing call is captured**
*Failure:* the callee does not answer.
**AC:** for an answered outgoing call on the registered number the panel row has
`direction=outgoing`, the dialled number normalised to E.164, `started_at` within
2 s of the call-log `DATE`, and `duration_sec` equal to the call log's `DURATION`
±1 s. For an unanswered outgoing call, `answered_at = null` and
`duration_sec = 0` — never reported as a conversation.

**UC-10 — Incoming answered call is captured**
**AC:** `direction=incoming`, caller number present, `answered_at` set,
`duration_sec` equal to call-log duration ±1 s.

**UC-11 — Missed, rejected and unanswered calls are classified correctly**
**AC:** over the acceptance window the panel's classification into {answered
incoming, answered outgoing, missed incoming, rejected incoming, unanswered
outgoing} matches the call log's `TYPE`/`DURATION` for **≥ 99 %** of calls, with
**zero** calls classified as answered that the call log shows as duration 0.

**UC-12 — A call made offline reaches the panel exactly once**
The client's own framing of the model: recorded on the phone, transferred when
the internet comes back.
*Failure:* the upload is interrupted after the server has committed.
**AC:** a call placed with the device in airplane mode appears in the panel
**within 5 minutes** of network restoration, **exactly once**. Re-sending the
same record (same `client_call_id`) returns the same server id, HTTP 200, and
creates no second row — verified by killing the app immediately after the request
is sent and letting it retry. Duplicate rate over the acceptance window is **0**.

**UC-13 — Calls made while the app was not running are recovered**
*Failure:* the call log itself was cleared by the user.
**AC:** after `adb shell am force-stop <pkg>`, with **4** further calls placed on
the registered number while the app is not running, all 4 appear in the panel
within **15 minutes** of the app restarting, matching the call log, each exactly
once, each flagged `audio_missing_reason = app_not_running`. If the call log was
cleared, the calls are reported as unrecoverable in the gap report (UC-23) rather
than silently absent.

**UC-14 — Audio is recorded and uploaded, or the reason is recorded**
*Main:* the route identified in S1 works on this model; audio is transcoded and
uploaded. *Failure:* the OEM recorder is off or absent, the platform blocks
capture, or the microphone is held by another app.
**AC (audio present):** the file is mono, 16 kHz, Opus ≤ 24 kbps, duration within
2 s of `duration_sec`, playable end-to-end with working seek. Upload is
resumable: interrupting at ≈50 % and resuming completes the same file (identical
SHA-256) without re-sending transferred bytes.
**AC (audio absent):** the call row still exists, `has_audio = false`, and
`audio_missing_reason` is one of a closed enum — `recording_route_unavailable`,
`oem_recorder_off`, `no_permission`, `capture_returned_silence`,
`app_not_running`, `upload_expired` — never null, never free text. A call is
**never** dropped because audio failed.
**AC (attribution):** audio is attached to a call only when the recording's time
window matches a captured call **on the registered subscription**. A recording
that cannot be matched to a registered-number call is discarded, never uploaded —
this is what stops a private call being harvested from a shared OEM recordings
folder (see UC-15 and §9).

**UC-15 — Dual-SIM: only the registered number is captured**
A personal phone very often carries the employee's own SIM alongside the company
SIM. This is now a first-class case.
**AC:**
- A call on a SIM whose number is **not** registered is **not recorded, not
  uploaded, and not counted** — no metadata, no number, no duration, no audio.
  Asserted by a scripted test placing calls on the unregistered SIM and checking
  that the server received nothing and the local queue holds nothing.
- Where the OS cannot tell which subscription a call belonged to, the call is
  treated as **unregistered** (fail-closed) and counted as
  `subscription_unknown` in the gap report. Capturing a private call by accident
  is a worse failure than missing a work call.
- The app's main screen states permanently which number is being recorded, so the
  employee can see the boundary rather than take it on trust (N41).
- Scripted concurrency test: (a) call waiting held and resumed, (b) call waiting
  rejected, (c) a call on SIM 1 followed within 30 s by one on SIM 2 — the panel
  shows exactly the registered-number calls, each with the correct subscription
  id, and no recording is attached to the wrong row.

### 4.5 Live control and the panel

**UC-16 — Click-to-call from the panel**
*Failure:* the device is offline, lacks `CALL_PHONE`, or the OS refuses.
**AC:** with the device online the phone starts dialling within **5 seconds** of
the click and the panel shows `acknowledged`. The resulting call row carries the
`command_id` that triggered it. No acknowledgement within 15 s → `failed` with a
reason, and no call row is ever linked to a failed command. A dial command older
than 2 minutes is discarded by the app and never attached to a manually dialled
call.
**[constraint]** the server needs a persistent push channel to the device
(WebSocket and/or push wake-up).

**UC-17 — Admin sees device health and the enrolment funnel**
**AC:** for each agent the panel shows their stage — `invited` → `installed` →
`permitted` → `number_verified` → `capturing` — and for each installation:
online/offline, last contact, app version, Android version, battery level,
battery-optimisation exemption, **each capability's verified state** (UC-03),
recording route and whether it currently works, pending queue depth (records and
MB), and **clock skew vs server in seconds**. A device that stops contacting the
server is OFFLINE within **10 minutes** (heartbeat every 2 min, 5 missed). Every
value is checkable against the device itself.

**UC-18 — Capture cannot be switched off silently**
**AC:** each of these produces an admin alert within **10 minutes** naming the
device, agent and specific cause: capture toggled off in the app, microphone
permission revoked, phone-state permission revoked, app force-stopped, battery
optimisation re-enabled, app uninstalled (detected as sustained absence). The
agent cannot dismiss or suppress the alert.
**Note on enforcement:** on a phone Bonvi does not own there is **no technical
enforcement** — no MDM to reinstall, no way to block uninstall. The alert plus a
management conversation *is* the enforcement mechanism, and the product must not
pretend otherwise.

**UC-19 — Manager browses and filters calls**
**AC:** a filtered page of 1,000 rows renders in under **2 seconds** and the
server responds in under **500 ms at p95** with 500,000 call rows. Paging is
stable: no row on two pages, none skipped when new calls arrive during paging.

**UC-20 — Manager listens to a recording**
**AC:** audio starts within **3 seconds** on a 20-minute recording over 10 Mbps,
and dragging to 15:00 starts playback there (HTTP Range → 206 + `Content-Range`).
A request without a valid token returns 401 and no bytes.

**UC-21 — Salesperson sees only their own calls**
**AC:** as `sales`, `GET /calls` returns only rows whose `agent_id` is that
user's; another agent's call by id returns **404** (not 403 — existence is not
disclosed); another agent's audio returns 404. Automated RBAC test per endpoint:
no token → 401, wrong role → 403, right role wrong owner → 404.

**UC-22 — Manager exports a call list**
**AC:** the export's row count equals the filtered count shown in the UI, contains
no audio and no columns the exporting role may not see. 50,000 rows in under 30 s.

**UC-23 — The gap report: calls without audio, and capture regressions**
Replaces BonviZvonki's hand-made `audiosiz_qongiroqlar_zaxira.csv`, and carries
the per-model regression watch from M0.
**AC:** the panel reports, for a chosen period, every call with `has_audio=false`
grouped by `audio_missing_reason`, agent and device model, with totals and a
percentage of answered calls; plus the production-rig delta (§4.1 B) per device.
Totals reconcile exactly with the call list filtered on `has_audio=false`. A
device model whose audio capture rate drops **more than 10 percentage points
below its M0 baseline** over any 7-day window raises an alert — this is how a
vendor update that silently kills the OEM recorder gets noticed.

**UC-24 — Every access to a recording is audited**
**AC:** playing or downloading writes an audit row (who, which call, when, from
which IP). Visible to `admin` only, append-only through the API (no endpoint
updates or deletes a row), count increases by exactly one per playback start.

### 4.6 Data hygiene and operations

**UC-25 — Internal vs external is decided automatically**
The L4 failure, fixed at the source. Q2 improves this: registered numbers are a
cleaner directory than device-derived numbers ever were.
**AC:** the company line directory is assembled automatically from **all
registered numbers** plus an admin-editable extra list accepting suffix rules
(e.g. `*700`). A call whose remote number is in that directory, or shorter than
6 digits (PBX extension), is `internal`; everything else `external`. If the
directory is empty the system **refuses to classify** and marks calls `unknown`
rather than defaulting them to `external` — the exact mistake BonviZvonki had to
fix. Verified by a test that empties the directory and asserts no call is
labelled `external`.

**UC-26 — Retention deletes audio, not history**
**AC:** audio older than the configured retention (default 12 months) is deleted
by a scheduled job; the call row, metadata and audit history remain, with
`audio_deleted_at` set. Playing such a call returns a specific "audio expired"
error, not a 500. No endpoint deletes an individual call or its audio: `DELETE`
on a call returns 405 for every role including `admin`.

**UC-27 — Silence is an alert, not a gap**
The MoyZvonki failure mode (L6) was "no new calls arrive and nobody is told".
**AC:** if a device active in the previous 7 working days reports zero calls for
4 consecutive working hours while at least one other device is reporting, the
admin is alerted by name. If the **whole fleet** reports zero for 2 consecutive
working hours, the alert is critical. This is also the only detection available
when a company SIM is moved into a phone that has no app installed.

**UC-28 — Withdrawn 2026-09-04 — out of scope (internal project).**
*(Id retained; `docs/TASKS.md` references it by number.)*

**UC-29 — A downstream system can pull the data**
**AC:** with a `service` token, `GET /export/calls?since=<cursor>` returns a
paginated, ordered, cursor-stable list of call metadata; audio is fetchable by
call id. The token cannot write, cannot read users, cannot read the audit log —
asserted by RBAC test. Two consecutive full passes over an unchanging dataset
return identical row sets.

---

## 5. Scope boundary — explicitly NOT in release 1

This list is what makes the project finishable. Anything here is a change
request, not a bug.

### 5.1 Not a PBX
- **No SIP, no SIP trunks, no Asterisk/FreeSWITCH, no softphone.** Calls ride
  ordinary mobile SIM cards in employees' phones — decided by the client. *Why:*
  a PBX needs an operator contract, licensing and a telecom skill set Bonvi does
  not have, and the trial proved the SIM-fleet model captures two-sided audio.
  The client asked not to be made to choose here and the coordinator is briefing
  them separately; **PBX remains the documented release-2 fallback** if the
  supported-model table from M0 turns out too small to cover the team.
- **No company DID numbers, no IVR, no queues, no transfer, no hold music, no
  conference, no barge-in / whisper / listen-in.**
- **No server-side call recording** — no media path traverses the server.
- **No real-time audio streaming.** A recording appears after the call ends.

### 5.2 Not on iOS
- **No iPhone app.** iOS provides no API to detect and record a cellular call.
  Any salesperson on an iPhone is **not covered**. *Why:* not possible, not
  merely expensive. How many people this affects is open item D1 (§8.2).

### 5.3 Not analytics
- **No ASR / transcription, no LLM scoring, no rubric, no red flags, no
  leaderboards, no "suspicious sales".** BonviZvonki does that; BonviCall
  produces the raw material.
- **No Telegram bot, no client surveys, no client ratings.**
- **No SAP / Excel sales import.**

### 5.4 Not coupled to BonviZvonki — **in release 1 only**

The client has confirmed the connection is coming: *"bonvizvonkini keyinchalik
bu projectga ulaymiz."* That makes this a **sequencing decision, not a
separation**, and it changes what release 1 owes the future:

- **Release 1:** no shared database, no live API, no dependency in either
  direction. BonviCall must be demonstrable on its own, and a BonviZvonki outage
  must not affect it.
- **Release 1 nevertheless ships the read-only export (UC-29)** — and because
  the connection is now planned rather than hypothetical, that export is a
  **committed contract**, not a convenience. It is designed to be consumed by an
  ingest adapter, versioned, and paged.
- **Release 2:** BonviZvonki gains a second ingest adapter that reads from
  BonviCall alongside its MoyZvonki one. Both sources run **in parallel for one
  month**, call counts are compared side by side, and only then is MoyZvonki
  cancelled. That comparison is itself a report, so the decision rests on
  evidence rather than confidence.

Two consequences for decisions taken *now*, in release 1:

1. **Field compatibility is not optional.** Phone-number normalisation must
   match BonviZvonki's exactly — E.164 with the **last 9 digits** as the
   matching key (N37) — and the export must carry everything BonviZvonki's
   pipeline needs: direction, both numbers, timestamps, duration, agent
   identity, internal/external classification, and a stable audio reference.
   Getting this wrong is cheap to prevent and expensive to discover in
   release 2.
2. **Audio access across the boundary is a design question to settle early.**
   BonviZvonki streams audio from MoyZvonki today and stores none itself. When
   it reads from BonviCall it will need the same, which means an authenticated
   service-to-service audio endpoint with Range support (N43) — not a public
   URL, and not a bulk copy that duplicates 200 GB/year.

The adapter work itself lives in the BonviZvonki repository and is **out of
scope here**; what is in scope is not making it impossible.

### 5.5 Not a CRM
- **No AmoCRM, Bitrix or any CRM integration.** CallSentry's `AmoCrmApiService`
  and CRM-selection screen were scaffolding for a different customer.
- **No client/deal database.** A call carries a number, an optional contact name,
  and a free-text note.
- **No SMS anywhere in the system** — not sending, not receiving, not logging,
  and no SMS gateway dependency. Number verification uses the callback route in
  UC-04. Out of scope, not deferred.
- **No auto-dialer, campaign or predictive dialling.**

### 5.6 Not captured
- **Only cellular voice calls on registered numbers.** WhatsApp, Telegram, IMO
  and other VoIP calls are out of scope and invisible. Measurable blind spot and
  a risk item — a seller can move to WhatsApp to avoid being recorded.
- **Calls on an unregistered SIM in the same phone are deliberately not
  captured** (UC-15). This is a *feature*, not a limitation.
- **No video calls. No voicemail.**

### 5.7 Not in the release-1 build
- **No managed-device / device-owner provisioning, and no full MDM.**
  Not deferred — **impossible**: it requires factory-resetting a phone Bonvi does
  not own. This was the most reliable route to guaranteed recording and Q2 closed
  it permanently.
- **Android Enterprise work profile (BYOD) is not in release 1** pending spike S2
  (§3.1). It is the one remaining administrative route to installing and
  permitting the app on a personal phone, but it may be unable to see calls from
  the personal dialer, which would make it useless here. Not promised.
- **No multi-tenant / multi-company support.** One Bonvi instance.
- **No billing or per-device tariff accounting.**
- **No mobile app for managers** — the panel is desktop-first.
- **No Russian or English UI.** Uzbek only.
- **No Google Play distribution** (N33); the APK is self-hosted.
- **No rooted / Magisk / Xposed recording techniques.** If audio requires them it
  does not ship.

### 5.8 Out of scope — removed by the client, 2026-09-04

Not deferred, not "release 2" — **out of scope.** The client's instruction:
*"loyihadan yurist hulosasi, siyosiy hujjatlar, SMS degan qismlarni olib tashla,
kerakmas, bu shunchaki kompaniya ichki loyihasi"* — this is an internal company
project.

- **No legal opinion, data-jurisdiction analysis or compliance work.** Where the
  audio physically lives is an ordinary engineering choice: cost, latency, backup
  convenience. Retention (N19) is a storage-cost decision.
- **No consent or notice machinery.** No consent gate, no recorded notice
  artefact, no notice versioning, no client-facing announcement feature. Nothing
  in the product gates on acknowledgement.
- **No SMS anywhere** — no sending, receiving, logging, or SMS gateway
  dependency. Number verification is the callback route (UC-04).

Withdrawn ids, kept in place so `docs/TASKS.md` cross-references stay valid:
**UC-28**, **N29**, **N30**, **B1**.

---

## 6. Non-functional requirements

### 6.1 Reliability of call capture

| # | Requirement | Checked by |
|---|---|---|
| N1 | **Capture rate ≥ 99.5 %** over the acceptance window, per device | §4.1 A, then §4.1 B continuously |
| N2 | **Duplicate rate = 0** | §4.1 A |
| N3 | **No silent loss.** Any call in the device call log and absent from the panel appears in the gap report within 24 h | UC-23, UC-13 |
| N4 | **Audio capture rate meets or exceeds the M0 baseline for that model**, and a model whose measured rate falls below **90 %** of its baseline is removed from the supported list rather than quietly under-performing. *Q2 changed the remedy:* Bonvi cannot swap an employee's phone, so removal from the list means either Bonvi buys that person a handset or that person is uncovered — it is a budget decision, not a config change | §4.1, UC-23 |
| N5 | 100 % of calls without audio carry a reason code from the closed enum | UC-14 |
| N6 | Metadata visible **≤ 60 s** after call end when online; **≤ 5 min** after reconnection | UC-12 |
| N7 | Audio available **≤ 15 min** after call end on Wi-Fi; **≤ 24 h** worst case, after which it uploads over cellular regardless of the Wi-Fi-only preference | UC-14 |

### 6.2 Offline behaviour

| # | Requirement |
|---|---|
| N8 | The device queues locally for **≥ 30 days / ≥ 2,000 calls / ≥ 1 GB of audio** without losing a record. *The audio figure is deliberately lower than the 2 GB of the previous revision: this is the employee's own storage* |
| N9 | Uploads are oldest-first; a poisoned record is parked after 5 attempts and reported to the admin instead of blocking the queue behind it |
| N10 | On queue-space exhaustion — or when the phone's free space drops below 1 GB — the app **stops recording new audio and alerts**, rather than deleting captured audio or filling the employee's phone. Metadata is never dropped (30 days of metadata is < 2 MB) |
| N11 | Local audio is deleted only after the server confirms receipt (checksum match) |
| N12 | An app reinstall must not lose an unsynced queue — the app warns before uninstall if the queue is non-empty, and the admin sees pending depth before revoking |

### 6.3 Battery and data budget — now an adoption requirement

The trial produced no battery or data complaints, so these no longer lead the
priority list (§4.2 Band 4). They remain mandatory and are **not** negotiable
downward, because after Q2 the phone is the employee's and — unless Bonvi
reimburses (§8.2 B2) — so is the data plan.

| # | Requirement | Checked by |
|---|---|---|
| N13 | ≤ **4 % of a full charge per 8-hour shift** attributable to the app, on a device handling 30 calls | `adb shell dumpsys batterystats` per package, averaged over 3 shifts per model |
| N14 | ≤ **1 GB cellular per device per month** (configurable cap), audio deferred to Wi-Fi by default | Server-side per-device counter, shown in device health |
| N15 | ≤ **5 MB cellular per device per day** when audio upload is deferred (metadata, heartbeat, commands only) | Same counter |
| N16 | No wake lock outside an active call, an active upload, or the push keep-alive | Code review + `dumpsys power` sampling |

### 6.4 Audio storage volume and retention

Volume model from BonviZvonki `docs/PLAN.md` §1, to be re-confirmed: 15 agents ×
30 calls/day × 26 days = **11,700 calls/month**, average 8 minutes = **1,560
hours/month**.

| # | Requirement |
|---|---|
| N17 | Audio stored as **mono, 16 kHz, Opus ≤ 24 kbps ≈ 10.8 MB/hour**, transcoded **on the device before upload**, so the cellular budget and the storage budget are the same number |
| N18 | At base volume that is **≈ 17 GB/month, ≈ 200 GB/year**; provision **≥ 250 GB steady state** at 12-month retention, with usage and 30-day growth shown in the panel |
| N19 | Retention: audio **12 months** then automatic deletion; metadata and audit log indefinite. An operational and storage-cost decision — 12 months keeps steady-state disk at ≈ 250 GB (N18) while covering a full year-on-year comparison. Configurable by `admin` only; lowering below 3 months requires explicit confirmation |
| N20 | Audio lives on **Bonvi-controlled storage**, never given a public or unauthenticated URL. This is the entire point of the project (L1). Where that storage physically sits is an ordinary engineering choice — cost, latency, backup convenience |
| N21 | Quality floor is "good enough for ASR later": the format must survive being fed to a speech-to-text engine without a second lossy transcode |

### 6.5 Security, privacy and access

| # | Requirement |
|---|---|
| N22 | HTTPS/WSS only; cleartext disabled in the manifest; certificate errors fatal, never bypassed |
| N23 | Every endpoint RBAC-protected; automated test per endpoint asserts 401 without a token, 403 with the wrong role |
| N24 | Credentials are **installation-bound**: a token copied to another device is rejected on first use and raises an admin alert |
| N25 | Short-lived access token + refresh token. Expiry never causes silent data loss — the queue holds and the device reports `auth_expired` |
| N26 | Tokens, passwords, enrolment codes and verification codes never appear in logs (last 4 characters at most) |
| N27 | Audio access is audited (UC-24); the audit log is append-only |
| N28 | **Personal-device data minimisation — hard boundary.** The app uploads only: call metadata for the registered number, audio for those calls, and a contact name where one resolves. It never uploads the contact book, SMS, location, installed-app list, media, or anything relating to an unregistered SIM. Where broad storage access is required to reach OEM recording files, the app reads **only** files that match a registered-number call's time window (UC-14) and uploads nothing else. Asserted by reviewing the outbound payload schema and by a test that places private-SIM calls and checks the server received nothing |
| N29 | *Withdrawn 2026-09-04 — out of scope (internal project). Id retained for `docs/TASKS.md`.* Audio hosting location is an ordinary engineering choice — pick for cost, latency and backup convenience |
| N30 | *Withdrawn 2026-09-04 — out of scope (internal project). Id retained for `docs/TASKS.md`.* |

### 6.6 Platform, distribution and interface constraints

| # | Constraint | Why |
|---|---|---|
| N31 | **[constraint]** The platform must support: a persistent foreground service of a call/microphone type, a boot-completed receiver, a durable background work queue with network constraints, a local database, and background audio capture. Practically: a native Android app (Kotlin by default unless `plan-stack` names a reason) | UC-05, UC-12, UC-13 |
| N32 | **[constraint]** Minimum Android 8.0 (API 26). Every OS version in the real fleet must be on the supported list before go-live. **`targetSdk` is a live design decision, not a default** — S1 may show the recording route depends on a low `targetSdk`, which is exactly what triggers the install friction of UC-02 and carries a deprecation clock | §3.1 S1, UC-02 |
| N33 | **[constraint]** The app **cannot ship through Google Play** — Play policy prohibits call-recording apps and would reject the permission set. Distribution is a signed APK from Bonvi's own server with an in-app updater. MDM push is **not** available (Q2). Therefore the install path must be walkable by the employee (UC-02) and the update path must reach every phone without an office visit |
| N34 | **[constraint]** Because updates depend on employee cooperation, the server enforces a **minimum supported app version**: an older client is refused with a distinct error, is told in Uzbek to update, and **its queued records are accepted first** so refusing an old version never destroys data | UC-17 |
| N35 | Uniform error envelope on every response: `{"error":{"code":"...","message":"..."}}`, message in Uzbek where an end user sees it | BonviZvonki convention |
| N36 | Wire timestamps are ISO-8601 with explicit UTC offset; the device also sends raw epoch millis and timezone so the server can compute clock skew. Server receipt time is authoritative for ordering | Devices lie about time |
| N37 | Numbers normalised to E.164 server-side; matching key is the **last 9 digits**, identical to BonviZvonki | Already solved once |
| N38 | Server availability ≥ 99 % during working hours (08:00–20:00 Asia/Tashkent). An outage must never lose a call: devices queue and drain (N8) |
| N39 | Uzbek UI in panel and app; code, identifiers, comments and internal docs in English | Global working rules |
| N40 | **Enrolment is a measured feature, not a README.** 3 of 3 unaided salespeople reach `capturing` in under 15 minutes each (UC-02), and the install procedure is written down per Android version and reproducible by someone who was not present |
| N41 | **Visible boundary.** The app permanently displays which number it records, and the agent can see their own captured calls. On a phone the employee owns, this is the difference between a tool and surveillance, and it is the cheapest adoption lever available |
| N42 | Capability drift (permission, recording route, Play Protect removal) is detected on-device at least every 6 hours and surfaced to the admin within 10 minutes | UC-06 |
| N43 | **[constraint]** The audio playback endpoint must support HTTP **Range** requests (206 + `Content-Range`), and the same applies to the service-to-service endpoint release 2 will use (§5.4). Without it, seeking in the player does not work. BonviZvonki hit exactly this and solved it with a Service Worker bridge for the `Authorization` header; expect to do the same. *Restored 2026-09-04 — this constraint existed in revision 1 and was lost in renumbering* | UC-20, §5.4 |

---

## 7. Data sources and data ownership

| Source | What comes from it | Volume | Owner | Format | Notes |
|---|---|---|---|---|---|
| **Registered numbers (admin entry)** | The identity anchor: agent ↔ number, time-boxed | ~15–30 rows | Bonvi | Web form | **The primary key of the whole system.** Everything is attributed through it |
| **Handset — telephony** | Direction, remote number, ring/answer/end timestamps, duration, subscription id — **for the registered number only** | ≈ 11,700 calls/month, ≈ 1 KB each | Bonvi (data) on employee-owned hardware | JSON over HTTPS | Reconciled against the device call log |
| **Handset — audio** | The recording, by the route S1 identifies | ≈ 1,560 h/month → ≈ 17 GB/month at 24 kbps Opus | **Bonvi** — the asset the project exists to own | Opus, mono 16 kHz | Availability is model-dependent → M0 table |
| **Handset — call log** | Reconciliation and gap detection; the production-rig denominator | Same order as calls | Employee's phone | Content provider | Read-only, never modified; filtered to the registered subscription |
| **Handset — contacts** | Contact name for a number, if permission granted | Small | **The employee** — this is their personal contact book | Content provider | Resolved on-device; a name is uploaded only for a captured registered-number call. The number is the identity, the name is decoration (L3) |
| **Handset — telemetry** | Battery, capability states, app version, OS version, queue depth, clock skew, self-measured call-log delta | ~1 KB every 2 min per device | Bonvi | JSON | Drives UC-17, UC-18, UC-23, UC-27 |
| **Admin manual entry** | Users, agents, company line extras and suffix rules, retention, alert thresholds, supported-model table | Tens of rows | Bonvi | Modal-only per house convention | The line directory is mostly *derived* from registered numbers — UC-25 |
| **One-off agent roster import** | Initial agents, optionally from BonviZvonki's `agents` table | ≈ 33 rows | Bonvi | CSV/XLSX, manual, once | Not a live integration; typing 33 rows is also acceptable |
| **Not a source in release 1** | MoyZvonki history, BonviZvonki DB, SAP exports, AmoCRM, SMS content, unregistered-SIM calls | — | — | — | §5.4, §5.5, §5.6 |

**Ownership statement.** All call metadata and audio produced by BonviCall belong
to Bonvi and reside on Bonvi-controlled infrastructure. No third party holds the
only copy of a recording. Nothing leaves except through the export (UC-29) or an
admin's audited download (UC-24).

**Ownership boundary created by Q2.** The *data* is Bonvi's; the *device* is the
employee's. Three consequences are load-bearing: Bonvi cannot wipe the device
(UC-08), cannot force an update (N34), and must not read anything on it beyond
the registered number's calls (N28).

**What the system deliberately does not collect.** Only calls on registered
numbers are captured. Calls on an unregistered SIM in the same handset produce
nothing — no metadata, no number, no audio (UC-15) — and the app uploads nothing
from the phone beyond registered-number call data (N28). This is a product
boundary, enforced in code and tested, not a policy statement.

---

## 8. Open items

### 8.1 Settled — 2026-09-04

| # | Question | Answer |
|---|---|---|
| Q1 | SIM fleet or PBX? | **SIM fleet.** Recorded on the phone, transferred when the internet returns. PBX stays as the documented release-2 fallback (§5.1); the client asked not to choose and is being briefed separately |
| Q2 | Fleet and ownership? | **Employees' own handsets; company-issued SIMs in most cases, personal in some. Identity anchor is the registered phone number.** Rewrote §4.3, UC-15, §4.1, §6.3, N33 |
| Q3 | Employee consent? | **None required; installation is mandatory** — all staff are Bonvi's own. No consent gate, and (per the 2026-09-04 scope reduction) no notice machinery either |
| Q4 | Feed BonviZvonki? | **Yes — connected later, as recommended.** Release 1 stays independent and ships the read-only export (UC-29); BonviZvonki is wired to it in release 2, after one month of parallel running against MoyZvonki. Client's words: "bonvizvonkini keyinchalik bu projectga ulaymiz" |
| Q5 | Was CallSentry trialled? | **Yes. Two-sided audio worked. No lost calls, no service death, no battery or data complaints, nobody turned it off. The problem was installation and permissions** — developer mode and/or disabling Play Protect. §4.2 reordered on this evidence |

### 8.2 Still open

**D1 — Data request, not a decision: which phones?** *(carried in `RISKS.md`)*
Still unknown: how many salespeople, which phone models and Android versions,
which models were in the trial, and how many carry iPhones. **No model mix is
assumed anywhere in this document.** If S1's hypothesis holds — that two-sided
audio comes from the OEM call recorder — then this list decides how much of the
team the product can actually cover, and it gates M0. A photo of Settings → About
phone from each salesperson is sufficient.

**B1 — Withdrawn 2026-09-04 — out of scope (internal project).**
*(Id retained; `docs/TASKS.md` references it by number.)*

**B2 — Business item: who pays for the mobile data?**
After Q2 the data plan is usually the employee's. Budget is ≤ 1 GB/month
cellular (N14) and near zero with Wi-Fi at the office.
> **Recommendation, applied unless corrected:** default to Wi-Fi-first upload
> with the 1 GB cap, which makes the cost small enough to ignore — and tell the
> team that in the manual, because an unexplained data cost on a personal phone
> is exactly the kind of grievance that gets an app uninstalled. If Bonvi
> prefers, reimbursing a fixed monthly amount removes the objection entirely for
> less than the MoyZvonki bill it replaces.

---

## 9. Risks that belong in `docs/RISKS.md`

Flagged here, analysed there. **The headline risk has changed.**

1. **~~Android blocks call recording~~ → "which models, by which route, and how do
   we notice when it stops".** The trial captured both voices, so the question is
   no longer feasibility but **coverage and regression**. The likely mechanism
   (S1 hypothesis) is harvesting the OEM call recorder's file, which means audio
   exists only on models that ship an enabled call recorder, and a vendor update
   can remove it silently on a phone Bonvi cannot administer. Mitigations are in
   the document: per-model baseline (M0), regression alert (UC-23), and the
   permanent fallback that **the call is always logged even without audio**
   (UC-14) — BonviZvonki's stray `audiosiz_qongiroqlar_zaxira.csv` turned into a
   supported product state.
2. **Installation and permissions on a phone Bonvi does not own.** Promoted to
   first place by the trial. Developer mode and Play Protect exemptions on
   fifteen personal phones, repeated on every new phone and after some OS
   updates, absorbed by non-technical users, with no MDM to fall back on.
The full candidate list, including the new Q2- and Q5-derived items, is in the
handover note to the coordinator.

---

## 10. Definition of done for release 1

- [ ] **S1 answered**: the recording mechanism is named and written down.
- [ ] **S2 answered**: the work-profile question is closed either way.
- [ ] **M0 published**: supported-model table with measured per-model audio
      capture rates, used as the regression baseline, **plus** confirmation that
      the UC-04 callback route works on every OEM and operator in the fleet.
- [ ] All UC-01…UC-29 acceptance criteria pass, **excluding the withdrawn
      UC-28** (§5.8).
- [ ] **N40 met**: 3 of 3 unaided salespeople complete install + permissions +
      number verification in under 15 minutes each, on real phones.
- [ ] The 7-day acceptance run (§4.1 A) meets N1–N7 on every model in the fleet;
      the production rig (§4.1 B) is live and reporting.
- [ ] UC-15 proven: calls on an unregistered SIM produce **nothing** on the
      server and nothing in the local queue.
- [ ] Battery (N13) and data (N14, N15) measured, not estimated.
- [ ] RBAC test per endpoint: 401 without token, 403 wrong role, 404 wrong owner.
- [ ] The scope boundary in §5 is unchanged, or every change is a signed change
      request.
- [ ] `docs/RISKS.md` exists with owner and mitigation per risk.
- [ ] Uzbek user manual (`docs/QOLLANMA.md`) covering: what the app records and
      what it does **not** (the other SIM), which number is being recorded, what
      the data costs and who pays, how to install past the security warnings, and
      what happens if you turn it off.
