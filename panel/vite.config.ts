/// <reference types="vitest/config" />
import path from 'node:path'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/**
 * macOS + Docker uses virtiofs, which does not forward inotify events, so the
 * dev server must POLL or hot reload dies silently. docker-compose sets
 * CHOKIDAR_USEPOLLING/CHOKIDAR_INTERVAL; outside a container polling is a waste
 * of CPU, hence the env check rather than an unconditional `usePolling: true`.
 * Raise the interval if it is noisy. Do not remove it.
 */
const usePolling = process.env.CHOKIDAR_USEPOLLING === 'true'
const pollInterval = Number(process.env.CHOKIDAR_INTERVAL ?? 1000)

/**
 * Dev requests reach the server through this proxy, never through a hard-coded
 * origin: the panel is same-origin in production behind Caddy, and the audio
 * endpoint MUST be same-origin or the browser withholds `Content-Range` and
 * seek breaks (CONVENTIONS-CLIENT.md §4).
 */
const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://backend:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    watch: usePolling
      ? { usePolling: true, interval: pollInterval, binaryInterval: 3000 }
      : undefined,
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true },
      // Docker and Caddy read these; the panel's own health check uses them to
      // prove the proxy is wired.
      '/healthz': { target: proxyTarget, changeOrigin: true },
      '/readyz': { target: proxyTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    css: false,
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
})
