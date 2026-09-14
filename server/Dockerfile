FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# The identity the deployment runs as. A container escape from a root process
# is host root; from this one it is a user that owns two data directories and
# nothing else (docs/SECURITY-BACKLOG.md item 4).
#
# The uid is FIXED at 10001 rather than allocated, because it is written into
# `docker-compose.prod.yml` as `user:` and the two must agree. A uid the
# distribution might reuse would make that pairing depend on the base image.
RUN useradd --system --uid 10001 --user-group --no-create-home bonvi

# Created HERE, owned HERE, and that is what makes the deployment work: Docker
# initialises a fresh named volume from the image directory it covers,
# ownership included. A volume mounted over a root-owned directory comes up
# root-owned, and the app — which is not root any more — then cannot write a
# single recording to it.
RUN mkdir -p /data/audio /data/releases && chown -R bonvi:bonvi /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R bonvi:bonvi /app

# No `USER` here, deliberately, and the reason is a running installation rather
# than a preference. Development mounts ./server over /app and keeps named
# volumes that already exist and are already owned by root — from every
# `compose up` before this file said anything about users. Switching the
# default would leave a developer's audio uploads failing on a permission
# error, in the one part of this product that was hardest to get working.
#
# So the deployment chooses the user instead: `user: "10001:10001"` on backend
# and worker in `docker-compose.prod.yml`, where the volumes are created fresh
# and correctly owned by the two RUN lines above.
# `tests/test_compose_wiring.py` fails if that line is ever dropped.
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
