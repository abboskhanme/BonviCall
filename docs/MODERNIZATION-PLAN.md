# BonviCall — from "it works" to "no developer can fault it"

**2026-09-12, after the first clean end-to-end capture on the Xiaomi 13 Lite.**
The pipeline the product exists for now works: a sales call is recorded with
both voices by the handset's own recorder, harvested, transcoded, attributed to
the registered SIM, and shown in the panel with its contact name. Three
consecutive calls confirmed it. This document is the plan to make it fast,
robust, and clean enough to survive a hostile code review — without breaking the
chain that now works.

The rule for every item below: **additive, measured, reversible, and verified on
the handset before it is called done.** No change to the working capture path
ships without a JVM test that fails before it and a real call after it.

---

## 1. Speed — the one thing the CEO can feel

Moi Zvonki shows a recording seconds after hang-up. BonviCall takes ~110 s.
Measured on two calls today, the delay is in two places, and only one of them is
large:

| Segment | Measured | Cause |
|---|---|---|
| hang-up → metadata on server | ~29 s | `POST_CALL_DELAY_SECONDS = 20 s` + OEM harvest poll + reconcile |
| metadata → audio on server | **≈ the call's own length** | the on-device transcode runs at ~1× real time |

The second is the real gap. A 35 s call's audio arrived 43 s after its metadata;
a 76 s call's, 81 s after. The pipeline is transcoding at roughly the speed the
call was spoken. Moi Zvonki has no such delay because **it does not transcode at
all** — it uploads the handset's MP3 as written.

### 1a. The architectural fork (CEO decision)

The transcode exists for one reason: the prototype uploaded 44 kHz / 128 kbps,
about 6 GB per phone per month of the employee's mobile data (R14). But the
files we now harvest are **already small**: the MIUI recorder writes 32 kbps
mono MP3 — a 76 s call is ~300 KB, already inside N17's budget. Transcoding it to
24 kbps Opus saves almost nothing, costs ~1× real time of CPU, and was the source
of today's 3× speed bug.

Two honest paths:

- **A — Upload the OEM file as-is when it is already within budget.**
  Near-instant, like Moi Zvonki. Needs the server to accept and play MP3 (a
  format column already exists; the player and storage must be checked). Transcode
  stays only as the fallback for oversized or app-recorded audio. This is the
  faster, simpler product and the one that matches the competitor.
- **B — Keep transcoding everything, but make it fast.** The transcode should run
  10–20× real time; today's 1× is a bug in the decode/encode loop (single-buffer
  stepping with 10 ms poll timeouts, and a per-sample resampler that allocates on
  every buffer). Fixing it keeps every recording in one uniform format at the
  cost of a few seconds of CPU per call.

**Recommendation: A, with B's loop fix underneath it as the fallback.** It is
what makes us at least as fast as Moi Zvonki, it removes an entire class of
transcode bugs from the common path, and it keeps a correct transcoder for the
handsets whose recorder writes something large or for the app's own recordings.
This is the one item that needs the CEO's word before I touch it, because it
changes what travels over the wire.

### 1b. The metadata delay (safe, no fork)

`POST_CALL_DELAY_SECONDS` is 20 s so the call-log row exists before
`client_call_id` is derived from it. On this fleet the row appears in ~2 s. Cut
the fixed delay to ~4 s and, when a finished call still has no log row, retry in
a few seconds rather than waiting for the 30-minute periodic sweep. Saves ~15 s
with no change to the id contract. Reversible one-liner, guarded by a test.

---

## 2. Robustness — what a reviewer would break

These are the sharp edges found today or still standing. Each becomes a test and
a fix, in this order of exposure:

1. **`ENDED` sessions are never deleted** — `CallStateMachine` does not mark
   `ENDED` terminal, so `resume()` reports "Resuming 9 sessions" and the row
   count grows without bound. Cosmetic today, a slow leak over a year.
2. **The parked/poison rows from before today's fixes** still sit on the test
   phone (two `queued_calls`, one 409 audio job). Clearing app data before the
   next real enrolment removes them; the server rows they map to cannot be
   re-lowered. Document the one-time reset.
3. **Two capture sources, one call** is fixed for the common phases, but call
   waiting on a dual-SIM handset is untested on hardware. Needs a real two-call
   test on the Galaxy.
4. **The Galaxy S21 (Android 15, scoped storage, `Recordings/Call`)** has never
   run the app. `modern34` + `MediaStore` locator is written and unproven. This
   is the next hardware milestone and may surface a whole new class of issue.
5. **Silence upload on Android 10+** — the app's own mic records digital silence
   during a call. Where the OEM route wins we discard it, but where it does not,
   we upload silence labelled `app_voice_communication`. Detect
   `AudioRecordingConfiguration.isClientSilenced()` and ship
   `capture_returned_silence` instead of a silent file; skip the mic route
   entirely once the OEM file exists.
6. **The `VOICE_CALL` retry** costs 15 s per call on Android 10+ for a source the
   platform will never grant a third-party app. Remove it on those versions.

---

## 3. Cleanliness — surviving the review

- **The unit suite is green (389 × 2 flavours) but the field fixes have no field
  test harness.** The live-server tests cover the wire; nothing exercises the
  transcode or the resampler against a real OEM file. Add a fixture: a short
  48 kHz MP3 checked into test resources, transcoded, asserted mono/16 kHz and
  correct duration. That is the test that would have caught the 3× bug before a
  human heard it.
- **`docs/ASSUMPTIONS.md` carries the full forensic trail** of today — every
  cause, every measurement. Fold the durable conclusions into `SPEC.md §7` so the
  next developer reads the design, not the archaeology.
- **Nothing is committed.** 42 files are changed in the working tree. Before any
  of this, the working set should be committed in reviewable pieces with the
  reasoning that is already written in ASSUMPTIONS — on the CEO's say-so, per the
  project rule that push/commit is asked first.

---

## 4. Sequence

1. **Commit today's working tree** (asked first) — lock in the win before
   building on it.
2. **1b** metadata delay cut — safe, immediate, ~15 s.
3. **CEO picks A or B** for the transcode fork — the big speed lever.
4. Implement the chosen path with its test and a real-call verification.
5. **Galaxy S21 bring-up** — the next hardware truth.
6. Robustness items 1, 5, 6; then the test fixtures and the SPEC fold-in.

Every step ends the same way: `./gradlew testLegacy28DebugUnitTest
testModern34DebugUnitTest` green, then a real call on a handset, then the row on
the server — not one of them assumed.
