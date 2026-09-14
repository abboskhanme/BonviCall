# Security and hardening backlog

**Reviewed 2026-09-13 against the running system, not against the SPEC.**
**Items 1–5 were built on 2026-09-14 and are marked DONE below, with what
was actually verified rather than what was intended. Item 6 — backups — is
untouched and is now the largest remaining risk.**
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

## 1. ~~There is no TLS~~ — DONE 2026-09-14

**Was: the highest risk, and not close.** The app reached the server over plain
HTTP at a LAN address. Anyone on the same Wi-Fi could read a **device token**
and then be that phone, the **admin password** as it was typed, and the
**audio** as it uploaded. Every control in "what is already right" above is
bypassed by reading the wire.

**Built:** `infra/Caddyfile` and `infra/caddy.Dockerfile`, fronting
`docker-compose.prod.yml`. Automatic certificates from Let's Encrypt, HTTP
permanently redirected, HSTS for a year. The panel is built into the same image
and served from the same origin — required, not tidy: the audio player needs
`Content-Range` back, and a browser withholds it cross-origin.

**Verified on the running stack, not reasoned about:**

- `http://…/healthz` → 308 to `https://`; `https://…/healthz` → 200.
- The panel, its deep routes, and the API all answer through the proxy, with the
  error envelope intact.
- A request carrying a forged `X-Forwarded-For` is counted against its **true**
  source address, so nobody can pick their own rate-limit bucket by sending a
  header. Caddy overwrites the header rather than appending to it, which is what
  makes that independent of which end of the list uvicorn happens to read.
- Two genuinely different source addresses get two different buckets — the other
  half of the same property, and the one whose absence would lock the office out.
- The backend records the real caller's address in `enrolment_attempts`, not
  Caddy's.

**The Android half needed nothing.** The release network security config already
refuses cleartext outright and trusts system CAs only; the debug flavour narrows
that to named dev hosts and `ManifestPermissionsTest` fails the build if anyone
widens it. It was written correctly the first time and was not touched.

**Still open on this item:** `caddy_data` holds the certificate and the ACME
account key and is not backed up. See item 6.

## 2. ~~The login and enrolment endpoints are not rate-limited~~ — DONE 2026-09-14

Both docstrings said they were. Neither called the limiter. `core/ratelimit.py`
existed, worked, and was wired to the install page and the two APK downloads —
never to the two endpoints its own docstring said it existed for. The project's
recurring failure shape, **a finished component with no caller**, for the third
recorded time.

**Built:** `check()` and `penalise()` beside the existing `hit()`, and both
endpoints wired to them, with tests that exhaust each window.

**The design decision worth reading.** These two count **failures only**, where
the install page counts every request. That is not a softening — it is the
difference between a limit that works here and one that breaks the rollout.
Fifteen handsets enrol from one office Wi-Fi, so they arrive as **one** source
address; and the app deliberately re-sends a redeem whose response was lost,
because that is the documented recovery path on a bad tunnel. Counting the
successes would have told the eleventh salesperson of the day to come back in an
hour, on the first day the product was used. Counting the failures leaves the
honest rollout untouched and still costs a guesser everything, because guessing
produces nothing but failures. Four tests pin both directions.

`LOGIN_PER_ACCOUNT` is keyed on **(IP, login)** as SPEC §4.0 words it, not on
the login alone — otherwise anyone who knew a colleague's login could shut them
out of the panel from anywhere by failing ten times.

**Not built, and stated so it is not assumed:** SPEC §4.0 also asks that a code
be auto-revoked *and an alert raised* after five attempts. The revocation was
already there — `EnrolmentService.MAX_CODE_ATTEMPTS`, counted on the code row
itself, so it survives a restart. **The alert is not.** An admin sees the
revoked code and the attempt rows; nothing tells them to look.

## 3. ~~No CI~~ — DONE 2026-09-14

759 server tests, 290 panel tests and two flavours of Android unit tests
existed, and nothing ran them unless somebody remembered to.

**Built:** `.github/workflows/ci.yml`, on pushes to `main`, `abboskhan` and
`dilijaxon` and on every pull request into `main`. Three jobs: the server suite
plus lint, `migrate-head-check`, `alembic check` and a contract-drift gate; the
panel's lint, tests and typed build; and the Android unit tests for **both**
flavours, since legacy28 is what the fleet actually runs.

The server job runs through **docker compose** rather than pip-installing on the
runner. Some of these tests are about the compose files themselves —
`test_compose_wiring.py` reads them from a mount — and a runner-native suite
would skip exactly the checks an infrastructure change is most likely to break.

`pip-audit` and `npm audit` report but do not fail the build: a CVE appearing
overnight in a transitive dependency should not block an unrelated fix, and what
matters is that somebody sees it. Drop the `|| true` when there is a person
whose job it is to clear the list.

## 4. ~~The backend container runs as root~~ — DONE 2026-09-14

**Built:** `server/Dockerfile` creates uid 10001 and gives it `/data/audio` and
`/data/releases`; `docker-compose.prod.yml` runs the backend and the worker as
that user. Verified by starting the deployed stack, running the full migration
history as that uid, and writing to the audio volume.

**Why the image does not simply say `USER`.** Docker initialises a fresh named
volume from the image directory it covers, ownership included — but an existing
volume keeps the ownership it has. Development has volumes created root-owned by
every `compose up` before this change, so a default of uid 10001 would have left
a developer's audio uploads failing on a permission error, in the one part of
this product that was hardest to get working. So the deployment selects the
user, where the volumes are new. `tests/test_compose_wiring.py` fails if that
line is ever dropped.

This is also why the deployment has a compose project name of its own,
`bonvicall-prod`: without it, running the deployment file in this directory
reuses the development volumes and fails exactly that way. That was found by
running it, not by thinking about it.

## 5. ~~PostgreSQL is published to the host~~ — DONE 2026-09-14

`ports: ["5443:5432"]` is right on a laptop and wrong on a server. The
deployment file publishes no database port at all — the backend reaches it over
the compose network — and publishes nothing for the backend either, which is
what makes `--forwarded-allow-ips="*"` safe there. Both are asserted by tests,
because the two lines sit far enough apart in the file that nobody would connect
them at midnight.

The development file is unchanged and still publishes 5443. That is correct for
a laptop and is where `make psql` goes.

## 6. No backups — **NOT DONE, and now the largest item**

Audio lives on one disk, on one host, with no copy anywhere. ~200 GB per year
per customer. Availability is the third leg of security, and for a product sold
as a service the loss of a customer's recordings is not an incident — it is a
contract.

Deployment added a third thing worth losing: `caddy_data` holds the TLS
certificate and the Let's Encrypt account key. It is small and it is not copied
anywhere either.

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
  a keystore that must never be committed. CI now exists, so this is a step to
  add rather than a thing to build.
- **No alert when an enrolment code is auto-revoked** for too many attempts. The
  revocation happens; nothing tells an admin to look (item 2).
- **The access token lives a week and cannot be called back.** At the client's
  request, so nobody is asked to sign in again during a working week. It is a
  signed JWT checked against no store: deactivating a user, or a lost laptop,
  leaves that token working until it expires. The refresh cookie is what a
  revocation actually stops. Written down in `.env.example` as well.

---

## Sequence

| # | Item | Effort | State |
|---|---|---|---|
| 1 | TLS + Caddy, and the app refusing cleartext in release | ½ day | **done** 2026-09-14 |
| 2 | Rate-limit login and redeem | 1 hour | **done** 2026-09-14 |
| 3 | CI with tests, contract drift, `pip-audit`, `npm audit` | ½ day | **done** 2026-09-14 |
| 4 | Non-root container, unpublished database port, deployment compose | 2 hours | **done** 2026-09-14 |
| 5 | Backups, with a restore that was actually run | 1 day | **open** |

Four of the five are built and the deployment path is `docs/DEPLOY.md`. What
stands between this and something a second company can be sold is now one item,
and it is the one whose absence cannot be recovered from afterwards.
