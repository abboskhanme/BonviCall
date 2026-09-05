# Getting the app onto a real phone (T81)

**Everything in BonviCall has so far been verified in a JVM. Not one call has
been captured on hardware.** Until that happens the audio question — the
project's largest risk — cannot even be asked. This is the shortest path from a
laptop to a captured call.

You need: an Android phone, a laptop running the stack, both on the same Wi-Fi.
You do **not** need a TLS certificate, a domain, or the signing key.

---

## 1. Find your laptop's LAN address

```bash
ipconfig getifaddr en0        # macOS, Wi-Fi
ip -4 addr show scope global  # Linux
```

Something like `192.168.1.23`. If it starts `127.` you have the loopback, which
the phone cannot reach.

## 2. Tell the build about it

`android/local.properties` (gitignored):

```properties
sdk.dir=/Users/you/Library/Android/sdk
bonvicall.devHost=192.168.1.23
```

That address is substituted into the **debug-only** network security config, so
the app may use cleartext **to that host and nowhere else**. The base config
still refuses cleartext everywhere, no build type trusts user-installed
certificates, and `src/debug/` is not part of any release artefact. Do not add a
wildcard; `ManifestPermissionsTest` fails the build if you do.

## 3. Serve the stack on the LAN, not on loopback

```bash
make up
```

Compose already publishes the backend on `0.0.0.0:8020`, so nothing to change.
Check from the **phone's browser** before going further:

```
http://192.168.1.23:8020/healthz     →  {"status":"ok"}
```

If that page does not load, stop here — it is a firewall or an AP-isolation
problem and no amount of app debugging will fix it. macOS: System Settings →
Network → Firewall. Many guest Wi-Fi networks block client-to-client traffic
entirely; use a phone hotspot with the laptop joined to it instead.

## 4. Build and install

```bash
cd android
./gradlew installLegacy28Debug          # phone connected by USB, debugging on
```

Or build and side-load, which is what an agent actually does:

```bash
./gradlew assembleLegacy28Debug
adb install -r app/build/outputs/apk/legacy28/debug/app-legacy28-debug.apk
```

`legacy28` is the flavour S1 says captures both voices. Build `modern34` too
when comparing — that comparison is M0's whole job.

## 5. Point the app at your laptop

The enrolment code carries its server, so in normal use there is nothing to set.
For a local server, the base URL is whatever the code's install link used.
Until the landing page is served locally, set it once through the enrolment
deep link:

```bash
adb shell am start -a android.intent.action.VIEW \
  -d "bonvicall://enrol?code=ABCD1234"
```

Create the code on the panel first (`http://192.168.1.23:5190`, agent page →
issue enrolment code).

## 6. Walk E1 → E6 with a stopwatch

**This is the N40 measurement, and it is the point of the whole exercise:**
3 of 3 unaided salespeople reach `capturing` in under 15 minutes each. Do it
yourself first, silently, without helping.

Watch for:

- **E2** — a row goes green only when the capability actually works. If the
  microphone row says "Ruxsat berilgan, lekin ishlamayapti", that is the OEM
  permission manager and it is a real finding, not a bug in the app.
- **E5** — route 1 (SIM MSISDN) is empty on most Uzbek SIMs, so expect the
  callback route. The receiver must be reachable from the phone's network.
- **E6** — "Tayyor" appears only when every required capability works **and**
  the number is proven. If it names a blocker instead, that is correct
  behaviour.

## 7. Make a call and watch it arrive

Place a call on the registered SIM. Then:

```bash
adb logcat -s BonviCall:* | grep -E "Call|Upload|Sweep"
```

Expected sequence: the detector logs the edges, the sweep runs ~20 s after
hang-up (it waits for the call-log row, because `client_call_id` derives from
it), the upload worker drains, and the call appears in the panel's call list.

Then the two tests that matter more than the happy path:

- **Call on the OTHER SIM.** Nothing must appear in the panel, and nothing in
  the queue. The log should show `Call discarded before capture:
  not_registered_subscription`. This is the privacy boundary, on hardware, for
  the first time.
- **Aeroplane mode, make a call, come back.** The call must arrive late rather
  than not at all.

## 8. Expect `audio_missing_reason: recording_route_unavailable`

There is **no audio yet** — the OEM locators are `NoOp` until M0 (T71b). A call
that arrives with correct direction, numbers, timestamps, duration and that
reason is a **complete, correct record** and exactly what this stage should
produce. The audio work lands into a pipeline that is already proven.

---

## What to write down

For each handset: manufacturer, model, Android version, which flavour, minutes
to reach `capturing`, which step took longest, and every capability that came
back `granted_not_working`. That last column is the fleet inventory nobody has
yet, and one real phone's worth of it is worth more than the list we are waiting
for.
