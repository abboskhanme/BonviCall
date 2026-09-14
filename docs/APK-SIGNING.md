# APK signing and key backup (T81)

**Who reads this:** whoever cuts a release, and whoever has to recover from
losing the key. English, like every other internal doc (`CONVENTIONS.md` §14).

---

## Why this document exists

BonviCall is **not distributed through Google Play** (N33). It is a signed APK
served from Bonvi's own host and side-loaded onto ~15 handsets the company does
not own.

That makes the signing key load-bearing in a way it is not for a Play app:

> **If the signing key is lost, no device can ever be updated again.**

Android refuses to install an update signed by a different key. With no Play
Store to re-publish through, the only remedy is uninstall-and-reinstall on every
handset in the fleet — which **destroys the local upload queue on each one**,
i.e. every call captured and not yet uploaded. There is no key-rotation path
that avoids this for a side-loaded app.

So the backup procedure below is part of the task, not an implied afterthought.

---

## Creating the key (once)

Run on the machine that will cut releases. `validity` is 10 000 days
deliberately: a key that expires is the same incident as a key that is lost, and
it arrives without warning.

```bash
keytool -genkeypair -v \
  -keystore android/bonvicall-release.jks \
  -alias bonvicall \
  -keyalg RSA -keysize 4096 \
  -validity 10000 \
  -dname "CN=BonviCall, OU=Bonvi, O=Bonvi, L=Tashkent, C=UZ"
```

Then, on the same machine:

```bash
cp android/keystore.properties.example android/keystore.properties
# fill in storePassword and keyPassword
```

`keystore.properties`, `*.jks` and `*.keystore` are gitignored. A commit that
adds one is a security incident, not a mistake to fix in the next commit.

---

## Backing it up — two places, two custodians

**One copy is not a backup, and two copies in one place is one copy.**

| Copy | Where | Who holds it |
|---|---|---|
| 1 | The release machine, at `android/bonvicall-release.jks` | the developer |
| 2 | Encrypted archive in the company password manager, with both passwords | the owner |
| 3 | Encrypted archive on offline media, held physically apart from 1 and 2 | the owner |

The archive for copies 2 and 3:

```bash
tar czf - android/bonvicall-release.jks | \
  gpg --symmetric --cipher-algo AES256 -o bonvicall-key-$(date +%F).tar.gz.gpg
```

**The passwords go in the password manager, not in the archive.** An encrypted
archive whose passphrase is stored beside it is a single copy wearing a
disguise.

### The part people skip

**Verify the backup restores, on a different machine, before the first
release.** An untested backup is a belief.

```bash
gpg -d bonvicall-key-YYYY-MM-DD.tar.gz.gpg | tar xzf -
keytool -list -v -keystore android/bonvicall-release.jks -alias bonvicall
```

The SHA-256 fingerprint it prints must match the one recorded below. Re-verify
whenever the custodian changes.

**Recorded fingerprint:**

```
29ea7737a691ae5fd68a3a9d3c6ae7fa09445d61a77ccb96cd2f3e2fccf24fa7
```

Read off the first release published to the production server on 2026-09-14,
from the APK's own v2 signing block rather than from the keystore — that is the
value a handset will compare, and a keystore that prints it is a keystore that
can still sign an update the fleet accepts.

It is also `APK_SIGNING_SHA256` in the deployment's `.env`, which turns the
check from advice into a refusal: an upload signed by any other key is rejected
by `ReleaseService.upload` rather than accepted and discovered later. Discovered
later means every handset must uninstall and reinstall, and an uninstall
destroys the calls that phone has not yet sent.

---

## Cutting a signed release

```bash
cd android
./gradlew assembleLegacy28Release        # or modern34, per M0's decision
```

Output: `app/build/outputs/apk/legacy28/release/app-legacy28-release.apk`.

Without `keystore.properties` the same command produces
`app-legacy28-release-unsigned.apk` and does **not** fail — CI and a developer
without the key must still be able to prove the release variant compiles.

Verify what you are about to serve:

```bash
"$ANDROID_HOME"/build-tools/34.0.0/apksigner verify --print-certs \
  app/build/outputs/apk/legacy28/release/app-legacy28-release.apk
```

The fingerprint must match the recorded one. **Check before uploading, not
after** — an APK signed with the wrong key installs fine on a clean handset and
fails only on phones that already have the app, which is every phone that
matters.

---

## If the key is lost anyway

There is no clever recovery:

1. Generate a new key and **back it up properly this time**.
2. Tell every agent the app must be uninstalled and reinstalled.
3. Accept that any call queued and not yet uploaded on those handsets is gone —
   the queue is app-private storage and uninstall removes it.
4. Re-enrol every device: the installation-bound credential does not survive
   either (N24, `allowBackup="false"`).

Point 3 is why this document exists. Everything else is inconvenience.
