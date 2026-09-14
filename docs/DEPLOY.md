# Deploying BonviCall

One host, one domain, one command. Written after the stack was brought up and
verified end to end on 2026-09-14; every command below was run, not sketched.

**This is `docker-compose.prod.yml`, not `docker-compose.yml`.** The development
file stays exactly as it is — it is what the handsets are being tested against,
and the recording path was hard enough to get working that it is not to be
disturbed for a deployment concern.

---

## What the deployed stack is

```
        internet
           │  443 / 80
      ┌────▼─────┐
      │  caddy   │  TLS, and the built panel as static files
      └────┬─────┘
           │  compose network only — nothing else publishes a port
   ┌───────┼──────────┬───────────┐
   │       │          │           │
┌──▼───┐ ┌─▼──────┐ ┌─▼───────┐ ┌─▼──────────┐
│panel │ │backend │ │ worker  │ │ postgres   │
│static│ │uid     │ │ uid     │ │ no host    │
│in    │ │10001   │ │ 10001   │ │ port       │
│caddy │ └────────┘ └─────────┘ └────────────┘
└──────┘
```

Four differences from development, each with a reason:

| | Development | Deployed | Why |
|---|---|---|---|
| TLS | none | Caddy, automatic | a device token, the admin password and the audio all travel the wire |
| Postgres | `5443:5432` | not published | on a server that is the database offered to the network behind one password |
| backend, worker | root | uid 10001 | a container escape from root is host root |
| panel | Vite dev server | static bundle inside Caddy | same origin as the API, which the audio player requires for `Content-Range` |

The compose project is named `bonvicall-prod`, so it can never reach into the
development stack's volumes. That is not cosmetic — the development volumes were
created root-owned, and the non-root user here cannot write a recording into
one.

---

## Before you start — what must be true

Verified on 2026-09-14 against this commit; re-run the first four before any
deployment, they are `make test`, `make lint` and two lines.

| Check | State |
|---|---|
| Server suite | 766 passed, 2 skipped |
| Panel suite | 302 passed |
| Lint, both sides | clean |
| Panel build (`tsc -b && vite build`) | clean |
| Migrations reach head from empty, and downgrade | clean |
| Models vs migrations (`alembic check`) | no drift |
| `contract/` current | no drift |
| `ENVIRONMENT=prod` refuses placeholder secrets | refuses |
| `ENVIRONMENT=prod` hides `/docs` and `/openapi.json` | hidden |
| Refresh cookie gains `Secure` in prod | yes |
| The whole TLS path, on a real stack | rehearsed — see below |

The last line is the one worth knowing about: the deployed stack was brought
up locally on 2026-09-14, migrated, seeded, given a real signed APK through
`scripts/publish_apk.sh`, and an install link was followed end to end. The
deep link came back as `server=https%3A%2F%2F…` and the APK downloaded, 2.6 MB,
through Caddy. That is the path a salesperson walks.

**What you need before step 1:** a host, a domain pointed at it, ports 80 and
443 open, and a decision about which APK the fleet gets (see step 6 — the build
sitting in `android/app/build/outputs/` may be older than the recording fixes).

---

## First deployment

### 1. The domain, before anything else

`BONVICALL_DOMAIN` must already resolve to this host's public address. Caddy
asks Let's Encrypt for a certificate the first time it serves the name; a
domain that does not point here yet is a failed challenge and a wait before the
next attempt is allowed.

```sh
dig +short call.bonvi.uz     # must print this server's address
```

Ports 80 and 443 must be open. 80 is not optional — it is how the certificate
is issued and renewed, and Caddy redirects it to 443 the rest of the time.

### 2. `.env`

```sh
cp .env.example .env
```

Then set, at minimum:

```sh
SECRET_KEY=$(openssl rand -hex 32)     # rotating this logs everyone out
POSTGRES_PASSWORD=…                    # and the same value inside DATABASE_URL
DATABASE_URL=postgresql+asyncpg://bonvicall:<that password>@postgres:5432/bonvicall
ENVIRONMENT=prod
BONVICALL_DOMAIN=call.bonvi.uz
BONVICALL_ACME_EMAIL=admin@bonvi.uz
SEED_ADMIN_EMAIL=admin@bonvi.uz
SEED_ADMIN_PASSWORD=…                  # required in prod; seeding refuses without it
```

`ENVIRONMENT=prod` is load-bearing and does four things: the log renderer
becomes JSON, `/docs` and `/openapi.json` disappear, the refresh cookie gains
`Secure`, and **the server refuses to start** while `SECRET_KEY` or
`POSTGRES_PASSWORD` still hold the placeholder from the example file.

`.env` is never committed. It holds the only copy of `SECRET_KEY`, and losing it
ends every session and makes any reversibly-stored credential unreadable.

### 3. Build and start

```sh
docker compose -f docker-compose.prod.yml up -d --build
```

The Caddy image builds the panel as part of itself (`npm ci && npm run build`),
so a TypeScript error stops the deployment here rather than reaching a browser
as a blank page.

### 4. Migrate and seed

```sh
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.prod.yml run --rm backend python -m src.seed
```

Migrations are **not** run automatically on container start, deliberately: a
schema change that runs itself on every restart is a schema change nobody
reviews, and this database holds recordings that cannot be re-made.

### 5. Check it

```sh
curl -s  -o /dev/null -w '%{http_code} -> %{redirect_url}\n' http://call.bonvi.uz/healthz   # 308
curl -s  -o /dev/null -w '%{http_code}\n'                    https://call.bonvi.uz/healthz  # 200
curl -sI https://call.bonvi.uz/ | grep -i strict-transport                                  # HSTS
```

Then sign in to `https://call.bonvi.uz/` and change the seeded password — the
account is created with `must_change_password`, so the panel will insist.

### 6. Publish the APK — a new server has none

**Do not skip this.** A fresh deployment has no build, `/i/<code>` renders
"APK not ready", and there is nothing for a salesperson to install. It is the
first thing to do on a new server and the easiest to forget, because the
panel's publishing screen was removed on 2026-09-14 at the client's request —
it was a page an admin opens once a month. The endpoints it drove are still
there; `scripts/publish_apk.sh` is the path without the screen.

```sh
make android-release          # needs android/keystore.properties — APK-SIGNING.md

scripts/publish_apk.sh \
  --url https://call.bonvi.uz --login admin --password '…' \
  --apk android/app/build/outputs/apk/legacy28/release/app-legacy28-release.apk
```

Version, version code and variant are read from
`android/app/build.gradle.kts` and from the APK's path. Pass them only to
override, and get them right if you do: the server does **not** open the
manifest, so `version_code` is whatever the call says it is, and a wrong one
leaves every handset either offered a build it already has for ever, or
refused as under-version while running the newest one. Neither fails loudly.

Both flavours are separate publications — `legacy28` is what the fleet runs
(SPEC §7.2); publish `modern34` as well if any handset needs it.

`--no-publish` uploads and stops, so the signer fingerprint can be read before
the fleet is committed to a build. A build signed with a different key cannot
install over an existing one, and the phone reports that as a bare failure.

### 7. Check the whole path, as a salesperson would

```sh
curl -s "https://call.bonvi.uz/i/<code>" | grep -o 'server=[^"]*'   # https, not http
curl -sL -o /tmp/x.apk -w '%{http_code} %{size_download}\n' "https://call.bonvi.uz/i/<code>/apk"
```

The `server=` in the deep link is what a release build is pointed at, and it
is built from the headers Caddy sets. It **must** be `https://` — a release
APK refuses cleartext outright and will not connect to anything else.

---

## Updating a running deployment

```sh
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
```

Read the migration before running it if one is new. Audio and the database
survive; `caddy_data` survives, so no new certificate is requested.

## Pointing the fleet at it

Nothing to configure on a handset. A release build **refuses cleartext
entirely** (`android/app/src/main/res/xml/network_security_config.xml`), so it
can only ever talk to a server like this one, and the address it uses arrives in
the deep link on the install page — built from the forwarded headers Caddy
sets, so it is the public `https://` name and not an internal one.

The install link is `https://call.bonvi.uz/i/<code>`, per salesperson, from the
panel.

---

## What is still missing

Honest list, so nobody believes this is finished.

- **No backups.** Audio is on one disk on one host. `docs/SECURITY-BACKLOG.md`
  item 6; it is the largest remaining item and the only one whose absence is
  not recoverable.
- **`caddy_data` is not backed up either**, and it holds the certificate and the
  ACME account key.
- **No log retention or shipping.** `docker compose logs` is all there is.
- **One host.** Losing it loses the service until it is rebuilt.
