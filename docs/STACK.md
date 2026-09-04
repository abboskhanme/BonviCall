# BonviCall — Stack

**Decided 2026-09-04 with the user (W06).** Rationale per layer; alternatives
that were considered and rejected are named, not hidden.

| Layer | Choice |
|---|---|
| Server | **Python · FastAPI · SQLAlchemy 2 (async) · Pydantic v2 · Alembic** |
| Database | **PostgreSQL 16** |
| Panel | **React 18 · Vite · TypeScript · TailwindCSS · TanStack Query** |
| Android | **Kotlin · Jetpack Compose · Hilt · Room · WorkManager · Retrofit/OkHttp** |
| Audio storage | **Local filesystem on the app server**, behind a storage interface |
| Infra | **Docker Compose** |
| Tests | **pytest** (server) · **Vitest** (panel) · **JUnit/Robolectric** (Android) |

## Why

**Server + panel — FastAPI + PostgreSQL + React.** The user's default, and
`../BonviZvonki` is built on exactly this. That is the deciding factor: its RBAC
registry, module layering, error-envelope convention and — critically — its
phone-number normalisation (E.164, last-9-digit matching, N37) transfer as
proven patterns rather than being reinvented. Release 2 couples the two systems
(§5.4), and a shared idiom makes that cheaper.

*Rejected:* **NestJS** — one language across server and panel is real, but
nothing transfers from BonviZvonki and the saving is small when agents write
most of the code. **Go** — genuinely better for concurrent audio upload and
streaming, but at 15 agents and ~12,000 calls/month that ceiling is never
approached; it would be optimising a problem this project does not have.

**Android — Kotlin + Compose.** N31 requires a persistent foreground service of
a call/microphone type, a boot-completed receiver, a durable network-constrained
work queue, a local database and background audio capture. Nothing outside a
native Android app provides these. `../CallSentry` is already this stack, so its
call-detection and recording patterns are readable reference.

**`targetSdk` is deliberately undecided** — M0 measures 28 (legacy, proven by the
trial) against 34 (All-files-access, better on every other axis) on real fleet
phones, and the measurement decides. Default is 34 if it captures both voices.
See `docs/S1-RECORDING.md`.

**Audio on the local filesystem, behind an interface.** ~17 GB/month, ~200 GB/year
(N18) on one server with one tenant is a solved problem; object storage would add
a moving part and a bill for no benefit at this size. The interface keeps S3 a
configuration change if volume or a second site ever justifies it.

*Rejected:* **object storage now** — premature. **Audio in PostgreSQL** — never.

## Constraints this stack must honour

- HTTP **Range** on the audio endpoint (206 + `Content-Range`, N43). BonviZvonki
  hit this and solved it with a Service Worker bridge for the `Authorization`
  header; expect the same and budget for it.
- Every endpoint RBAC-protected, with a per-endpoint test asserting 401/403/404
  (N23).
- Uzbek UI in the panel and the app; code, identifiers and internal docs in
  English.
