# S1 — How CallSentry captured both voices

**T01 / D0 deliverable. Answered 2026-09-04 by reading the prototype's source.**
This was the project's biggest open technical question. It is now closed, and
the answer is more decisive than the hypothesis in `RISKS.md` assumed.

---

## The finding, in one line

**`targetSdk = 28` is the mechanism.** Not a side effect, not an accident — a
deliberate choice, documented in the prototype's own build file, and it is what
both recording paths depend on.

`../CallSentry/app/build.gradle.kts:17-21`:

```kotlin
minSdk = 26
// MUHIM: qo'ng'iroq yozib olish uchun ataylab 28 (Play Store uchun emas, ichki APK).
// targetSdk 29+ bo'lsa Android 14 suhbatdosh ovozini va phoneCall FGS turini qattiq
// cheklaydi; 28 "eski rejim"da ko'p qurilmalarda ikkala tomon ham yoziladi.
targetSdk = 28
```

> *"IMPORTANT: deliberately 28 for call recording (not for the Play Store — an
> internal APK). At targetSdk 29+ Android 14 tightly restricts the other party's
> audio and the phoneCall FGS type; at 28, in 'legacy mode', both sides are
> recorded on many devices."*

---

## Two recording paths, and both need the legacy target

`CtiForegroundService.onIdle()` tries them in order and **prefers the OEM file**.

### Path 1 (preferred) — harvest the phone's own call recorder

`OemRecordingLocator` scans, by raw file path, in preference order:

```
/sdcard/Recordings/Call
/sdcard/Recordings/Voice Recorder
/sdcard/Call
/sdcard/Sounds/Call
/sdcard/CallRecordings
```

and picks the newest audio file whose `lastModified` falls inside the call
window — from **answer time − 5 s** to **end time + 2 min** (the OEM writer
flushes late), skipping anything under 2 KB. It retries four times at 1-second
intervals because the file appears after the call ends. The source comment is
unambiguous: the device's built-in recorder *"ikkala tomon ovozini toza yozadi"*
— records both sides cleanly.

**Why it needs targetSdk 28:** it reaches `/sdcard` through
`Environment.getExternalStorageDirectory()` and plain `File` objects. That is
legacy storage. Scoped storage (targetSdk 29+) closes this path.

It is read-only — files are never modified or deleted.

### Path 2 (fallback) — the app records for itself

`RecordingManager` tries four audio sources in descending order of quality:

| Source | Reality per the source comments |
|---|---|
| `VOICE_CALL` | Best, but **forbidden to non-system apps** |
| `VOICE_RECOGNITION` | **Captures the other party on Samsung and some devices** |
| `VOICE_COMMUNICATION` | Mostly own voice only |
| `MIC` | Last resort; nothing from the other side on Bluetooth/headset |

Output goes to app-private `filesDir` as `.m4a`. The audio-source restrictions
that make `VOICE_RECOGNITION` usable are the same "legacy mode" the build
comment describes.

---

## What this confirms, and what it costs

The hypothesis in `RISKS.md` (S1 box) was that the audio mechanism and the
install friction are the same decision. **They are.** But the coupling is
tighter than assumed: `targetSdk 28` is load-bearing for *both* recording paths,
not only the OEM harvest.

**Consequences, all now certain rather than suspected:**

1. **Audio and install friction cannot be separated.** The low target is what
   Play Protect flags and what forces the developer-mode install (R17). There is
   no configuration that keeps the audio and removes the friction.
2. **The deprecation clock is real and dated.** Android raises the minimum
   installable `targetSdk` with each release. When that floor passes 28, the app
   stops installing on new phones — not degraded, blocked. This is not
   mitigable, only survivable, and it must be in the release-2 conversation from
   the start.
3. **Play Store distribution was never possible anyway**, and the prototype's
   author knew it — the comment says so outright. N33 stands.
4. **Coverage depends on the handset's own recorder** for the preferred path, so
   the fleet inventory (W01) decides how much of the team is covered. M0's job
   is to measure which of the two paths fires on each model, and at what rate.

---

## What BonviCall does with this

- **Release 1 targets SDK 28**, deliberately and with the reason written down.
- **Both paths ship**, with the OEM harvest preferred and the app's own recording
  as fallback — the prototype's ordering was correct.
- **The capture route is recorded per call**, so the panel can show which
  mechanism produced each recording and M0's per-model baseline means something.
- **The capture layer sits behind an interface**, so a modern-target build can be
  swapped in without touching the rest of the app.
- **The OEM scan is restricted to the registered number's call window** — the
  same folder holds the employee's private call recordings, so the time-window
  match is a privacy boundary, not just a correctness detail (R18, N28).

**S2 (Android Enterprise work profile) is now moot for recording.** A work
profile cannot see the personal dialer's calls and cannot read the OEM
recorder's files in the personal profile. It remains worth a look only for
distribution, and not on the critical path.
