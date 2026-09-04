# Dev image for the panel. docker-compose mounts ./panel over /app and keeps
# this image's node_modules alive through an anonymous volume on
# /app/node_modules, so the dependencies installed here are the ones that run.
FROM node:22-alpine

WORKDIR /app

# Dependencies are a separate layer: editing source must not reinstall them.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite dev server. Compose overrides this with the same command plus --host.
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
