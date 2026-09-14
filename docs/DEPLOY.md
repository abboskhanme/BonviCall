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
