# Security and hardening backlog

**Reviewed 2026-09-13 against the running system, not against the SPEC.**
Every item below was verified in the code or measured on the stack; nothing here
is a generic checklist entry. Ordered by real risk, not by effort.

The list exists because these are the items that separate "an internal tool that
works" from "a service another company can be sold". None of them is a stack
question — changing the server language fixes none of them.

---

## What is already right

Stated first, so nobody re-solves it. This codebase is above average here:

- **Every endpoint is RBAC-protected, and a test walks the route table to prove
  it** (`tests/test_app.py::test_every_registered_route_is_protected_or_declared_public`).
  Six public routes, each with a written reason in `core/permissions.py`.
- **Argon2id** for passwords; verification never raises, so one corrupt row
  cannot take the login endpoint down.
- **Refresh-token rotation with reuse detection** — a replayed token revokes the
  whole chain (N24). Most production systems do not do this.
- **Tokens are stored as SHA-256**, never in plaintext: a database dump is not
  replayable.
- **404, never 403,** for a row owned by somebody else — existence is not
  confirmed to a caller who may not read it.
- **A wrong password and an unknown account give the identical answer**, so the
  login form is not an account enumerator.
- **The error envelope never carries a traceback**; the request id links the
  client's message to the server log.
- **Production refuses to start with placeholder secrets**
  (`Settings.assert_production_ready`).
- **An audit log with a closed action set** — adding a value is a migration, on
  purpose, so "everything that happened" is answerable from one column.

---

## 1. There is no TLS — the whole system talks cleartext

**Risk: highest, and it is not close.** The app reaches the server over plain
HTTP at a LAN address (`docs/ON-DEVICE-TESTING.md` step 2 configures exactly
that, deliberately, for the field test). Anyone on the same Wi-Fi can read:

- a **device token** — and then be that phone: post fabricated calls, or read
  that employee's call list through the device API;
- the **admin password** as it is typed into the panel;
- the **audio** as it uploads.

Every control in "what is already right" above is bypassed by reading the wire.

**Fix:** Caddy in front, automatic TLS, one hostname per deployment. SPEC names
it; nothing built it. The app should also refuse cleartext outside the debug
flavour — the debug network-security config already scopes cleartext to one
host, so the release side is the part to assert.

**Effort:** half a day. **Blocks:** selling to anyone.

## 2. The login and enrolment endpoints are not rate-limited

Both docstrings say they are. Neither calls the limiter.

- `LoginRequest` (`modules/auth/schemas.py`): *"``POST /api/v1/auth/login`` —
  public, rate-limited."*
- `redeem` (`api/device/enrolment.py`): *"Public, rate-limited."*

`core/ratelimit.py` exists, works, and is wired to exactly three places: the
install landing page, the APK download, and the per-version download. Its own
docstring says it exists to *"raise the cost of guessing an eight-character
enrolment code and of hammering the login form"* — the two places it is not
called from.

This is the project's recurring failure shape — **a finished component with no
caller** (`STATUS.md`) — for the third recorded time.

**Fix:** `ratelimit.hit("login", ip, LOGIN_PER_IP)` and the same for redeem, with
a test per endpoint that exhausts the window. **Effort:** one hour.

## 3. No CI, so no dependency scanning and no gate on a broken test

766 server tests, 250 panel tests and 389 × 2 Android tests exist, and **nothing
runs them automatically.** The Makefile's own comments describe a CI that was
never built ("CI runs: `make contract && git diff --exit-code contract/`").

With two people working on two branches this is a question of when, not if.

**Fix:** one workflow — server tests, panel tests + build, Android unit tests,
`make migrate-head-check`, `make contract` drift check, plus `pip-audit` and
`npm audit`. **Effort:** half a day.

## 4. The backend container runs as root

`server/Dockerfile` declares no `USER`. A container escape is a host root. One
line, plus making the writable paths (`/data/...`) owned by that user.

**Effort:** one hour, and it must be verified against the audio and release
stores, which write at runtime.

## 5. PostgreSQL is published to the host

`ports: ["5443:5432"]` is right on a laptop and wrong on a server: the database
is reachable from the network with only a password in front of it. On a
deployment the port should not be published at all — the backend reaches it over
the compose network.

**Effort:** one line, but it needs a deployment compose file separate from the
development one, which does not exist yet.

## 6. No backups

Audio lives on one disk, on one host, with no copy anywhere. ~200 GB per year
per customer. Availability is the third leg of security, and for a product sold
as a service the loss of a customer's recordings is not an incident — it is a
contract.

**Fix:** `pg_dump` plus an audio sync to a second location, scheduled and
**restore-tested**. A backup nobody has restored is a hope.

## 7. Smaller, still worth doing

- **No `SECRET_KEY` rotation path.** Rotating it invalidates every session — and,
  once the telephony account work lands, the stored provider API key too
  (documented there).
- **Device access tokens live 12 hours** (`DEVICE_ACCESS_TOKEN_HOURS`). Fine, but
  it is the window an ex-employee's phone keeps working in; revocation exists and
  is enforced on the next heartbeat.
- **No secret scanning** in CI, on a repository that has an `.env` next to it and
  a keystore that must never be committed.

---

## Sequence

| # | Item | Effort |
|---|---|---|
| 1 | TLS + Caddy, and the app refusing cleartext in release | ½ day |
| 2 | Rate-limit login and redeem | 1 hour |
| 3 | CI with tests, contract drift, `pip-audit`, `npm audit` | ½ day |
| 4 | Non-root container, unpublished database port, deployment compose | 2 hours |
| 5 | Backups, with a restore that was actually run | 1 day |

Three days of work, and the difference between an internal tool and something a
second company can be sold. Item 2 is one hour and closes a hole the code
already claims to have closed.
