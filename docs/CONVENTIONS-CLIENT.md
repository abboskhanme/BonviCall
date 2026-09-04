# BonviCall — Client conventions (panel + Android)

**Who reads this:** `build-frontend` (React panel) and `build-android` (Kotlin
app), and `qa-review` when reviewing either. Everything cross-cutting — the wire
contract, errors, time, phone numbers, idempotency, permissions, naming, testing,
language — lives in **`docs/CONVENTIONS.md`** and is not repeated here.

## Rules in `CONVENTIONS.md` that bind you too

Read these there, not here. They are shared with the server, and a duplicated
rule is a rule that will drift.

| Rule | Where |
|---|---|
| Contract generation; DTOs and TS types are generated, never hand-written | `CONVENTIONS.md` §1 |
| Device API versioning, additive-only, the N34 min-version gate | §4 |
| Idempotency — client UUID in the body, always 200 with the same id | §5 |
| Time — three timestamps, `elapsedRealtime()` for durations, server time orders | §6 |
| Phone key and `contract/phone-vectors.json` | §7 |
| **The privacy boundary** — `PrivacyBoundary`, `Decision.Capture`, the buffer constants, the three undeletable tests | §8 |
| Error envelope and the status→code table | §9 |
| Permissions, including the two-place panel gate (`<Gate anyOf>` + `NAV[].anyOf`) | §11 |
| Naming, including `<Name>Page.tsx`, query keys, i18n keys, Kotlin class suffixes | §12 |
| Testing — the fixture list, what must have a test, no `assert True` | §13 |
| Language — English code and comments, Uzbek UI strings only | §14 |
| The `Everywhere` forbidden block | §15 |

---

## 1. Panel module

```
panel/src/modules/<name>/
├── api.ts             TanStack Query hooks only — no components, no fetch
├── <Name>Page.tsx
└── <What>Modal.tsx    one per dialog
```

A component needed in three or more modules moves to `panel/src/shared/ui/`.
Panel module names need not match server module names 1:1, but a mapping that
differs is written in the module's `api.ts` docstring.
*(BonviZvonki has four silent mismatches — `contacts`→`clients`,
`activity`/`dashboard`→`analytics`, `rubric`→`scoring` — discoverable only by
reading imports.)*

## 2. State, fetching, and the three non-success states

- **Server state is TanStack Query. Always.** Local UI state is `useState`.
  Global state is zustand and holds exactly two things — auth and theme. A third
  store needs a line in `docs/ASSUMPTIONS.md`.
- **All HTTP goes through `panel/src/shared/api/client.ts`** (`api.get/post/…`,
  `postForm`). Check: `grep -rn "fetch(" panel/src --include=*.ts*` → only
  `client.ts` and the audio Service Worker. `Content-Type` is never set by hand
  on multipart (adopted, with BonviZvonki's reason: the boundary is lost).
- **Loading / empty / error have one answer, not twenty.**
  `panel/src/shared/ui/QueryBoundary.tsx` takes a query result and renders
  `<Skeleton/>`, `<Empty/>` or `<ErrorState/>`; pages render only the success
  branch. Check: `grep -rn "isLoading\|isPending" panel/src/modules/` → empty.
  *This is new.* BonviZvonki has `isLoading` 67 times across 33 files and no
  convention, so every page's empty state looks slightly different.
- **Screen state lives in the URL** (`useSearchParams`): tab, filters, page.
  Adopted, with its reason — a `useState` tab cannot be linked to and the back
  button leaves the page.
- Mutations invalidate `['<module>']` in `onSuccess`.
- **Types come from `panel/src/shared/api/types.gen.ts`**, generated from
  `contract/openapi-panel-v1.json`. A hand-written interface mirroring a
  response is a violation (`CONVENTIONS.md` §1).
- Errors surface as `ApiError(status, code, message)` parsed from the §9
  envelope; 401 clears the token and navigates to `/login`.

## 3. Components, layout, styling, text

- **Create/edit only inside `shared/ui/Modal.tsx` + `ModalFields`** — no inline
  form on a page. Adopted; T88 already assumes it.
- Layout via `shared/layout/Page.tsx` (`Page` / `PageHeader` / `PageGrid`), no
  hard `max-width` (adopted — the `viewer` board is a TV).
- Colour through CSS tokens (`hsl(var(--accent))`), never hex, and never rely on
  the `dark:` variant: in "system" mode there is no `data-theme` attribute, so
  all three cases are written out.
- **Uzbek only** (§5.7). One catalogue, `panel/src/shared/i18n/uz.json`; strings
  stay out of components so a second locale is later a file, not a refactor.
  *Rejected from BonviZvonki:* its three-locale rule with `fallbackLng`. There is
  no second locale in release 1; empty `ru.json`/`en.json` rot.
- Import paths use the `@/` alias.

## 4. Audio playback (N43, UC-20)

N43 requires HTTP **Range** on the audio endpoint (206 + `Content-Range`), and
the endpoint requires an `Authorization` header, which `<audio src>` cannot send.

- **Adopted wholesale from BonviZvonki `web/src/modules/calls/audio.ts`:** a
  Service Worker (`panel/public/audio-sw.js`) intercepts the request and adds the
  header, so the browser's own player issues `Range` requests and native seek
  works. The `fetch`+blob path is the fallback for non-secure contexts, where
  seek still works but the whole file is fetched first.
- **The audio URL is always same-origin.** Cross-origin, the browser withholds
  `Content-Range` from both JS and the SW response, and seek breaks.
- Download uses `fetch`+blob and takes the filename from the server's
  `Content-Disposition` — never builds it client-side, or the two rules diverge.

---

## 5. Android module layout

- **One Gradle module, `:app`.** Package root `uz.bonvi.call`, split
  `core / data{local,remote} / domain / capture / service / ui / di`. Multi-module
  Gradle buys parallel builds this project does not need and costs configuration
  on every change.
- `data/remote/dto/` is machine-generated from `contract/openapi-device-v1.json`.
  A hand-written DTO there is a violation, and a DTO containing a free-form map
  is a privacy violation (`CONVENTIONS.md` §8.5).

## 6. The capture route (S1, T71)

- **`capture/` owns the recording route, behind `RecordingStrategy`** — the
  interface already exists in
  `../CallSentry/service/recording/RecordingStrategy.kt` and is adopted as-is:
  `isSupported()`, `start(File)`, `stop(): File?`.
- Two implementations ship on day one: `OemHarvestStrategy` (preferred) and
  `MediaRecorderStrategy` (fallback). `CaptureRouter` picks one and **records
  which one produced the audio** in `capture_route`; the panel and the M0
  baseline both depend on that field.
- `OemHarvestStrategy.locate()` takes `Decision.Capture`, not a raw number.
  That signature is the privacy boundary — see `CONVENTIONS.md` §8 before
  touching this package.

## 7. `targetSdk` is a build variant, not an assumption in the code

- `productFlavors { legacy28 { targetSdk = 28 }; modern34 { targetSdk = 34 } }`.
- Every behavioural difference is asked as a *capability*, not a version:
  `Capabilities.canReadOemRecordings()`,
  `Capabilities.canUseVoiceRecognitionSource()`.
- **`Build.VERSION.SDK_INT` may appear only in `core/Capabilities.kt`** —
  `grep -rn "SDK_INT" android/` outside that file is a violation.
- *Rejected from CallSentry:* `targetSdk = 28` hard-coded in `build.gradle.kts`
  with no flavor. S1 shows both recording paths depend on it, so the
  modern-target build must be buildable and measurable without editing source.

## 8. Threading

- Suspend functions and `Dispatchers.IO` for disk and network; `WorkManager` for
  anything that must survive process death (upload, sweep, heartbeat);
  `ViewModel` + `StateFlow` for UI.
- Forbidden: `Thread {}`, `AsyncTask`, `GlobalScope`, `runBlocking` outside
  tests. Nothing touches disk or network on the main thread.
- Durations are measured with `SystemClock.elapsedRealtime()`, never wall-clock
  subtraction (`CONVENTIONS.md` §6).

## 9. Manifest, transport, queue

- The full permission set is declared in T22 and minimised in T104. **Every
  `<uses-permission>` carries a comment naming the UC that needs it** — an
  uncommented permission is a review failure, because each one is another
  alarming screen during N40's 15 minutes.
- Cleartext disabled; certificate errors fatal and never bypassed (N22).
- No Google Play Services dependency in the capture or upload path — the APK is
  self-hosted (N33).
- Room is the queue of record (N8): oldest-first, a record parked after 5
  attempts and reported, never deleted. Local audio is deleted only after the
  server confirms the checksum (N11).

---

## 10. Client testing

The cross-cutting testing rules are in `CONVENTIONS.md` §13. Client-specific:

- **Panel — Vitest.** A page test asserts all three `QueryBoundary` states
  render. A module with a `<Gate>` has a test that the wrong role is redirected.
- **Android — JUnit + Robolectric.** `PhoneTest` reads
  `contract/phone-vectors.json`, the same file the server's phone test reads.
- `OemLocatorPrivacyTest` is one of the three undeletable tests
  (`CONVENTIONS.md` §8): a private-SIM recording sitting in the same folder is
  never returned.
- Every `RecordingStrategy` implementation has a test for `isSupported()`
  returning false — the fallback path is the one that will actually run on most
  of the fleet.

---

## 11. Forbidden

The `Everywhere` block in `CONVENTIONS.md` §15 applies here as well.

**Panel**
- `any`, `@ts-ignore`, `@ts-expect-error`
- bare `fetch(` outside `shared/api/client.ts`
- a hand-written type mirroring an API response
- `isLoading` handled inside a page
- a hex colour, or reliance on the `dark:` variant
- an inline create/edit form outside a `Modal`
- a cross-origin audio URL

**Android**
- `Build.VERSION.SDK_INT` outside `core/Capabilities.kt`
- `GlobalScope`, `runBlocking`, `Thread {}`, `AsyncTask`
- reading the OEM recordings folder outside `OemHarvestStrategy.kt`
- reading `SubscriptionManager` / `PHONE_ACCOUNT_ID` outside `PrivacyBoundary.kt`
- deleting or modifying an OEM file
- a hand-written or free-form-map device DTO
- a `<uses-permission>` without a comment naming its UC
- cleartext HTTP, or any certificate-error bypass
