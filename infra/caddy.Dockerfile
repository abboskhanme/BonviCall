# Caddy, with the built panel inside it.
#
# The panel is a static bundle in production — no Node process, no dev server —
# so the thing that serves the API is the thing that serves the panel, and the
# two are the same origin. That is required rather than tidy: the audio player
# needs `Content-Range` back from the server, and a browser withholds it
# cross-origin (CONVENTIONS-CLIENT.md §4).
#
# Build context is the REPOSITORY ROOT, not ./infra — this stage needs ../panel.
# `docker-compose.prod.yml` sets it.

FROM node:22-alpine AS panel

WORKDIR /build
COPY panel/package.json panel/package-lock.json ./
RUN npm ci

COPY panel/ ./
# `npm run build` is `tsc -b && vite build`: a type error fails the deployment
# here rather than reaching a salesperson's browser as a blank page.
RUN npm run build

FROM caddy:2.8-alpine

COPY infra/Caddyfile /etc/caddy/Caddyfile
COPY --from=panel /build/dist /srv/panel
